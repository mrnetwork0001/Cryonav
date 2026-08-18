"""
FortyGuard Temperature API(R) integration layer.

Two interchangeable data paths behind one interface:

  1. **Live**  -- ``POST {FORTYGUARD_BASE_URL}/v1/heat-intelligence`` when ``FORTYGUARD_API_KEY``
     is present. Requests 2 m above-ground-level readings at 10 mi^2 microclimate resolution.
  2. **Mock**  -- a deterministic physical simulation of the same payload, so the entire stack
     (routing, agents, dashboard, tests, live demo) runs offline with zero API budget.

The mock is not noise. It is a small urban-climate model: a diurnal air-temperature curve,
Gaussian urban-heat-island sources, canopy and water cooling sinks, a solar-driven asphalt
surface-temperature term, and the radiant/humidity coupling from :mod:`thermal`. That is what
makes the demo defensible -- the cool routes it finds are the routes real shade would produce.

Determinism matters: every reading is a pure function of (city, lat, lon, hour). Screenshots
and tests reproduce byte-for-byte.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import thermal
from thermal import clamp, haversine_m

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CITIES_PATH = DATA_DIR / "cities.json"

DEFAULT_BASE_URL = "https://api.fortyguard.com"
HEAT_INTELLIGENCE_PATH = "/v1/heat-intelligence"

#: Advertised capability of the FortyGuard Temperature API(R) product we integrate against.
SENSING_ELEVATION_M = 2.0
MICROCLIMATE_RESOLUTION_MI2 = 10.0

SURFACE_TYPES = ("asphalt", "concrete", "canopy_shade", "covered_walkway", "park_turf", "waterfront")

# Overlapping influence zones sum, so they need soft saturation or a point sitting inside three
# heat islands reports a physically impossible uplift. tanh keeps small values ~linear and
# asymptotes at the cap, which is how these effects actually behave in the field.
UHI_CAP_F = 7.0
CANOPY_COOLING_CAP_F = 9.5
SURFACE_BOOST_CAP_F = 20.0
WATER_COOLING_CAP_F = 5.0


def _saturate(value: float, cap: float) -> float:
    """Soft-clip an additive influence sum to a physical ceiling."""
    if cap <= 0:
        return 0.0
    return cap * math.tanh(value / cap)


def _polyline_distance_m(point: Tuple[float, float], path: Sequence[Sequence[float]]) -> float:
    """Shortest distance from a point to a polyline, in metres.

    Urban thermal structure is overwhelmingly *linear*: a six-lane arterial is a hot ribbon,
    a mature street-tree alley is a cool ribbon. Modelling those as point blobs produces a
    smooth field with no walkable gradient -- and therefore no cool route to find. Working in
    a local equirectangular projection is accurate to well under a metre at tile scale.
    """
    if len(path) < 2:
        return float("inf")
    kx = 111_320.0 * math.cos(math.radians(point[0]))
    ky = 110_574.0
    px, py = point[1] * kx, point[0] * ky

    best = float("inf")
    for a, b in zip(path, path[1:]):
        ax, ay = a[1] * kx, a[0] * ky
        bx, by = b[1] * kx, b[0] * ky
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        t = 0.0 if seg_len_sq == 0 else clamp(((px - ax) * dx + (py - ay) * dy) / seg_len_sq, 0.0, 1.0)
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - cx, py - cy))
    return best


# --------------------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThermalReading:
    """A single 2 m AGL microclimate observation, live or simulated."""

    lat: float
    lon: float
    air_temp_2m_f: float
    surface_temp_f: float
    mean_radiant_temp_f: float
    heat_index_f: float
    wbgt_f: float
    exposure_index_f: float
    thermal_stress_score: float
    risk_level: str
    relative_humidity_pct: float
    wind_speed_mph: float
    solar_irradiance_wm2: float
    canopy_cover_pct: float
    sky_view_factor: float
    asphalt_spike_f: float
    surface_type: str

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_color"] = thermal.RISK_COLORS[self.risk_level]
        return d


@dataclass
class FeedStatus:
    """What the dashboard's live-feed pill renders."""

    source: str
    status_code: int
    ok: bool
    latency_ms: float
    resolution_mi2: float = MICROCLIMATE_RESOLUTION_MI2
    elevation_m: float = SENSING_ELEVATION_M
    endpoint: str = HEAT_INTELLIGENCE_PATH
    detail: str = ""
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------------------


