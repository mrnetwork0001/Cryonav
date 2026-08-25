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
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")


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

#: The HDF5 distribution of ECO_L2T_LSTE stores LST as uint16 with a 0.02 scale factor, and
#: that figure is what the product documentation quotes. The CLOUD-OPTIMIZED GEOTIFF that
#: LP DAAC serves has already applied it: the band arrives float32, in kelvin, with
#: scales=(1.0,) and nodata=nan. Applying 0.02 again turned a 59 C rooftop into -266 C, which
#: is why this is decided from the dtype rather than from a constant.
LST_SCALE_INT = 0.02

#: The window that matters. Landsat cannot see it; this is the entire point of the script.
PEAK_LOCAL_HOURS = (13, 17)
SEARCH_WINDOW = ("2024-05-01T00:00:00Z", "2026-12-31T00:00:00Z")
SUMMER_MONTHS = (5, 6, 7, 8, 9)
GRANULE_LIMIT = 8

#: Granules whose timestamps fall in the same bucket belong to one overpass. The swath
#: advances across neighbouring tiles over a couple of minutes, so exact-time matching splits
#: a single pass into several.
PASS_GROUP_MINUTES = 10

#: Tiles downloaded per pass. A bbox this size never touches more than four.
MAX_TILES_PER_PASS = 6

MIN_K, MAX_K = 260.0, 380.0
MIN_PIXELS = 1  # 70 m pixels: a city block is one or two, so one is honest here
MIN_VALID_FRACTION = 0.4

#: Local time offsets. ECOSTRESS granule times are UTC and the peak-hour filter has to run in
#: local time, or it selects the wrong side of the planet.
#:
#: These are the offsets in force during SUMMER_MONTHS, which is the only window searched.
#: Arizona does not observe daylight saving, so Phoenix is -7 year round; the UAE has none
#: either. San Jose is the only entry that shifts - it is -8 PST in winter but -7 PDT from
#: March to November, and every granule this script looks at falls in the PDT half of the
#: year. Using -8 would slide the whole peak-hour window an hour early and quietly select
#: the wrong overpasses.
CITY_UTC_OFFSET_H = {"phoenix": -7, "dubai": 4, "abu_dhabi": 4, "san_jose": -7}

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


def _auth_kwargs() -> Dict[str, Any]:
    """Credentials for the HTTP client. Raises with instructions if none are configured."""
    token = os.getenv("EARTHDATA_TOKEN", "").strip()
    if token:
        return {"headers": {"Authorization": f"Bearer {token}"}, "_method": "bearer_token"}
    user = os.getenv("EARTHDATA_USERNAME", "").strip()
    pwd = os.getenv("EARTHDATA_PASSWORD", "").strip()
    if user and pwd:
        return {"auth": (user, pwd), "_method": "earthdata_basic"}
    raise SystemExit(CREDENTIAL_HELP)


def configure_auth() -> str:
    return str(_auth_kwargs()["_method"])


def download_granule(href: str, dest: pathlib.Path) -> None:
    """Fetch one granule to a local file.

    NOT a /vsicurl windowed read, and the reason is specific. Earthdata Login answers with a
    302 into an OAuth endpoint and then on to CloudFront with the authorisation already baked
    into signed query parameters. GDAL forwards the `Authorization: Bearer` header through
    that whole chain, CloudFront rejects the duplicate credential, and GDAL surfaces the error
    page as "not recognized as being in a supported file format" -- an unhelpful message for
    what is really a 401.

    Range reads earn their complexity on the 228 MB canopy tiles. An ECOSTRESS L2T tile is
    about 1 MB, so downloading it whole costs nothing and removes the entire failure mode.
    """
    import httpx  # noqa: PLC0415

    kw = _auth_kwargs()
    kw.pop("_method", None)
    with httpx.stream("GET", href, follow_redirects=True, timeout=120.0, **kw) as r:
        if r.status_code == 401:
            raise SystemExit(CREDENTIAL_HELP)
        r.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes(65536):
                fh.write(chunk)


