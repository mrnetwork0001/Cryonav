"""
Cryonav agentic layer.

Three specialised agents cooperate over a shared blackboard to answer one request:

    ThermalSensingAgent          -> what is the heat actually doing on this tile right now?
    CoolRouteOptimizationAgent   -> given that, what are the two routes and what does B buy?
    EmergencyThermalSentinelAgent-> is the chosen route survivable, and if not, what changes?

The Sentinel is the one that can *revise* another agent's output: if the cool route still
carries more continuous high-risk exposure than the profile tolerates, it re-runs the optimiser
with a mandatory cooling-shelter waypoint. That feedback edge is what makes this an agent loop
rather than a three-stage pipeline.

Every agent appends structured entries to a shared trace. The dashboard renders that trace
live, so the reasoning is visible rather than asserted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import notify as notify_module
import thermal
from fortyguard_service import FortyGuardService
from routing_engine import Coord, Route, RoutingEngine, profile_or_default
from thermal import haversine_m

#: Air temperature above which the Sentinel treats a corridor as an acute-danger zone.
EXTREME_AIR_TEMP_F = 110.0

#: A stationary user in extreme heat for longer than this is treated as possible incapacitation.
IMMOBILITY_ALERT_MINUTES = 8.0

#: GPS jitter floor -- movement below this over the dwell window is not real movement.
IMMOBILITY_RADIUS_M = 25.0


# --------------------------------------------------------------------------------------
# Blackboard
# --------------------------------------------------------------------------------------


@dataclass
class Blackboard:
    """Shared working memory. Agents read what earlier agents wrote and may revise it."""

    city_id: str
    hour: float
    profile: Dict[str, Any]
    origin: Coord
    destination: Coord
    facts: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        agent: str,
        action: str,
        detail: str,
        data: Optional[Dict[str, Any]] = None,
        elapsed_ms: float = 0.0,
    ) -> None:
        self.trace.append(
            {
                "step": len(self.trace) + 1,
                "agent": agent,
                "action": action,
                "detail": detail,
                "data": data or {},
                "elapsed_ms": round(elapsed_ms, 2),
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )


class Agent:
    """Base class: gives every agent a name and a timed ``run`` wrapper."""

    name = "agent"
    role = ""

    def __init__(self, service: FortyGuardService, engine: RoutingEngine) -> None:
        self.service = service
        self.engine = engine

    def run(self, bb: Blackboard) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def execute(self, bb: Blackboard) -> float:
        started = time.perf_counter()
        self.run(bb)
        return (time.perf_counter() - started) * 1000.0


# --------------------------------------------------------------------------------------
# 1. Thermal Sensing Agent
# --------------------------------------------------------------------------------------


class ThermalSensingAgent(Agent):
    """Polls the FortyGuard Temperature API(R) and classifies the tile's risk vectors."""

    name = "thermal_sensing"
    role = "Polls FortyGuard live feeds, classifies microclimate risk, tracks asphalt radiation spikes."

    def run(self, bb: Blackboard) -> None:
        started = time.perf_counter()

        # Probe the corridor itself plus the tile centroid, so the feed status reflects the
        # geography the user is about to walk through rather than an arbitrary point.
        probes = [
            bb.origin,
            bb.destination,
            ((bb.origin[0] + bb.destination[0]) / 2, (bb.origin[1] + bb.destination[1]) / 2),
        ]
        # prefer_live=False is deliberate, not a downgrade. The upstream heat_intelligence
        # endpoint is an async PDF-report generator: a synchronous call at request time would
        # submit a billable job per navigation and still have to serve this response from the
        # local field. Live FortyGuard data enters through the calibrated daily pull
        # (scripts/calibrate.py -> env_params + heatmap), which this sample already contains.
        intel = self.service.heat_intelligence(probes, bb.city_id, bb.hour, prefer_live=False)
        readings = intel["readings"]

        origin_reading, dest_reading, mid_reading = readings[0], readings[1], readings[2]
        peak = max(readings, key=lambda r: r["exposure_index_f"])
        spike = max(r["surface_temp_f"] - r["air_temp_2m_f"] for r in readings)

        bb.facts["feed"] = intel["feed"]
        bb.facts["sensing"] = intel["sensing"]
        bb.facts["origin_reading"] = origin_reading
        bb.facts["destination_reading"] = dest_reading
        bb.facts["corridor_reading"] = mid_reading
        bb.facts["ambient"] = {
            "air_temp_2m_f": mid_reading["air_temp_2m_f"],
            "surface_temp_f": mid_reading["surface_temp_f"],
            "heat_index_f": mid_reading["heat_index_f"],
            "wbgt_f": mid_reading["wbgt_f"],
            "exposure_index_f": mid_reading["exposure_index_f"],
            "relative_humidity_pct": mid_reading["relative_humidity_pct"],
            "wind_speed_mph": mid_reading["wind_speed_mph"],
            "risk_level": mid_reading["risk_level"],
            "risk_color": mid_reading["risk_color"],
            "advisory": thermal.RISK_ADVISORY[mid_reading["risk_level"]],
        }
        bb.facts["risk_vector"] = {
            "peak_risk_level": peak["risk_level"],
            "peak_exposure_index_f": peak["exposure_index_f"],
            "peak_at": [peak["lat"], peak["lon"]],
            "asphalt_radiation_spike_f": round(spike, 1),
            "asphalt_trap_detected": spike >= 35.0,
            "acute_danger_zone": peak["air_temp_2m_f"] >= EXTREME_AIR_TEMP_F,
        }

        elapsed = (time.perf_counter() - started) * 1000.0
        bb.record(
            self.name,
            "poll_fortyguard",
            (
                f"{intel['feed']['source']} {intel['feed']['status_code']} OK - corridor "
                f"{mid_reading['air_temp_2m_f']}F air / {mid_reading['surface_temp_f']}F surface, "
                f"{peak['risk_level'].upper()} risk"
            ),
            {
                "source": intel["feed"]["source"],
                "resolution_mi2": intel["sensing"]["resolution_mi2"],
                "elevation_m": intel["sensing"]["elevation_m"],
                "probes": len(probes),
                "asphalt_radiation_spike_f": round(spike, 1),
                "peak_risk_level": peak["risk_level"],
            },
            elapsed,
        )

        if bb.facts["risk_vector"]["asphalt_trap_detected"]:
            bb.record(
                self.name,
                "flag_asphalt_trap",
                (
                    f"Asphalt thermal trap: surface running {round(spike)}F above 2m air "
                    f"temperature. Radiant load is the dominant hazard on this corridor."
                ),
                {"spike_f": round(spike, 1)},
            )


