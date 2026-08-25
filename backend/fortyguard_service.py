"""
FortyGuard Temperature API(R) integration layer.

Two interchangeable data paths behind one interface:

  1. **Live**  -- ``POST {FORTYGUARD_BASE_URL}/v1/heat_intelligence`` when ``FORTYGUARD_API_KEY``
     is present, authenticated with an ``api-key`` request header. Requests 2 m above-ground-level
     readings at 10 mi^2 microclimate resolution.
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

import standards
import thermal
from thermal import clamp, haversine_m

from urban import UrbanIndex, display_layers, load_urban_index  # noqa: E402  (local module)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CITIES_PATH = DATA_DIR / "cities.json"
CALIBRATION_DIR = DATA_DIR / "calibration"
URBAN_DIR = DATA_DIR / "urban"
SHELTERS_DIR = DATA_DIR / "shelters"
REPORTS_DIR = DATA_DIR / "reports"

DEFAULT_BASE_URL = "https://api.fortyguard.com"

#: Real endpoint paths, recovered from the FortyGuard docs application bundle and confirmed
#: against the live host. Note the UNDERSCORE: an earlier guess at "/v1/heat-intelligence"
#: (hyphen) would have 404'd forever behind an auth check that fires before routing.
HEAT_INTELLIGENCE_PATH = "/v1/heat_intelligence"
ENV_PARAMS_PATH = "/v1/env_params"
HEATMAP_PATH = "/v1/heatmap"
SATELLITE_PATH = "/v1/satellite"
STREETVIEW_PATH = "/v1/streetview"
STATUS_PATH = "/v1/status/"

#: FortyGuard authenticates with a bare ``api-key`` request header, NOT an OAuth-style
#: ``Authorization: Bearer`` token. The live API is explicit about this:
#:   {"error": true, "status_code": 401, "details": {"message":
#:    "Missing required 'api-key' header. Send your key in the 'api-key' request header."}}
API_KEY_HEADER = "api-key"

#: Advertised capability of the FortyGuard Temperature API(R) product we integrate against.
SENSING_ELEVATION_M = 2.0
#: How many points of a request are fetched live. /v1/env_params is an asynchronous poll
#: costing seconds per point, so a route that samples hundreds of coordinates cannot be
#: fully live. The response always states how many actually were.
MAX_LIVE_POINTS = 4

#: How long an INTERACTIVE live call waits for the async job before giving up and serving the
#: calibrated field. The upstream queue is unbounded in practice -- the same two-point request
#: measured 22 s once and over 120 s a few minutes later -- so a request path that waits for it
#: indefinitely will hang. The daily calibration job uses the long timeout; this one does not.
LIVE_POLL_TIMEOUT_S = 25.0

#: The metrics we ask the upstream for. Also the checklist used to report how much of a
#: "live" reading was genuinely upstream data versus locally modelled.
LIVE_METRIC_FIELDS = (
    "air_temperature_2m",
    "surface_temperature",
    "relative_humidity",
    "wind_speed",
    "solar_irradiance",
)

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


class FortyGuardUpstreamError(RuntimeError):
    """An upstream call that failed in a way worth reporting precisely.

    Carries the real HTTP status so the feed pill can say "401 Unauthorized" instead of
    laundering every failure into a green 200.
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    #: NIOSH 2016-106 Table 6-2 adjusted temperature (air + sun + RH terms). This, not the
    #: composite exposure index, is what `risk_level` and the exposure ceilings read.
    niosh_adjusted_temp_f: float
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
    elevation_m: float = SENSING_ELEVATION_M
    endpoint: str = ENV_PARAMS_PATH
    detail: str = ""
    #: True when a live feed was configured and attempted but the simulation had to stand in.
    #: Without this a 401 or a wrong endpoint path is indistinguishable from a healthy feed.
    degraded: bool = False
    #: The upstream HTTP status actually observed, or None when live was never attempted.
    upstream_status_code: Optional[int] = None
    #: Which reading fields genuinely came from the upstream response. Anything absent here
    #: was synthesised locally, so "live" data is never silently part-simulated.
    live_fields: List[str] = field(default_factory=list)
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
        self._calibration: Dict[str, Dict[str, Any]] = {}
        self._heatmaps: Dict[str, Dict[str, Any]] = {}
        self._urban: Dict[str, Optional[UrbanIndex]] = {}
        self._real_shelters: Dict[str, Dict[str, Any]] = {}
        #: Memoised per-point env_params series, keyed (lat3, lon3, date). The upstream is
        #: an async poll, so a request that samples one coordinate repeatedly must not
        #: re-fetch it. Bounded by the number of distinct points a session touches.
        self._live_cache: Dict[Tuple[float, float, str], Dict[str, Any]] = {}
        #: How many points of the last request were genuinely fetched live.
        self._live_point_count: int = 0
        self._load_cities(cities_path)
        self._load_calibrations()
        self._load_heatmaps()
        self._load_urban()
        self._load_real_shelters()
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
        """Honest name for the data path actually serving requests.

        A configured key does NOT make request-time readings live: the upstream
        enterprise endpoints are async report/raster generators, so requests are always
        served from the local field anchored to the cached FortyGuard calibration. The
        old name "fortyguard_live" conflated key presence with data path.
        """
        if self.api_key:
            return "fortyguard_calibrated"
        return "cryonav_simulation"

    @property
    def live(self) -> bool:
        return bool(self.api_key)

    def cities(self) -> List[Dict[str, Any]]:
        """Catalogue entries for the city selector (no heavy geometry)."""
        out = []
        for city in self._cities.values():
            hm = self._heatmaps.get(city["id"])
            out.append(
                {
                    "id": city["id"],
                    "name": city["name"],
                    "region": city["region"],
                    "raster_tiles": hm["compact"]["tile_count"] if hm else 0,
                    "calibrated": city["id"] in self._calibration,
                    "has_report": self.report_meta(city["id"]) is not None,
                    "report_date": (self.report_meta(city["id"]) or {}).get("date"),
                    "country_code": city["country_code"],
                    "timezone": city["timezone"],
                    "center": city["center"],
                    "bounds": self.bounds(city["id"]),
                    "season": city["climate"]["season"],
                    "air_temp_max_f": city["climate"]["air_temp_max_f"],
                    "presets": city["presets"],
                    "shelter_count": (
                        self._real_shelters[city["id"]]["count"]
                        if city["id"] in self._real_shelters
                        else len(city["shelters"])
                    ),
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

    def data_provenance(self) -> Dict[str, Any]:
        """Per-city provenance for the measured terrain inputs.

        Read from the urban files themselves, so it cannot drift away from the data it
        describes: if a city has not been through scripts/fetch_canopy.py or fetch_lst.py, it
        reports that honestly instead of inheriting another city's citation.
        """
        out: Dict[str, Any] = {}
        for city_id in self.city_ids():
            idx = self._urban.get(city_id)
            data = getattr(idx, "data", None) if idx is not None else None
            if not data:
                out[city_id] = {"status": "no urban file; modelled fixtures in use"}
                continue
            entry: Dict[str, Any] = {
                "geometry": {
                    "source": data.get("source"),
                    "fetched_at": data.get("fetched_at"),
                    "license": data.get("license"),
                },
            }
            for key, label in (
                ("canopy", "canopy"),
                ("surface_temperature", "surface_temperature"),
                ("surface_temperature_peak", "surface_temperature_peak"),
            ):
                block = data.get(key)
                if block:
                    entry[label] = {
                        k: block[k]
                        for k in (
                            "source",
                            "resolution_m",
                            "measured_at",
                            "license",
                            "baseline_reference",
                            "canopy_height_threshold_m",
                            "city_canopy_fraction",
                            "note",
                        )
                        if k in block
                    }
                    scenes = block.get("scenes") or block.get("granules")
                    if scenes:
                        entry[label]["observations"] = len(scenes)
            # Anything still estimated must say so; silence would read as "all measured".
            remaining = {
                k: v for k, v in (data.get("assumptions") or {}).items() if k != "note"
            }
            entry["still_estimated"] = remaining or None
            out[city_id] = entry
        return out

    # -- terrain -----------------------------------------------------------------------

    def terrain(self, city_id: str, lat: float, lon: float) -> Dict[str, Any]:
        """Canopy / heat-island / water influence at a point, before any temperature maths.

        Prefers REAL OSM urban geometry (parks, street trees, covered ways, parking lots,
        lane-counted arterials) via :class:`urban.UrbanIndex`; the hand-authored gaussian
        fixtures remain only as a fallback for cities without a fetched urban file.
        Returns the same keys either way, so the thermal sampler is source-agnostic.
        """
        idx = self._urban.get(city_id)
        if idx is not None:
            raw = idx.terrain(lat, lon)
            canopy = clamp(raw["canopy_fraction"], 0.0, 0.95)
            svf = clamp(1.0 - canopy * 0.92, 0.05, 1.0)
            surface_boost = _saturate(raw["surface_boost_f"], SURFACE_BOOST_CAP_F)
            if raw["covered"] > 0.45:
                surface_type = "covered_walkway"
            elif canopy > 0.55:
                surface_type = "park_turf"
            elif raw["water_cooling_f"] > 1.6:
                surface_type = "waterfront"
            elif canopy > 0.28:
                surface_type = "canopy_shade"
            elif raw["arterial"] > 0.4 or raw.get("near_road", 0.0) > 0.5:
                # surface_boost_f is now a measured anomaly centred on zero, so it can no
                # longer stand in for "is this asphalt" -- road proximity, which is what the
                # old `> 6.0` test was really proxying for, says it directly.
                surface_type = "asphalt"
            else:
                surface_type = "concrete"
            return {
                "canopy_fraction": canopy,
                "canopy_cooling_f": _saturate(raw["canopy_cooling_f"], CANOPY_COOLING_CAP_F),
                "sky_view_factor": svf,
                "uhi_uplift_f": _saturate(raw["uhi_uplift_f"], UHI_CAP_F),
                "surface_boost_f": surface_boost,
                "water_cooling_f": _saturate(raw["water_cooling_f"], WATER_COOLING_CAP_F),
                "humidity_boost_pct": min(raw["humidity_boost_pct"], 15.0),
                "surface_type": surface_type,
                "source": "openstreetmap",
            }

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

    def sample(
        self,
        city_id: str,
        lat: float,
        lon: float,
        hour: float = 15.0,
        terr: Optional[Dict[str, Any]] = None,
    ) -> ThermalReading:
        """One simulated 2 m AGL reading. Pure function of its arguments.

        ``terr`` lets callers reuse a precomputed :meth:`terrain` result. Terrain is
        hour-independent and by far the most expensive part of a sample, so the routing
        engine computes it once per street edge and replays it across hour buckets --
        the difference between a ~6 s and a ~1 s graph rebuild on the real OSM network.
        """
        city = self.city(city_id)
        clim = city["climate"]
        peak = clim.get("peak_hour", 15.0)
        if terr is None:
            terr = self.terrain(city_id, lat, lon)

        # Prefer a real FortyGuard-derived ambient curve when this tile has been calibrated;
        # fall back to the synthetic diurnal model otherwise. Only the *ambient baseline* comes
        # from upstream -- the microclimate structure below is always locally modelled, because
        # no ambient feed resolves the 40 deg F that canopy and asphalt add within one block.
        cal = self._calibration.get(city_id)
        if cal:
            peak = cal.get("peak_hour", peak)
            base_air = self._interp_hourly(cal["air_temp_f"], hour)
            clearness = self._interp_hourly(cal["sky_clearness"], hour)
        else:
            base_air = thermal.diurnal_air_temp_f(
                clim["air_temp_min_f"], clim["air_temp_max_f"], hour, peak
            )
            clearness = clim["sky_clearness"]
        solar = thermal.solar_elevation_factor(hour, peak)

        # Desert-city urban heat island is chiefly a *nocturnal* air-temperature phenomenon:
        # by mid-afternoon the boundary layer is well mixed, while at 22:00 stored asphalt heat
        # keeps downtown several degrees hotter. The daytime penalty a pedestrian actually feels
        # is radiant, and it lives in the surface term below -- precisely the signal conventional
        # navigation drops.
        #
        # Both modulations are deliberately shallow. These are offsets riding on the diurnal
        # curve, so if their dusk-to-peak swing exceeds the curve's own amplitude the sum stops
        # being a diurnal cycle at all and air temperature climbs after sunset.
        # Cubed, not linear: the urban/rural differential is roughly flat through the day and
        # only opens up sharply once the sun is down and rural ground starts radiating away.
        # A linear ramp still climbs measurably through the afternoon, and real ambient curves
        # plateau rather than falling like a sinusoid -- so a linear ramp moves the daily
        # exposure peak to 18:00 the moment the model is fed real data.
        # Spatial air structure: prefer the real FortyGuard raster (/v1/heatmap, ~100 m tiles)
        # when cached. Its observed spread is a few tenths of a degree C -- physically right,
        # the 2 m layer is well mixed -- so when it is present the synthetic UHI/canopy air
        # offsets below must be dropped entirely: the observation already contains whatever
        # park cooling and asphalt warming exists in air temperature, and layering modelled
        # offsets on top would double-count them at 10x the observed magnitude. The radiant
        # and surface terms further down stay ours either way; air mixing does not erase the
        # 40 F a body feels between canopy shade and open asphalt.
        observed_anomaly = self.heatmap_anomaly_f(city_id, lat, lon)
        if observed_anomaly is not None:
            air = base_air + observed_anomaly
        else:
            uhi_air_weight = 0.55 + 0.45 * (1.0 - solar) ** 3
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
            * clearness
            * exposure_to_sun
        )
        # Thermal mass keeps a residual after sundown.
        residual = 6.0 * (1.0 - solar) * exposure_to_sun if 17.0 <= hour <= 23.0 else 0.0
        surface = air + asphalt_spike + residual

        # RH is derived from a conserved dewpoint, not scaled by the sun -- see
        # thermal.humidity_from_dewpoint for why that ordering matters. When calibrated, the
        # dewpoint comes from the real (ambient temp, RH) pair for this hour, so local RH
        # correctly rises in canopy shade and falls over hot asphalt.
        if cal:
            ambient_rh = self._interp_hourly(cal["relative_humidity_pct"], hour)
            dew_f = thermal.dewpoint_f(base_air, ambient_rh)
        else:
            dew_f = self._dewpoint_f(city_id)
        humidity = clamp(
            thermal.humidity_from_dewpoint(air, dew_f) + terr["humidity_boost_pct"], 4.0, 98.0
        )
        # Canopy and buildings slow the wind; open asphalt plazas get more ventilation.
        wind = clim["wind_speed_mph"] * clamp(0.45 + 0.55 * terr["sky_view_factor"], 0.35, 1.0)
        irradiance = 1000.0 * solar * clearness * exposure_to_sun

        hi = thermal.heat_index_f(air, humidity)
        mrt = thermal.mean_radiant_temp_f(air, surface, terr["sky_view_factor"])
        wbgt = thermal.wbgt_f(air, humidity, mrt, wind)
        exposure = thermal.exposure_index_f(air, hi, mrt)
        # Risk banding runs on NIOSH's own adjusted temperature -- its published sun term
        # takes our sky view factor, so shade and asphalt separate exactly as the table
        # intends, without misapplying a shade-defined heat-index tier to a radiant index.
        adjusted = standards.niosh_adjusted_temp_f(
            air_temp_f=air,
            humidity_pct=humidity,
            sky_view_factor=terr["sky_view_factor"],
            solar_factor=solar,
            sky_clearness=clearness,
        )

        return ThermalReading(
            lat=round(lat, 6),
            lon=round(lon, 6),
            air_temp_2m_f=round(air, 1),
            surface_temp_f=round(surface, 1),
            mean_radiant_temp_f=round(mrt, 1),
            heat_index_f=round(hi, 1),
            wbgt_f=round(wbgt, 1),
            exposure_index_f=round(exposure, 1),
            niosh_adjusted_temp_f=round(adjusted, 1),
            thermal_stress_score=thermal.thermal_stress_score(exposure),
            risk_level=standards.band_from_adjusted_temp(adjusted),
            relative_humidity_pct=round(humidity, 1),
            wind_speed_mph=round(wind, 1),
            solar_irradiance_wm2=round(irradiance, 0),
            canopy_cover_pct=round(terr["canopy_fraction"] * 100.0, 1),
            sky_view_factor=round(terr["sky_view_factor"], 3),
            asphalt_spike_f=round(asphalt_spike + residual, 1),
            surface_type=terr["surface_type"],
        )

    # -- live calibration via /v1/env_params ---------------------------------------------

    def env_params(
        self,
        lat: float,
        lon: float,
        reference_temp_f: float,
        date: Optional[str] = None,
        filter_type: int = 3,
        poll_timeout_s: float = 120.0,
        poll_interval_s: float = 4.0,
    ) -> Dict[str, Any]:
        """Fetch a real 24 h environmental series from ``POST /v1/env_params``.

        FortyGuard's enterprise endpoints are **asynchronous**: the POST returns an
        ``activity_id`` and the payload is collected from ``GET /v1/status/{activity_id}``
        once its status flips from "Processing" to "Completed". ``env_params`` typically
        settles in a few seconds; ``heat_intelligence`` takes minutes and yields a PDF report
        rather than machine-readable data, which is why routing calibrates from this endpoint.
        """
        import httpx  # noqa: PLC0415

        if not self.api_key:
            raise FortyGuardUpstreamError("no API key configured", status_code=401)

        headers = {
            API_KEY_HEADER: self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26)",
        }
        body = {
            "latitude": lat,
            "longitude": lon,
            "temperature": reference_temp_f,
            "date_time": {
                "start_date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "filter_type": filter_type,
            },
        }

        try:
            resp = httpx.post(
                f"{self.base_url}{ENV_PARAMS_PATH}", json=body, headers=headers, timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise FortyGuardUpstreamError(f"transport error: {exc}") from exc

        payload = self._decode(resp)
        activity_id = (payload.get("data") or {}).get("activity_id")
        if not activity_id:
            raise FortyGuardUpstreamError(
                f"no activity_id in submit response: {str(payload)[:160]}", status_code=resp.status_code
            )

        deadline = time.monotonic() + poll_timeout_s
        while True:
            try:
                poll = httpx.get(
                    f"{self.base_url}/v1/status/{activity_id}", headers=headers, timeout=self.timeout_s
                )
            except httpx.HTTPError as exc:
                raise FortyGuardUpstreamError(f"transport error while polling: {exc}") from exc

            data = self._decode(poll).get("data") or {}
            status = str(data.get("status", ""))
            if status.lower() == "completed":
                result = data.get("result")
                if not isinstance(result, dict):
                    raise FortyGuardUpstreamError("completed job carried no result object")
                return result
            if status.lower() not in ("processing", "pending", "queued", "running", ""):
                raise FortyGuardUpstreamError(f"job ended in state '{status}'")
            if time.monotonic() >= deadline:
                raise FortyGuardUpstreamError(
                    f"activity {activity_id} still '{status}' after {poll_timeout_s:.0f}s"
                )
            time.sleep(poll_interval_s)

    def _decode(self, resp: Any) -> Dict[str, Any]:
        """Decode a FortyGuard response, honouring its in-body error envelope."""
        if resp.status_code >= 400:
            snippet = resp.text[:200].replace("\n", " ").strip()
            raise FortyGuardUpstreamError(snippet or "HTTP error", status_code=resp.status_code)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise FortyGuardUpstreamError("upstream returned non-JSON", status_code=resp.status_code) from exc
        if isinstance(payload, dict) and payload.get("error"):
            details = payload.get("details") or {}
            message = (details.get("message") if isinstance(details, dict) else str(details)) or "upstream error"
            raise FortyGuardUpstreamError(str(message), status_code=payload.get("status_code"))
        return payload if isinstance(payload, dict) else {"data": payload}

    @staticmethod
    def dry_bulb_from_wet_bulb_f(wet_bulb_temp_f: float, humidity_pct: float) -> float:
        """Recover dry-bulb air temperature by inverting the wet-bulb relation.

        ``env_params`` publishes apparent temperature, wet-bulb and RH but no dry-bulb series.
        Apparent temperature already folds humidity in, so using it as air temperature would
        double-count that term downstream. Wet-bulb plus RH pins dry-bulb uniquely, and
        bisection over a monotonic function is exact enough at ~0.001 deg F in 60 iterations.
        """
        lo, hi = 20.0, 160.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if thermal.wet_bulb_f(mid, humidity_pct) < wet_bulb_temp_f:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def calibrate_city(
        self, city_id: str, date: Optional[str] = None, persist: bool = True
    ) -> Dict[str, Any]:
        """Derive a real 24 h ambient profile for a tile and cache it to disk.

        This is the fusion point of the whole system. FortyGuard supplies the *ambient truth* --
        the actual hourly dry-bulb curve, humidity and solar load over this city today. Cryonav
        supplies the *urban form* -- canopy, arterials, sky view factor -- that turns one ambient
        number into the 10 m microclimate field a pedestrian actually walks through. Neither
        half is useful alone.
        """
        city = self.city(city_id)
        clim = city["climate"]
        result = self.env_params(
            city["center"][0], city["center"][1], clim["air_temp_max_f"], date=date
        )

        parsed = self._parse_env_series(result, clim)
        loc, params, air_f, rh, wb_c, clearness, solar = (
            parsed["loc"], parsed["params"], parsed["air_f"], parsed["rh"],
            parsed["wb_c"], parsed["clearness"], parsed["solar"],
        )

        calibration = {
            "city_id": city_id,
            "date": (result.get("metadata") or {}).get("time_range", {}).get("start", date),
            "source": "fortyguard_env_params",
            "endpoint": ENV_PARAMS_PATH,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "center": city["center"],
            "elevation_m": loc.get("elevation"),
            "timezone": (result.get("metadata") or {}).get("timezone"),
            "air_temp_f": air_f,
            "relative_humidity_pct": [round(float(v), 2) for v in rh[:24]],
            "wet_bulb_f": [round(thermal.c_to_f(v), 2) for v in wb_c[:24]],
            "apparent_temp_f": [
                round(thermal.c_to_f(v), 2) for v in (params.get("apparent_temperature_celsius") or [])[:24]
            ],
            "sky_clearness": clearness,
            "clear_sky_ghi": solar.get("ghi"),
            "clear_sky_dni": solar.get("dni"),
            "air_temp_min_f": round(min(air_f), 2),
            "air_temp_max_f": round(max(air_f), 2),
            "peak_hour": float(air_f.index(max(air_f))),
        }

        if persist:
            CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
            path = CALIBRATION_DIR / f"{city_id}.json"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(calibration, fh, indent=2)
        self._calibration[city_id] = calibration
        return calibration

    def _parse_env_series(self, result: Dict[str, Any], clim: Dict[str, Any]) -> Dict[str, Any]:
        """The 24 h arrays inside an /v1/env_params response.

        Shared by the daily city calibration and the per-request live call, so the two can
        never drift into interpreting the same upstream payload differently.
        """
        loc = (result.get("locations") or [{}])[0]
        params = loc.get("parameters") or {}
        rh = params.get("relative_humidity_percent") or []
        wb_c = params.get("wet_bulb_temperature_celsius") or []
        if len(rh) < 24 or len(wb_c) < 24:
            raise FortyGuardUpstreamError(
                f"expected 24 hourly samples, got rh={len(rh)} wet_bulb={len(wb_c)}"
            )
        air_f = [
            round(self.dry_bulb_from_wet_bulb_f(thermal.c_to_f(wb_c[h]), rh[h]), 2) for h in range(24)
        ]
        clouds = params.get("cloud_cover_octas") or []
        clearness = [
            round(clamp(1.0 - (clouds[h] / 100.0) * 0.6, 0.35, 1.0), 3)
            if h < len(clouds) else clim["sky_clearness"]
            for h in range(24)
        ]
        solar = (loc.get("solar_irradiance") or {}).get("clear_sky") or {}
        return {
            "loc": loc, "params": params, "air_f": air_f, "rh": rh, "wb_c": wb_c,
            "clearness": clearness, "solar": solar,
        }

    def heatmap_fetch(
        self, city_id: str, date: Optional[str] = None, persist: bool = True,
        poll_timeout_s: float = 180.0,
    ) -> Dict[str, Any]:
        """Fetch the real FortyGuard thermal raster for a tile via ``POST /v1/heatmap``.

        The upstream returns a GeoJSON FeatureCollection of ~100 m tiles, each carrying
        ``average/min/max_temperature`` in Celsius. That is FortyGuard's actual microclimate
        product -- and it is stored compacted to centroids (~60 KB instead of ~1 MB of square
        polygons that can be reconstructed from a centroid and a cell size).
        """
        import httpx  # noqa: PLC0415

        if not self.api_key:
            raise FortyGuardUpstreamError("no API key configured", status_code=401)

        b = self.bounds(city_id)
        ring = [
            [b["west"], b["south"]], [b["east"], b["south"]],
            [b["east"], b["north"]], [b["west"], b["north"]], [b["west"], b["south"]],
        ]
        headers = {
            API_KEY_HEADER: self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26)",
        }
        body = {
            "polygon_aoi": {"type": "Polygon", "coordinates": [ring]},
            "date_time": {
                "start_date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "filter_type": 3,
            },
        }
        try:
            resp = httpx.post(
                f"{self.base_url}{HEATMAP_PATH}", json=body, headers=headers, timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise FortyGuardUpstreamError(f"transport error: {exc}") from exc

        payload = self._decode(resp)
        activity_id = (payload.get("data") or {}).get("activity_id")
        if not activity_id:
            raise FortyGuardUpstreamError("no activity_id in heatmap submit response")

        deadline = time.monotonic() + poll_timeout_s
        while True:
            try:
                poll = httpx.get(
                    f"{self.base_url}/v1/status/{activity_id}", headers=headers, timeout=self.timeout_s
                )
            except httpx.HTTPError as exc:
                raise FortyGuardUpstreamError(f"transport error while polling: {exc}") from exc
            data = self._decode(poll).get("data") or {}
            status = str(data.get("status", ""))
            if status.lower() == "completed":
                fc = ((data.get("result") or {}).get("map_data")) or {}
                compact = self._compact_heatmap(city_id, fc, body["date_time"]["start_date"])
                if persist:
                    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
                    with open(CALIBRATION_DIR / f"{city_id}_heatmap.json", "w", encoding="utf-8") as fh:
                        json.dump(compact, fh)
                self._install_heatmap(compact)
                return compact
            if status.lower() not in ("processing", "pending", "queued", "running", ""):
                raise FortyGuardUpstreamError(f"heatmap job ended in state '{status}'")
            if time.monotonic() >= deadline:
                raise FortyGuardUpstreamError(f"heatmap still '{status}' after {poll_timeout_s:.0f}s")
            time.sleep(4.0)

    @staticmethod
    def _compact_heatmap(city_id: str, fc: Dict[str, Any], date: str) -> Dict[str, Any]:
        """Reduce a FeatureCollection of square tiles to centroid arrays."""
        feats = fc.get("features") or []
        if not feats:
            # The raster product has narrower geographic coverage than env_params: US tiles
            # return ~2,400 features, Gulf tiles return an empty collection. Say that, rather
            # than a generic parse error, so an operator doesn't chase a schema bug.
            raise FortyGuardUpstreamError(
                "heatmap returned no tiles for this AOI (raster coverage appears US-only; "
                "ambient env_params still works here)"
            )
        lats: List[float] = []
        lons: List[float] = []
        avg: List[float] = []
        tmin: List[float] = []
        tmax: List[float] = []
        for f in feats:
            try:
                ring = f["geometry"]["coordinates"][0]
                props = f["properties"]
                lats.append(round(sum(pt[1] for pt in ring) / len(ring), 6))
                lons.append(round(sum(pt[0] for pt in ring) / len(ring), 6))
                avg.append(float(props["average_temperature"]))
                tmin.append(float(props["min_temperature"]))
                tmax.append(float(props["max_temperature"]))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        if not lats:
            raise FortyGuardUpstreamError("no parseable features in heatmap response")
        mean_avg = sum(avg) / len(avg)
        return {
            "city_id": city_id,
            "kind": "fortyguard_heatmap",
            "endpoint": HEATMAP_PATH,
            "date": date,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tile_count": len(lats),
            "cell_size_m": 100.0,
            "units": "celsius",
            "mean_avg_temp_c": round(mean_avg, 4),
            "lat": lats,
            "lon": lons,
            "avg_temp_c": avg,
            "min_temp_c": tmin,
            "max_temp_c": tmax,
        }

    def _install_heatmap(self, compact: Dict[str, Any]) -> None:
        """Index a compact heatmap for O(1) nearest-centroid lookup during sampling."""
        lats, lons = compact["lat"], compact["lon"]
        step = 0.001  # ~100 m bins matching the upstream tile size
        index: Dict[Tuple[int, int], int] = {}
        for i in range(len(lats)):
            index[(int(lats[i] / step), int(lons[i] / step))] = i
        mean_avg = compact["mean_avg_temp_c"]
        self._heatmaps[compact["city_id"]] = {
            "compact": compact,
            "index": index,
            "step": step,
            "mean_avg_c": mean_avg,
        }

    def heatmap(self, city_id: str) -> Optional[Dict[str, Any]]:
        entry = self._heatmaps.get(city_id)
        return entry["compact"] if entry else None

    def heatmap_anomaly_f(self, city_id: str, lat: float, lon: float) -> Optional[float]:
        """Observed air-temperature anomaly (deg F) at a point, relative to the tile mean.

        Returns ``None`` when no raster is cached or the point falls outside it, so the
        caller can fall back to the modelled anomaly rather than treating "no data" as zero.
        """
        entry = self._heatmaps.get(city_id)
        if entry is None:
            return None
        step = entry["step"]
        index = entry["index"]
        base = (int(lat / step), int(lon / step))
        for dr in (0, -1, 1):
            for dc in (0, -1, 1):
                i = index.get((base[0] + dr, base[1] + dc))
                if i is not None:
                    avg = entry["compact"]["avg_temp_c"][i]
                    return (avg - entry["mean_avg_c"]) * 1.8
        return None

    def _load_heatmaps(self) -> None:
        if not CALIBRATION_DIR.is_dir():
            return
        for path in CALIBRATION_DIR.glob("*_heatmap.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    compact = json.load(fh)
            except (OSError, ValueError):
                continue
            if compact.get("kind") == "fortyguard_heatmap" and compact.get("city_id") in self._cities:
                self._install_heatmap(compact)

    def _load_calibrations(self) -> None:
        """Load any cached FortyGuard calibration so the demo starts already fused."""
        if not CALIBRATION_DIR.is_dir():
            return
        for path in CALIBRATION_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cal = json.load(fh)
            except (OSError, ValueError):
                continue
            if cal.get("city_id") in self._cities and len(cal.get("air_temp_f", [])) == 24:
                self._calibration[cal["city_id"]] = cal

    def fetch_heat_report(self, city_id: str, poll_timeout_s: float = 600.0) -> Dict[str, Any]:
        """Generate and cache FortyGuard's heat-intelligence analyst report (PDF).

        ``POST /v1/heat_intelligence`` is an async report generator (~2.5 min): it returns an
        ``activity_id`` whose completed result carries a presigned S3 link. That link embeds
        the caller's API key in the object path, so it is downloaded HERE, server-side, and
        only the stored bytes are ever served to a browser. Cached to data/reports/ with a
        metadata sidecar; the daily calibration timer refreshes it.
        """
        import httpx  # noqa: PLC0415

        if not self.api_key:
            raise FortyGuardUpstreamError("no API key configured", status_code=401)

        city = self.city(city_id)
        headers = {
            API_KEY_HEADER: self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Cryonav/1.0 (FortyGuard Hackathon 26)",
        }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = {
            "latitude": city["center"][0],
            "longitude": city["center"][1],
            "temperature": city["climate"]["air_temp_max_f"],
            "date": today,
            "analysis": ["geographic", "environmental", "urban", "events", "anthropogenic"],
        }
        try:
            resp = httpx.post(
                f"{self.base_url}{HEAT_INTELLIGENCE_PATH}", json=body, headers=headers,
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise FortyGuardUpstreamError(f"transport error: {exc}") from exc
        payload = self._decode(resp)
        activity_id = (payload.get("data") or {}).get("activity_id")
        if not activity_id:
            raise FortyGuardUpstreamError("no activity_id in heat_intelligence submit response")

        deadline = time.monotonic() + poll_timeout_s
        link = None
        while True:
            try:
                poll = httpx.get(
                    f"{self.base_url}/v1/status/{activity_id}", headers=headers,
                    timeout=self.timeout_s,
                )
            except httpx.HTTPError as exc:
                raise FortyGuardUpstreamError(f"transport error while polling: {exc}") from exc
            data = self._decode(poll).get("data") or {}
            status = str(data.get("status", "")).lower()
            if status == "completed":
                link = ((data.get("result") or {}).get("download_link"))
                break
            if status not in ("processing", "pending", "queued", "running", ""):
                raise FortyGuardUpstreamError(f"report job ended in state '{status}'")
            if time.monotonic() >= deadline:
                raise FortyGuardUpstreamError(
                    f"report still processing after {poll_timeout_s:.0f}s"
                )
            time.sleep(6.0)
        if not link:
            raise FortyGuardUpstreamError("completed report carried no download_link")

        # Download immediately: the link is a short-lived presigned URL AND contains the
        # API key in its object path — it must not be stored or forwarded.
        try:
            pdf = httpx.get(link, timeout=60.0)
            pdf.raise_for_status()
        except httpx.HTTPError as exc:
            raise FortyGuardUpstreamError(f"report download failed: {exc}") from exc
        if not pdf.content.startswith(b"%PDF"):
            raise FortyGuardUpstreamError(
                f"report is not a PDF ({pdf.headers.get('content-type', 'unknown')})"
            )

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = REPORTS_DIR / f"{city_id}.pdf"
        with open(pdf_path, "wb") as fh:
            fh.write(pdf.content)
        meta = {
            "city_id": city_id,
            "date": today,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": HEAT_INTELLIGENCE_PATH,
            "analyses": body["analysis"],
            "bytes": len(pdf.content),
            "source": "fortyguard_heat_intelligence",
        }
        with open(REPORTS_DIR / f"{city_id}.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1)
        return meta

    def report_meta(self, city_id: str) -> Optional[Dict[str, Any]]:
        """Metadata of the cached analyst report, or None when absent."""
        path = REPORTS_DIR / f"{city_id}.json"
        if not path.is_file() or not (REPORTS_DIR / f"{city_id}.pdf").is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def report_path(self, city_id: str) -> Path:
        return REPORTS_DIR / f"{city_id}.pdf"

    def _load_urban(self) -> None:
        """Real OSM urban form (scripts/fetch_urban.py). Missing file => legacy fixtures."""
        for cid in self._cities:
            self._urban[cid] = load_urban_index(URBAN_DIR, cid)

    def _load_real_shelters(self) -> None:
        """Real refuge data (scripts/fetch_shelters.py): official MAG network for Phoenix,
        OSM POIs for the Gulf. Missing file => the hand-authored cities.json list."""
        if not SHELTERS_DIR.is_dir():
            return
        for path in SHELTERS_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            if data.get("city_id") in self._cities and data.get("shelters"):
                self._real_shelters[data["city_id"]] = data

    def urban(self, city_id: str) -> Optional[UrbanIndex]:
        return self._urban.get(city_id)

    def shelter_source(self, city_id: str) -> Dict[str, Any]:
        real = self._real_shelters.get(city_id)
        if real:
            return {
                "source": real["source"],
                "attribution": real.get("attribution"),
                "disclaimer": real.get("disclaimer"),
                "fetched_at": real.get("fetched_at"),
                "count": real["count"],
            }
        return {"source": "hand_authored_fixture", "count": len(self.city(city_id)["shelters"])}

    def calibration(self, city_id: str) -> Optional[Dict[str, Any]]:
        return self._calibration.get(city_id)

    def calibration_summary(self, city_id: str) -> Dict[str, Any]:
        """Provenance of this tile's ambient baseline, for the dashboard to display.

        The distinction matters: a calibrated tile's temperature curve is real FortyGuard
        observation, while an uncalibrated one is entirely modelled. Presenting both the same
        way would overstate what the live integration actually contributes.
        """
        cal = self._calibration.get(city_id)
        if not cal:
            return {
                "calibrated": False,
                "source": "synthetic_diurnal_model",
                "detail": "ambient curve modelled locally; run scripts/calibrate.py for live data",
            }
        return {
            "calibrated": True,
            "source": cal.get("source", "fortyguard_env_params"),
            "endpoint": cal.get("endpoint", ENV_PARAMS_PATH),
            "date": cal.get("date"),
            "fetched_at": cal.get("fetched_at"),
            "timezone": cal.get("timezone"),
            "elevation_m": cal.get("elevation_m"),
            "air_temp_min_f": cal.get("air_temp_min_f"),
            "air_temp_max_f": cal.get("air_temp_max_f"),
            "peak_hour": cal.get("peak_hour"),
            "detail": (
                f"ambient 24 h curve from FortyGuard {ENV_PARAMS_PATH}; "
                f"microclimate structure modelled locally"
            ),
        }

    @staticmethod
    def _interp_hourly(series: Sequence[float], hour: float) -> float:
        """Linear interpolation across a 24 h series, wrapping at midnight."""
        h = hour % 24.0
        i = int(h)
        frac = h - i
        return float(series[i]) * (1.0 - frac) + float(series[(i + 1) % 24]) * frac

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
        # Per-request, not per-instance. Left as instance state it survived into the NEXT
        # request and reported points as live that this call never fetched.
        self._live_point_count = 0

        if prefer_live and self.live:
            try:
                readings, live_fields = self._call_live(points, resolved_city, hour)
                status = FeedStatus(
                    source="fortyguard_live",
                    status_code=200,
                    ok=True,
                    upstream_status_code=200,
                    live_fields=live_fields,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    detail=(
                        "FortyGuard Temperature API(R) 200 OK"
                        + ("" if len(live_fields) == len(LIVE_METRIC_FIELDS)
                           else f" -- {len(live_fields)}/{len(LIVE_METRIC_FIELDS)} metrics present, "
                                f"remainder modelled locally")
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - degrade, never crash the demo
                # Report the real upstream status. Laundering a 401 or a 404 into a green
                # "200 OK" is worse than the outage itself: it hides a broken integration
                # behind data that looks live, which is exactly how a wrong endpoint path
                # ships unnoticed.
                upstream = getattr(exc, "status_code", None)
                status = FeedStatus(
                    source="cryonav_simulation",
                    status_code=upstream or 503,
                    ok=False,
                    degraded=True,
                    upstream_status_code=upstream,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    detail=(
                        f"FortyGuard upstream failed ({upstream or type(exc).__name__}: {exc}); "
                        f"served from deterministic simulation"
                    ),
                )

        if readings is None:
            readings = [self.sample(resolved_city, lat, lon, hour) for lat, lon in points]
            status.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            if not status.detail:
                # Say what the local field is actually made of. "Simulation" alone undersells a
                # tile whose ambient curve and spatial raster both came from FortyGuard today.
                cal = self._calibration.get(resolved_city)
                has_raster = resolved_city in self._heatmaps
                if cal and has_raster:
                    status.source = "fortyguard_calibrated"
                    status.detail = (
                        f"calibrated field: FortyGuard env_params {str(cal.get('date'))[:10]} "
                        f"+ heatmap raster; microclimate structure modelled locally"
                    )
                elif cal:
                    status.source = "fortyguard_calibrated"
                    status.detail = (
                        f"calibrated field: FortyGuard env_params {str(cal.get('date'))[:10]}; "
                        f"spatial structure modelled locally"
                    )
                else:
                    status.detail = "deterministic microclimate simulation (uncalibrated tile)"

        self.last_status = status
        peak = max(readings, key=lambda r: r.exposure_index_f)

        return {
            "city_id": resolved_city,
            "hour": hour,
            "feed": status.as_dict(),
            # Resolution is reported as what each source actually delivers. A single
            # "resolution_mi2: 10.0" used to sit here; it was Cryonav's own invention, sent
            # to an endpoint that has no resolution parameter, and published as though it
            # were FortyGuard's specification.
            "sensing": {
                "elevation_m": SENSING_ELEVATION_M,
                "endpoint": ENV_PARAMS_PATH,
                "tile_area_mi2": self.tile_area_mi2(resolved_city),
                "live_points": getattr(self, "_live_point_count", 0),
                "resolution": {
                    "fortyguard_ambient": "point query, 24 h hourly series (no spatial parameter)",
                    "fortyguard_raster_m": 100 if resolved_city in self._heatmaps else None,
                    "canopy_m": 1.19,
                    "surface_temp_m": 70 if "surface_temperature_peak" in (
                        getattr(self._urban.get(resolved_city), "data", {}) or {}
                    ) else 30,
                },
                "calibration": self.calibration_summary(resolved_city),
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
    ) -> Tuple[List[ThermalReading], List[str]]:
        """Per-request call to the real FortyGuard API, one point at a time.

        WHAT THIS USED TO DO, AND WHY IT WAS WRONG. It POSTed a ``locations`` array plus a
        ``resolution_mi2`` field to /v1/heat_intelligence. That endpoint accepts neither: it
        wants a flat latitude/longitude, and it has no resolution parameter at all. Every call
        returned 422, the caller caught it, and the app silently served its daily calibration
        while reporting a green feed. The invented ``resolution_mi2: 10.0`` was then published
        in the API response as if it were FortyGuard's figure.

        The real contract is /v1/env_params: flat lat/lon plus a reference temperature and a
        date_time object, answered ASYNCHRONOUSLY -- the POST returns an activity_id and the
        payload is collected from /v1/status/{id}. It yields the observed 24 h series for that
        point, which is what a per-request live call should use.

        Because each call is a poll costing seconds, only the first MAX_LIVE_POINTS points are
        fetched live; the rest come from the calibrated field. The caller is told exactly how
        many were live, so a partially-live answer never presents itself as fully live.
        """
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        clim = self.city(city_id)["climate"]
        h = int(clamp(hour, 0, 23))

        readings: List[ThermalReading] = []
        live_count = 0
        fields: set = set()

        for idx, (lat, lon) in enumerate(points):
            if idx >= MAX_LIVE_POINTS:
                readings.append(self.sample(city_id, lat, lon, hour))
                continue
            series = self._live_series(lat, lon, clim["air_temp_max_f"], date)
            record = {
                "air_temperature_2m": series["air_f"][h],
                "relative_humidity": float(series["rh"][h]),
                "wind_speed": clim["wind_speed_mph"],
                "solar_irradiance": self._hour_irradiance(series, h),
            }
            fields.update(("air_temperature_2m", "relative_humidity"))
            if series["solar"].get("ghi") is not None:
                fields.add("solar_irradiance")
            readings.append(self._reading_from_live(city_id, (lat, lon), record))
            live_count += 1

        if live_count == 0:
            raise FortyGuardUpstreamError("no point could be fetched live", status_code=503)
        self._live_point_count = live_count
        return readings, sorted(fields)

    @staticmethod
    def _hour_irradiance(series: Dict[str, Any], hour: int) -> float:
        """Irradiance at one hour, W/m^2.

        env_params reports clear-sky GHI as a SINGLE daily figure, not an hourly array, while
        cloud cover -- and therefore sky clearness -- is hourly. So the hour's load is the
        day's clear-sky ceiling shaped by the sun's elevation and then reduced by the cloud
        actually observed in that hour. Both inputs are upstream measurements; only the
        elevation curve is ours, and it is the same one the modelled path uses.

        Handles a list too, in case the upstream starts returning an hourly series.
        """
        ghi = series["solar"].get("ghi")
        if ghi is None:
            return 0.0
        if isinstance(ghi, (list, tuple)):
            return float(ghi[hour]) if hour < len(ghi) else 0.0
        clearness = series["clearness"]
        c = float(clearness[hour]) if hour < len(clearness) else 1.0
        return round(float(ghi) * thermal.solar_elevation_factor(float(hour)) * c, 1)

    def _live_series(
        self, lat: float, lon: float, reference_temp_f: float, date: str
    ) -> Dict[str, Any]:
        """Observed 24 h series for one point, memoised.

        env_params is an async poll, so the same coordinate must not be re-fetched within a
        request that samples it repeatedly. Keyed at 3 decimal places -- about 110 m, finer
        than the upstream's own sampling, so the cache never merges genuinely distinct places.
        """
        key = (round(lat, 3), round(lon, 3), date)
        cached = self._live_cache.get(key)
        if cached is not None:
            return cached
        result = self.env_params(
            lat, lon, reference_temp_f, date=date,
            poll_timeout_s=LIVE_POLL_TIMEOUT_S, poll_interval_s=2.0,
        )
        parsed = self._parse_env_series(result, self.city(self.resolve_city(lat, lon))["climate"])
        self._live_cache[key] = parsed
        return parsed

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
        # Risk banding runs on NIOSH's own adjusted temperature -- its published sun term
        # takes our sky view factor, so shade and asphalt separate exactly as the table
        # intends, without misapplying a shade-defined heat-index tier to a radiant index.
        # No hour is in scope here, but the upstream record carries irradiance -- so the
        # sun term is driven by the OBSERVED solar load rather than a modelled curve.
        # ~1000 W/m2 is clear-sky noon; the ratio is the fraction of full sun.
        observed_solar = clamp(irradiance / 1000.0, 0.0, 1.0)
        adjusted = standards.niosh_adjusted_temp_f(
            air_temp_f=air,
            humidity_pct=humidity,
            sky_view_factor=terr["sky_view_factor"],
            solar_factor=observed_solar,
            sky_clearness=clim.get("sky_clearness", 1.0),
        )

        return ThermalReading(
            lat=round(lat, 6),
            lon=round(lon, 6),
            air_temp_2m_f=round(air, 1),
            surface_temp_f=round(surface, 1),
            mean_radiant_temp_f=round(mrt, 1),
            heat_index_f=round(hi, 1),
            wbgt_f=round(wbgt, 1),
            exposure_index_f=round(exposure, 1),
            niosh_adjusted_temp_f=round(adjusted, 1),
            thermal_stress_score=thermal.thermal_stress_score(exposure),
            risk_level=standards.band_from_adjusted_temp(adjusted),
            relative_humidity_pct=round(humidity, 1),
            wind_speed_mph=round(wind, 1),
            solar_irradiance_wm2=round(irradiance, 0),
            canopy_cover_pct=round(terr["canopy_fraction"] * 100.0, 1),
            sky_view_factor=round(terr["sky_view_factor"], 3),
            asphalt_spike_f=round(max(surface - air, 0.0), 1),
            surface_type=terr["surface_type"],
        )

    # -- grid --------------------------------------------------------------------------

    def raster_grid(self, city_id: str) -> Dict[str, Any]:
        """The real FortyGuard /v1/heatmap raster, shaped like :meth:`thermal_grid`.

        Same array layout so the dashboard's canvas can render either layer, but the values
        are observed daily-average air temperature per ~100 m tile -- FortyGuard's data,
        not Cryonav's model. Raises ``KeyError`` when no raster is cached for the city.
        """
        entry = self._heatmaps.get(city_id)
        if entry is None:
            raise KeyError(f"no FortyGuard raster cached for '{city_id}'")
        c = entry["compact"]
        avg_f = [round(v * 1.8 + 32.0, 2) for v in c["avg_temp_c"]]
        max_f = [round(v * 1.8 + 32.0, 2) for v in c["max_temp_c"]]
        cells = [
            [c["lat"][i], c["lon"][i], avg_f[i], max_f[i]] for i in range(len(avg_f))
        ]
        return {
            "city_id": city_id,
            "source": "fortyguard_heatmap",
            "endpoint": c["endpoint"],
            "date": c["date"],
            "fetched_at": c["fetched_at"],
            "units_label": "observed avg air temp (deg F)",
            "resolution": None,
            "cell_size_m": c["cell_size_m"],
            "bounds": self.bounds(city_id),
            "tile_area_mi2": self.tile_area_mi2(city_id),
            "cells": cells,
            "exposure_index_f": avg_f,
            "risk_rank": [],
            "legend": [],
            "stats": {
                "min_exposure_f": round(min(avg_f), 2),
                "max_exposure_f": round(max(avg_f), 2),
                "mean_exposure_f": round(sum(avg_f) / len(avg_f), 2),
                "extreme_cell_pct": 0.0,
            },
        }

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
        real = self._real_shelters.get(city_id)
        catalogue = real["shelters"] if real else city["shelters"]

        out: List[Dict[str, Any]] = []
        for shelter in catalogue:
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