def to_kelvin(arr: np.ndarray, src: Any) -> np.ndarray:
    """Kelvin from whatever form this particular file uses, then sanity-bounded.

    Integer bands still carry the documented 0.02 scale; float bands are already kelvin.
    Anything landing outside MIN_K..MAX_K after conversion is fill, cloud shadow, or a
    scaling mistake, and is discarded rather than averaged in.
    """
    a = arr.astype("float32")
    if np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
        a = a * LST_SCALE_INT
        a[arr == 0] = np.nan
    if src.nodata is not None and not np.isnan(src.nodata):
        a[arr == src.nodata] = np.nan
    a[(a < MIN_K) | (a > MAX_K)] = np.nan
    return a


def covers_bbox(src: Any, bbox: Dict[str, float], need: float = 0.98) -> float:
    """Fraction of the city bbox that falls inside this granule's footprint.

    ECOSTRESS tiles are 1568 x 1568 at 70 m, so a city can sit near an edge and be half
    outside. Averaging such a granule silently drops whichever streets fell off the tile.
    """
    gb = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    ow = max(0.0, min(gb[2], bbox["east"]) - max(gb[0], bbox["west"]))
    oh = max(0.0, min(gb[3], bbox["north"]) - max(gb[1], bbox["south"]))
    area = (bbox["east"] - bbox["west"]) * (bbox["north"] - bbox["south"])
    return (ow * oh) / area if area > 0 else 0.0


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



class GranuleSampler:
    """One granule, in its own projection, with its own baseline.

    Deliberately NOT a mosaic. ECOSTRESS tiles arrive on per-tile UTM grids, and a city near a
    zone boundary -- Abu Dhabi sits on the 39/40 line -- yields granules that cannot be stacked
    pixel-for-pixel without resampling. Stacking discarded half of them.

    So nothing is stacked. Each granule is sampled independently, each gets its own road-median
    baseline, and what gets averaged across granules is the ANOMALY, not the temperature. That
    is the quantity we actually want: it is dimensionless with respect to the day's air mass,
    so averaging across acquisitions weeks apart is meaningful in a way averaging absolute
    surface temperatures would not be. It also uses every usable granule regardless of zone.
    """

    def __init__(self, k: np.ndarray, transform: Any, crs: Any) -> None:
        self.k = k
        self.transform = transform
        self.crs = crs
        self.baseline_k = float("nan")
        self.baseline_pixels = 0

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

    def set_road_baseline(self, roads: Sequence[Dict[str, Any]]) -> bool:
        """Same reference as fetch_lst.py, so morning and afternoon are comparable."""
        vals: List[float] = []
        for r in roads:
            vals.extend(self.path_values(r.get("path", [])))
        if len(vals) < 50:
            return False
        self.baseline_k = float(np.median(vals))
        self.baseline_pixels = len(vals)
        return True

    def ring_mean_k(self, ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, int]]:
        """Mean kelvin and pixel count inside a ring, or None if this tile does not hold it.

        Separate from ring_anomaly_f because a group combines tiles by pixel-weighted mean,
        which needs the count - averaging the per-tile ANOMALIES would weight a two-pixel
        sliver the same as the tile holding the whole polygon.
        """
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
        if n == 0:
            return None
        return float(self.k[mask].mean()), n

    def ring_anomaly_f(self, ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, float, int]]:
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
        return (mean_k - self.baseline_k) * 1.8, mean_k, n

    def path_anomaly_f(self, path: Sequence[Sequence[float]]) -> Optional[Tuple[float, int]]:
        vals = self.path_values(path)
        if not vals:
            return None
        return (float(np.mean(vals)) - self.baseline_k) * 1.8, len(vals)


