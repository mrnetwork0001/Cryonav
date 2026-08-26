#!/usr/bin/env python3
"""
Replace assumed canopy density with measured canopy from the Meta / WRI Canopy Height Maps.

WHAT THIS FIXES
    OpenStreetMap knows a polygon is tagged `leisure=park`. It does not know whether that
    park is a shaded grove or a bare lawn, and the routing engine's whole claim -- that it
    can find you shade -- rested on a lookup table that said "park = 60% canopy" for every
    park on earth. Two parks 400 m apart in Phoenix differ by more than that table's entire
    range. This script measures each one.

SOURCE
    Meta / WRI Canopy Height Maps, v6 (`alsgedi_global_v6_float`), CC-BY-4.0, on AWS Open
    Data at s3://dataforgood-fb-data/forests/v1/. Global, 1.19 m ground sample, uint8 canopy
    height in metres, EPSG:3857, tiled by zoom-9 quadkey. Derived from Maxar imagery with a
    DINOv2 backbone, calibrated against GEDI spaceborne lidar.

    Cloud-Optimized GeoTIFF, so the 228 MB Phoenix tile is never downloaded: GDAL issues HTTP
    range requests and pulls only the ~5000 x 5000 px city window (about 8 s, ~25 MB).

METHOD
    Canopy FRACTION is the share of ground under vegetation at least CANOPY_HEIGHT_M tall --
    the conventional tree-cover threshold, which excludes turf, shrubs and bare soil that
    cast no useful shade. For each feature the script measures:

      green / hot polygons  fraction inside the ring
      roads, tree rows,     fraction within a corridor buffer of the walking line, since
      covered ways          what shades a pedestrian is canopy near the path, not far from it
      individual trees      fraction within TREE_RADIUS_M of the trunk, replacing the flat
                            per-tree constant that assumed every OSM tree was mature

    Nothing here is inferred from a tag. Every number is counted pixels.

USAGE
    backend/.venv/bin/python scripts/fetch_canopy.py [city ...]
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
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
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

BASE = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float"
CHM_URL = BASE + "/chm/{qk}.tif"

#: Vegetation must reach this height to count as canopy. 3 m is the standard tree-cover
#: threshold (it is what NLCD, GEDI-derived products and FAO forest definitions use), and it
#: is also roughly the height below which a plant stops shading a standing adult.
CANOPY_HEIGHT_M = 3.0

#: Radius sampled around an OSM tree point. Street trees in these cities are mostly Palo
#: Verde, Ghaf and date palm; 8 m comfortably contains a mature crown without bleeding into
#: the next tree's.
TREE_RADIUS_M = 8.0

#: Half-width of the corridor sampled along a walking line. A pedestrian is shaded by canopy
#: overhanging the footway, not by trees across a six-lane road.
PATH_BUFFER_M = 10.0

#: Spacing of sample discs along a path.
PATH_STEP_M = 4.0

LICENSE = (
    "Canopy height: Meta / World Resources Institute Canopy Height Maps v6, CC-BY-4.0, "
    "via the AWS Open Data registry."
)


# --------------------------------------------------------------------------------------
# Tiling
# --------------------------------------------------------------------------------------


def quadkey(lat: float, lon: float, zoom: int = 9) -> str:
    """Bing/Slippy quadkey, the CHM tile naming scheme."""
    sin = math.sin(math.radians(lat))
    x = int((lon + 180.0) / 360.0 * (1 << zoom))
    y = int((0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * (1 << zoom))
    out = []
    for i in range(zoom, 0, -1):
        digit, mask = 0, 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        out.append(str(digit))
    return "".join(out)


def tiles_for_bbox(bbox: Dict[str, float]) -> List[str]:
    corners = [
        (bbox["south"], bbox["west"]),
        (bbox["south"], bbox["east"]),
        (bbox["north"], bbox["west"]),
        (bbox["north"], bbox["east"]),
    ]
    seen: List[str] = []
    for lat, lon in corners:
        qk = quadkey(lat, lon)
        if qk not in seen:
            seen.append(qk)
    return seen


# --------------------------------------------------------------------------------------
# Raster window held in memory for the whole city
# --------------------------------------------------------------------------------------


class CanopyWindow:
    """The city's canopy-height window, plus the geometry to sample it."""

    def __init__(self, heights: np.ndarray, transform: Any, crs: Any) -> None:
        self.h = heights
        self.transform = transform
        self.crs = crs
        self.canopy = heights >= CANOPY_HEIGHT_M
        # Metres per pixel, needed to turn a radius in metres into a pixel radius. EPSG:3857
        # exaggerates distance by 1/cos(lat), so undo that or every buffer is too small.
        self.px_m = abs(transform.a)

    def _rowcol(self, lat: float, lon: float) -> Tuple[int, int]:
        xs, ys = warp_transform("EPSG:4326", self.crs, [lon], [lat])
        col = int((xs[0] - self.transform.c) / self.transform.a)
        row = int((ys[0] - self.transform.f) / self.transform.e)
        return row, col

    def _scale_at(self, lat: float) -> float:
        """True ground metres per pixel at this latitude."""
        return self.px_m * math.cos(math.radians(lat))

    def disc(self, lat: float, lon: float, radius_m: float) -> Optional[np.ndarray]:
        """Boolean canopy mask values inside a disc, or None if off-tile."""
        row, col = self._rowcol(lat, lon)
        r = max(1, int(round(radius_m / self._scale_at(lat))))
        r0, r1 = row - r, row + r + 1
        c0, c1 = col - r, col + r + 1
        if r1 <= 0 or c1 <= 0 or r0 >= self.h.shape[0] or c0 >= self.h.shape[1]:
            return None
        r0, c0 = max(0, r0), max(0, c0)
        r1, c1 = min(self.h.shape[0], r1), min(self.h.shape[1], c1)
        sub = self.canopy[r0:r1, c0:c1]
        if sub.size == 0:
            return None
        yy, xx = np.ogrid[r0 - row : r1 - row, c0 - col : c1 - col]
        return sub[(yy * yy + xx * xx) <= r * r]

    def ring_fraction(self, ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, float, int]]:
        """(canopy fraction, mean height m, pixel count) inside a lat/lon ring."""
        if len(ring) < 3:
            return None
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        xs, ys = warp_transform("EPSG:4326", self.crs, lons, lats)
        geom = {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}
        try:
            mask = geometry_mask(
                [geom], out_shape=self.h.shape, transform=self.transform, invert=True
            )
        except Exception:
            return None
        n = int(mask.sum())
        if n == 0:
            return None
        return float(self.canopy[mask].mean()), float(self.h[mask].mean()), n

    def path_fraction(
        self, path: Sequence[Sequence[float]], buffer_m: float
    ) -> Optional[Tuple[float, int]]:
        """(canopy fraction, samples) in a corridor around a polyline."""
        vals: List[np.ndarray] = []
        for a, b in zip(path, path[1:]):
            seg_m = _haversine_m(a, b)
            steps = max(1, int(seg_m / PATH_STEP_M))
            for i in range(steps + 1):
                f = i / steps
                lat = a[0] + (b[0] - a[0]) * f
                lon = a[1] + (b[1] - a[1]) * f
                d = self.disc(lat, lon, buffer_m)
                if d is not None and d.size:
                    vals.append(d)
        if not vals:
            return None
        stacked = np.concatenate(vals)
        return float(stacked.mean()), len(vals)