# --------------------------------------------------------------------------------------
# 2. Cool-Route Optimization Agent
# --------------------------------------------------------------------------------------


class CoolRouteOptimizationAgent(Agent):
    """Solves the dual-path problem and explains what the cool route bought."""

    name = "cool_route_optimizer"
    role = "Generates Standard vs Cryonav Cool Route and scores the thermal trade-off."

    def run(self, bb: Blackboard) -> None:
        started = time.perf_counter()
        solution = self.engine.solve(
            city_id=bb.city_id,
            origin=bb.origin,
            destination=bb.destination,
            hour=bb.hour,
            profile_id=bb.profile["id"],
            via=bb.facts.get("forced_waypoints"),
            baseline=bb.facts.get("standard_route"),
        )
        elapsed = (time.perf_counter() - started) * 1000.0

        standard: Route = solution["standard"]
        cool: Route = solution["cool"]
        comparison = solution["comparison"]

        bb.facts["standard_route"] = standard
        bb.facts["cool_route"] = cool
        bb.facts["comparison"] = comparison
        bb.facts["search_trace"] = solution["search_trace"]
        bb.facts["graph"] = solution["graph"]
        bb.facts["hotspots"] = self.engine.corridor_hotspots(
            solution["graph"], standard, limit=3
        )

        rejected = [s for s in solution["search_trace"] if not s["accepted"]]
        bb.record(
            self.name,
            "solve_dual_route",
            (
                f"Evaluated {len(solution['search_trace'])} thermal weightings; "
                f"{len(rejected)} rejected on detour/dose grounds. "
                f"Cool route sheds {comparison['thermal_load_reduction_f']}F thermal load "
                f"for {comparison['added_minutes']:+.1f} min."
            ),
            {
                "candidates": solution["search_trace"],
                "selected_aversion": cool.thermal_aversion_used,
                "detour_ratio": comparison["detour_ratio"],
            },
            elapsed,
        )
        bb.record(
            self.name,
            "score_tradeoff",
            (
                f"Path A {standard.distance_m / 1000:.2f} km @ {standard.mean_exposure_index_f:.1f}F mean "
                f"vs Path B {cool.distance_m / 1000:.2f} km @ {cool.mean_exposure_index_f:.1f}F mean - "
                f"heat stress {comparison['heat_stress_reduction_pct']:+.1f}%, "
                f"shade coverage {comparison['shade_coverage_gain_pct']:+.1f}%."
            ),
            {
                "thermal_load_reduction_f": comparison["thermal_load_reduction_f"],
                "heat_stress_reduction_pct": comparison["heat_stress_reduction_pct"],
                "thermal_dose_reduction_pct": comparison["thermal_dose_reduction_pct"],
                "high_risk_exposure_reduction_pct": comparison["high_risk_exposure_reduction_pct"],
            },
        )

        if bb.facts["hotspots"]:
            worst = bb.facts["hotspots"][0]
            bb.record(
                self.name,
                "identify_hazard",
                (
                    f"Worst trap avoided on Path A: {worst['surface_type']} at "
                    f"{worst['surface_temp_f']}F surface ({worst['risk_level'].upper()})."
                ),
                worst,
            )


