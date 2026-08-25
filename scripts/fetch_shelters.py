#!/usr/bin/env python
"""Fetch REAL cooling-refuge data for each Cryonav tile.

    python scripts/fetch_shelters.py [city ...]

Phoenix - the OFFICIAL Maricopa Association of Governments "Heat Relief Network"
ArcGIS feature service (public, anonymous): actual municipal cooling centers,
hydration stations and respite sites for the 2026 season, with per-day hours.
MAG disclaims accuracy; attribution + disclaimer are stored with the data.

Dubai / Abu Dhabi - no official machine-readable network exists; real OSM POIs
stand in: mosques (cooled, open through prayer times), malls, souks, cooled
Dubai Metro stations, and public drinking water. Air-conditioning is assumed
by category (the tag exists on ~1 POI region-wide) and flagged `assumed`.

Writes data/shelters/<city>.json.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from fortyguard_service import FortyGuardService  # noqa: E402

OUT_DIR = ROOT / "data" / "shelters"
UA = {"User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26 project)"}

MAG_URL = (
    "https://services1.arcgis.com/MdyCMZnX1raZ7TS3/arcgis/rest/services/"
    "HRN_Public_view/FeatureServer/0/query"
)

MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: Category defaults where the source has no hours/AC data. Assumptions, stored as such.
CATEGORY_DEFAULTS = {
    "mosque": {"type": "cooling_center", "ac": True, "hours": "04:30-22:00", "indoor_f": 74},
    "mall": {"type": "mall_refuge", "ac": True, "hours": "10:00-23:00", "indoor_f": 71},
    "marketplace": {"type": "mall_refuge", "ac": True, "hours": "09:00-22:00", "indoor_f": 75},
    "metro": {"type": "cooled_transit", "ac": True, "hours": "05:00-00:00", "indoor_f": 73},
    "library": {"type": "cooling_center", "ac": True, "hours": "09:00-18:00", "indoor_f": 72},
    "community_centre": {"type": "cooling_center", "ac": True, "hours": "08:00-20:00", "indoor_f": 73},
    "drinking_water": {"type": "hydration_station", "ac": False, "hours": "24/7", "indoor_f": None},
}


def fetch_phoenix(svc: FortyGuardService) -> dict:
    b = svc.bounds("phoenix")
    params = {
        "where": "Year=2026 AND Active='Yes'",
        "geometry": f"{b['west']},{b['south']},{b['east']},{b['north']}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "f": "geojson",
    }
    r = httpx.get(MAG_URL, params=params, headers=UA, timeout=60.0)
    r.raise_for_status()
    fc = r.json()

    type_map = {
        "Cooling Center": "cooling_center",
        "Respite Center": "cooling_center",
        "Hydration Station": "hydration_station",
    }
    shelters = []
    for i, f in enumerate(fc.get("features", [])):
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"][:2]
        name = (p.get("Location") or p.get("Organization") or "Heat Relief Site").strip()
        hrs = {d: [p.get(f"{d}Open"), p.get(f"{d}Close")] for d in DAYS if p.get(f"{d}Open")}
        kind = type_map.get((p.get("HeatRelief_Type") or "").strip(), "cooling_center")
        shelters.append({
            "id": f"mag-{p.get('OBJECTID', i)}",
            "name": name,
            "type": kind,
            "center": [round(lat, 6), round(lon, 6)],
            "air_conditioned": kind != "hydration_station",
            "ac_assumed": False if kind != "hydration_station" else True,
            "water": True,
            "hours": p.get("Hours") or "; ".join(f"{d} {v[0]}-{v[1]}" for d, v in hrs.items()) or "see source",
            "hours_by_day": hrs or None,
            "season": [p.get("Start_Date"), p.get("End_Date")],
            "organization": (p.get("Organization") or "").strip() or None,
            "address": (p.get("Address") or "").strip() or None,
            "phone": (p.get("PrimaryPhone") or "").strip() or None,
            "wheelchair": p.get("Wheelchair_access") or p.get("ADA_accessible"),
            "pets": p.get("Pets"),
            "indoor_temp_f": 72 if kind != "hydration_station" else None,
            "indoor_temp_assumed": True,
        })
    return {
        "city_id": "phoenix",
        "source": "mag_heat_relief_network",
        "endpoint": MAG_URL,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attribution": "Maricopa Association of Governments Heat Relief Network",
        "disclaimer": (
            "MAG aggregates partner-submitted sites and cannot vouch for authenticity or "
            "accuracy; verify independently. Medical emergencies: call 911."
        ),
        "count": len(shelters),
        "shelters": shelters,
    }


def overpass(query: str) -> dict:
    last = None
    for attempt in range(4):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = httpx.post(url, data={"data": query}, headers=UA, timeout=180.0)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(15 + attempt * 10)
    raise SystemExit(f"overpass failed: {last}")


def fetch_gulf(city_id: str, svc: FortyGuardService) -> dict:
    b = svc.bounds(city_id)
    bbox = f"({b['south']},{b['west']},{b['north']},{b['east']})"
    raw = overpass(f"""[out:json][timeout:90];
