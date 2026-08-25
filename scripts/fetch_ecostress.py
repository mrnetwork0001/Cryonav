#!/usr/bin/env python3
"""
Measure surface temperature at the hour that actually hurts, using ECOSTRESS.

WHY THIS EXISTS
    `fetch_lst.py` uses Landsat, which is excellent and free and crosses the equator at
    roughly 10:00 local. Cryonav's design hour is 15:00. Between those two times asphalt and
    concrete diverge sharply -- they have different thermal inertia, so a morning ranking of
    surfaces is not the afternoon ranking, it is merely correlated with it. Every claim the
    product makes about a 15:00 walk therefore rested on a 10:00 observation.

    ECOSTRESS flies on the International Space Station, which has a precessing orbit and so
    is the only thermal instrument that samples the same ground across the whole day. Over
    the Phoenix bbox, CMR lists 24 granules in the 13:00-17:00 local window (checked
    2026-08-25) -- the window Landsat never sees.

SOURCE
    ECOSTRESS Tiled Land Surface Temperature and Emissivity, ECO_L2T_LSTE v003
    (collection C3998139651-LPCLOUD), NASA/JPL via LP DAAC. 70 m native, delivered on a 70 m
    UTM grid as Cloud-Optimized GeoTIFF. LST band is uint16 kelvin, scale factor 0.02.

CREDENTIALS -- READ THIS
    LP DAAC serves this behind NASA Earthdata Login. It is free and takes about two minutes:

        1. Register at https://urs.earthdata.nasa.gov/users/new
        2. Either export EARTHDATA_USERNAME and EARTHDATA_PASSWORD,
           or create a token at https://urs.earthdata.nasa.gov/profile
           and export EARTHDATA_TOKEN.

    Without them every asset request returns 401 and this script exits with instructions
    rather than silently writing nothing. Landsat needs no credentials, so the product
    remains fully measured without this step; ECOSTRESS sharpens the afternoon, it does not
    unlock it.

METHOD
    Identical to fetch_lst.py so the two are comparable: average the clearest granules in the
    peak-heat local-time window, reference every anomaly to the median surface temperature
    under the city's own road network, and write the result as `boost_f`. The Landsat value
    is preserved alongside as `lst_anomaly_f` so the morning-to-afternoon divergence stays
    visible instead of being overwritten.

USAGE
    backend/.venv/bin/python scripts/fetch_ecostress.py [city ...]
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
os.environ.setdefault("GDAL_HTTP_COOKIEFILE", "/tmp/cryonav_edl_cookies")
os.environ.setdefault("GDAL_HTTP_COOKIEJAR", "/tmp/cryonav_edl_cookies")

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import geometry_mask  # noqa: E402
from rasterio.warp import transform as warp_transform  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
URBAN_DIR = ROOT / "data" / "urban"

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
COLLECTION = "C3998139651-LPCLOUD"  # ECO_L2T_LSTE v003
SHORT_NAME = "ECO_L2T_LSTE"

#: ECOSTRESS L2T LST is uint16 kelvin with this scale; 0 is fill.
LST_SCALE = 0.02

#: The window that matters. Landsat cannot see it; this is the entire point of the script.
PEAK_LOCAL_HOURS = (13, 17)
SEARCH_WINDOW = ("2024-05-01T00:00:00Z", "2026-12-31T00:00:00Z")
SUMMER_MONTHS = (5, 6, 7, 8, 9)
GRANULE_LIMIT = 8

MIN_K, MAX_K = 260.0, 380.0
MIN_PIXELS = 1  # 70 m pixels: a city block is one or two, so one is honest here
MIN_VALID_FRACTION = 0.4

#: Local standard time offsets. ECOSTRESS granule times are UTC; the peak-hour filter has to
#: happen in local time or it selects the wrong side of the planet.
CITY_UTC_OFFSET_H = {"phoenix": -7, "dubai": 4, "abu_dhabi": 4}

LICENSE = (
    "Peak-hour surface temperature: NASA/JPL ECOSTRESS ECO_L2T_LSTE v003 via LP DAAC "
    "(NASA open data)."
)

CREDENTIAL_HELP = """
ECOSTRESS needs a free NASA Earthdata Login.

    1. Register:  https://urs.earthdata.nasa.gov/users/new
    2. Then either

           export EARTHDATA_USERNAME=you
           export EARTHDATA_PASSWORD=...

       or create a token at https://urs.earthdata.nasa.gov/profile and

           export EARTHDATA_TOKEN=...

