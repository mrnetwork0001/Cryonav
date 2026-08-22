#!/usr/bin/env python
"""Fetch the real pedestrian street network for each Cryonav tile from OpenStreetMap.

    python scripts/fetch_streets.py [city ...]

Queries Overpass for walkable ways inside the FortyGuard coverage bbox, collapses
degree-2 chains into single edges (keeping their true geometry, simplified to ~5 m),
and writes data/streets/<city>.json. The files are committed: routing must work at
demo time with no network and reproduce byte-for-byte.

No osmnx/geopandas — the routing engine only needs nodes, edges and lengths, and a
direct Overpass query keeps the dependency footprint at 'httpx'.
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
from thermal import haversine_m  # noqa: E402

OUT_DIR = ROOT / "data" / "streets"

#: Ways a pedestrian can use. Motorways/trunks excluded outright; everything else in a
#: downtown grid either has sidewalks or is itself the walking surface.
WALKABLE = (
    "footway|path|pedestrian|living_street|steps|track|cycleway|residential|"
    "service|unclassified|tertiary|tertiary_link|secondary|secondary_link|"
    "primary|primary_link"
)

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

#: Douglas-Peucker simplification tolerance for edge geometry, metres.
SIMPLIFY_M = 5.0


def overpass(bbox: dict) -> dict:
    query = f"""
[out:json][timeout:120];
way["highway"~"^({WALKABLE})$"]["foot"!~"no"]["access"!~"private"]
  ({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
(._;>;);
out body;
"""
    last = None
    for url in MIRRORS:
        try:
            print(f"  querying {url.split('/')[2]} …", flush=True)
            r = httpx.post(
                url,
                data={"data": query},
                headers={"User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26 project)"},
                timeout=180.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"    mirror failed: {exc}")
            time.sleep(2)
    raise SystemExit(f"all Overpass mirrors failed: {last}")


def simplify(points, tol_m):
    """Iterative Douglas-Peucker on (lat, lon) points."""
    if len(points) < 3:
        return points
    # local equirectangular metres
    k = math.cos(math.radians(points[0][0]))

    def xy(p):
        return (p[1] * 111320.0 * k, p[0] * 110574.0)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy(points[a])
        bx, by = xy(points[b])
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        worst, wd = -1, tol_m
        for i in range(a + 1, b):
            px, py = xy(points[i])
            if seg2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > wd:
                worst, wd = i, d
        if worst >= 0:
            keep[worst] = True
            stack.append((a, worst))
            stack.append((worst, b))
    return [p for p, k_ in zip(points, keep) if k_]


def build(city_id: str, svc: FortyGuardService) -> dict:
    bbox = svc.bounds(city_id)
    raw = overpass(bbox)

    nodes = {}
    ways = []
    for el in raw.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way":
            ways.append(el)
    print(f"  raw: {len(nodes)} nodes, {len(ways)} walkable ways")

    # Node degree across ways → intersections are nodes used by >1 way or >1 time.
    use = {}
    for w in ways:
        nds = [n for n in w["nodes"] if n in nodes]
        for i, n in enumerate(nds):
            # endpoints always count as junction candidates
            use[n] = use.get(n, 0) + (2 if i in (0, len(nds) - 1) else 1)
    junction = {n for n, c in use.items() if c >= 2}

    # Split ways at junctions into edges; collapse interior geometry.
    out_nodes = {}  # osm id -> compact index
    node_list = []
    edges = []

    def idx(n):
        if n not in out_nodes:
            out_nodes[n] = len(node_list)
            node_list.append([round(nodes[n][0], 6), round(nodes[n][1], 6)])
        return out_nodes[n]

    for w in ways:
        hw = w.get("tags", {}).get("highway", "unclassified")
        nds = [n for n in w["nodes"] if n in nodes]
        if len(nds) < 2:
            continue
        start = 0
        for i in range(1, len(nds)):
            if nds[i] in junction or i == len(nds) - 1:
                chain = nds[start : i + 1]
                pts = [nodes[n] for n in chain]
                length = sum(haversine_m(pts[j], pts[j + 1]) for j in range(len(pts) - 1))
                if length >= 3.0:
                    geom = simplify(pts, SIMPLIFY_M)
                    edges.append(
                        {
                            "a": idx(chain[0]),
                            "b": idx(chain[-1]),
                            "len": round(length, 1),
                            "hw": hw,
                            "geom": [[round(la, 6), round(lo, 6)] for la, lo in geom],
                        }
                    )
                start = i

    # Keep only the largest connected component — Overpass clips at the bbox, leaving
    # orphan fragments that would make nearest-node snapping route into a dead island.
    adj = {}
    for i, e in enumerate(edges):
        adj.setdefault(e["a"], []).append((e["b"], i))
        adj.setdefault(e["b"], []).append((e["a"], i))
    seen = set()
    best_comp = set()
    for root in adj:
        if root in seen:
            continue
        comp = {root}
        stack = [root]
        seen.add(root)
        while stack:
            u = stack.pop()
            for v, _ in adj.get(u, []):
                if v not in seen:
                    seen.add(v)
                    comp.add(v)
                    stack.append(v)
        if len(comp) > len(best_comp):
            best_comp = comp
    kept = [e for e in edges if e["a"] in best_comp]
    print(f"  compact: {len(node_list)} nodes, {len(edges)} edges -> {len(kept)} in main component")

    # Reindex after component filter.
    remap = {}
    final_nodes = []
    for e in kept:
        for key in ("a", "b"):
            old = e[key]
            if old not in remap:
                remap[old] = len(final_nodes)
                final_nodes.append(node_list[old])
            e[key] = remap[old]

    return {
        "city_id": city_id,
        "source": "openstreetmap_overpass",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": bbox,
        "node_count": len(final_nodes),
        "edge_count": len(kept),
        "nodes": final_nodes,
        "edges": kept,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