def _haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    k = math.cos(math.radians(a[0]))
    return math.hypot((b[1] - a[1]) * 111320.0 * k, (b[0] - a[0]) * 110574.0)


def padded_bounds(bbox: Dict[str, float], margin_m: float = 250.0) -> Dict[str, float]:
    """The city bbox with a margin, so edge-straddling polygons are measured whole.

    Overpass returns any polygon that INTERSECTS the query box, so a park on the boundary
    comes back complete while a window stopping at the boundary cannot measure it.
    Coffelt-Lamoreaux Park extended 109 m west of the Phoenix window and therefore kept the
    per-class default of 60% canopy - which made it the second-shadiest polygon in the tile,
    on a number nobody measured.

    The margin is deliberately a fixed pad on the BBOX rather than the extent of the features.
    An earlier attempt used the feature extent and ballooned the window to 43146 x 21884 px,
    because OSM returns whole road ways that run far outside the tile; at that size nothing
    was measured at all. A few hundred metres is all an edge-straddling polygon needs.
    """
    dlat = margin_m / 110574.0
    mid = (bbox["south"] + bbox["north"]) / 2.0
    dlon = margin_m / (111320.0 * max(0.2, math.cos(math.radians(mid))))
    return {
        "south": bbox["south"] - dlat, "north": bbox["north"] + dlat,
        "west": bbox["west"] - dlon, "east": bbox["east"] + dlon,
    }


def load_window(bbox: Dict[str, float], tile_bbox: Optional[Dict[str, float]] = None) -> CanopyWindow:
    """Read `bbox` from the CHM tile that covers `tile_bbox` (default: bbox itself).

    The two differ because the read window is widened to the features' extent while the tile
    is still chosen by the city. Selecting the tile from the widened box put one CORNER over a
    tile boundary and aborted the run, even though every feature sat inside a single tile -
    a margin of a few hundred metres should not change which tile a city is in.
    """
    tiles = tiles_for_bbox(tile_bbox or bbox)
    if len(tiles) > 1:
        # Every current city fits one zoom-9 tile (they are ~78 km across at these
        # latitudes). Mosaicking is real work; refuse loudly rather than silently sampling
        # only part of the city.
        raise SystemExit(
            f"bbox spans {len(tiles)} CHM tiles ({', '.join(tiles)}); mosaicking is not implemented"
        )
    url = "/vsicurl/" + CHM_URL.format(qk=tiles[0])
    print(f"    tile {tiles[0]} (range-reading, not downloading)")
    with rasterio.open(url) as src:
        b = transform_bounds(
            "EPSG:4326", src.crs, bbox["west"], bbox["south"], bbox["east"], bbox["north"]
        )
        win = from_bounds(*b, transform=src.transform)
        arr = src.read(1, window=win)
        return CanopyWindow(arr, src.window_transform(win), src.crs)