Landsat (scripts/fetch_lst.py) needs none of this and already provides measured surface
temperature; ECOSTRESS only sharpens the afternoon. Nothing was written.
"""


def configure_auth() -> str:
    """Wire Earthdata credentials into GDAL's HTTP layer. Returns the method used."""
    token = os.getenv("EARTHDATA_TOKEN", "").strip()
    if token:
        os.environ["GDAL_HTTP_HEADERS"] = f"Authorization: Bearer {token}"
        return "bearer_token"
    user = os.getenv("EARTHDATA_USERNAME", "").strip()
    pwd = os.getenv("EARTHDATA_PASSWORD", "").strip()
    if user and pwd:
        # EDL answers with a 302 to its OAuth endpoint; GDAL must follow it and keep the
        # session cookie, or every tile read restarts the handshake.
        os.environ["GDAL_HTTP_AUTH"] = "BASIC"
        os.environ["GDAL_HTTP_USERPWD"] = f"{user}:{pwd}"
        os.environ["CPL_VSIL_CURL_USE_HEAD"] = "NO"
        return "earthdata_basic"
    raise SystemExit(CREDENTIAL_HELP)


def search_granules(bbox: Dict[str, float], city_id: str) -> List[Dict[str, Any]]:
    """CMR granules over the bbox whose LOCAL acquisition hour is in the peak window."""
    import urllib.parse
    import urllib.request

    offset = CITY_UTC_OFFSET_H.get(city_id)
    if offset is None:
        raise SystemExit(f"no UTC offset known for {city_id}; add it to CITY_UTC_OFFSET_H")

    query = urllib.parse.urlencode(
        {
            "collection_concept_id": COLLECTION,
            "bounding_box": f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}",
            "temporal": ",".join(SEARCH_WINDOW),
            "page_size": 2000,
        }
    )
    with urllib.request.urlopen(f"{CMR}?{query}", timeout=90) as fh:
        entries = json.load(fh)["feed"]["entry"]

    import datetime as dt

    out: List[Dict[str, Any]] = []
    for g in entries:
        started = dt.datetime.fromisoformat(g["time_start"].replace("Z", "+00:00"))
        local = started + dt.timedelta(hours=offset)
        if not (PEAK_LOCAL_HOURS[0] <= local.hour <= PEAK_LOCAL_HOURS[1]):
            continue
        if local.month not in SUMMER_MONTHS:
            continue
        href = next(
            (
                l.get("href")
                for l in g.get("links", [])
                if l.get("href", "").endswith("_LST.tif")
            ),
            None,
        )
        if not href:
            continue
        cloud = next(
            (
                l.get("href")
                for l in g.get("links", [])
                if l.get("href", "").endswith("_cloud.tif")
            ),
            None,
        )
        out.append(
            {
                "id": g["id"],
                "title": g.get("title", ""),
                "utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "local_time": local.strftime("%Y-%m-%d %H:%M"),
                "local_hour": local.hour,
                "lst_href": href,
                "cloud_href": cloud,
            }
        )
    # Nearest to 15:00 first -- the hour the product is designed around.
    out.sort(key=lambda g: (abs(g["local_hour"] - 15), g["utc"]))
    return out


