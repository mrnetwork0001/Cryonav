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
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import thermal
from agents import CryonavOrchestrator, EXTREME_AIR_TEMP_F
from fortyguard_service import (
    HEAT_INTELLIGENCE_PATH,
    MICROCLIMATE_RESOLUTION_MI2,
    SENSING_ELEVATION_M,
    FortyGuardService,
)
from routing_engine import PROFILES, RoutingEngine

API_PREFIX = "/api/v1"
VERSION = "1.0.0"

service = FortyGuardService()
engine = RoutingEngine(service)
orchestrator = CryonavOrchestrator(service, engine)

app = FastAPI(
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
    prefer_live: bool = Field(True, description="Set false to force the simulation path.")


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
            "endpoint": HEAT_INTELLIGENCE_PATH,
            "resolution_mi2": MICROCLIMATE_RESOLUTION_MI2,
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


@app.get(f"{API_PREFIX}/cities/{{city_id}}/layers")
def city_layers(city_id: str) -> Dict[str, Any]:
    """Urban-morphology layers (heat corridors, canopy corridors, zones) for map rendering."""
    try:
        city = service.city(city_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "city_id": city_id,
        "heat_islands": city["heat_islands"],
        "heat_corridors": city.get("heat_corridors", []),
        "canopy_zones": city["canopy_zones"],
        "canopy_corridors": city.get("canopy_corridors", []),
        "water_bodies": city.get("water_bodies", []),
        "shelters": city["shelters"],
    }


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
            "resolution_mi2": result["sensing"]["resolution_mi2"],
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
    payload["edge"] = {
        "runtime": "NVIDIA Jetson Orin Nano (simulated)",
        "accelerator": "Ampere 1024-core GPU / 32 TOPS INT8",
        "inference_ms": round(compute_ms, 2),
        "payload_bytes": len(str(payload).encode("utf-8")),
        "offline_capable": True,
        "cached_tile_mi2": result["sensing"]["tile_area_mi2"],
    }
    return payload