# --------------------------------------------------------------------------------------
# City pass
# --------------------------------------------------------------------------------------


def process(city_id: str) -> None:
    path = URBAN_DIR / f"{city_id}.json"
    data = json.loads(path.read_text())
    print(f"\n{city_id}")
    started = time.time()
    # Widened to the features' own extent: a polygon Overpass returned whole must be measured
    # whole, or it silently keeps its per-class default.
    win = load_window(padded_bounds(data["bbox"]), tile_bbox=data["bbox"])
    total_px = win.h.size
    print(
        f"    window {win.h.shape[1]} x {win.h.shape[0]} px @ {win.px_m:.2f} m"
        f" | city canopy {100 * win.canopy.mean():.2f}%"
    )

    stats: Dict[str, int] = {}

    def bump(key: str) -> None:
        stats[key] = stats.get(key, 0) + 1

    # -- polygons ---------------------------------------------------------------------
    for group in ("green", "hot"):
        for feat in data.get(group, []):
            res = win.ring_fraction(feat.get("ring", []))
            if res is None:
                feat["canopy_measured"] = False
                bump(f"{group}:unmeasured")
                continue
            frac, mean_h, n = res
            feat["canopy"] = round(frac, 4)
            feat["canopy_mean_height_m"] = round(mean_h, 2)
            feat["canopy_pixels"] = n
            feat["canopy_measured"] = True
            bump(f"{group}:measured")

    # -- linear features ---------------------------------------------------------------
    for group, buf in (
        ("roads", PATH_BUFFER_M),
        ("tree_rows", PATH_BUFFER_M),
        ("covered_ways", PATH_BUFFER_M),
    ):
        for feat in data.get(group, []):
            res = win.path_fraction(feat.get("path", []), buf)
            if res is None:
                feat["canopy_measured"] = False
                bump(f"{group}:unmeasured")
                continue
            frac, n = res
            feat["canopy"] = round(frac, 4)
            feat["canopy_samples"] = n
            feat["canopy_measured"] = True
            bump(f"{group}:measured")

    # -- individual trees ---------------------------------------------------------------
    # OSM gives a trunk position and nothing else. The old model gave every one of them the
    # same crown. Measure each instead; a newly planted sapling now contributes what it
    # actually contributes, which is close to nothing.
    trees = data.get("trees", [])
    measured = 0
    for t in trees:
        d = win.disc(t[0], t[1], TREE_RADIUS_M)
        if d is None or d.size == 0:
            if len(t) >= 3:
                t[2] = None
            continue
        if len(t) >= 3:
            t[2] = round(float(d.mean()), 4)
        else:
            t.append(round(float(d.mean()), 4))
        measured += 1
    if trees:
        vals = [t[2] for t in trees if len(t) > 2 and t[2] is not None]
        print(
            f"    trees {measured}/{len(trees)} measured"
            f" | mean crown cover {100 * (sum(vals) / len(vals)):.1f}%"
            if vals
            else f"    trees {measured}/{len(trees)} measured"
        )

    # -- provenance ---------------------------------------------------------------------
    assumptions = data.setdefault("assumptions", {})
    assumptions.pop("canopy_fraction_by_class", None)
    data["canopy"] = {
        "source": "meta_wri_canopy_height_v6",
        "product": "alsgedi_global_v6_float/chm",
        "tile_quadkey": tiles_for_bbox(data["bbox"])[0],
        "window": "widened to the extent of the fetched features, not the city bbox",
        "resolution_m": round(win.px_m, 3),
        "canopy_height_threshold_m": CANOPY_HEIGHT_M,
        "tree_sample_radius_m": TREE_RADIUS_M,
        "path_buffer_m": PATH_BUFFER_M,
        "city_canopy_fraction": round(float(win.canopy.mean()), 4),
        "window_pixels": int(total_px),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "license": LICENSE,
        "note": (
            "Canopy fractions are counted pixels of vegetation at least "
            f"{CANOPY_HEIGHT_M:.0f} m tall, not per-class estimates."
        ),
    }
    note = assumptions.get("note", "")
    assumptions["note"] = (
        "Surface temperature boost per class remains estimated; canopy is now measured "
        "(see the `canopy` block)."
        if "surface_boost_by_class_f" in assumptions
        else note
    )

    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"    {dict(sorted(stats.items()))}")
    print(f"    wrote {path.name} in {time.time() - started:.1f}s")


def main() -> None:
    cities = sys.argv[1:] or [p.stem for p in sorted(URBAN_DIR.glob("*.json"))]
    for city in cities:
        process(city)


if __name__ == "__main__":
    main()