class PeakWindow:
    """Per-pixel mean peak-hour surface temperature, kelvin."""

    def __init__(self, mean_k: np.ndarray, transform: Any, crs: Any, granules: List[Dict[str, Any]]):
        self.k = mean_k
        self.transform = transform
        self.crs = crs
        self.granules = granules
        valid = mean_k[np.isfinite(mean_k)]
        self.baseline_k = float(np.median(valid)) if valid.size else float("nan")
        self.baseline_source = "city_median"
        self.baseline_pixels = int(valid.size)

    def path_values(self, path: Sequence[Sequence[float]]) -> List[float]:
        vals: List[float] = []
        for a, b in zip(path, path[1:]):
            kk = math.cos(math.radians(a[0]))
            seg = math.hypot((b[1] - a[1]) * 111320.0 * kk, (b[0] - a[0]) * 110574.0)
            steps = max(1, int(seg / 35.0))
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

    def set_road_baseline(self, roads: Sequence[Dict[str, Any]]) -> None:
        """Same reference as fetch_lst.py, so the two anomalies are directly comparable."""
        vals: List[float] = []
        for r in roads:
            vals.extend(self.path_values(r.get("path", [])))
        if len(vals) < 50:
            print(f"      road baseline unusable ({len(vals)} px); keeping city median")
            return
        self.baseline_k = float(np.median(vals))
        self.baseline_source = "road_network_median"
        self.baseline_pixels = len(vals)

    def ring_anomaly_f(self, ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, float, int]]:
        if len(ring) < 3:
            return None
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        xs, ys = warp_transform("EPSG:4326", self.crs, lons, lats)
        geom = {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}
        try:
            mask = geometry_mask([geom], out_shape=self.k.shape, transform=self.transform, invert=True)
        except Exception:
            return None
        mask &= np.isfinite(self.k)
        n = int(mask.sum())
        if n < MIN_PIXELS:
            return None
        mean_k = float(self.k[mask].mean())
        return (mean_k - self.baseline_k) * 1.8, mean_k, n

    def path_anomaly_f(self, path: Sequence[Sequence[float]]) -> Optional[Tuple[float, int]]:
        vals = self.path_values(path)
        if not vals:
            return None
        return (float(np.mean(vals)) - self.baseline_k) * 1.8, len(vals)


def build_window(bbox: Dict[str, float], city_id: str) -> PeakWindow:
    granules = search_granules(bbox, city_id)
    if not granules:
        raise SystemExit(f"no ECOSTRESS granules for {city_id} in the peak-hour window")
    print(f"    {len(granules)} candidate granules in {PEAK_LOCAL_HOURS[0]}:00-{PEAK_LOCAL_HOURS[1]}:00 local")

    stack: List[np.ndarray] = []
    used: List[Dict[str, Any]] = []
    ref_transform = ref_crs = ref_shape = None
    for g in granules:
        if len(used) >= GRANULE_LIMIT:
            break
        url = "/vsicurl/" + g["lst_href"]
        try:
            with rasterio.open(url) as src:
                b = transform_bounds(
                    "EPSG:4326", src.crs, bbox["west"], bbox["south"], bbox["east"], bbox["north"]
                )
                win = from_bounds(*b, transform=src.transform)
                dn = src.read(1, window=win).astype("float32")
                tr = src.window_transform(win)
                if ref_transform is None:
                    ref_transform, ref_crs, ref_shape = tr, src.crs, dn.shape
                elif dn.shape != ref_shape or src.crs != ref_crs:
                    print(f"      skip {g['local_time']}: grid {dn.shape}/{src.crs} differs")
                    continue
                k = dn * LST_SCALE
                k[(dn == 0) | (k < MIN_K) | (k > MAX_K)] = np.nan
                frac = float(np.isfinite(k).mean())
                if frac < MIN_VALID_FRACTION:
                    print(f"      skip {g['local_time']}: {frac:.0%} valid (cloud)")
                    continue
                stack.append(k)
                g = dict(g, valid_pixel_fraction=round(frac, 3))
                used.append(g)
                print(
                    f"      {g['local_time']} local  mean {np.nanmean(k) - 273.15:5.1f} C"
                    f"  valid {frac:.0%}"
                )
        except SystemExit:
            raise
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "Access denied" in msg or "403" in msg:
                raise SystemExit(CREDENTIAL_HELP)
            print(f"      skip {g['local_time']}: {type(exc).__name__}")
            continue

    if not stack:
        raise SystemExit("no usable ECOSTRESS granules after quality filtering")
    with np.errstate(invalid="ignore"):
        mean_k = np.nanmean(np.stack(stack), axis=0)
    return PeakWindow(mean_k, ref_transform, ref_crs, used)