class FortyGuardService:
    """Client + simulator for the FortyGuard Temperature API(R)."""

    def __init__(
        self,
        cities_path: Path = CITIES_PATH,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: float = 6.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("FORTYGUARD_API_KEY", "").strip()
        self.base_url = (base_url or os.getenv("FORTYGUARD_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = timeout_s
        self._cities: Dict[str, Dict[str, Any]] = {}
        self._dewpoints: Dict[str, float] = {}
        self._load_cities(cities_path)
        self.last_status: FeedStatus = FeedStatus(
            source=self.mode, status_code=200, ok=True, latency_ms=0.0, detail="initialised"
        )

    # -- catalogue ---------------------------------------------------------------------

    def _load_cities(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        for city in payload["cities"]:
            self._cities[city["id"]] = city

    @property
    def mode(self) -> str:
        return "fortyguard_live" if self.api_key else "cryonav_simulation"

    @property
    def live(self) -> bool:
        return bool(self.api_key)

    def cities(self) -> List[Dict[str, Any]]:
        """Catalogue entries for the city selector (no heavy geometry)."""
        out = []
        for city in self._cities.values():
            out.append(
                {
                    "id": city["id"],
                    "name": city["name"],
                    "region": city["region"],
                    "country_code": city["country_code"],
                    "timezone": city["timezone"],
                    "center": city["center"],
                    "bounds": self.bounds(city["id"]),
                    "season": city["climate"]["season"],
                    "air_temp_max_f": city["climate"]["air_temp_max_f"],
                    "presets": city["presets"],
                    "shelter_count": len(city["shelters"]),
                    "canopy_zone_count": len(city["canopy_zones"]),
                    "heat_island_count": len(city["heat_islands"]),
                }
            )
        return out

    def city(self, city_id: str) -> Dict[str, Any]:
        if city_id not in self._cities:
            raise KeyError(f"unknown city '{city_id}' (known: {', '.join(sorted(self._cities))})")
        return self._cities[city_id]

    def city_ids(self) -> List[str]:
        return sorted(self._cities)

    def bounds(self, city_id: str) -> Dict[str, float]:
        """Bounding box of the ~10 mi^2 FortyGuard coverage tile."""
        city = self.city(city_id)
        (lat, lon) = city["center"]
        dlat, dlon = city["tile_half_extent_deg"]
        return {
            "south": round(lat - dlat, 6),
            "north": round(lat + dlat, 6),
            "west": round(lon - dlon, 6),
            "east": round(lon + dlon, 6),
        }

    def _dewpoint_f(self, city_id: str) -> float:
        """Conserved daily dewpoint, derived once from the city's reference RH at mean temp."""
        cached = self._dewpoints.get(city_id)
        if cached is None:
            clim = self.city(city_id)["climate"]
            mean_temp = (clim["air_temp_max_f"] + clim["air_temp_min_f"]) / 2.0
            cached = thermal.dewpoint_f(mean_temp, clim["relative_humidity_pct"])
            self._dewpoints[city_id] = cached
        return cached

    def tile_area_mi2(self, city_id: str) -> float:
        b = self.bounds(city_id)
        mid_lat = math.radians((b["north"] + b["south"]) / 2)
        h_km = (b["north"] - b["south"]) * 110.574
        w_km = (b["east"] - b["west"]) * 111.320 * math.cos(mid_lat)
        return round(h_km * w_km * 0.386102, 2)

    def resolve_city(self, lat: float, lon: float) -> str:
        """Nearest city tile for a free-form coordinate (edge devices send raw GPS)."""
        best_id, best_d = None, float("inf")
        for cid, city in self._cities.items():
            d = haversine_m((lat, lon), tuple(city["center"]))
            if d < best_d:
                best_id, best_d = cid, d
        return best_id or "phoenix"

    # -- terrain -----------------------------------------------------------------------

    def terrain(self, city_id: str, lat: float, lon: float) -> Dict[str, Any]:
        """Canopy / heat-island / water influence at a point, before any temperature maths.

        Returns the urban-morphology inputs that the FortyGuard reading is then fused with:
        canopy fraction, sky view factor, heat-island uplift, water proximity, surface class.
        """
        city = self.city(city_id)
        p = (lat, lon)

        canopy = 0.0
        canopy_cool = 0.0
        covered = 0.0
        for zone in city["canopy_zones"]:
            d = haversine_m(p, tuple(zone["center"]))
            w = math.exp(-((d / zone["radius_m"]) ** 2))
            canopy = max(canopy, (zone["canopy_pct"] / 100.0) * w)
            canopy_cool += zone["cooling_f"] * w
            if zone["canopy_pct"] >= 85:
                covered = max(covered, w)

        # Linear shade: street-tree alleys, arcades, canal promenades.
        for corr in city.get("canopy_corridors", []):
            d = _polyline_distance_m(p, corr["path"])
            w = math.exp(-((d / corr["width_m"]) ** 2))
            canopy = max(canopy, (corr["canopy_pct"] / 100.0) * w)
            canopy_cool += corr["cooling_f"] * w
            if corr["canopy_pct"] >= 85:
                covered = max(covered, w)

        uhi = 0.0
        surface_boost = 0.0
        for zone in city["heat_islands"]:
            d = haversine_m(p, tuple(zone["center"]))
            w = math.exp(-((d / zone["radius_m"]) ** 2))
            uhi += zone["intensity_f"] * w
            surface_boost += zone["surface_boost_f"] * w

        # Linear heat: multi-lane arterials, elevated highways, rail cuttings.
        arterial = 0.0
        for corr in city.get("heat_corridors", []):
            d = _polyline_distance_m(p, corr["path"])
            w = math.exp(-((d / corr["width_m"]) ** 2))
            uhi += corr["intensity_f"] * w
            surface_boost += corr["surface_boost_f"] * w
            arterial = max(arterial, w)

        water_cool = 0.0
        humidity_boost = 0.0
        water_prox = 0.0
        for zone in city.get("water_bodies", []):
            d = haversine_m(p, tuple(zone["center"]))
            w = math.exp(-((d / zone["radius_m"]) ** 2))
            water_cool += zone["cooling_f"] * w
            humidity_boost += zone["humidity_boost_pct"] * w
            water_prox = max(water_prox, w)

        canopy = clamp(canopy, 0.0, 0.95)
        # Sky view factor: how much hot sky/surface the body actually exchanges radiation with.
        svf = clamp(1.0 - canopy * 0.92, 0.05, 1.0)

        if covered > 0.45:
            surface_type = "covered_walkway"
        elif canopy > 0.55:
            surface_type = "park_turf"
        elif water_prox > 0.5:
            surface_type = "waterfront"
        elif canopy > 0.28:
            surface_type = "canopy_shade"
        elif arterial > 0.4 or surface_boost > 6.0:
            surface_type = "asphalt"
        else:
            surface_type = "concrete"

        return {
            "canopy_fraction": canopy,
            "canopy_cooling_f": _saturate(canopy_cool, CANOPY_COOLING_CAP_F),
            "sky_view_factor": svf,
            "uhi_uplift_f": _saturate(uhi, UHI_CAP_F),
            "surface_boost_f": _saturate(surface_boost, SURFACE_BOOST_CAP_F),
            "water_cooling_f": _saturate(water_cool, WATER_COOLING_CAP_F),
            "humidity_boost_pct": min(humidity_boost, 15.0),
            "surface_type": surface_type,
        }

    # -- sampling ----------------------------------------------------------------------

    def sample(self, city_id: str, lat: float, lon: float, hour: float = 15.0) -> ThermalReading:
        """One simulated 2 m AGL reading. Pure function of its arguments."""
        city = self.city(city_id)
        clim = city["climate"]
        peak = clim.get("peak_hour", 15.0)
        terr = self.terrain(city_id, lat, lon)

        solar = thermal.solar_elevation_factor(hour, peak)
        base_air = thermal.diurnal_air_temp_f(
            clim["air_temp_min_f"], clim["air_temp_max_f"], hour, peak
        )

        # Desert-city urban heat island is chiefly a *nocturnal* air-temperature phenomenon:
        # by mid-afternoon the boundary layer is well mixed, while at 22:00 stored asphalt heat
        # keeps downtown several degrees hotter. The daytime penalty a pedestrian actually feels
        # is radiant, and it lives in the surface term below -- precisely the signal conventional
        # navigation drops.
        #
        # Both modulations are deliberately shallow. These are offsets riding on the diurnal
        # curve, so if their dusk-to-peak swing exceeds the curve's own amplitude the sum stops
        # being a diurnal cycle at all and air temperature climbs after sunset.
        uhi_air_weight = 0.55 + 0.45 * (1.0 - solar)
        air = (
            base_air
            + terr["uhi_uplift_f"] * uhi_air_weight
            - terr["canopy_cooling_f"] * (0.65 + 0.35 * solar)
            - terr["water_cooling_f"] * (0.7 + 0.3 * solar)
        )

        # Asphalt surface temperature: air + solar-driven uplift, suppressed by canopy shade.
        exposure_to_sun = terr["sky_view_factor"]
        asphalt_spike = (
            (clim["asphalt_uplift_f"] + terr["surface_boost_f"])
            * solar
            * clim["sky_clearness"]
            * exposure_to_sun
        )
        # Thermal mass keeps a residual after sundown.
        residual = 6.0 * (1.0 - solar) * exposure_to_sun if 17.0 <= hour <= 23.0 else 0.0
        surface = air + asphalt_spike + residual

        # RH is derived from a conserved daily dewpoint, not scaled by the sun -- see
        # thermal.humidity_from_dewpoint for why that ordering matters.
        humidity = clamp(
            thermal.humidity_from_dewpoint(air, self._dewpoint_f(city_id))
            + terr["humidity_boost_pct"],
            4.0,
            98.0,
        )
        # Canopy and buildings slow the wind; open asphalt plazas get more ventilation.
        wind = clim["wind_speed_mph"] * clamp(0.45 + 0.55 * terr["sky_view_factor"], 0.35, 1.0)
        irradiance = 1000.0 * solar * clim["sky_clearness"] * exposure_to_sun

        hi = thermal.heat_index_f(air, humidity)
        mrt = thermal.mean_radiant_temp_f(air, surface, terr["sky_view_factor"])
        wbgt = thermal.wbgt_f(air, humidity, mrt, wind)
        exposure = thermal.exposure_index_f(air, hi, mrt)

        return ThermalReading(
            lat=round(lat, 6),
            lon=round(lon, 6),
            air_temp_2m_f=round(air, 1),
            surface_temp_f=round(surface, 1),
            mean_radiant_temp_f=round(mrt, 1),
            heat_index_f=round(hi, 1),
            wbgt_f=round(wbgt, 1),
            exposure_index_f=round(exposure, 1),
            thermal_stress_score=thermal.thermal_stress_score(exposure),
            risk_level=thermal.classify_risk(exposure),
            relative_humidity_pct=round(humidity, 1),
            wind_speed_mph=round(wind, 1),
            solar_irradiance_wm2=round(irradiance, 0),
            canopy_cover_pct=round(terr["canopy_fraction"] * 100.0, 1),
            sky_view_factor=round(terr["sky_view_factor"], 3),
            asphalt_spike_f=round(asphalt_spike + residual, 1),
            surface_type=terr["surface_type"],
        )

    # -- the public API surface ---------------------------------------------------------

    def heat_intelligence(
        self,
        points: Sequence[Tuple[float, float]],
        city_id: Optional[str] = None,
        hour: float = 15.0,
        prefer_live: bool = True,
    ) -> Dict[str, Any]:
        """Mirror of ``POST /v1/heat-intelligence``.

        Tries the live FortyGuard endpoint when a key is configured and falls back to the
        simulation on any failure -- a hackathon demo must never die on someone's wifi.
        """
        if not points:
            raise ValueError("at least one point is required")

        resolved_city = city_id or self.resolve_city(points[0][0], points[0][1])
        self.city(resolved_city)  # validate

        started = time.perf_counter()
        readings: Optional[List[ThermalReading]] = None
        status = FeedStatus(source="cryonav_simulation", status_code=200, ok=True, latency_ms=0.0)

        if prefer_live and self.live:
            try:
                readings = self._call_live(points, resolved_city, hour)
                status = FeedStatus(
                    source="fortyguard_live",
                    status_code=200,
                    ok=True,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    detail="FortyGuard Temperature API(R) 200 OK",
                )
            except Exception as exc:  # noqa: BLE001 - degrade, never crash the demo
                status = FeedStatus(
                    source="cryonav_simulation",
                    status_code=200,
                    ok=True,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    detail=f"live feed unavailable ({type(exc).__name__}), served from simulation",
                )

        if readings is None:
            readings = [self.sample(resolved_city, lat, lon, hour) for lat, lon in points]
            status.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            if not status.detail:
                status.detail = "deterministic microclimate simulation (no API key configured)"

        self.last_status = status
        peak = max(readings, key=lambda r: r.exposure_index_f)

        return {
            "city_id": resolved_city,
            "hour": hour,
            "feed": status.as_dict(),
            "sensing": {
                "elevation_m": SENSING_ELEVATION_M,
                "resolution_mi2": MICROCLIMATE_RESOLUTION_MI2,
                "tile_area_mi2": self.tile_area_mi2(resolved_city),
                "endpoint": HEAT_INTELLIGENCE_PATH,
            },
            "count": len(readings),
            "readings": [r.as_dict() for r in readings],
            "summary": {
                "mean_air_temp_2m_f": round(sum(r.air_temp_2m_f for r in readings) / len(readings), 1),
                "max_surface_temp_f": round(max(r.surface_temp_f for r in readings), 1),
                "mean_exposure_index_f": round(
                    sum(r.exposure_index_f for r in readings) / len(readings), 1
                ),
                "peak_risk_level": peak.risk_level,
                "peak_risk_at": [peak.lat, peak.lon],
                "advisory": thermal.RISK_ADVISORY[peak.risk_level],
            },
        }

    def _call_live(
        self, points: Sequence[Tuple[float, float]], city_id: str, hour: float
    ) -> List[ThermalReading]:
        """Real FortyGuard call. Imported lazily so the offline path has no hard dependency."""
        import httpx  # noqa: PLC0415

        body = {
            "locations": [{"latitude": lat, "longitude": lon} for lat, lon in points],
            "elevation_m": SENSING_ELEVATION_M,
            "resolution_mi2": MICROCLIMATE_RESOLUTION_MI2,
            "metrics": [
                "air_temperature_2m",
                "surface_temperature",
                "relative_humidity",
                "wind_speed",
                "solar_irradiance",
            ],
            "units": "imperial",
        }
        resp = httpx.post(
            f"{self.base_url}{HEAT_INTELLIGENCE_PATH}",
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26)",
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        return [
            self._reading_from_live(city_id, point, record)
            for point, record in zip(points, payload.get("results", payload.get("data", [])))
        ]

    def _reading_from_live(
        self, city_id: str, point: Tuple[float, float], record: Dict[str, Any]
    ) -> ThermalReading:
        """Fuse a live FortyGuard record with local canopy/morphology GIS.

        FortyGuard supplies the temperature truth; Cryonav supplies the urban-form context
        (canopy fraction, sky view factor, surface class) that converts it into radiant load.
        """
        lat, lon = point
        terr = self.terrain(city_id, lat, lon)
        clim = self.city(city_id)["climate"]

        air = float(record.get("air_temperature_2m", record.get("temperature", clim["air_temp_max_f"])))
        humidity = float(record.get("relative_humidity", clim["relative_humidity_pct"]))
        wind = float(record.get("wind_speed", clim["wind_speed_mph"]))
        irradiance = float(record.get("solar_irradiance", 0.0))
        surface = float(
            record.get(
                "surface_temperature",
                air + (clim["asphalt_uplift_f"] + terr["surface_boost_f"]) * terr["sky_view_factor"],
            )
        )

        hi = thermal.heat_index_f(air, humidity)
        mrt = thermal.mean_radiant_temp_f(air, surface, terr["sky_view_factor"])
        wbgt = thermal.wbgt_f(air, humidity, mrt, wind)
        exposure = thermal.exposure_index_f(air, hi, mrt)

        return ThermalReading(
            lat=round(lat, 6),
            lon=round(lon, 6),
            air_temp_2m_f=round(air, 1),
            surface_temp_f=round(surface, 1),
            mean_radiant_temp_f=round(mrt, 1),
            heat_index_f=round(hi, 1),
            wbgt_f=round(wbgt, 1),
            exposure_index_f=round(exposure, 1),
            thermal_stress_score=thermal.thermal_stress_score(exposure),
            risk_level=thermal.classify_risk(exposure),
            relative_humidity_pct=round(humidity, 1),
            wind_speed_mph=round(wind, 1),
            solar_irradiance_wm2=round(irradiance, 0),
            canopy_cover_pct=round(terr["canopy_fraction"] * 100.0, 1),
            sky_view_factor=round(terr["sky_view_factor"], 3),
            asphalt_spike_f=round(max(surface - air, 0.0), 1),
            surface_type=terr["surface_type"],
        )

    # -- grid --------------------------------------------------------------------------

    def thermal_grid(self, city_id: str, hour: float = 15.0, resolution: int = 24) -> Dict[str, Any]:
        """Rasterise the coverage tile into a heat grid for the dashboard overlay.

        Returned as flat parallel arrays rather than objects -- a 32x32 grid of dicts is ~180 KB
        of JSON, the array form is ~25 KB, and the canvas layer wants typed arrays anyway.
        """
        resolution = int(clamp(resolution, 8, 64))
        b = self.bounds(city_id)
        lat_step = (b["north"] - b["south"]) / resolution
        lon_step = (b["east"] - b["west"]) / resolution

        cells: List[List[float]] = []
        exposures: List[float] = []
        risks: List[int] = []
        for row in range(resolution):
            lat = b["south"] + (row + 0.5) * lat_step
            for col in range(resolution):
                lon = b["west"] + (col + 0.5) * lon_step
                r = self.sample(city_id, lat, lon, hour)
                cells.append([round(lat, 6), round(lon, 6), r.air_temp_2m_f, r.surface_temp_f])
                exposures.append(r.exposure_index_f)
                risks.append(thermal.risk_rank(r.risk_level))

        return {
            "city_id": city_id,
            "hour": hour,
            "resolution": resolution,
            "bounds": b,
            "cell_size_deg": [round(lat_step, 6), round(lon_step, 6)],
            "tile_area_mi2": self.tile_area_mi2(city_id),
            "cells": cells,
            "exposure_index_f": exposures,
            "risk_rank": risks,
            "legend": [
                {"level": lvl, "color": thermal.RISK_COLORS[lvl], "min_exposure_f": thermal.RISK_THRESHOLDS_F[lvl]}
                for lvl in thermal.RISK_LEVELS
            ],
            "stats": {
                "min_exposure_f": round(min(exposures), 1),
                "max_exposure_f": round(max(exposures), 1),
                "mean_exposure_f": round(sum(exposures) / len(exposures), 1),
                "extreme_cell_pct": round(
                    100.0 * sum(1 for r in risks if r == 3) / len(risks), 1
                ),
            },
        }

    # -- shelters ----------------------------------------------------------------------

    def shelters(
        self,
        city_id: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        radius_m: float = 3000.0,
        limit: int = 10,
        hour: float = 15.0,
        require_ac: bool = False,
    ) -> List[Dict[str, Any]]:
        """Municipal cooling centres, hydration stations and cooled transit, nearest first."""
        city = self.city(city_id)
        origin = (lat, lon) if lat is not None and lon is not None else tuple(city["center"])

        out: List[Dict[str, Any]] = []
        for shelter in city["shelters"]:
            if require_ac and not shelter["air_conditioned"]:
                continue
            d = haversine_m(origin, tuple(shelter["center"]))
            if d > radius_m:
                continue
            reading = self.sample(city_id, shelter["center"][0], shelter["center"][1], hour)
            relief = (
                round(reading.exposure_index_f - float(shelter["indoor_temp_f"]), 1)
                if shelter["air_conditioned"] and shelter.get("indoor_temp_f") is not None
                else round(reading.exposure_index_f - reading.air_temp_2m_f, 1)
            )
            out.append(
                {
                    **shelter,
                    "distance_m": round(d),
                    "walk_minutes": round(d / 78.0, 1),  # 1.3 m/s heat-derated walking pace
                    "outdoor_exposure_index_f": reading.exposure_index_f,
                    "outdoor_risk_level": reading.risk_level,
                    "thermal_relief_f": relief,
                }
            )

        out.sort(key=lambda s: s["distance_m"])
        return out[:limit]
