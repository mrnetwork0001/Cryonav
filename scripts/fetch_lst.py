#!/usr/bin/env python3
"""
Replace assumed per-class surface heating with measured land surface temperature.

WHAT THIS FIXES
    The urban files carried a table -- parking +16 F, industrial +14 F, retail +11 F,
    commercial +9 F, railway +12 F -- applied to every polygon of that class in every city.
    It is a plausible table. It is also the single largest un-measured input to the radiant
    load, and radiant load is what separates Cryonav's exposure index from a weather app's
    temperature reading. A shaded multi-storey car park and an open asphalt lot are both
    tagged `amenity=parking`; they are not both +16 F.

SOURCE
    Landsat Collection 2 Level-2 Surface Temperature (USGS/NASA, public domain), via the
    Microsoft Planetary Computer STAC API. Band ST_B10 (`lwir11`), 30 m, delivered as scaled
    uint16: kelvin = DN * 0.00341802 + 149.0. Cloud-Optimized, so only the city window is
    read over HTTP.

METHOD
    A single scene is a single day's weather, so the script averages the clearest summer
    scenes in the window (SCENE_LIMIT of them) into a per-pixel mean surface temperature.
    What each polygon then gets is not an absolute temperature -- that would drift with the
    day's air mass -- but an ANOMALY, in Fahrenheit degrees, against a reference. An anomaly
    is stable across scenes in a way an absolute reading is not.

    THE REFERENCE IS THE ROAD NETWORK, and that choice is forced by how the value is used.
    The sampler computes

        surface = air + (asphalt_uplift_f + surface_boost_f) * solar * clearness * SVF

    where `asphalt_uplift_f` (52 F in Phoenix) already describes a generic sunlit road. So
    `surface_boost_f` can only mean "hotter than a typical road" -- anything else double-
    counts. Referencing the median of all city pixels instead would fold in parks and water
    and quietly inflate every boost. The baseline here is therefore the median surface
    temperature of the pixels the city's own road geometry actually crosses.

KNOWN LIMIT
    Landsat crosses at ~10:00-11:00 local. Peak pavement temperature is three to five hours
    later. So these anomalies rank surfaces correctly but understate the afternoon spread;
    `scripts/fetch_ecostress.py` covers the afternoon window Landsat never samples.

USAGE
    backend/.venv/bin/python scripts/fetch_lst.py [city ...]
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

import numpy as np  # noqa: E402
import planetary_computer  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import geometry_mask  # noqa: E402
from rasterio.warp import transform as warp_transform  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
URBAN_DIR = ROOT / "data" / "urban"

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "landsat-c2-l2"

#: Published scaling for Collection 2 Level-2 ST_B10.
ST_SCALE = 0.00341802
ST_OFFSET = 149.0

#: Scenes averaged per city. More scenes means less single-day weather in the answer;
#: beyond about eight the anomaly stops moving.
SCENE_LIMIT = 6
MAX_CLOUD_PCT = 10.0
SEARCH_WINDOW = "2023-05-01/2026-12-31"
#: Northern-hemisphere summer for all three cities.
SUMMER_MONTHS = (5, 6, 7, 8, 9)

#: Physically plausible surface temperature range; anything outside is fill or cloud shadow.
MIN_K, MAX_K = 260.0, 360.0

#: A polygon smaller than a couple of 30 m pixels cannot be measured honestly.
MIN_PIXELS = 2

LICENSE = (
    "Land surface temperature: USGS/NASA Landsat Collection 2 Level-2 (public domain), "
    "accessed via the Microsoft Planetary Computer."
)


def k_to_f_delta(dk: float) -> float:
    """A DIFFERENCE in kelvin is 1.8x the same difference in Fahrenheit degrees."""
    return dk * 1.8


class LSTWindow:
    """Per-pixel mean surface temperature over the city, in kelvin."""

    def __init__(self, mean_k: np.ndarray, transform: Any, crs: Any, scenes: List[Dict[str, Any]]):
        self.k = mean_k
        self.transform = transform
        self.crs = crs
        self.scenes = scenes
        valid = mean_k[np.isfinite(mean_k)]
        # Provisional only; set_road_baseline replaces it with the reference the model needs.
        self.baseline_k = float(np.median(valid)) if valid.size else float("nan")
        self.baseline_source = "city_median"
        self.baseline_pixels = int(valid.size)

    def set_road_baseline(self, roads: Sequence[Dict[str, Any]]) -> None:
        """Reference = the median surface temperature under the city's own roads."""
        vals: List[float] = []
        for r in roads:
            vals.extend(self.path_values(r.get("path", [])))
        if len(vals) < 50:
            print(f"      road baseline unusable ({len(vals)} px); keeping city median")
            return
        self.baseline_k = float(np.median(vals))
        self.baseline_source = "road_network_median"
        self.baseline_pixels = len(vals)

    def path_values(self, path: Sequence[Sequence[float]]) -> List[float]:
        """Raw kelvin at the pixels a polyline crosses."""
        vals: List[float] = []
        for a, b in zip(path, path[1:]):
            kk = math.cos(math.radians(a[0]))
            seg = math.hypot((b[1] - a[1]) * 111320.0 * kk, (b[0] - a[0]) * 110574.0)
            steps = max(1, int(seg / 15.0))
            for i in range(steps + 1):
                f = i / steps
                lat, lon = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                xs, ys = warp_transform("EPSG:4326", self.crs, [lon], [lat])
                col = int((xs[0] - self.transform.c) / self.transform.a)
                row = int((ys[0] - self.transform.f) / self.transform.e)
                if 0 <= row < self.k.shape[0] and 0 <= col < self.k.shape[1]:
                    v = self.k[row, col]
                    if np.isfinite(v):
                        vals.append(float(v))
        return vals

    def ring_anomaly_f(
        self, ring: Sequence[Sequence[float]]
    ) -> Optional[Tuple[float, float, int]]:
        """(anomaly F, absolute mean K, pixels) inside a lat/lon ring."""
        if len(ring) < 3:
            return None
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        xs, ys = warp_transform("EPSG:4326", self.crs, lons, lats)
        geom = {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}
        try:
            mask = geometry_mask(
                [geom], out_shape=self.k.shape, transform=self.transform, invert=True
            )
        except Exception:
            return None
        mask &= np.isfinite(self.k)
        n = int(mask.sum())
        if n < MIN_PIXELS:
            return None
        mean_k = float(self.k[mask].mean())
        return k_to_f_delta(mean_k - self.baseline_k), mean_k, n

    def path_anomaly_f(self, path: Sequence[Sequence[float]]) -> Optional[Tuple[float, int]]:
        """Anomaly sampled at the pixels a walking line crosses."""
        vals = self.path_values(path)
        if not vals:
            return None
        return k_to_f_delta(float(np.mean(vals)) - self.baseline_k), len(vals)