( nwr["amenity"="place_of_worship"]["religion"="muslim"]{bbox};
  nwr["shop"="mall"]{bbox};
  nwr["amenity"="marketplace"]{bbox};
  nwr["amenity"="library"]{bbox};
  nwr["amenity"="community_centre"]{bbox};
  nwr["railway"="station"]["station"="subway"]{bbox};
  node["amenity"="drinking_water"]{bbox}; );
out tags center;""")

    shelters = []
    seen = set()
    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None:
            continue
        key = (round(lat, 5), round(lon, 5))
        if key in seen:
            continue
        seen.add(key)

        if tags.get("amenity") == "drinking_water":
            cat = "drinking_water"
            name = tags.get("name:en") or tags.get("name") or "Public drinking water"
        elif tags.get("station") == "subway":
            cat = "metro"
            name = (tags.get("name:en") or tags.get("name") or "Metro station") + " Metro Station"
        elif tags.get("shop") == "mall":
            cat = "mall"
            name = tags.get("name:en") or tags.get("name") or "Shopping mall"
        elif tags.get("amenity") == "marketplace":
            cat = "marketplace"
            name = tags.get("name:en") or tags.get("name") or "Covered market"
        elif tags.get("amenity") == "library":
            cat = "library"
            name = tags.get("name:en") or tags.get("name") or "Public library"
        elif tags.get("amenity") == "community_centre":
            cat = "community_centre"
            name = tags.get("name:en") or tags.get("name") or "Community centre"
        else:
            cat = "mosque"
            name = tags.get("name:en") or tags.get("name") or "Mosque"

        d = CATEGORY_DEFAULTS[cat]
        shelters.append({
            "id": f"osm-{el['type'][0]}{el['id']}",
            "name": name,
            "type": d["type"],
            "category": cat,
            "center": [round(lat, 6), round(lon, 6)],
            "air_conditioned": d["ac"],
            "ac_assumed": True,
            "water": cat in ("drinking_water", "mosque", "mall"),
            "hours": tags.get("opening_hours") or d["hours"],
            "hours_assumed": "opening_hours" not in tags,
            "indoor_temp_f": d["indoor_f"],
            "indoor_temp_assumed": d["indoor_f"] is not None,
        })

    # Hydration points everywhere is noise; keep enterable refuges + all water points.
    return {
        "city_id": city_id,
        "source": "openstreetmap_overpass",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attribution": "Map data (c) OpenStreetMap contributors, ODbL",
        "disclaimer": (
            "Air-conditioning and hours are category-level assumptions where OSM carries no "
            "tags (measured coverage: opening_hours 2-6%, air_conditioning ~0%)."
        ),
        "count": len(shelters),
        "shelters": shelters,
    }


def main() -> int:
    svc = FortyGuardService()
    targets = sys.argv[1:] or svc.city_ids()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for city_id in targets:
        print(f"→ {city_id}")
        data = fetch_phoenix(svc) if city_id == "phoenix" else fetch_gulf(city_id, svc)
        path = OUT_DIR / f"{city_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        types = {}
        for s in data["shelters"]:
            types[s["type"]] = types.get(s["type"], 0) + 1
        print(f"  {data['count']} shelters ({types}) from {data['source']} -> {path.name}")
        time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
