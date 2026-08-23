#!/usr/bin/env python
"""Fetch REAL urban thermal-form data from OpenStreetMap for each Cryonav tile.

    python scripts/fetch_urban.py [city ...]

Replaces the hand-authored canopy/heat fixtures with observed geometry:
  cool  — park/garden/green polygons, individual street trees, tree rows,
          covered pedestrian ways, water polygons
  hot   — surface parking lots, industrial/commercial/retail land, major-road
          ribbons (with real lane counts), railway land

Writes data/urban/<city>.json (committed — offline & deterministic at demo time).
Uses the maps.mail.ru Overpass mirror first: recon measured overpass-api.de
rate-limiting this IP, and the mirror served identical same-day data.
"""

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from fortyguard_service import FortyGuardService  # noqa: E402

OUT_DIR = ROOT / "data" / "urban"
UA = {"User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26 project)"}
MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

#: Canopy fraction assumed per green-feature class (OSM carries no density data — recon
#: verified zero height/diameter_crown tags in all three tiles). Estimates, labelled as such.
GREEN_CANOPY = {
    "park": 0.60, "garden": 0.65, "forest": 0.85, "wood": 0.85, "orchard": 0.70,
    "grass": 0.25, "meadow": 0.25, "village_green": 0.40, "scrub": 0.35,
}

#: Surface-boost (deg F above ambient surface) assumed per hot-surface class.
HOT_BOOST = {
    "parking": 16.0, "industrial": 14.0, "retail": 11.0, "commercial": 9.0, "railway": 12.0,
}


def q(query: str, tries: int = 4) -> dict:
    last = None
    for attempt in range(tries):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = httpx.post(url, data={"data": query}, headers=UA, timeout=240.0)
            if r.status_code == 200:
                return r.json()
            last = f"{url}: HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = f"{url}: {exc}"
        print(f"    retry ({last})", flush=True)
        time.sleep(15 + attempt * 10)
    raise SystemExit(f"overpass failed after {tries} tries: {last}")


def ring_of(el):
    g = el.get("geometry") or []
    return [[round(p["lat"], 6), round(p["lon"], 6)] for p in g]


def simplify_ring(pts, keep_every_m=12.0):
    """Cheap decimation: keep points at least ~keep_every_m apart (rings are display/terrain
    aids, not survey data). Always keeps first/last."""
    if len(pts) <= 8:
        return pts
    out = [pts[0]]
    k = 111_320.0 * math.cos(math.radians(pts[0][0]))
    for p in pts[1:-1]:
        prev = out[-1]
        d = math.hypot((p[1] - prev[1]) * k, (p[0] - prev[0]) * 110_574.0)
        if d >= keep_every_m:
            out.append(p)
    out.append(pts[-1])
    return out