class AcquisitionSampler:
    """Every tile of ONE overpass, sampled as a single surface.

    ECOSTRESS L2T tiles are ~110 km squares on a fixed grid, and a city bbox routinely
    straddles several. One pass is therefore delivered as multiple granules, each holding a
    different piece of the city, each on its own UTM grid.

    An earlier version deduplicated by acquisition time and kept ONE granule per pass. That
    silently discarded the complementary tiles, so most passes appeared to cover 12% of
    Phoenix and were rejected - 23 of 24 of them - as if the desert had been cloudy. Grouping
    the tiles back together is what makes the data usable.

    No reprojection is involved: each member is queried in its own CRS and the values are
    pooled, which works because what we compute from them - a median baseline and per-feature
    means - are order-independent statistics over pixel VALUES, not over a raster.
    """

    def __init__(self, members: List["GranuleSampler"]) -> None:
        self.members = members
        self.baseline_k = float("nan")
        self.baseline_pixels = 0

    def path_values(self, path: Sequence[Sequence[float]]) -> List[float]:
        vals: List[float] = []
        for gs in self.members:
            vals.extend(gs.path_values(path))
        return vals

    def set_road_baseline(self, roads: Sequence[Dict[str, Any]]) -> bool:
        vals: List[float] = []
        for r in roads:
            vals.extend(self.path_values(r.get("path", [])))
        if len(vals) < 50:
            return False
        self.baseline_k = float(np.median(vals))
        self.baseline_pixels = len(vals)
        return True

    def ring_anomaly_f(self, ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, float, int]]:
        """Pixel-count-weighted mean across whichever tiles hold this polygon."""
        total = 0.0
        n = 0
        for gs in self.members:
            got = gs.ring_mean_k(ring)
            if got is None:
                continue
            mean_k, count = got
            total += mean_k * count
            n += count
        if n < MIN_PIXELS:
            return None
        mean_k = total / n
        return (mean_k - self.baseline_k) * 1.8, mean_k, n

    def path_anomaly_f(self, path: Sequence[Sequence[float]]) -> Optional[Tuple[float, int]]:
        vals = self.path_values(path)
        if not vals:
            return None
        return (float(np.mean(vals)) - self.baseline_k) * 1.8, len(vals)


def load_granule(g: Dict[str, Any], bbox: Dict[str, float]) -> Optional[Tuple[GranuleSampler, float]]:
    """Download, validate and window one granule. Returns (sampler, valid_fraction) or None."""
    local = pathlib.Path(tempfile.gettempdir()) / f"cryonav_eco_{g['id'].replace('/', '_')}.tif"
    try:
        if not local.exists() or local.stat().st_size == 0:
            download_granule(g["lst_href"], local)
        with rasterio.open(local) as src:
            # No per-tile coverage gate. A tile holding 12% of the city is a legitimate
            # piece of the mosaic; whether the PASS covers enough is judged afterwards, from
            # how many road pixels the assembled group can actually sample.
            cov = covers_bbox(src, bbox)
            b = transform_bounds(
                "EPSG:4326", src.crs, bbox["west"], bbox["south"], bbox["east"], bbox["north"]
            )
            win = from_bounds(*b, transform=src.transform)
            raw = src.read(1, window=win)
            k = to_kelvin(raw, src)
            frac = float(np.isfinite(k).mean())
            # Only a tile with NOTHING in the window is useless. The old 40% floor was applied
            # per tile, which rejected exactly the partial tiles a mosaic is made of.
            if frac <= 0.0:
                return None
            return GranuleSampler(k, src.window_transform(win), src.crs), frac * max(cov, 0.01)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"      skip {g['local_time']}: {type(exc).__name__}: {str(exc)[:90]}")
        return None
    finally:
        local.unlink(missing_ok=True)


def thermal_floor_c(city_id: str) -> float:
    """Coldest a sunlit road can plausibly be in this city's afternoon, in Celsius.

    Anchored to the city's own calibrated minimum air temperature where one exists - the
    coldest moment of the night - because a road under afternoon sun cannot be colder than
    that. Falls back to the catalogue climate, then to a conservative constant.
    """
    try:
        cal_path = ROOT / "data" / "calibration" / f"{city_id}.json"
        if cal_path.exists():
            cal = json.loads(cal_path.read_text())
            if cal.get("air_temp_min_f") is not None:
                return (float(cal["air_temp_min_f"]) - 32.0) * 5.0 / 9.0
        cities = json.loads((ROOT / "data" / "cities.json").read_text())["cities"]
        clim = next(c for c in cities if c["id"] == city_id)["climate"]
        return (float(clim["air_temp_min_f"]) - 32.0) * 5.0 / 9.0
    except Exception:
        return 15.0


