"""
Cryonav REST API.

FastAPI surface over the FortyGuard Temperature API(R) integration, the cool-routing engine
and the three-agent orchestrator. Also hosts the simulated NVIDIA Jetson edge endpoint used by
smart-city pedestrian kiosks and delivery-worker wearables.

Run:  uvicorn main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

import standards
import thermal
from agents import CryonavOrchestrator, EXTREME_AIR_TEMP_F
from fortyguard_service import (
    ENV_PARAMS_PATH,
    HEAT_INTELLIGENCE_PATH,
    SENSING_ELEVATION_M,
    FortyGuardService,
)
from routing_engine import PROFILES, RoutingEngine

API_PREFIX = "/api/v1"
VERSION = "1.0.0"

service = FortyGuardService()
engine = RoutingEngine(service)
orchestrator = CryonavOrchestrator(service, engine)


def _refresh_stale_calibration() -> None:
    """Re-pull FortyGuard data in the background when the cached day is not today.

    The systemd timer owns this in production; this hook covers laptops and freshly
    deployed hosts so "today's curve" is actually today's without a manual run. Failures
    are logged and ignored -- the app must serve the last good calibration regardless.
    """
    import threading
    from datetime import datetime, timezone

    if not service.live or os.getenv("CRYONAV_AUTO_CALIBRATE", "1") != "1":
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stale = [
        cid
        for cid in service.city_ids()
        if str((service.calibration(cid) or {}).get("date", ""))[:10] != today
    ]
    if not stale:
        return

    def run() -> None:
        for cid in stale:
            try:
                cal = service.calibrate_city(cid)
                print(f"[calibrate] {cid}: {cal['air_temp_min_f']}-{cal['air_temp_max_f']}F for {str(cal['date'])[:10]}")
            except Exception as exc:  # noqa: BLE001 - keep serving cached data
                print(f"[calibrate] {cid} FAILED: {exc}")
            try:
                hm = service.heatmap_fetch(cid)
                print(f"[calibrate] {cid} raster: {hm['tile_count']} tiles")
            except Exception as exc:  # noqa: BLE001 - raster coverage is US-only / flaky
                print(f"[calibrate] {cid} raster skipped: {exc}")
        # Invalidate hour-bucket graphs so new ambient curves take effect.
        engine._graphs.clear()

    threading.Thread(target=run, name="cryonav-calibrate", daemon=True).start()


def _warm_graphs() -> None:
    """Build each city's street graph off the request path.

    The first build pays real-terrain sampling over the whole OSM network (~5 s for
    Phoenix); warming in a background thread means no user request ever eats it.
    """
    import threading

    def run() -> None:
        for cid in service.city_ids():
            try:
                engine.graph(cid, 15.0)
            except Exception as exc:  # noqa: BLE001
                print(f"[warm] {cid} graph failed: {exc}")

    threading.Thread(target=run, name="cryonav-warm", daemon=True).start()


app = FastAPI(
    # Swagger moves under /api so that /docs can serve the human documentation site.
    # An API reference and a product manual are different documents for different
    # readers, and the reader who types /docs is almost never looking for OpenAPI.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",

    title="Cryonav",
    version=VERSION,
    description=(
        "Hyperlocal thermal navigation and microclimate cool-routing engine, "
        "powered by the FortyGuard Temperature API(R)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv(
            "CRYONAV_CORS_ORIGINS",
            "http://localhost:5180,http://127.0.0.1:5180,"
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
        ).split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup_refresh() -> None:
    _refresh_stale_calibration()
    _warm_graphs()


# --------------------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------------------


class LatLon(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)

    def as_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)


class HeatIntelligenceRequest(BaseModel):
    """Mirror of the upstream ``POST /v1/heat-intelligence`` contract."""

    locations: List[LatLon] = Field(..., min_length=1, max_length=256)
    city_id: Optional[str] = Field(None, description="Omit to auto-resolve from coordinates.")
    hour: float = Field(15.0, ge=0, lt=24, description="Local hour of day, 0-23.99.")
    prefer_live: bool = Field(
        False,
        description=(
            "Call FortyGuard per request instead of serving the calibrated local field. "
            "Off by default because the upstream is an asynchronous job queue whose latency "
            "is not bounded: the same two-point call was measured at 22 s and then at over "
            "120 s minutes apart. A synchronous HTTP endpoint cannot depend on that, so live "
            "is opt-in, capped at the first few points, and abandoned after "
            "25 s rather than left hanging. Results are memoised per "
            "coordinate per day, so a repeat is instant. sensing.live_points reports how many "
            "points were genuinely live; the feed says so when it had to fall back."
        ),
    )


class CoolRouteRequest(BaseModel):
    origin: LatLon
    destination: LatLon
    city_id: Optional[str] = None
    hour: float = Field(15.0, ge=0, lt=24)
    profile: str = Field("pedestrian", description="pedestrian | delivery_worker | elderly_vulnerable")
    allow_shelter_reroute: bool = True


class JetsonKioskRequest(BaseModel):
    """Lightweight request shape for an edge device with a constrained uplink."""

    origin: LatLon
    destination: LatLon
    city_id: Optional[str] = None
    hour: float = Field(15.0, ge=0, lt=24)
    profile: str = "pedestrian"
    device_id: str = Field("jetson-kiosk-001", max_length=64)
    max_polyline_points: int = Field(24, ge=4, le=128)


class SentinelMonitorRequest(BaseModel):
    position: LatLon
    city_id: Optional[str] = None
    hour: float = Field(15.0, ge=0, lt=24)
    profile: str = "pedestrian"
    dwell_minutes: float = Field(0.0, ge=0, le=600)
    moved_m: Optional[float] = Field(
        None, ge=0, description="Distance moved during the dwell window; drives immobility detection."
    )
    accuracy_m: Optional[float] = Field(
        None, ge=0, description="Reported GPS horizontal accuracy, carried into the alert."
    )
    notify: bool = Field(
        True, description="Set false to evaluate the escalation without sending a push alert."
    )


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _resolve_city(city_id: Optional[str], point: LatLon) -> str:
    if city_id:
        if city_id not in service.city_ids():
            raise HTTPException(404, f"unknown city '{city_id}'")
        return city_id
    return service.resolve_city(point.lat, point.lon)


def _decimate(points: List[List[float]], limit: int) -> List[List[float]]:
    """Uniformly thin a polyline to at most ``limit`` points, keeping both endpoints.

    Edge devices render on a small panel over a metered link; shipping 90 vertices when 24
    are visually identical is wasted bandwidth and battery.
    """
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    thinned = [points[int(round(i * step))] for i in range(limit)]
    thinned[-1] = points[-1]
    return thinned


# --------------------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------------------


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "Cryonav",
        "tagline": "Hyperlocal thermal navigation powered by the FortyGuard Temperature API(R)",
        "version": VERSION,
        "docs": "/docs",
        "endpoints": [
            f"{API_PREFIX}/health",
            f"{API_PREFIX}/meta",
            f"{API_PREFIX}/cities",
            f"{API_PREFIX}/cities/{{city_id}}/grid",
            f"{API_PREFIX}/fortyguard/heat-intelligence",
            f"{API_PREFIX}/navigate/cool-route",
            f"{API_PREFIX}/shelters/nearby",
            f"{API_PREFIX}/edge/jetson-kiosk",
            f"{API_PREFIX}/sentinel/monitor",
        ],
    }


@app.get(f"{API_PREFIX}/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": VERSION,
        "fortyguard": {
            "mode": service.mode,
            "live": service.live,
            # The endpoint the live path actually calls. It used to say heat_intelligence
            # while _call_live posted a shape that endpoint rejects; health reported the
            # intention rather than the behaviour.
            "endpoint": ENV_PARAMS_PATH,
            "elevation_m": SENSING_ELEVATION_M,
            "last_status": service.last_status.as_dict(),
        },
        "cities": service.city_ids(),
        "calibration": {
            cid: service.calibration_summary(cid) for cid in service.city_ids()
        },
    }


@app.get(f"{API_PREFIX}/meta")
def meta() -> Dict[str, Any]:
    """Everything the frontend needs to render legends, selectors and agent panels."""
    return {
        "profiles": [
            {
                "id": p["id"],
                "label": p["label"],
                "description": p["description"],
                "max_detour_ratio": p["max_detour_ratio"],
                "base_walk_speed_mps": p["base_walk_speed_mps"],
            }
            for p in PROFILES.values()
        ],
        "risk_levels": [
            {
                "level": lvl,
                "color": thermal.RISK_COLORS[lvl],
                "min_exposure_index_f": thermal.RISK_THRESHOLDS_F[lvl],
                "advisory": thermal.RISK_ADVISORY[lvl],
                "safe_exposure_minutes": thermal.SAFE_EXPOSURE_MINUTES[lvl],
            }
            for lvl in thermal.RISK_LEVELS
        ],
        "agents": orchestrator.roster,
        "thresholds": {
            "comfort_baseline_f": thermal.COMFORT_BASELINE_F,
            "survival_limit_f": thermal.SURVIVAL_LIMIT_F,
            "extreme_air_temp_f": EXTREME_AIR_TEMP_F,
        },
        # Provenance for every safety threshold, so a reader can check the numbers against
        # the published source rather than taking the app's word for them.
        "citations": standards.CITATIONS,
        "niosh_wbgt_limit_f": {
            "acclimatised": round(standards.niosh_wbgt_limit_f(acclimatised=True), 1),
            "unacclimatised": round(standards.niosh_wbgt_limit_f(acclimatised=False), 1),
            "metabolic_watts": standards.METABOLIC_WATTS_WALKING,
        },
        # Where the terrain numbers physically come from, per city, straight out of the data
        # files rather than a hand-written list that could drift from them.
        "observed_data": service.data_provenance(),
    }


# --------------------------------------------------------------------------------------
# Facts about the system, computed rather than quoted
# --------------------------------------------------------------------------------------

#: The two coordinates the landing page and the docs use to show that air temperature cannot
#: separate two streets. They are fixed because they are geographic places with names, but
#: their READINGS are always sampled live - a hardcoded temperature goes stale the moment the
#: calibration changes, and this pair carries the product's central claim.
CONTRAST_POINTS = {
    "hot": ("Van Buren St x 7th Ave", "unshaded asphalt corridor", 33.4520, -112.0825),
    "cool": ("Virginia G. Piper Plaza", "highest measured canopy in the tile", 33.4508, -112.0691),
}


@lru_cache(maxsize=8)
def _street_node_count(city_id: str) -> int:
    """Routable nodes in a city's fetched OSM graph.

    Read from the streets file's own node_count rather than by building the routing graph,
    which is expensive and would make a metadata endpoint slower than a route solve.
    """
    path = Path(__file__).resolve().parent.parent / "data" / "streets" / f"{city_id}.json"
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return int(json.load(fh).get("node_count", 0))
    except Exception:
        return 0


@lru_cache(maxsize=8)
def _shelter_assumed_count(city_id: str) -> int:
    """Shelter fields explicitly flagged as assumed rather than sourced.

    The OSM and municipal feeds rarely publish air-conditioning or indoor temperature, so the
    fetcher marks those fields ac_assumed / indoor_temp_assumed rather than inventing a value.
    They are honest flags, and they must be counted where the site claims a number of remaining
    assumptions.
    """
    path = Path(__file__).resolve().parent.parent / "data" / "shelters" / f"{city_id}.json"
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            shelters = json.load(fh).get("shelters", [])
    except Exception:
        return 0
    return sum(
        1
        for s in shelters
        for k, v in s.items()
        if k.endswith("_assumed") and v is True
    )


@lru_cache(maxsize=1)
def _test_count() -> int:
    """Number of test functions in the suite, counted from the files.

    The landing page and the docs both quote this. Quoting it as a literal meant the number
    was correct only until the next test was written, and nothing would have caught the drift.
    """
    total = 0
    tests_dir = Path(__file__).resolve().parent / "tests"
    for path in tests_dir.glob("test_*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("def test_"):
                total += 1
    return total


@app.get(f"{API_PREFIX}/facts")
def facts() -> Dict[str, Any]:
    """Every figure the interface quotes about Cryonav itself, computed at request time.

    This endpoint exists because the landing page and the documentation had accumulated
    forty-odd hardcoded numbers - canopy resolutions, node counts, payload sizes, the
    two-street temperature comparison. Each was true when written and had no mechanism to stay
    true. A page that states a stale figure confidently is worse than one that states nothing,
    so the figures now come from the running system and cannot disagree with it.

    Fixed here are only the things that genuinely are fixed: which two coordinates illustrate
    the contrast, and their street names. Every value attached to them is sampled.
    """
    cities = service.cities()
    provenance = service.data_provenance()

    layers, still_assumed = set(), 0
    nodes = 0
    for cid in service.city_ids():
        prov = provenance.get(cid, {})
        if prov.get("geometry"):
            layers.update({"osm_streets", "osm_urban", "osm_shelters"})
        if prov.get("canopy"):
            layers.add("canopy")
        if prov.get("surface_temperature"):
            layers.add("surface_temperature")
        if prov.get("surface_temperature_peak"):
            layers.add("surface_temperature_peak")
        if prov.get("still_estimated"):
            still_assumed += len(prov["still_estimated"])
        # Shelter records carry their own per-field assumed flags. Counting only the urban
        # assumptions blocks made this number 0 by construction: those blocks were emptied
        # when canopy and surface temperature became measured, while hundreds of shelter
        # fields remained explicitly flagged as assumed in the very same repo.
        still_assumed += _shelter_assumed_count(cid)
        nodes += _street_node_count(cid)

    hour = 15.0
    contrast: Dict[str, Any] = {"city_id": "phoenix", "hour": hour}
    for key, (name, kind, lat, lon) in CONTRAST_POINTS.items():
        r = service.sample("phoenix", lat, lon, hour)
        contrast[key] = {
            "name": name,
            "kind": kind,
            "coords": [lat, lon],
            "air_temp_2m_f": r.air_temp_2m_f,
            "surface_temp_f": r.surface_temp_f,
            "mean_radiant_temp_f": r.mean_radiant_temp_f,
            "exposure_index_f": r.exposure_index_f,
            "canopy_cover_pct": r.canopy_cover_pct,
            "risk_level": r.risk_level,
        }
    contrast["air_gap_f"] = round(
        contrast["hot"]["air_temp_2m_f"] - contrast["cool"]["air_temp_2m_f"], 1
    )
    contrast["radiant_gap_f"] = round(
        contrast["hot"]["mean_radiant_temp_f"] - contrast["cool"]["mean_radiant_temp_f"], 1
    )
    contrast["exposure_gap_f"] = round(
        contrast["hot"]["exposure_index_f"] - contrast["cool"]["exposure_index_f"], 1
    )

    phx = provenance.get("phoenix", {})
    return {
        "cities": len(cities),
        "shelters": sum(int(c.get("shelter_count", 0)) for c in cities),
        "raster_cells": sum(int(c.get("raster_tiles", 0)) for c in cities),
        "routable_nodes": nodes or None,
        "measured_layers": len(layers),
        "assumed_constants_remaining": still_assumed,
        "tests": _test_count(),
        "resolution": {
            "sensing_agl_m": SENSING_ELEVATION_M,
            "canopy_m": (phx.get("canopy") or {}).get("resolution_m"),
            "surface_m": (phx.get("surface_temperature") or {}).get("resolution_m"),
            "surface_peak_m": (phx.get("surface_temperature_peak") or {}).get("resolution_m"),
        },
        "contrast": contrast,
    }


@app.get(f"{API_PREFIX}/cities")
def cities() -> Dict[str, Any]:
    return {"count": len(service.city_ids()), "cities": service.cities()}


@app.get(f"{API_PREFIX}/cities/{{city_id}}/grid")
def city_grid(
    city_id: str,
    hour: float = Query(15.0, ge=0, lt=24),
    resolution: int = Query(28, ge=8, le=64),
    source: str = Query("model", pattern="^(model|fortyguard)$"),
) -> Dict[str, Any]:
    """Heat grid for the map overlay.

    ``source=model`` (default) is Cryonav's exposure-index field -- the composite the routes
    are optimised on. ``source=fortyguard`` is the raw /v1/heatmap raster: observed average
    air temperature per ~100 m tile, FortyGuard's data with no Cryonav modelling on top.
    """
    try:
        if source == "fortyguard":
            return service.raster_grid(city_id)
        grid = service.thermal_grid(city_id, hour, resolution)
        grid["source"] = "cryonav_exposure_model"
        grid["units_label"] = "modelled exposure index (deg F)"
        return grid
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get(f"{API_PREFIX}/cities/{{city_id}}/report.pdf")
def city_report(city_id: str):
    """FortyGuard's heat-intelligence analyst report for this tile (cached daily).

    Generated upstream by POST /v1/heat_intelligence and downloaded server-side -
    the upstream link embeds the API key and is never exposed. 404 when no report
    has been cached (no key, or the tile's report fetch failed).
    """
    from fastapi.responses import FileResponse  # noqa: PLC0415

    if city_id not in service.city_ids():
        raise HTTPException(404, f"unknown city '{city_id}'")
    meta = service.report_meta(city_id)
    if meta is None:
        raise HTTPException(404, "no cached FortyGuard report for this tile")
    return FileResponse(
        service.report_path(city_id),
        media_type="application/pdf",
        filename=f"fortyguard-heat-intelligence-{city_id}-{meta['date']}.pdf",
        headers={"X-Report-Date": str(meta["date"])},
    )


@app.get(f"{API_PREFIX}/cities/{{city_id}}/layers")
def city_layers(city_id: str) -> Dict[str, Any]:
    """Urban-morphology layers for map rendering.

    Served from REAL OpenStreetMap geometry when the city has a fetched urban file
    (parks with true areas, covered walkways, lane-counted arterials, actual parking
    lots), and real shelter data (official MAG Heat Relief Network for Phoenix, OSM
    POIs for the Gulf). Hand-authored fixtures remain only as fallback.
    """
    try:
        city = service.city(city_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    idx = service.urban(city_id)
    shelters = service.shelters(city_id, radius_m=50_000.0, limit=500)
    base: Dict[str, Any] = {"city_id": city_id, "shelter_source": service.shelter_source(city_id)}

    if idx is not None:
        from urban import display_layers  # noqa: PLC0415

        layers = display_layers(idx)
        layers.update(base)
        layers["shelters"] = shelters
        return layers

    base.update(
        {
            "source": "hand_authored_fixture",
            "heat_islands": city["heat_islands"],
            "heat_corridors": city.get("heat_corridors", []),
            "canopy_zones": city["canopy_zones"],
            "canopy_corridors": city.get("canopy_corridors", []),
            "water_bodies": city.get("water_bodies", []),
            "shelters": shelters,
        }
    )
    return base


# --------------------------------------------------------------------------------------
# FortyGuard proxy
# --------------------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/fortyguard/heat-intelligence")
def heat_intelligence(req: HeatIntelligenceRequest) -> Dict[str, Any]:
    """Proxy to the FortyGuard Temperature API(R), with the simulation as fallback."""
    city_id = _resolve_city(req.city_id, req.locations[0])
    try:
        return service.heat_intelligence(
            [loc.as_tuple() for loc in req.locations],
            city_id=city_id,
            hour=req.hour,
            prefer_live=req.prefer_live,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


# --------------------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/navigate/cool-route")
def cool_route(req: CoolRouteRequest) -> Dict[str, Any]:
    """Run the full three-agent loop and return Path A vs Path B with the thermal scoreboard."""
    city_id = _resolve_city(req.city_id, req.origin)
    try:
        return orchestrator.navigate(
            city_id=city_id,
            origin=req.origin.as_tuple(),
            destination=req.destination.as_tuple(),
            hour=req.hour,
            profile_id=req.profile,
            allow_shelter_reroute=req.allow_shelter_reroute,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get(f"{API_PREFIX}/shelters/nearby")
def shelters_nearby(
    city_id: Optional[str] = None,
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    radius_m: float = Query(3000.0, ge=100, le=20000),
    limit: int = Query(10, ge=1, le=50),
    hour: float = Query(15.0, ge=0, lt=24),
    require_ac: bool = False,
) -> Dict[str, Any]:
    """Nearest municipal cooling centres, hydration stations and cooled transit."""
    if city_id is None:
        if lat is None or lon is None:
            raise HTTPException(400, "provide city_id, or lat and lon")
        city_id = service.resolve_city(lat, lon)
    if city_id not in service.city_ids():
        raise HTTPException(404, f"unknown city '{city_id}'")

    found = service.shelters(
        city_id, lat=lat, lon=lon, radius_m=radius_m, limit=limit, hour=hour, require_ac=require_ac
    )
    return {
        "city_id": city_id,
        "count": len(found),
        "source": service.shelter_source(city_id),
        "search": {"lat": lat, "lon": lon, "radius_m": radius_m, "require_ac": require_ac},
        "shelters": found,
    }


@app.post(f"{API_PREFIX}/sentinel/monitor")
def sentinel_monitor(req: SentinelMonitorRequest) -> Dict[str, Any]:
    """Live transit telemetry check from a wearable or kiosk."""
    city_id = _resolve_city(req.city_id, req.position)
    return orchestrator.sentinel.monitor_transit(
        city_id=city_id,
        position=req.position.as_tuple(),
        hour=req.hour,
        dwell_minutes=req.dwell_minutes,
        profile_id=req.profile,
        moved_m=req.moved_m,
        accuracy_m=req.accuracy_m,
        notify=req.notify,
    )


# --------------------------------------------------------------------------------------
# NVIDIA Jetson edge module
# --------------------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/edge/jetson-kiosk")
def jetson_kiosk(req: JetsonKioskRequest) -> Dict[str, Any]:
    """Bandwidth-optimised route payload for NVIDIA Jetson pedestrian kiosks and wearables.

    Same routing core as the dashboard endpoint, but stripped for the edge:
      * polylines decimated to the panel's usable resolution,
      * per-segment telemetry and the agent trace dropped,
      * a single pre-rendered instruction string, because kiosk firmware should not have to
        do string assembly or unit conversion.

    ``payload_bytes`` is reported so a fleet operator can see the uplink cost per query.
    """
    started = time.perf_counter()
    city_id = _resolve_city(req.city_id, req.origin)
    try:
        result = orchestrator.navigate(
            city_id=city_id,
            origin=req.origin.as_tuple(),
            destination=req.destination.as_tuple(),
            hour=req.hour,
            profile_id=req.profile,
            allow_shelter_reroute=True,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    cool = result["routes"]["cool"]
    standard = result["routes"]["standard"]
    comparison = result["comparison"]
    ambient = result["ambient"]
    safety = result["safety"]

    shelter = None
    if result["shelter_reroute"].get("applied"):
        s = result["shelter_reroute"]["shelter"]
        shelter = {
            "name": s["name"],
            "type": s["type"],
            "coords": s["center"],
            "indoor_f": s["indoor_temp_f"],
            "walk_min": s["walk_minutes"],
        }
    elif result["nearby_shelters"]:
        s = result["nearby_shelters"][0]
        shelter = {
            "name": s["name"],
            "type": s["type"],
            "coords": s["center"],
            "indoor_f": s["indoor_temp_f"],
            "walk_min": s["walk_minutes"],
        }

    payload: Dict[str, Any] = {
        "device_id": req.device_id,
        "city_id": city_id,
        "feed": {
            "source": result["feed"]["source"],
            "status": result["feed"]["status_code"],
            "resolution": result["sensing"]["resolution"],
            "elevation_m": result["sensing"]["elevation_m"],
        },
        "now": {
            "air_f": ambient["air_temp_2m_f"],
            "surface_f": ambient["surface_temp_f"],
            "risk": ambient["risk_level"],
            "color": ambient["risk_color"],
        },
        "route": {
            "polyline": _decimate(cool["geometry"], req.max_polyline_points),
            "distance_m": cool["metrics"]["distance_m"],
            "minutes": cool["metrics"]["duration_min"],
            "risk": cool["metrics"]["risk_level"],
            "shade_pct": cool["metrics"]["shade_coverage_pct"],
        },
        "standard_route": {
            "polyline": _decimate(standard["geometry"], req.max_polyline_points),
            "distance_m": standard["metrics"]["distance_m"],
            "minutes": standard["metrics"]["duration_min"],
            "risk": standard["metrics"]["risk_level"],
        },
        "savings": {
            "thermal_load_f": comparison["thermal_load_reduction_f"],
            "heat_stress_pct": comparison["heat_stress_reduction_pct"],
            "added_min": comparison["added_minutes"],
        },
        "shelter": shelter,
        "instruction": (
            f"COOL ROUTE: {cool['metrics']['distance_km']} km, "
            f"{round(cool['metrics']['duration_min'])} min. "
            f"{comparison['thermal_load_reduction_f']} F cooler than the direct route. "
            f"{safety.get('advisory', '')} Carry {cool['metrics']['hydration_ml']} ml water."
        ).strip(),
        "hydration_ml": cool["metrics"]["hydration_ml"],
    }

    # Jetson-style telemetry. The routing core is pure Python over a pre-built graph, so the
    # figure quoted here is the real server-side compute for this request, not a benchmark.
    compute_ms = (time.perf_counter() - started) * 1000.0
    _blob = json.dumps(payload, separators=(",", ":"))
    _self_contained = "http://" not in _blob and "https://" not in _blob
    _renders_without_lookup = bool(payload.get("instruction")) and bool(
        payload.get("route", {}).get("polyline")
    )
    payload["edge"] = {
        "runtime": "NVIDIA Jetson Orin Nano (simulated)",
        # No TOPS figure quoted: the hardware is not present, and the number previously
        # here (32 TOPS) was the pre-Super devkit spec anyway. Naming the class of device
        # the payload is shaped for is honest; quoting its benchmark is not.
        "accelerator": "Ampere-class embedded GPU (device not present; payload shaped for it)",
        "inference_ms": round(compute_ms, 2),
        "payload_bytes": len(str(payload).encode("utf-8")),
        # Checked, not asserted. "Offline capable" can only mean one thing here: once this
        # response lands, the kiosk needs no further network to guide the walk. That holds
        # only if nothing inside is a reference to dereference later, the instruction is
        # already rendered as a string (so firmware never does unit conversion), and the
        # geometry to draw is present. This used to be a hardcoded True, which would have
        # kept claiming offline capability even if a future change embedded a tile URL.
        "offline_capable": _self_contained and _renders_without_lookup,
        "no_external_references": _self_contained,
        "instruction_prerendered": _renders_without_lookup,
        "cached_tile_mi2": result["sensing"]["tile_area_mi2"],
    }
    return payload