def build_window(bbox: Dict[str, float]) -> LSTWindow:
    cat = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    search = cat.search(
        collections=[COLLECTION],
        bbox=[bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
        datetime=SEARCH_WINDOW,
        query={
            "eo:cloud_cover": {"lt": MAX_CLOUD_PCT},
            "platform": {"in": ["landsat-8", "landsat-9"]},
        },
    )
    items = [i for i in search.items() if i.datetime.month in SUMMER_MONTHS]
    if not items:
        raise SystemExit("no clear summer Landsat scenes for this bbox")
    # Clearest first, then most recent -- recency matters because cities are rebuilt.
    items.sort(key=lambda i: (i.properties.get("eo:cloud_cover", 100), -i.datetime.timestamp()))
    # Adjacent Landsat paths image the same city on the same day. Averaging both would weight
    # that day twice and let the run report more independent observations than it has.
    seen_dates = set()
    unique = []
    for it in items:
        day = it.datetime.date()
        if day in seen_dates:
            continue
        seen_dates.add(day)
        unique.append(it)
    items = unique[:SCENE_LIMIT]

    stack: List[np.ndarray] = []
    meta: List[Dict[str, Any]] = []
    ref_transform = ref_crs = None
    for it in items:
        asset = it.assets.get("lwir11")
        if asset is None:
            continue
        with rasterio.open(asset.href) as src:
            b = transform_bounds(
                "EPSG:4326", src.crs, bbox["west"], bbox["south"], bbox["east"], bbox["north"]
            )
            win = from_bounds(*b, transform=src.transform)
            dn = src.read(1, window=win).astype("float32")
            tr = src.window_transform(win)
            if ref_transform is None:
                ref_transform, ref_crs, ref_shape = tr, src.crs, dn.shape
            elif dn.shape != ref_shape:
                # Different Landsat path/row grids do not align pixel-for-pixel. Rather than
                # resample (and quietly blur a 30 m signal), skip the odd one out.
                print(f"      skip {it.id}: grid {dn.shape} != {ref_shape}")
                continue
            k = dn * ST_SCALE + ST_OFFSET
            k[(dn == 0) | (k < MIN_K) | (k > MAX_K)] = np.nan
            frac = float(np.isfinite(k).mean())
            if frac < 0.5:
                print(f"      skip {it.id}: only {frac:.0%} valid pixels")
                continue
            stack.append(k)
            meta.append(
                {
                    "id": it.id,
                    "datetime": it.datetime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "platform": it.properties.get("platform"),
                    "cloud_cover_pct": it.properties.get("eo:cloud_cover"),
                    "valid_pixel_fraction": round(frac, 3),
                }
            )
            print(
                f"      {it.datetime:%Y-%m-%d %H:%M}Z {it.properties.get('platform'):<9}"
                f" cloud {it.properties.get('eo:cloud_cover'):4.1f}%"
                f" mean {np.nanmean(k) - 273.15:5.1f} C"
            )
    if not stack:
        raise SystemExit("no usable scenes after quality filtering")
    with np.errstate(invalid="ignore"):
        mean_k = np.nanmean(np.stack(stack), axis=0)
    return LSTWindow(mean_k, ref_transform, ref_crs, meta)


def process(city_id: str) -> None:
    path = URBAN_DIR / f"{city_id}.json"
    data = json.loads(path.read_text())
    print(f"\n{city_id}")
    started = time.time()
    win = build_window(data["bbox"])
    win.set_road_baseline(data.get("roads", []))
    print(
        f"    {len(win.scenes)} scenes averaged | grid {win.k.shape[1]} x {win.k.shape[0]} px"
        f" | baseline {win.baseline_k - 273.15:.1f} C ({win.baseline_source},"
        f" {win.baseline_pixels} px)"
    )

    stats: Dict[str, int] = {}

    def bump(k: str) -> None:
        stats[k] = stats.get(k, 0) + 1

    for group in ("hot", "green", "water"):
        for feat in data.get(group, []):
            res = win.ring_anomaly_f(feat.get("ring", []))
            if res is None:
                feat["lst_measured"] = False
                bump(f"{group}:unmeasured")
                continue
            anomaly_f, mean_k, n = res
            feat["lst_anomaly_f"] = round(anomaly_f, 2)
            feat["lst_mean_c"] = round(mean_k - 273.15, 2)
            feat["lst_pixels"] = n
            feat["lst_measured"] = True
            if group == "hot":
                # The field the terrain model actually reads. Only positive anomalies are a
                # heat *boost*; a car park that runs cooler than the city median contributes
                # nothing rather than a negative boost the model was never built to take.
                feat["boost_f"] = round(max(0.0, anomaly_f), 2)
            bump(f"{group}:measured")

    for feat in data.get("roads", []):
        res = win.path_anomaly_f(feat.get("path", []))
        if res is None:
            feat["lst_measured"] = False
            bump("roads:unmeasured")
            continue
        anomaly_f, n = res
        feat["lst_anomaly_f"] = round(anomaly_f, 2)
        feat["lst_samples"] = n
        feat["lst_measured"] = True
        bump("roads:measured")

    # Polygons smaller than a couple of 30 m pixels cannot be measured directly. Rather than
    # leave them on the discarded global table, fill them from the median of MEASURED
    # polygons of the same class IN THIS CITY -- still observation-derived, and it carries a
    # different provenance label so the distinction survives into the API.
    filled = 0
    for group in ("hot", "green"):
        feats = data.get(group, [])
        by_class: Dict[str, List[float]] = {}
        for f in feats:
            if f.get("lst_measured"):
                by_class.setdefault(f.get("class", "?"), []).append(f["lst_anomaly_f"])
        overall = sorted(v for vs in by_class.values() for v in vs)
        for f in feats:
            if f.get("lst_measured"):
                f["lst_source"] = "measured"
                continue
            vals = sorted(by_class.get(f.get("class", "?"), [])) or overall
            if not vals:
                f["lst_source"] = "unavailable"
                continue
            med = vals[len(vals) // 2]
            f["lst_anomaly_f"] = round(med, 2)
            f["lst_source"] = "city_class_median"
            if group == "hot":
                f["boost_f"] = round(max(0.0, med), 2)
            filled += 1
    if filled:
        print(f"    {filled} sub-pixel polygons filled from this city's measured class medians")

    assumptions = data.setdefault("assumptions", {})
    assumptions.pop("surface_boost_by_class_f", None)
    if not assumptions.get("canopy_fraction_by_class"):
        assumptions["note"] = (
            "No per-class estimates remain: canopy and surface temperature are both measured."
        )
    data["surface_temperature"] = {
        "source": "landsat_c2_l2_st_b10",
        "collection": COLLECTION,
        "provider": "microsoft_planetary_computer",
        "band": "lwir11 (ST_B10)",
        "resolution_m": 30,
        "scale": ST_SCALE,
        "offset": ST_OFFSET,
        "scenes": win.scenes,
        "baseline_surface_c": round(win.baseline_k - 273.15, 2),
        "baseline_reference": win.baseline_source,
        "baseline_pixels": win.baseline_pixels,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "license": LICENSE,
        "sub_pixel_fill": (
            "Polygons under {n} pixels take the median anomaly of measured polygons of the "
            "same class in this city, labelled lst_source=city_class_median."
        ).format(n=MIN_PIXELS),
        "note": (
            "boost_f is a measured anomaly against the city's own median surface, not a "
            "per-class constant. Landsat overpass is ~10:00-11:00 local, so afternoon "
            "spread is understated; see the ecostress block where present."
        ),
    }

    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"    {dict(sorted(stats.items()))}")
    print(f"    wrote {path.name} in {time.time() - started:.1f}s")


def main() -> None:
    cities = sys.argv[1:] or [p.stem for p in sorted(URBAN_DIR.glob("*.json"))]
    for city in cities:
        process(city)


if __name__ == "__main__":
    main()
