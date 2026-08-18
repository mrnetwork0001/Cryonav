"""
Cryonav cool-routing engine.

Builds a walkable street graph over a FortyGuard coverage tile, attaches a live microclimate
reading to every edge, and solves the same origin/destination pair twice:

  * **Path A -- Standard Direct Route**: minimise metres. This is what every navigation app
    on the planet returns, and in July in Phoenix it walks you down an unshaded asphalt corridor.
  * **Path B -- Cryonav Cool Route**: minimise *thermal cost* -- metres weighted by the
    radiant load a body actually absorbs there -- subject to a detour budget.

The interesting part is the detour budget. A naive thermal-weighted Dijkstra will happily send
an elderly pedestrian 2.4 km around a park to save 9 deg F. So the optimiser searches over
thermal-aversion values, taking the coolest route that still fits the profile's tolerated
detour ratio. That search loop is what the Cool-Route Optimization Agent drives.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import thermal
from fortyguard_service import FortyGuardService, ThermalReading
from thermal import clamp, haversine_m

Coord = Tuple[float, float]

# --------------------------------------------------------------------------------------
# User profiles
# --------------------------------------------------------------------------------------

#: Each profile encodes how much detour a person will accept to shed radiant load, how fast
#: they walk, and how quickly heat degrades that pace.
PROFILES: Dict[str, Dict[str, Any]] = {
    "pedestrian": {
        "id": "pedestrian",
        "label": "Pedestrian",
        "description": "Healthy adult on foot, moderate heat tolerance.",
        "thermal_aversion": 2.2,
        "max_detour_ratio": 1.40,
        "base_walk_speed_mps": 1.35,
        "heat_derate": 0.85,
        "hydration_multiplier": 1.0,
        "safe_exposure_scale": 1.0,
    },
    "delivery_worker": {
        "id": "delivery_worker",
        "label": "Outdoor Delivery Worker",
        "description": "Time-pressured, carrying load, 6-8 h cumulative outdoor exposure per shift.",
        "thermal_aversion": 2.9,
        "max_detour_ratio": 1.25,
        "base_walk_speed_mps": 1.45,
        "heat_derate": 1.15,
        "hydration_multiplier": 1.35,
        "safe_exposure_scale": 0.75,
    },
    "elderly_vulnerable": {
        "id": "elderly_vulnerable",
        "label": "Elderly / Vulnerable",
        "description": "Reduced thermoregulation; heat illness onset at far lower dose.",
        "thermal_aversion": 4.2,
        # Deliberately *tighter* than the healthy-pedestrian budget despite far higher heat
        # aversion. At 1.05 m/s a 40% detour is 15 extra minutes on foot, and for this profile
        # time-on-feet is itself the hazard -- shade cannot outrun the added dose.
        "max_detour_ratio": 1.30,
        "base_walk_speed_mps": 1.05,
        "heat_derate": 1.45,
        "hydration_multiplier": 1.2,
        "safe_exposure_scale": 0.55,
    },
}

DEFAULT_PROFILE = "pedestrian"

#: Exposure index below which walking is essentially unpenalised (physiological zero).
COMFORT_BASELINE_F = thermal.COMFORT_BASELINE_F
#: Exposure surplus (deg F above baseline) that maps to a normalised surplus of 1.0.
PENALTY_SCALE_F = 28.0
#: Heat-illness risk is convex in exposure: ten minutes at 125 deg F is far worse than twice
#: five minutes at 100 deg F. A linear penalty prices only *average* exposure and therefore
#: never buys a detour; this exponent makes the optimiser specifically flee the extreme band.
PENALTY_EXPONENT = 2.5

#: Street-graph density across the tile. 28 x 28 gives ~180 m blocks -- close to real
#: downtown Phoenix / Dubai block spacing, and small enough to route in single-digit ms.
GRAPH_RESOLUTION = 28

#: 8-connected: cardinal streets plus plaza/mid-block cut-throughs, which keeps the rendered
#: polylines from looking like staircase artefacts.
_NEIGHBOUR_OFFSETS = (
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
)


def profile_or_default(profile_id: Optional[str]) -> Dict[str, Any]:
    return PROFILES.get((profile_id or DEFAULT_PROFILE).strip().lower(), PROFILES[DEFAULT_PROFILE])


# --------------------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------------------


@dataclass
class EdgeData:
    """A walkable segment with its microclimate already resolved."""

    target: int
    distance_m: float
    exposure_index_f: float
    air_temp_2m_f: float
    surface_temp_f: float
    canopy_cover_pct: float
    risk_level: str
    surface_type: str


@dataclass
class StreetGraph:
    city_id: str
    hour: float
    resolution: int
    nodes: List[Coord]
    adjacency: List[List[EdgeData]]
    node_readings: List[ThermalReading]
    bounds: Dict[str, float]

    def nearest_node(self, point: Coord) -> int:
        """Snap an arbitrary GPS fix onto the walkable network.

        Uses the grid's regular spacing to jump straight to the containing cell, then checks
        its immediate neighbourhood -- O(1) instead of scanning 784 nodes per request.
        """
        b = self.bounds
        lat_span = b["north"] - b["south"]
        lon_span = b["east"] - b["west"]
        n = self.resolution
        row = int(round((clamp(point[0], b["south"], b["north"]) - b["south"]) / lat_span * (n - 1)))
        col = int(round((clamp(point[1], b["west"], b["east"]) - b["west"]) / lon_span * (n - 1)))

        best_idx, best_d = row * n + col, float("inf")
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                r, c = row + dr, col + dc
                if 0 <= r < n and 0 <= c < n:
                    idx = r * n + c
                    d = haversine_m(point, self.nodes[idx])
                    if d < best_d:
                        best_idx, best_d = idx, d
        return best_idx


# --------------------------------------------------------------------------------------
# Route model
# --------------------------------------------------------------------------------------


@dataclass
class RouteSegment:
    start: Coord
    end: Coord
    distance_m: float
    exposure_index_f: float
    air_temp_2m_f: float
    surface_temp_f: float
    canopy_cover_pct: float
    risk_level: str
    surface_type: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start": [self.start[0], self.start[1]],
            "end": [self.end[0], self.end[1]],
            "distance_m": round(self.distance_m, 1),
            "exposure_index_f": round(self.exposure_index_f, 1),
            "air_temp_2m_f": round(self.air_temp_2m_f, 1),
            "surface_temp_f": round(self.surface_temp_f, 1),
            "canopy_cover_pct": round(self.canopy_cover_pct, 1),
            "risk_level": self.risk_level,
            "risk_color": thermal.RISK_COLORS[self.risk_level],
            "surface_type": self.surface_type,
        }


@dataclass
class Route:
    """A solved path plus every thermal statistic the dashboard and agents need."""

    kind: str
    label: str
    geometry: List[Coord]
    segments: List[RouteSegment]
    distance_m: float
    duration_min: float
    mean_exposure_index_f: float
    peak_exposure_index_f: float
    mean_air_temp_2m_f: float
    peak_surface_temp_f: float
    shade_coverage_pct: float
    thermal_dose_f_min: float
    thermal_stress_score: float
    risk_level: str
    extreme_exposure_min: float
    high_plus_exposure_min: float
    longest_high_risk_leg_min: float
    hydration_ml: int
    thermal_aversion_used: float = 0.0
    waypoints: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "geometry": [[lat, lon] for lat, lon in self.geometry],
            "segments": [s.as_dict() for s in self.segments],
            "waypoints": self.waypoints,
            "metrics": {
                "distance_m": round(self.distance_m),
                "distance_km": round(self.distance_m / 1000.0, 2),
                "duration_min": round(self.duration_min, 1),
                "mean_exposure_index_f": round(self.mean_exposure_index_f, 1),
                "peak_exposure_index_f": round(self.peak_exposure_index_f, 1),
                "mean_air_temp_2m_f": round(self.mean_air_temp_2m_f, 1),
                "peak_surface_temp_f": round(self.peak_surface_temp_f, 1),
                "shade_coverage_pct": round(self.shade_coverage_pct, 1),
                "thermal_dose_f_min": round(self.thermal_dose_f_min, 1),
                "thermal_stress_score": round(self.thermal_stress_score, 1),
                "extreme_exposure_min": round(self.extreme_exposure_min, 1),
                "high_plus_exposure_min": round(self.high_plus_exposure_min, 1),
                "longest_high_risk_leg_min": round(self.longest_high_risk_leg_min, 1),
                "hydration_ml": self.hydration_ml,
                "risk_level": self.risk_level,
                "risk_color": thermal.RISK_COLORS[self.risk_level],
                "thermal_aversion_used": round(self.thermal_aversion_used, 2),
            },
        }


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------


class RoutingEngine:
    """Graph construction, thermal weighting and dual-path solving."""

    def __init__(self, service: FortyGuardService, resolution: int = GRAPH_RESOLUTION) -> None:
        self.service = service
        self.resolution = resolution
        self._graphs: Dict[Tuple[str, float], StreetGraph] = {}

    # -- graph -------------------------------------------------------------------------

    @staticmethod
    def _hour_bucket(hour: float) -> float:
        """Graphs are cached in 30-minute buckets; microclimate does not move faster than that."""
        return round(clamp(hour, 0.0, 23.99) * 2.0) / 2.0

    def graph(self, city_id: str, hour: float = 15.0) -> StreetGraph:
        key = (city_id, self._hour_bucket(hour))
        cached = self._graphs.get(key)
        if cached is None:
            cached = self._build_graph(city_id, key[1])
            self._graphs[key] = cached
        return cached

    def _build_graph(self, city_id: str, hour: float) -> StreetGraph:
        b = self.service.bounds(city_id)
        n = self.resolution
        lat_step = (b["north"] - b["south"]) / (n - 1)
        lon_step = (b["east"] - b["west"]) / (n - 1)

        nodes: List[Coord] = []
        readings: List[ThermalReading] = []
        for row in range(n):
            lat = b["south"] + row * lat_step
            for col in range(n):
                lon = b["west"] + col * lon_step
                nodes.append((lat, lon))
                readings.append(self.service.sample(city_id, lat, lon, hour))

        adjacency: List[List[EdgeData]] = [[] for _ in range(n * n)]
        for row in range(n):
            for col in range(n):
                idx = row * n + col
                for dr, dc in _NEIGHBOUR_OFFSETS:
                    r, c = row + dr, col + dc
                    if not (0 <= r < n and 0 <= c < n):
                        continue
                    jdx = r * n + c
                    a, z = nodes[idx], nodes[jdx]
                    dist = haversine_m(a, z)
                    # Sample the segment at its midpoint: a street's microclimate is the
                    # microclimate of the ground you actually walk over, not of its junctions.
                    mid = ((a[0] + z[0]) / 2.0, (a[1] + z[1]) / 2.0)
                    m = self.service.sample(city_id, mid[0], mid[1], hour)
                    adjacency[idx].append(
                        EdgeData(
                            target=jdx,
                            distance_m=dist,
                            exposure_index_f=m.exposure_index_f,
                            air_temp_2m_f=m.air_temp_2m_f,
                            surface_temp_f=m.surface_temp_f,
                            canopy_cover_pct=m.canopy_cover_pct,
                            risk_level=m.risk_level,
                            surface_type=m.surface_type,
                        )
                    )

        return StreetGraph(
            city_id=city_id,
            hour=hour,
            resolution=n,
            nodes=nodes,
            adjacency=adjacency,
            node_readings=readings,
            bounds=b,
        )

    # -- weighting ---------------------------------------------------------------------

    @staticmethod
    def thermal_penalty(exposure_f: float) -> float:
        """Convex penalty for walking a metre at this exposure index.

        Normalised surplus above the comfort baseline, raised to :data:`PENALTY_EXPONENT`.
        Convexity is what makes cool routing work at all: under a linear penalty the cost
        ratio between shaded and unshaded ground is too small to ever justify leaving the
        straight line, so the "cool route" degenerates into the standard route.
        """
        surplus = max(exposure_f - COMFORT_BASELINE_F, 0.0) / PENALTY_SCALE_F
        return surplus ** PENALTY_EXPONENT

    def edge_cost(self, edge: EdgeData, aversion: float, profile: Dict[str, Any]) -> float:
        """Cost of traversing an edge.

        ``aversion == 0`` is pure distance -- literally what a standard navigator optimises,
        which is what makes Path A an honest baseline rather than a strawman.

        Above zero the cost becomes *thermal dose*: minutes in the sun multiplied by how
        punishing that sun is. Weighting by time rather than distance matters because heat
        also slows people down, so a hot segment is penalised twice over -- and because dose
        is the quantity the route card actually reports. Optimising mean exposure while
        reporting dose lets the "cool" route come back with a *higher* dose than the direct one.
        """
        if aversion <= 0.0:
            return edge.distance_m
        time_min = edge.distance_m / self.walking_speed_mps(edge.exposure_index_f, profile) / 60.0
        return time_min * (1.0 + aversion * self.thermal_penalty(edge.exposure_index_f))

    # -- search ------------------------------------------------------------------------

    def _dijkstra(
        self, graph: StreetGraph, source: int, target: int, aversion: float, profile: Dict[str, Any]
    ) -> List[int]:
        """Standard Dijkstra over the thermal-weighted graph. Returns node indices."""
        n = len(graph.nodes)
        dist = [math.inf] * n
        prev = [-1] * n
        visited = [False] * n
        dist[source] = 0.0
        queue: List[Tuple[float, int]] = [(0.0, source)]

        while queue:
            d, u = heapq.heappop(queue)
            if visited[u]:
                continue
            visited[u] = True
            if u == target:
                break
            for edge in graph.adjacency[u]:
                v = edge.target
                if visited[v]:
                    continue
                nd = d + self.edge_cost(edge, aversion, profile)
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(queue, (nd, v))

        if not visited[target] and target != source:
            return []

        path, cur = [], target
        while cur != -1:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return path if path and path[0] == source else []

    def _path_through(
        self, graph: StreetGraph, stops: Sequence[int], aversion: float, profile: Dict[str, Any]
    ) -> List[int]:
        """Chain Dijkstra across ordered waypoints (origin -> shelter -> destination)."""
        full: List[int] = []
        for a, b in zip(stops, stops[1:]):
            leg = self._dijkstra(graph, a, b, aversion, profile)
            if not leg:
                return []
            full.extend(leg if not full else leg[1:])
        return full

    # -- measurement --------------------------------------------------------------------

    def measure(
        self,
        graph: StreetGraph,
        path: Sequence[int],
        kind: str,
        label: str,
        profile: Dict[str, Any],
        aversion: float = 0.0,
        break_nodes: Optional[Sequence[int]] = None,
    ) -> Route:
        """Turn a node path into a fully-costed Route.

        Thermal dose is the physiologically meaningful quantity: exposure integrated over the
        time spent in it. A short brutal stretch and a long mild one can carry the same dose,
        and heat illness tracks dose, not peak.

        ``break_nodes`` are graph nodes where the traveller goes indoors (a cooling shelter).
        They reset the continuous-exposure accumulator, which is the entire point of routing
        through one: total time in the heat barely moves, but the longest *unbroken* stretch --
        the quantity heat-illness guidance is written against -- is cut in half.
        """
        breaks = set(break_nodes or ())
        edge_by_target: Dict[Tuple[int, int], EdgeData] = {}
        for u in set(path):
            for e in graph.adjacency[u]:
                edge_by_target[(u, e.target)] = e

        segments: List[RouteSegment] = []
        total_dist = 0.0
        total_time_s = 0.0
        dose = 0.0
        weighted_exposure = 0.0
        weighted_air = 0.0
        weighted_canopy = 0.0
        peak_exposure = 0.0
        peak_surface = 0.0
        extreme_s = 0.0
        high_plus_s = 0.0
        current_leg_s = 0.0
        longest_leg_s = 0.0

        for u, v in zip(path, path[1:]):
            edge = edge_by_target.get((u, v))
            if edge is None:
                continue
            if u in breaks:
                longest_leg_s = max(longest_leg_s, current_leg_s)
                current_leg_s = 0.0
            speed = self.walking_speed_mps(edge.exposure_index_f, profile)
            seg_time_s = edge.distance_m / speed
            seg_min = seg_time_s / 60.0

            total_dist += edge.distance_m
            total_time_s += seg_time_s
            # Dose is integrated *above the comfort baseline*, not from absolute zero.
            # Absolute-zero integration is dominated by the constant 88 deg F floor, so a
            # slightly longer route always looks worse no matter how much shade it gains --
            # it measures walking time, not heat strain.
            dose += max(edge.exposure_index_f - COMFORT_BASELINE_F, 0.0) * seg_min
            weighted_exposure += edge.exposure_index_f * edge.distance_m
            weighted_air += edge.air_temp_2m_f * edge.distance_m
            weighted_canopy += edge.canopy_cover_pct * edge.distance_m
            peak_exposure = max(peak_exposure, edge.exposure_index_f)
            peak_surface = max(peak_surface, edge.surface_temp_f)
            if edge.risk_level == "extreme":
                extreme_s += seg_time_s
            if edge.risk_level in ("high", "extreme"):
                high_plus_s += seg_time_s
                current_leg_s += seg_time_s
            else:
                longest_leg_s = max(longest_leg_s, current_leg_s)
                current_leg_s = 0.0

            segments.append(
                RouteSegment(
                    start=graph.nodes[u],
                    end=graph.nodes[v],
                    distance_m=edge.distance_m,
                    exposure_index_f=edge.exposure_index_f,
                    air_temp_2m_f=edge.air_temp_2m_f,
                    surface_temp_f=edge.surface_temp_f,
                    canopy_cover_pct=edge.canopy_cover_pct,
                    risk_level=edge.risk_level,
                    surface_type=edge.surface_type,
                )
            )

        denom = max(total_dist, 1e-6)
        mean_exposure = weighted_exposure / denom
        duration_min = total_time_s / 60.0
        longest_leg_s = max(longest_leg_s, current_leg_s)

        return Route(
            kind=kind,
            label=label,
            geometry=[graph.nodes[i] for i in path],
            segments=segments,
            distance_m=total_dist,
            duration_min=duration_min,
            mean_exposure_index_f=mean_exposure,
            peak_exposure_index_f=peak_exposure,
            mean_air_temp_2m_f=weighted_air / denom,
            peak_surface_temp_f=peak_surface,
            shade_coverage_pct=weighted_canopy / denom,
            thermal_dose_f_min=dose,
            thermal_stress_score=thermal.thermal_stress_score(mean_exposure),
            risk_level=thermal.classify_risk(mean_exposure),
            extreme_exposure_min=extreme_s / 60.0,
            high_plus_exposure_min=high_plus_s / 60.0,
            longest_high_risk_leg_min=longest_leg_s / 60.0,
            hydration_ml=int(
                thermal.hydration_ml_per_hour(mean_exposure, profile["hydration_multiplier"])
                * max(duration_min, 1.0)
                / 60.0
            ),
            thermal_aversion_used=aversion,
        )

    @staticmethod
    def walking_speed_mps(exposure_f: float, profile: Dict[str, Any]) -> float:
        """Heat slows people down. Pace decay above the comfort baseline is roughly linear
        until it floors out; ignoring it understates time-in-heat on the hot route by ~15%."""
        surplus = max(exposure_f - COMFORT_BASELINE_F, 0.0)
        decay = 1.0 - profile["heat_derate"] * (surplus / 100.0)
        return profile["base_walk_speed_mps"] * clamp(decay, 0.45, 1.0)

    # -- the dual-route solve ------------------------------------------------------------

    def solve(
        self,
        city_id: str,
        origin: Coord,
        destination: Coord,
        hour: float = 15.0,
        profile_id: str = DEFAULT_PROFILE,
        via: Optional[Sequence[Coord]] = None,
        baseline: Optional[Route] = None,
    ) -> Dict[str, Any]:
        """Solve Path A and Path B, then quantify what the cool route bought.

        The cool route is searched, not merely computed: thermal aversion is stepped down from
        the profile's ideal until the detour fits the profile's tolerance. The rejected
        candidates are returned in ``search_trace`` so the UI can show the agent reasoning.

        ``baseline`` pins the Path A comparison to a caller-supplied route. The Sentinel needs
        this when it re-solves through a cooling shelter: without it, Path A would be recomputed
        *through the shelter too*, and the scoreboard would compare a detour against itself.
        """
        graph = self.graph(city_id, hour)
        profile = profile_or_default(profile_id)

        source = graph.nearest_node(origin)
        target = graph.nearest_node(destination)
        via_nodes = [graph.nearest_node(v) for v in (via or [])]
        stops = [source] + via_nodes + [target]

        if source == target:
            raise ValueError("origin and destination snap to the same street node -- pick points further apart")

        # --- Path A: what every other navigation app returns. Always the *direct* origin ->
        # destination path, never routed through the Sentinel's waypoints.
        standard_path = self._path_through(graph, [source, target], aversion=0.0, profile=profile)
        if not standard_path:
            raise ValueError("no walkable path between those points on this tile")
        standard = baseline or self.measure(
            graph, standard_path, "standard", "Standard Direct Route", profile, 0.0
        )

        # --- Path B: sweep the thermal-aversion ladder and keep the best *admissible* result.
        #
        # Taking the first candidate that fits the detour budget is a bug dressed up as an
        # optimisation: the highest aversion that fits is not necessarily the one that sheds
        # the most heat strain. Two admissibility rules apply to every candidate:
        #   1. it must fit the profile's detour budget, and
        #   2. it must actually lower thermal dose -- a route that is cooler per metre but
        #      long enough to raise total heat strain is not a cool route, it is a worse one.
        # When the Sentinel mandates a shelter stop, the detour to reach it is not optional and
        # must not be charged against the cool route's budget. Measure the detour against the
        # *shortest path that also visits the waypoints*, and drop the dose guard -- breaking a
        # continuous exposure leg is the objective there, and it legitimately costs dose.
        mandated_stop = bool(via_nodes)
        if mandated_stop:
            via_direct_path = self._path_through(graph, stops, aversion=0.0, profile=profile)
            reference_distance = (
                self.measure(graph, via_direct_path, "cool", "via", profile, 0.0).distance_m
                if via_direct_path
                else standard.distance_m
            )
        else:
            reference_distance = standard.distance_m

        max_detour = profile["max_detour_ratio"]
        ideal = profile["thermal_aversion"]
        ladder = [ideal, ideal * 0.75, ideal * 0.5, ideal * 0.3, ideal * 0.15]
        search_trace: List[Dict[str, Any]] = []
        admissible: List[Route] = []

        for aversion in ladder:
            candidate_path = self._path_through(graph, stops, aversion=aversion, profile=profile)
            if not candidate_path:
                continue
            candidate = self.measure(
                graph, candidate_path, "cool", "Cryonav Cool Route", profile, aversion,
                break_nodes=via_nodes,
            )
            ratio = candidate.distance_m / max(reference_distance, 1e-6)
            dose_delta_pct = (
                (standard.thermal_dose_f_min - candidate.thermal_dose_f_min)
                / max(standard.thermal_dose_f_min, 1e-6)
                * 100.0
            )

            within_budget = ratio <= max_detour
            lowers_dose = mandated_stop or candidate.thermal_dose_f_min <= standard.thermal_dose_f_min
            accepted = within_budget and lowers_dose
            if not within_budget:
                reason = f"detour {round((ratio - 1) * 100)}% exceeds {round((max_detour - 1) * 100)}% budget"
            elif not lowers_dose:
                reason = f"detour fits but raises heat-strain dose by {abs(round(dose_delta_pct, 1))}%"
            else:
                reason = (
                    f"admissible: {round(dose_delta_pct, 1)}% less dose, "
                    f"{round((ratio - 1) * 100)}% detour"
                )

            search_trace.append(
                {
                    "thermal_aversion": round(aversion, 2),
                    "distance_ratio": round(ratio, 3),
                    "mean_exposure_index_f": round(candidate.mean_exposure_index_f, 1),
                    "thermal_dose_delta_pct": round(dose_delta_pct, 1),
                    "accepted": accepted,
                    "reason": reason,
                }
            )
            if accepted:
                admissible.append(candidate)

        if admissible:
            cool = min(admissible, key=lambda r: r.thermal_dose_f_min)
            for step in search_trace:
                step["selected"] = step["thermal_aversion"] == round(cool.thermal_aversion_used, 2)
        else:
            # Nothing beat the direct path on both counts; return it rather than invent a
            # detour that would make the user hotter.
            cool = self.measure(
                graph,
                standard_path,
                "cool",
                "Cryonav Cool Route (direct path already optimal)",
                profile,
                0.0,
            )

        return {
            "graph": graph,
            "profile": profile,
            "standard": standard,
            "cool": cool,
            "search_trace": search_trace,
            "comparison": self.compare(standard, cool),
        }

    @staticmethod
    def compare(standard: Route, cool: Route) -> Dict[str, Any]:
        """The scoreboard: what did the cool route actually save?"""
        stress_a = max(standard.thermal_stress_score, 1e-6)
        dose_a = max(standard.thermal_dose_f_min, 1e-6)

        return {
            "thermal_load_reduction_f": round(
                standard.mean_exposure_index_f - cool.mean_exposure_index_f, 1
            ),
            "peak_exposure_reduction_f": round(
                standard.peak_exposure_index_f - cool.peak_exposure_index_f, 1
            ),
            "surface_temp_avoided_f": round(
                standard.peak_surface_temp_f - cool.peak_surface_temp_f, 1
            ),
            "heat_stress_reduction_pct": round(
                (standard.thermal_stress_score - cool.thermal_stress_score) / stress_a * 100.0, 1
            ),
            "thermal_dose_reduction_pct": round(
                (standard.thermal_dose_f_min - cool.thermal_dose_f_min) / dose_a * 100.0, 1
            ),
            "shade_coverage_gain_pct": round(
                cool.shade_coverage_pct - standard.shade_coverage_pct, 1
            ),
            "extreme_minutes_avoided": round(
                standard.extreme_exposure_min - cool.extreme_exposure_min, 1
            ),
            # Time spent in the high/extreme risk bands is the metric public-health guidance
            # is actually written against ("limit continuous exposure to 20 minutes"), so it
            # is the reduction figure that maps onto an intervention people already understand.
            "high_risk_minutes_avoided": round(
                standard.high_plus_exposure_min - cool.high_plus_exposure_min, 1
            ),
            "high_risk_exposure_reduction_pct": (
                round(
                    (standard.high_plus_exposure_min - cool.high_plus_exposure_min)
                    / standard.high_plus_exposure_min
                    * 100.0,
                    1,
                )
                if standard.high_plus_exposure_min > 0.05
                else 0.0
            ),
            "added_distance_m": round(cool.distance_m - standard.distance_m),
            "added_minutes": round(cool.duration_min - standard.duration_min, 1),
            "detour_ratio": round(cool.distance_m / max(standard.distance_m, 1e-6), 3),
            "hydration_saved_ml": max(standard.hydration_ml - cool.hydration_ml, 0),
        }

    # -- helpers used by the agents -------------------------------------------------------

    def corridor_hotspots(
        self, graph: StreetGraph, route: Route, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """The worst thermal traps along a route, for the Sensing Agent's report."""
        ranked = sorted(route.segments, key=lambda s: s.exposure_index_f, reverse=True)
        out: List[Dict[str, Any]] = []
        seen: set = set()
        for seg in ranked:
            bucket = (round(seg.start[0], 3), round(seg.start[1], 3))
            if bucket in seen:
                continue
            seen.add(bucket)
            out.append(
                {
                    "at": [round(seg.start[0], 6), round(seg.start[1], 6)],
                    "exposure_index_f": round(seg.exposure_index_f, 1),
                    "surface_temp_f": round(seg.surface_temp_f, 1),
                    "air_temp_2m_f": round(seg.air_temp_2m_f, 1),
                    "risk_level": seg.risk_level,
                    "surface_type": seg.surface_type,
                    "asphalt_radiation_spike_f": round(seg.surface_temp_f - seg.air_temp_2m_f, 1),
                }
            )
            if len(out) >= limit:
                break
        return out