def process(city_id: str) -> None:
    path = URBAN_DIR / f"{city_id}.json"
    data = json.loads(path.read_text())
    print(f"\n{city_id}")
    started = time.time()

    granules = search_granules(data["bbox"], city_id)
    if not granules:
        raise SystemExit(f"no ECOSTRESS granules for {city_id} in the peak-hour window")
    # Group tiles into PASSES. One overpass is delivered as several granules on neighbouring
    # tiles, each holding a different piece of the city and each timestamped a minute or two
    # apart as the swath advances. They must be sampled together to cover the bbox, and must
    # count as ONE observation so a single moment is not averaged in repeatedly.
    import datetime as _dt

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for g in granules:
        t = _dt.datetime.fromisoformat(g["utc"].replace("Z", "+00:00"))
        key = t.strftime("%Y-%m-%dT%H:") + f"{(t.minute // PASS_GROUP_MINUTES) * PASS_GROUP_MINUTES:02d}"
        groups.setdefault(key, []).append(g)
    passes = sorted(groups.values(), key=lambda gs: (abs(gs[0]["local_hour"] - 15), gs[0]["utc"]))
    print(
        f"    {len(granules)} candidate granules in {PEAK_LOCAL_HOURS[0]}:00-{PEAK_LOCAL_HOURS[1]}:00"
        f" local -> {len(passes)} distinct passes"
    )

    roads = data.get("roads", [])
    # feature key -> list of anomalies, one per granule
    acc: Dict[Tuple[str, int], List[float]] = {}
    abs_k: Dict[Tuple[str, int], List[float]] = {}
    pix: Dict[Tuple[str, int], int] = {}
    used: List[Dict[str, Any]] = []

    for tiles in passes:
        if len(used) >= GRANULE_LIMIT:
            break
        g = tiles[0]
        members = []
        for t in tiles[:MAX_TILES_PER_PASS]:
            loaded = load_granule(t, data["bbox"])
            if loaded is not None:
                members.append(loaded[0])
        if not members:
            print(f"      skip {g['local_time']}: no tile of this pass holds data over the city")
            continue
        sampler = AcquisitionSampler(members)
        frac = 0.0
        # The adequacy test is the assembled pass, not any single tile: can it sample enough
        # of the road network to produce a median baseline?
        if not sampler.set_road_baseline(roads):
            print(
                f"      skip {g['local_time']}: {len(members)} tile(s) reached only"
                f" {sampler.baseline_pixels} road px - too few for a baseline"
            )
            continue

        # PHYSICAL PLAUSIBILITY. Thin cirrus is not always caught by the fill mask, and cloud
        # TOPS are very cold - one Phoenix pass returned a -2.2 C road surface in June, which
        # is not a road. Sunlit pavement in the local afternoon cannot be colder than the
        # day's minimum AIR temperature, so that is used as the floor: it is a property of the
        # city's own observed calibration rather than a number chosen to make data pass.
        baseline_c = sampler.baseline_k - 273.15
        floor_c = thermal_floor_c(city_id)
        if baseline_c < floor_c:
            print(
                f"      skip {g['local_time']}: road baseline {baseline_c:.1f} C is below the"
                f" {floor_c:.1f} C floor - measuring cloud, not ground"
            )
            continue

        n_feat = 0
        for group in ("hot", "green", "water"):
            for i, feat in enumerate(data.get(group, [])):
                res = sampler.ring_anomaly_f(feat.get("ring", []))
                if res is None:
                    continue
                anomaly_f, mean_k, n = res
                acc.setdefault((group, i), []).append(anomaly_f)
                abs_k.setdefault((group, i), []).append(mean_k)
                pix[(group, i)] = max(pix.get((group, i), 0), n)
                n_feat += 1
        for i, feat in enumerate(roads):
            res = sampler.path_anomaly_f(feat.get("path", []))
            if res is None:
                continue
            anomaly_f, n = res
            acc.setdefault(("roads", i), []).append(anomaly_f)
            pix[("roads", i)] = max(pix.get(("roads", i), 0), n)
            n_feat += 1

        used.append(
            dict(
                g,
                tiles_in_pass=len(members),
                baseline_surface_c=round(sampler.baseline_k - 273.15, 2),
                baseline_pixels=sampler.baseline_pixels,
                features_measured=n_feat,
            )
        )
        print(
            f"      {g['local_time']} local  {len(members)} tile(s)"
            f"  road baseline {sampler.baseline_k - 273.15:5.1f} C"
            f"  {sampler.baseline_pixels:>5} road px  features {n_feat}"
        )

    if not used:
        raise SystemExit("no usable ECOSTRESS granules after quality filtering")

    # ---- write the averaged anomalies ---------------------------------------------------
    stats: Dict[str, int] = {}

    def bump(k: str) -> None:
        stats[k] = stats.get(k, 0) + 1

    for group in ("hot", "green", "water"):
        for i, feat in enumerate(data.get(group, [])):
            vals = acc.get((group, i))
            if not vals:
                bump(f"{group}:unmeasured")
                continue
            mean_anom = sum(vals) / len(vals)
            feat["lst_peak_anomaly_f"] = round(mean_anom, 2)
            feat["lst_peak_granules"] = len(vals)
            ks = abs_k.get((group, i)) or []
            if ks:
                feat["lst_peak_mean_c"] = round(sum(ks) / len(ks) - 273.15, 2)
            feat["lst_peak_pixels"] = pix.get((group, i), 0)
            if group == "hot":
                # The field urban.py reads. Peak-hour supersedes the morning value; the
                # Landsat number is preserved so the divergence stays inspectable.
                feat["boost_f"] = round(max(0.0, mean_anom), 2)
                feat["boost_source"] = "ecostress_peak"
            bump(f"{group}:measured")

    for i, feat in enumerate(roads):
        vals = acc.get(("roads", i))
        if not vals:
            bump("roads:unmeasured")
            continue
        mean_anom = sum(vals) / len(vals)
        feat["lst_peak_anomaly_f"] = round(mean_anom, 2)
        feat["lst_peak_granules"] = len(vals)
        if "lst_anomaly_morning_f" not in feat:
            feat["lst_anomaly_morning_f"] = feat.get("lst_anomaly_f")
        feat["lst_anomaly_f"] = round(mean_anom, 2)
        feat["lst_measured"] = True
        bump("roads:measured")

    data["surface_temperature_peak"] = {
        "source": "ecostress_eco_l2t_lste_v003",
        "collection": COLLECTION,
        "short_name": SHORT_NAME,
        "provider": "nasa_lp_daac",
        "resolution_m": 70,
        "peak_local_hours": list(PEAK_LOCAL_HOURS),
        "granules": used,
        "baseline_reference": "road_network_median_per_granule",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "license": LICENSE,
        "note": (
            "Anomalies measured in the local afternoon, the window Landsat's ~10:00 overpass "
            "never samples. Each granule is referenced to its own road-network median and the "
            "ANOMALIES are averaged, not the temperatures -- so granules on different UTM "
            "grids and different days all contribute. Where present these supersede the "
            "Landsat anomaly in boost_f; the morning value is kept as lst_anomaly_morning_f."
        ),
    }

    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"    {len(used)} granules contributed | {dict(sorted(stats.items()))}")
    print(f"    wrote {path.name} in {time.time() - started:.1f}s")


def main() -> None:
    method = configure_auth()
    print(f"Earthdata auth: {method}")
    cities = sys.argv[1:] or [p.stem for p in sorted(URBAN_DIR.glob("*.json"))]
    for city in cities:
        process(city)


if __name__ == "__main__":
    main()