# --------------------------------------------------------------------------------------
# 3. Emergency Thermal Sentinel Agent
# --------------------------------------------------------------------------------------


class EmergencyThermalSentinelAgent(Agent):
    """Guards the chosen route, and revises it when continuous exposure exceeds tolerance."""

    name = "emergency_sentinel"
    role = "Monitors transit dwell in >110F zones; triggers shelter reroute or dispatch."

    def run(self, bb: Blackboard) -> None:
        started = time.perf_counter()
        cool: Route = bb.facts["cool_route"]
        profile = bb.profile

        # Public-health guidance is written as a continuous-exposure ceiling per risk band,
        # scaled here by how well this profile thermoregulates.
        band = thermal.classify_risk(cool.mean_exposure_index_f)
        ceiling_min = thermal.SAFE_EXPOSURE_MINUTES[band] * profile["safe_exposure_scale"]

        # The ceiling applies to *continuous* exposure, not the route total. A 40-minute walk
        # broken by an air-conditioned lobby is materially safer than an unbroken 25-minute one,
        # and only the longest unbroken leg is comparable to published guidance.
        exceeded = cool.longest_high_risk_leg_min > ceiling_min

        bb.facts["safety"] = {
            "risk_band": band,
            "continuous_exposure_ceiling_min": round(ceiling_min, 1),
            "route_high_risk_min": round(cool.high_plus_exposure_min, 1),
            "longest_high_risk_leg_min": round(cool.longest_high_risk_leg_min, 1),
            "ceiling_exceeded": exceeded,
            "hydration_ml": cool.hydration_ml,
            "advisory": thermal.RISK_ADVISORY[band],
        }

        shelters = self.service.shelters(
            bb.city_id,
            lat=cool.geometry[len(cool.geometry) // 2][0],
            lon=cool.geometry[len(cool.geometry) // 2][1],
            radius_m=1800.0,
            limit=5,
            hour=bb.hour,
            require_ac=True,
        )
        bb.facts["nearby_shelters"] = shelters

        elapsed = (time.perf_counter() - started) * 1000.0
        bb.record(
            self.name,
            "assess_exposure",
            (
                f"{cool.high_plus_exposure_min:.1f} min continuous high-risk exposure against a "
                f"{ceiling_min:.0f} min ceiling for {profile['label']} in the {band.upper()} band."
            ),
            bb.facts["safety"],
            elapsed,
        )

        if not exceeded:
            bb.record(
                self.name,
                "clear",
                f"Route within safe continuous-exposure limits. Carry {cool.hydration_ml} ml water.",
                {"hydration_ml": cool.hydration_ml},
            )
            return

        # Exposure assessment above always runs; only the corrective reroute is optional, so
        # that turning the shelter feature off still leaves the user with a safety verdict.
        if not bb.facts.get("allow_shelter_reroute", True):
            bb.record(
                self.name,
                "reroute_suppressed",
                (
                    f"Continuous-exposure ceiling exceeded by "
                    f"{cool.longest_high_risk_leg_min - ceiling_min:.1f} min, but shelter rerouting is "
                    f"disabled. Enable it to insert a cooling break."
                ),
                {"shortfall_min": round(cool.longest_high_risk_leg_min - ceiling_min, 1)},
            )
            bb.facts["shelter_reroute"] = {"applied": False, "reason": "shelter rerouting disabled"}
            return

        if not shelters:
            bb.record(
                self.name,
                "escalate",
                "Exposure ceiling exceeded and no air-conditioned shelter within 1.8 km. "
                "Recommend postponing transit or arranging vehicle pickup.",
                {"escalation": "no_shelter_in_range"},
            )
            bb.facts["escalation"] = "no_shelter_in_range"
            return

        # --- The feedback edge: trial each candidate shelter as a mandatory waypoint and keep
        # the one that best breaks the continuous-exposure leg. Trialling rather than assuming
        # matters -- the nearest shelter is frequently the wrong one, because a shelter that
        # sits beside the route splits it evenly while a closer one just adds a dead-end spur.
        bb.record(
            self.name,
            "request_shelter_reroute",
            (
                f"Longest unbroken high-risk leg is {cool.longest_high_risk_leg_min:.1f} min against a "
                f"{ceiling_min:.0f} min ceiling. Trialling {len(shelters[:3])} cooling shelters as "
                f"mandatory waypoints."
            ),
            {"candidates": [s["name"] for s in shelters[:3]]},
        )

        baseline_standard: Route = bb.facts["standard_route"]
        baseline_comparison = bb.facts["comparison"]
        baseline_search = bb.facts["search_trace"]

        trials: List[Tuple[Dict[str, Any], Route, Dict[str, Any]]] = []
        for shelter in shelters[:3]:
            try:
                trial = self.engine.solve(
                    city_id=bb.city_id,
                    origin=bb.origin,
                    destination=bb.destination,
                    hour=bb.hour,
                    profile_id=profile["id"],
                    via=[tuple(shelter["center"])],
                    baseline=baseline_standard,
                )
            except ValueError:
                continue
            trials.append((shelter, trial["cool"], trial["comparison"]))

        improving = [
            t for t in trials if t[1].longest_high_risk_leg_min < cool.longest_high_risk_leg_min
        ]
        if not improving:
            bb.record(
                self.name,
                "escalate",
                (
                    "No reachable shelter shortens the longest unbroken exposure leg. Keeping the "
                    "cool route and advising the user to postpone or arrange vehicle pickup."
                ),
                {"escalation": "no_shelter_improves_exposure", "trialled": len(trials)},
            )
            bb.facts["escalation"] = "no_shelter_improves_exposure"
            bb.facts["shelter_reroute"] = {"applied": False, "reason": "no improvement available"}
            return

        best, revised, revised_comparison = min(
            improving, key=lambda t: t[1].longest_high_risk_leg_min
        )
        revised.waypoints = [
            {
                "id": best["id"],
                "name": best["name"],
                "type": best["type"],
                "coords": best["center"],
                "indoor_temp_f": best["indoor_temp_f"],
                "thermal_relief_f": best["thermal_relief_f"],
            }
        ]
        revised.label = "Cryonav Cool Route + Cooling Shelter"

        bb.facts["cool_route"] = revised
        bb.facts["comparison"] = revised_comparison
        bb.facts["search_trace"] = baseline_search
        bb.facts["safety"]["longest_high_risk_leg_min"] = round(revised.longest_high_risk_leg_min, 1)
        bb.facts["safety"]["ceiling_exceeded"] = (
            revised.longest_high_risk_leg_min > ceiling_min
        )
        bb.facts["shelter_reroute"] = {
            "applied": True,
            "shelter": best,
            "trialled": len(trials),
            "longest_leg_min_before": round(cool.longest_high_risk_leg_min, 1),
            "longest_leg_min_after": round(revised.longest_high_risk_leg_min, 1),
            "added_minutes": round(revised.duration_min - cool.duration_min, 1),
        }
        bb.record(
            self.name,
            "shelter_reroute_applied",
            (
                f"{best['name']} selected from {len(trials)} trials: longest unbroken high-risk leg "
                f"{cool.longest_high_risk_leg_min:.1f} -> {revised.longest_high_risk_leg_min:.1f} min "
                f"for {revised.duration_min - cool.duration_min:+.1f} min."
            ),
            bb.facts["shelter_reroute"],
        )

    # -- live monitoring (edge / kiosk telemetry) ----------------------------------------

    def monitor_transit(
        self,
        city_id: str,
        position: Coord,
        hour: float,
        dwell_minutes: float,
        profile_id: str = "pedestrian",
        moved_m: Optional[float] = None,
        accuracy_m: Optional[float] = None,
        notify: bool = True,
    ) -> Dict[str, Any]:
        """Evaluate a live position report from a wearable, kiosk or Jetson device.

        Returns an escalation decision: ``ok`` / ``advisory`` / ``reroute`` / ``dispatch``.
        Immobility inside an acute-danger zone is the trigger that matters -- a delivery
        worker who has not moved 25 m in eight minutes at 112 deg F is the emergency this
        agent exists to catch.
        """
        profile = profile_or_default(profile_id)
        reading = self.service.sample(city_id, position[0], position[1], hour)
        band = reading.risk_level
        ceiling = thermal.SAFE_EXPOSURE_MINUTES[band] * profile["safe_exposure_scale"]

        immobile = (
            moved_m is not None
            and moved_m < IMMOBILITY_RADIUS_M
            and dwell_minutes >= IMMOBILITY_ALERT_MINUTES
        )
        acute = reading.air_temp_2m_f >= EXTREME_AIR_TEMP_F or band == "extreme"

        if immobile and acute:
            status, action = "dispatch", (
                "Immobility detected in an extreme-heat zone. Alerting the nominated "
                "emergency contact with position and nearest air-conditioned refuge."
            )
        elif dwell_minutes >= ceiling and acute:
            status, action = "reroute", (
                f"Continuous exposure {dwell_minutes:.0f} min exceeds the {ceiling:.0f} min ceiling. "
                "Diverting to the nearest air-conditioned shelter now."
            )
        elif dwell_minutes >= ceiling * 0.7:
            status, action = "advisory", (
                f"Approaching the {ceiling:.0f} min continuous-exposure ceiling. "
                "Hydrate and plan a shade break."
            )
        else:
            status, action = "ok", "Exposure within safe limits."

        shelters = self.service.shelters(
            city_id, position[0], position[1], radius_m=2000.0, limit=3, hour=hour, require_ac=True
        )

        result: Dict[str, Any] = {
            "status": status,
            "action": action,
            "position": [position[0], position[1]],
            "dwell_minutes": round(dwell_minutes, 1),
            "moved_m": moved_m,
            "position_accuracy_m": accuracy_m,
            "immobility_suspected": immobile,
            "acute_danger_zone": acute,
            "continuous_exposure_ceiling_min": round(ceiling, 1),
            "reading": reading.as_dict(),
            "hydration_ml_per_hour": thermal.hydration_ml_per_hour(
                reading.exposure_index_f, profile["hydration_multiplier"]
            ),
            "nearest_shelters": shelters,
        }

        # Escalation is the one place this system acts on the world rather than describing
        # it, so the response reports what was actually delivered -- never a claim that a
        # message went out when it did not.
        if status == "dispatch":
            result["notification"] = (
                notify_module.send_dispatch(
                    position=position,
                    reading=result["reading"],
                    dwell_minutes=dwell_minutes,
                    accuracy_m=accuracy_m,
                    shelter=shelters[0] if shelters else None,
                    city_id=city_id,
                )
                if notify
                else {"sent": False, "channel": "ntfy", "reason": "notification suppressed by caller"}
            )
        else:
            result["notification"] = None
        return result


# --------------------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------------------


class CryonavOrchestrator:
    """Runs the three agents over a shared blackboard and assembles the response."""

    def __init__(self, service: FortyGuardService, engine: Optional[RoutingEngine] = None) -> None:
        self.service = service
        self.engine = engine or RoutingEngine(service)
        self.sensing = ThermalSensingAgent(self.service, self.engine)
        self.optimizer = CoolRouteOptimizationAgent(self.service, self.engine)
        self.sentinel = EmergencyThermalSentinelAgent(self.service, self.engine)

    @property
    def roster(self) -> List[Dict[str, str]]:
        return [
            {"name": a.name, "role": a.role}
            for a in (self.sensing, self.optimizer, self.sentinel)
        ]

    def navigate(
        self,
        city_id: str,
        origin: Coord,
        destination: Coord,
        hour: float = 15.0,
        profile_id: str = "pedestrian",
        allow_shelter_reroute: bool = True,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        profile = profile_or_default(profile_id)
        bb = Blackboard(
            city_id=city_id, hour=hour, profile=profile, origin=origin, destination=destination
        )

        bb.facts["allow_shelter_reroute"] = allow_shelter_reroute

        self.sensing.execute(bb)
        self.optimizer.execute(bb)
        self.sentinel.execute(bb)

        standard: Route = bb.facts["standard_route"]
        cool: Route = bb.facts["cool_route"]
        graph = bb.facts["graph"]
        total_ms = (time.perf_counter() - started) * 1000.0

        return {
            "city_id": city_id,
            "network": {
                "source": graph.source,
                "nodes": len(graph.nodes),
            },
            "hour": hour,
            "profile": {
                "id": profile["id"],
                "label": profile["label"],
                "description": profile["description"],
                "max_detour_ratio": profile["max_detour_ratio"],
            },
            "origin": [origin[0], origin[1]],
            "destination": [destination[0], destination[1]],
            "feed": bb.facts["feed"],
            "sensing": bb.facts["sensing"],
            "ambient": bb.facts["ambient"],
            "risk_vector": bb.facts["risk_vector"],
            "routes": {"standard": standard.as_dict(), "cool": cool.as_dict()},
            "comparison": bb.facts["comparison"],
            "hotspots": bb.facts["hotspots"],
            "safety": bb.facts.get("safety", {}),
            "shelter_reroute": bb.facts.get("shelter_reroute", {"applied": False}),
            "nearby_shelters": bb.facts.get("nearby_shelters", []),
            "optimizer_search": bb.facts.get("search_trace", []),
            "agents": self.roster,
            "agent_trace": bb.trace,
            "compute_ms": round(total_ms, 2),
        }