def area_m2(ring):
    if len(ring) < 3:
        return 0.0
    k = 111_320.0 * math.cos(math.radians(ring[0][0]))
    xs = [(p[1] * k, p[0] * 110_574.0) for p in ring]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(xs, xs[1:] + xs[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def build(city_id: str, svc: FortyGuardService) -> dict:
    b = svc.bounds(city_id)
    bbox = f"({b['south']},{b['west']},{b['north']},{b['east']})"

    # ---------------- cool features ----------------
    print("  green polygons …", flush=True)
    green_raw = q(f"""[out:json][timeout:120];
( way["leisure"~"^(park|garden)$"]{bbox}; relation["leisure"~"^(park|garden)$"]{bbox};
  way["landuse"~"^(grass|forest|orchard|meadow|village_green)$"]{bbox};
  way["natural"~"^(wood|scrub)$"]{bbox}; );
out tags geom;""")
    green = []
    for el in green_raw.get("elements", []):
        ring = simplify_ring(ring_of(el))
        if len(ring) < 3:
            continue
        tags = el.get("tags", {})
        cls = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "park"
        a = area_m2(ring)
        if a < 400:  # sub-20x20m patches don't shade a street
            continue
        green.append({
            "name": tags.get("name"),
            "class": cls,
            "canopy": GREEN_CANOPY.get(cls, 0.4),
            "area_m2": round(a),
            "ring": ring,
        })
    print(f"    {len(green)} polygons kept")

    time.sleep(8)
    print("  trees / tree rows / covered ways / water …", flush=True)
    # Trees need `out body` — `out tags` omits node coordinates entirely.
    misc_raw = q(f"""[out:json][timeout:120];
node["natural"="tree"]{bbox};
out body;
( way["natural"="tree_row"]{bbox};
  way["highway"~"^(footway|pedestrian|path|steps)$"]["covered"="yes"]{bbox};
  way["highway"~"^(footway|pedestrian|path)$"]["tunnel"="building_passage"]{bbox};
  way["natural"="water"]{bbox}; relation["natural"="water"]{bbox}; );
out tags geom;""")
    trees, tree_rows, covered, water = [], [], [], []
    for el in misc_raw.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "node" and tags.get("natural") == "tree" and "lat" in el:
            # palms cast almost no usable shade (recon: Dubai flags them via leaf_type)
            weight = 0.35 if tags.get("leaf_type") == "palm" else 1.0
            trees.append([round(el["lat"], 6), round(el["lon"], 6), weight])
        elif tags.get("natural") == "tree_row":
            pts = simplify_ring(ring_of(el), 10.0)
            if len(pts) >= 2:
                tree_rows.append({"name": tags.get("name"), "path": pts})
        elif tags.get("natural") == "water" or tags.get("type") == "multipolygon" and "water" in str(tags):
            ring = simplify_ring(ring_of(el))
            if len(ring) >= 3 and area_m2(ring) > 900:
                water.append({"name": tags.get("name"), "ring": ring, "area_m2": round(area_m2(ring))})
        elif tags.get("covered") == "yes" or tags.get("tunnel") == "building_passage":
            pts = simplify_ring(ring_of(el), 10.0)
            if len(pts) >= 2:
                covered.append({"name": tags.get("name"), "path": pts})
    print(f"    {len(trees)} trees, {len(tree_rows)} tree rows, {len(covered)} covered ways, {len(water)} water polygons")

    # ---------------- hot features ----------------
    time.sleep(8)
    print("  hot surfaces …", flush=True)
    # Abu Dhabi's lots are 98% missing the parking= subtag (recon-measured); everywhere,
    # at-grade is the default and only structured/underground parking must be excluded.
    hot_raw = q(f"""[out:json][timeout:120];
( way["amenity"="parking"]["parking"!~"^(underground|multi-storey|rooftop)$"]{bbox};
  way["landuse"~"^(industrial|retail|commercial|railway)$"]{bbox};
  relation["landuse"~"^(industrial|retail|commercial|railway)$"]{bbox}; );
out tags geom;""")
    hot = []
    for el in hot_raw.get("elements", []):
        ring = simplify_ring(ring_of(el))
        if len(ring) < 3:
            continue
        tags = el.get("tags", {})
        cls = "parking" if tags.get("amenity") == "parking" else tags.get("landuse", "commercial")
        a = area_m2(ring)
        if a < 600:
            continue
        hot.append({
            "name": tags.get("name"),
            "class": cls,
            "boost_f": HOT_BOOST.get(cls, 9.0),
            "area_m2": round(a),
            "ring": ring,
        })
    print(f"    {len(hot)} hot polygons kept")

    time.sleep(8)
    print("  major road ribbons …", flush=True)
    roads_raw = q(f"""[out:json][timeout:120];
way["highway"~"^(primary|secondary|trunk|primary_link|secondary_link|trunk_link)$"]{bbox};
out tags geom;""")
    roads = []
    for el in roads_raw.get("elements", []):
        pts = simplify_ring(ring_of(el), 15.0)
        if len(pts) < 2:
            continue
        tags = el.get("tags", {})
        try:
            lanes = int(str(tags.get("lanes", "2")).split(";")[0])
        except ValueError:
            lanes = 2
        # Ribbon half-width from real lane count (3.4 m lanes + shoulders); dual
        # carriageways appear as separate ways, so this is per-roadbed.
        roads.append({
            "name": tags.get("name"),
            "lanes": lanes,
            "width_m": round(lanes * 3.4 + 6.0, 1),
            "path": pts,
        })
    print(f"    {len(roads)} road ribbons")

    return {
        "city_id": city_id,
        "source": "openstreetmap_overpass",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": b,
        "assumptions": {
            "canopy_fraction_by_class": GREEN_CANOPY,
            "surface_boost_by_class_f": HOT_BOOST,
            "note": "OSM carries no canopy density or surface temperature; per-class values are estimates applied to real geometry.",
        },
        "green": green,
        "trees": trees,
        "tree_rows": tree_rows,
        "covered_ways": covered,
        "water": water,
        "hot": hot,
        "roads": roads,
        "license": "Map data (c) OpenStreetMap contributors, ODbL",
    }


def main() -> int:
    svc = FortyGuardService()
    targets = sys.argv[1:] or svc.city_ids()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for city_id in targets:
        print(f"→ {city_id}")
        data = build(city_id, svc)
        path = OUT_DIR / f"{city_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        print(f"  wrote {path} ({path.stat().st_size // 1024} KB)")
        time.sleep(10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
