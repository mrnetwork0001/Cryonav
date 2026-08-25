"""
Real urban thermal form, from OpenStreetMap geometry.

:class:`UrbanIndex` turns the per-city ``data/urban/<city>.json`` produced by
``scripts/fetch_urban.py`` into an O(1)-per-query terrain oracle: given a point, how much
real canopy shades it, how much real asphalt surrounds it, which real road ribbon it walks
along. This replaces the hand-authored gaussian fixtures with observed geometry -- parks,
individual street trees, covered walkways, surface parking lots, industrial land and
lane-counted arterials.

What stays estimated (and is labelled as such in the data files): per-class canopy density
and per-class surface heat boost. OSM records *where* a park or a parking lot is, not its
leaf density or its afternoon surface temperature; those coefficients are the model's, applied
to real shapes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Spatial-hash cell size, degrees (~220 m). Features register in every cell their
#: geometry touches (padded by their influence radius), so a query only inspects one cell.
CELL_DEG = 0.002

#: Influence falloffs, metres.
GREEN_EDGE_DECAY_M = 60.0     # park cooling reaches beyond its fence
TREE_RADIUS_M = 45.0          # street trees within this radius shade a sidewalk point
COVERED_NEAR_M = 12.0         # covered walkway counts when the path itself is walked
TREE_ROW_NEAR_M = 14.0
WATER_DECAY_M = 80.0
HOT_EDGE_DECAY_M = 40.0

#: A tree's canopy contribution saturates: ~6 well-placed trees give full street shade.
TREE_CANOPY_PER_TREE = 0.14
TREE_COOLING_PER_TREE = 0.7
TREE_COOLING_CAP_F = 4.5


def _project(lat: float, lon: float, k: float) -> Tuple[float, float]:
    return lon * 111_320.0 * k, lat * 110_574.0


class UrbanIndex:
    """Spatial index over one city's real urban features."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.city_id = data["city_id"]
        # Whether this city's tree points carry measured crown cover (from
        # scripts/fetch_canopy.py) or the old placeholder weight. It decides how nearby trees
        # are combined -- max for measurements, saturating sum for counts.
        self._trees_measured = bool(data.get("canopy", {}).get("source"))
        self.fetched_at = data.get("fetched_at")
        self.data = data
        self._k = math.cos(math.radians(data["bbox"]["south"]))
        # cell -> list of (kind, feature_index)
        self._cells: Dict[Tuple[int, int], List[Tuple[str, int]]] = {}
        self._register_polys("green", data.get("green", []), GREEN_EDGE_DECAY_M)
        self._register_polys("hot", data.get("hot", []), HOT_EDGE_DECAY_M)
        self._register_polys("water", data.get("water", []), WATER_DECAY_M)
        self._register_lines("roads", data.get("roads", []), pad_m=40.0)
        self._register_lines("covered", data.get("covered_ways", []), pad_m=30.0)
        self._register_lines("tree_rows", data.get("tree_rows", []), pad_m=30.0)
        self._register_trees(data.get("trees", []))

    # ------------------------------------------------------------------ registration --
    def _cells_for_bbox(self, lat0, lon0, lat1, lon1, pad_m):
        pad_lat = pad_m / 110_574.0
        pad_lon = pad_m / (111_320.0 * self._k)
        r0 = int((lat0 - pad_lat) / CELL_DEG)
        r1 = int((lat1 + pad_lat) / CELL_DEG)
        c0 = int((lon0 - pad_lon) / CELL_DEG)
        c1 = int((lon1 + pad_lon) / CELL_DEG)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                yield (r, c)

    def _register_polys(self, kind: str, feats: List[Dict], pad_m: float) -> None:
        for i, f in enumerate(feats):
            ring = f["ring"]
            lats = [p[0] for p in ring]
            lons = [p[1] for p in ring]
            for cell in self._cells_for_bbox(min(lats), min(lons), max(lats), max(lons), pad_m):
                self._cells.setdefault(cell, []).append((kind, i))

    def _register_lines(self, kind: str, feats: List[Dict], pad_m: float) -> None:
        for i, f in enumerate(feats):
            path = f["path"]
            pad = max(pad_m, f.get("width_m", 0.0))
            for a, b in zip(path, path[1:]):
                for cell in self._cells_for_bbox(
                    min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]), pad
                ):
                    bucket = self._cells.setdefault(cell, [])
                    if not bucket or bucket[-1] != (kind, i):
                        bucket.append((kind, i))

    def _register_trees(self, trees: List[Sequence[float]]) -> None:
        # Trees are numerous (8.6k in Phoenix); store per-cell point lists directly.
        self._tree_cells: Dict[Tuple[int, int], List[Tuple[float, float, float]]] = {}
        for t in trees:
            cell = (int(t[0] / CELL_DEG), int(t[1] / CELL_DEG))
            self._tree_cells.setdefault(cell, []).append((t[0], t[1], t[2] if len(t) > 2 else 1.0))

    # ----------------------------------------------------------------------- geometry --
    def _point_in_ring(self, px: float, py: float, ring_xy: List[Tuple[float, float]]) -> bool:
        inside = False
        n = len(ring_xy)
        j = n - 1
        for i in range(n):
            xi, yi = ring_xy[i]
            xj, yj = ring_xy[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi:
                inside = not inside
            j = i
        return inside

    def _ring_xy(self, f: Dict) -> List[Tuple[float, float]]:
        cached = f.get("_xy")
        if cached is None:
            cached = [_project(p[0], p[1], self._k) for p in f["ring"]]
            f["_xy"] = cached
        return cached

    def _path_xy(self, f: Dict) -> List[Tuple[float, float]]:
        cached = f.get("_xy")
        if cached is None:
            cached = [_project(p[0], p[1], self._k) for p in f["path"]]
            f["_xy"] = cached
        return cached

    @staticmethod
    def _dist_to_segments(px: float, py: float, xy: List[Tuple[float, float]]) -> float:
        best = float("inf")
        for (ax, ay), (bx, by) in zip(xy, xy[1:]):
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d < best:
                best = d
        return best

    # -------------------------------------------------------------------------- query --
    def terrain(self, lat: float, lon: float) -> Dict[str, Any]:
        """Urban-morphology inputs at a point, from real geometry.

        Returns the same keys as the legacy hand-authored terrain so the thermal sampler
        is source-agnostic: canopy_fraction, canopy_cooling_f, sky_view_factor,
        uhi_uplift_f, surface_boost_f, water_cooling_f, humidity_boost_pct, surface_type.
        """
        px, py = _project(lat, lon, self._k)
        cell = (int(lat / CELL_DEG), int(lon / CELL_DEG))

        canopy = 0.0
        canopy_cool = 0.0
        near_road = 0.0
        # Measured surface anomalies are AVERAGED, never summed. An anomaly says "this place
        # runs N degrees hotter than a typical road"; five overlapping roads each at -3.5 F
        # describe one location that is 3.5 F cool, not one that is 17.5 F cool. The unmeasured
        # fallbacks below are additive contributions and still accumulate into surface_boost.
        anom_num = 0.0
        anom_den = 0.0
        covered = 0.0
        uhi = 0.0
        surface_boost = 0.0
        water_cool = 0.0
        humidity_boost = 0.0
        on_arterial = 0.0

        seen: set = set()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for kind, i in self._cells.get((cell[0] + dr, cell[1] + dc), ()):
                    if (kind, i) in seen:
                        continue
                    seen.add((kind, i))

                    if kind == "green":
                        f = self.data["green"][i]
                        xy = self._ring_xy(f)
                        if self._point_in_ring(px, py, xy):
                            w = 1.0
                        else:
                            d = self._dist_to_segments(px, py, xy + xy[:1])
                            w = math.exp(-((d / GREEN_EDGE_DECAY_M) ** 2))
                        if w > 0.02:
                            canopy = max(canopy, f["canopy"] * w)
                            # Bigger parks cool harder; ln keeps a pocket park honest.
                            strength = min(2.0 + 1.1 * math.log1p(f["area_m2"] / 2000.0), 8.5)
                            canopy_cool += strength * w

                    elif kind == "hot":
                        f = self.data["hot"][i]
                        xy = self._ring_xy(f)
                        if self._point_in_ring(px, py, xy):
                            w = 1.0
                        else:
                            d = self._dist_to_segments(px, py, xy + xy[:1])
                            w = math.exp(-((d / HOT_EDGE_DECAY_M) ** 2))
                        if w > 0.02:
                            if f.get("lst_measured") or f.get("lst_source"):
                                anom_num += f["boost_f"] * w
                                anom_den += w
                            else:
                                surface_boost += f["boost_f"] * w
                            uhi += min(1.5 + f["area_m2"] / 25000.0, 4.0) * w

                    elif kind == "water":
                        f = self.data["water"][i]
                        xy = self._ring_xy(f)
                        if self._point_in_ring(px, py, xy):
                            w = 1.0
                        else:
                            d = self._dist_to_segments(px, py, xy + xy[:1])
                            w = math.exp(-((d / WATER_DECAY_M) ** 2))
                        if w > 0.02:
                            water_cool += 3.5 * w
                            humidity_boost += 8.0 * w

                    elif kind == "roads":
                        f = self.data["roads"][i]
                        d = self._dist_to_segments(px, py, self._path_xy(f))
                        half = f["width_m"] / 2.0
                        if d <= half:
                            w = 1.0
                        else:
                            w = math.exp(-(((d - half) / 25.0) ** 2))
                        if w > 0.02:
                            lanes = f.get("lanes", 2)
                            # Measured Landsat anomaly for THIS road where available. The
                            # lane-count fallback below is a proxy for road width, which is a
                            # proxy for exposure -- two inferences deep. The measurement is
                            # relative to the city's own road median, so a typical road
                            # contributes 0 and asphalt_uplift_f alone carries it.
                            if f.get("lst_measured"):
                                # Clamped at zero, and not for tidiness: a road measuring
                                # COOLER than the city's road median is almost always cooler
                                # because it is shaded -- and sky_view_factor already applies
                                # that shade to the whole spike. Letting the negative through
                                # would discount the same canopy twice. Positive anomalies
                                # survive, since those are material (dark, dense, low-albedo
                                # surface in full sun) and nothing else in the model sees them.
                                anom_num += max(0.0, f["lst_anomaly_f"]) * w
                                anom_den += w
                            else:
                                surface_boost += (6.0 + 1.6 * lanes) * w
                            uhi += min(0.35 * lanes, 2.5) * w
                            near_road = max(near_road, w)
                            if lanes >= 4:
                                on_arterial = max(on_arterial, w)

                    elif kind == "covered":
                        f = self.data["covered_ways"][i]
                        d = self._dist_to_segments(px, py, self._path_xy(f))
                        w = math.exp(-((d / COVERED_NEAR_M) ** 2))
                        if w > 0.05:
                            covered = max(covered, w)
                            # A roofed arcade blocks sky regardless of vegetation, so the
                            # structural 0.92 stands; the measurement only raises it where
                            # trees overhang the arcade too.
                            over = max(0.92, f["canopy"]) if f.get("canopy_measured") else 0.92
                            canopy = max(canopy, over * w)
                            canopy_cool += 5.0 * w

                    elif kind == "tree_rows":
                        f = self.data["tree_rows"][i]
                        d = self._dist_to_segments(px, py, self._path_xy(f))
                        w = math.exp(-((d / TREE_ROW_NEAR_M) ** 2))
                        if w > 0.05:
                            frac = f["canopy"] if f.get("canopy_measured") else 0.68
                            canopy = max(canopy, frac * w)
                            canopy_cool += 3.0 * (frac / 0.68) * w

        # Individual street trees. Two aggregations, because the two data shapes mean
        # different things:
        #
        #   measured   `wgt` is the canopy fraction actually observed within 8 m of that
        #              trunk, so nearby trees are combined by MAX -- their crowns overlap and
        #              each measurement already counts its neighbours' shade. Summing would
        #              count the same pixels once per tree.
        #   unmeasured `wgt` is a placeholder count, so the old saturating sum stands.
        tree_weight = 0.0
        measured_canopy = 0.0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for tlat, tlon, wgt in self._tree_cells.get((cell[0] + dr, cell[1] + dc), ()):
                    tx, ty = _project(tlat, tlon, self._k)
                    d = math.hypot(px - tx, py - ty)
                    if d > TREE_RADIUS_M:
                        continue
                    prox = 1.0 - d / TREE_RADIUS_M
                    if wgt is None:
                        continue
                    if self._trees_measured:
                        measured_canopy = max(measured_canopy, wgt * prox)
                    else:
                        tree_weight += wgt * prox
        if measured_canopy > 0:
            canopy = max(canopy, min(0.85, measured_canopy))
            canopy_cool += min(TREE_COOLING_CAP_F * measured_canopy / 0.5, TREE_COOLING_CAP_F)
        elif tree_weight > 0:
            canopy = max(canopy, min(0.85, TREE_CANOPY_PER_TREE * tree_weight))
            canopy_cool += min(TREE_COOLING_PER_TREE * tree_weight, TREE_COOLING_CAP_F)

        if anom_den > 0:
            surface_boost += anom_num / anom_den

        return {
            "canopy_fraction": min(canopy, 0.95),
            "canopy_cooling_f": canopy_cool,   # soft-capped by the caller
            "covered": covered,
            "uhi_uplift_f": uhi,
            "surface_boost_f": surface_boost,
            "water_cooling_f": water_cool,
            "humidity_boost_pct": humidity_boost,
            "arterial": on_arterial,
            "near_road": near_road,
        }


# --------------------------------------------------------------------------------------
# Loading + display derivation
# --------------------------------------------------------------------------------------


def load_urban_index(urban_dir: Path, city_id: str) -> Optional[UrbanIndex]:
    path = urban_dir / f"{city_id}.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get("city_id") != city_id or not data.get("bbox"):
        return None
    return UrbanIndex(data)


def _centroid(ring: List[List[float]]) -> List[float]:
    return [
        round(sum(p[0] for p in ring) / len(ring), 6),
        round(sum(p[1] for p in ring) / len(ring), 6),
    ]


def display_layers(idx: UrbanIndex, limit_zones: int = 80, limit_lines: int = 150) -> Dict[str, Any]:
    """Shape the real features into the structures the map already renders.

    Zones become centre+radius circles (radius from true area), lines keep their real
    polylines. Counts are capped for payload size, largest features first, and the caps
    are reported so truncation is never silent.
    """
    d = idx.data
    green = sorted(d.get("green", []), key=lambda f: -f["area_m2"])[:limit_zones]
    hot = sorted(d.get("hot", []), key=lambda f: -f["area_m2"])[:limit_zones]
    roads = sorted(
        (r for r in d.get("roads", []) if r.get("lanes", 0) >= 4),
        key=lambda r: -r.get("lanes", 0),
    )[:limit_lines]
    corridors = (d.get("covered_ways", []) + d.get("tree_rows", []))[:limit_lines]

    return {
        "source": "openstreetmap",
        "fetched_at": d.get("fetched_at"),
        "attribution": d.get("license"),
        "truncation": {
            "green_shown": len(green), "green_total": len(d.get("green", [])),
            "hot_shown": len(hot), "hot_total": len(d.get("hot", [])),
            "roads_shown": len(roads),
            "roads_total": sum(1 for r in d.get("roads", []) if r.get("lanes", 0) >= 4),
        },
        "canopy_zones": [
            {
                "name": f.get("name") or f"{f['class'].replace('_', ' ').title()}",
                "center": _centroid(f["ring"]),
                "radius_m": round(math.sqrt(f["area_m2"] / math.pi), 1),
                "canopy_pct": round(f["canopy"] * 100),
            }
            for f in green
        ],
        "heat_islands": [
            {
                "name": f.get("name") or f"{f['class'].title()} surface",
                "center": _centroid(f["ring"]),
                "radius_m": round(math.sqrt(f["area_m2"] / math.pi), 1),
                "surface_boost_f": f["boost_f"],
            }
            for f in hot
        ],
        "heat_corridors": [
            {
                "name": r.get("name") or f"{r.get('lanes', '?')}-lane arterial",
                "path": r["path"],
                "width_m": r["width_m"],
                "lanes": r.get("lanes"),
            }
            for r in roads
        ],
        "canopy_corridors": [
            {"name": c.get("name") or "Covered walkway", "path": c["path"], "width_m": 14}
            for c in corridors
        ],
        "water_bodies": [
            {
                "name": w.get("name") or "Water",
                "center": _centroid(w["ring"]),
                "radius_m": round(math.sqrt(w["area_m2"] / math.pi), 1),
            }
            for w in d.get("water", [])
        ],
        "tree_count": len(d.get("trees", [])),
    }