def process(city_id: str) -> None:
    path = URBAN_DIR / f"{city_id}.json"
    data = json.loads(path.read_text())
    print(f"\n{city_id}")
    started = time.time()
    win = build_window(data["bbox"], city_id)
    win.set_road_baseline(data.get("roads", []))
    print(
        f"    {len(win.granules)} granules averaged | grid {win.k.shape[1]} x {win.k.shape[0]} px"
        f" | baseline {win.baseline_k - 273.15:.1f} C ({win.baseline_source})"
    )

    stats: Dict[str, int] = {}

    def bump(k: str) -> None:
        stats[k] = stats.get(k, 0) + 1

    for group in ("hot", "green", "water"):
        for feat in data.get(group, []):
            res = win.ring_anomaly_f(feat.get("ring", []))
            if res is None:
                bump(f"{group}:unmeasured")
                continue
            anomaly_f, mean_k, n = res
            feat["lst_peak_anomaly_f"] = round(anomaly_f, 2)
            feat["lst_peak_mean_c"] = round(mean_k - 273.15, 2)
            feat["lst_peak_pixels"] = n
            if group == "hot":
                # Peak-hour supersedes the morning value for the field the model reads. The
                # Landsat number stays under lst_anomaly_f so the divergence is inspectable.
                feat["boost_f"] = round(max(0.0, anomaly_f), 2)
                feat["boost_source"] = "ecostress_peak"
            bump(f"{group}:measured")

    for feat in data.get("roads", []):
        res = win.path_anomaly_f(feat.get("path", []))
        if res is None:
            bump("roads:unmeasured")
            continue
        anomaly_f, n = res
        feat["lst_peak_anomaly_f"] = round(anomaly_f, 2)
        # urban.py reads lst_anomaly_f; point it at the hour the product is designed for.
        feat["lst_anomaly_morning_f"] = feat.get("lst_anomaly_f")
        feat["lst_anomaly_f"] = round(anomaly_f, 2)
        feat["lst_measured"] = True
        bump("roads:measured")

    data["surface_temperature_peak"] = {
        "source": "ecostress_eco_l2t_lste_v003",
        "collection": COLLECTION,
        "short_name": SHORT_NAME,
        "provider": "nasa_lp_daac",
        "resolution_m": 70,
        "scale": LST_SCALE,
        "peak_local_hours": list(PEAK_LOCAL_HOURS),
        "granules": win.granules,
        "baseline_surface_c": round(win.baseline_k - 273.15, 2),
        "baseline_reference": win.baseline_source,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "license": LICENSE,
        "note": (
            "Anomalies measured in the local afternoon, the window Landsat's ~10:00 overpass "
            "never samples. Where present these supersede the Landsat anomaly in boost_f; "
            "the morning value is retained as lst_anomaly_morning_f."
        ),
    }

    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"    {dict(sorted(stats.items()))}")
    print(f"    wrote {path.name} in {time.time() - started:.1f}s")


def main() -> None:
    method = configure_auth()
    print(f"Earthdata auth: {method}")
    cities = sys.argv[1:] or [p.stem for p in sorted(URBAN_DIR.glob("*.json"))]
    for city in cities:
        process(city)


if __name__ == "__main__":
    main()
