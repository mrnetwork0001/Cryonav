"""Routing engine tests.

The load-bearing guarantee is in :class:`TestNoRegressions` -- across every demo corridor and
every profile, the cool route must never be worse than the direct route on any headline metric.
That property is what makes the dashboard's scoreboard trustworthy.
"""

import pytest

import thermal
from routing_engine import COMFORT_BASELINE_F, PROFILES, RoutingEngine, profile_or_default


class TestProfiles:
    def test_known_profiles(self):
        assert set(PROFILES) == {"pedestrian", "delivery_worker", "elderly_vulnerable"}

    def test_unknown_profile_falls_back(self):
        assert profile_or_default("astronaut")["id"] == "pedestrian"
        assert profile_or_default(None)["id"] == "pedestrian"
        assert profile_or_default("  DELIVERY_WORKER ")["id"] == "delivery_worker"

    def test_vulnerable_profile_has_tightest_detour_budget(self):
        """Slow walkers cannot outrun added dose, so their detour budget is deliberately small."""
        assert (
            PROFILES["elderly_vulnerable"]["max_detour_ratio"]
            < PROFILES["pedestrian"]["max_detour_ratio"]
        )
        assert (
            PROFILES["elderly_vulnerable"]["thermal_aversion"]
            > PROFILES["pedestrian"]["thermal_aversion"]
        )


class TestGraph:
    def test_real_street_network_loads(self, engine):
        """All three cities carry committed OSM street files and must use them."""
        for city_id in ("phoenix", "dubai", "abu_dhabi"):
            g = engine.graph(city_id, 15.0)
            assert g.source == "openstreetmap", city_id
            assert g.resolution is None
            assert len(g.nodes) > 5000, f"{city_id}: implausibly small network"
            assert not g.node_readings  # per-node sampling deliberately skipped on OSM graphs

    def test_graph_is_cached_per_half_hour_bucket(self, engine):
        assert engine.graph("phoenix", 15.0) is engine.graph("phoenix", 15.2)
        assert engine.graph("phoenix", 15.0) is not engine.graph("phoenix", 16.0)

    def test_network_is_one_connected_component(self, engine):
        """fetch_streets.py keeps only the largest component; no dead islands allowed."""
        g = engine.graph("phoenix", 15.0)
        seen = {0}
        stack = [0]
        while stack:
            u = stack.pop()
            for e in g.adjacency[u]:
                if e.target not in seen:
                    seen.add(e.target)
                    stack.append(e.target)
        assert len(seen) == len(g.nodes)

    def test_edges_carry_real_geometry(self, engine):
        g = engine.graph("phoenix", 15.0)
        with_geom = sum(1 for adj in g.adjacency for e in adj if len(e.geometry) >= 2)
        total = sum(len(adj) for adj in g.adjacency)
        assert with_geom == total, "every OSM edge must carry its street polyline"

    def test_nearest_node_snaps_within_a_block(self, engine):
        g = engine.graph("phoenix", 15.0)
        idx = g.nearest_node((33.4520, -112.0740))
        assert thermal.haversine_m((33.4520, -112.0740), g.nodes[idx]) < 200

    def test_nearest_node_refuses_far_off_network_points(self, engine):
        """Snapping a point 500 m+ off-network would silently answer a different question."""
        g = engine.graph("phoenix", 15.0)
        with pytest.raises(ValueError, match="walkable network"):
            g.nearest_node((0.0, 0.0))

    def test_lattice_fallback_when_no_street_file(self, service):
        from routing_engine import RoutingEngine

        eng = RoutingEngine(service, streets_dir=None)
        g = eng.graph("phoenix", 15.0)
        assert g.source == "synthetic_lattice"
        assert len(g.nodes) == g.resolution ** 2


class TestCostModel:
    def test_penalty_is_zero_at_comfort_baseline(self, engine):
        assert engine.thermal_penalty(COMFORT_BASELINE_F) == 0.0
        assert engine.thermal_penalty(50.0) == 0.0

    def test_penalty_is_convex(self, engine):
        """Convexity is what makes a detour worth paying for; a linear penalty never buys one."""
        lo = engine.thermal_penalty(COMFORT_BASELINE_F + 14)
        mid = engine.thermal_penalty(COMFORT_BASELINE_F + 28)
        hi = engine.thermal_penalty(COMFORT_BASELINE_F + 42)
        assert (hi - mid) > (mid - lo)

    def test_heat_slows_walking(self, engine):
        cool = engine.walking_speed_mps(90.0, PROFILES["pedestrian"])
        hot = engine.walking_speed_mps(130.0, PROFILES["pedestrian"])
        assert hot < cool

    def test_zero_aversion_is_pure_distance(self, engine):
        g = engine.graph("phoenix", 15.0)
        edge = g.adjacency[400][0]
        assert engine.edge_cost(edge, 0.0, PROFILES["pedestrian"]) == edge.distance_m

    def test_stairs_slow_the_walker(self, engine):
        """OSM steps edges carry a speed factor that must raise traversal time."""
        from routing_engine import EdgeData

        base = dict(
            target=1, distance_m=100.0, exposure_index_f=100.0, air_temp_2m_f=100.0,
            surface_temp_f=120.0, canopy_cover_pct=10.0, risk_level="moderate",
            surface_type="concrete",
        )
        flat = EdgeData(**base)
        stairs = EdgeData(**{**base, "speed_factor": 0.55})
        p = PROFILES["pedestrian"]
        assert engine.edge_cost(stairs, 2.0, p) > engine.edge_cost(flat, 2.0, p)


class TestSolve:
    def test_returns_both_paths(self, engine):
        out = engine.solve("phoenix", (33.4485, -112.0962), (33.4576, -112.0705), 15.0, "pedestrian")
        assert out["standard"].kind == "standard"
        assert out["cool"].kind == "cool"
        assert len(out["standard"].geometry) >= 2
        assert len(out["cool"].geometry) >= 2

    def test_identical_endpoints_rejected(self, engine):
        with pytest.raises(ValueError):
            engine.solve("phoenix", (33.4520, -112.0740), (33.4520, -112.0740), 15.0)

    def test_standard_route_is_never_longer_than_cool(self, engine, all_presets):
        """Path A minimises distance by construction, so nothing may undercut it."""
        for city_id, _pid, origin, dest, profile in all_presets:
            out = engine.solve(city_id, origin, dest, 15.0, profile)
            assert out["standard"].distance_m <= out["cool"].distance_m + 1.0

    def test_detour_budget_is_respected(self, engine, all_presets):
        for city_id, pid, origin, dest, profile in all_presets:
            out = engine.solve(city_id, origin, dest, 15.0, profile)
            ratio = out["cool"].distance_m / out["standard"].distance_m
            budget = PROFILES[profile]["max_detour_ratio"]
            assert ratio <= budget + 1e-6, f"{city_id}/{pid}/{profile} ratio {ratio}"

    def test_search_trace_is_populated_and_explained(self, engine):
        out = engine.solve("dubai", (25.1858, 55.2540), (25.1892, 55.2672), 15.0, "pedestrian")
        assert out["search_trace"]
        for step in out["search_trace"]:
            assert step["reason"]
            assert "thermal_aversion" in step
            assert isinstance(step["accepted"], bool)

    def test_waypoint_routing_visits_the_waypoint(self, engine):
        shelter = (33.4525, -112.0812)
        out = engine.solve(
            "phoenix", (33.4485, -112.0962), (33.4576, -112.0705), 15.0, "pedestrian", via=[shelter]
        )
        nearest = min(thermal.haversine_m(shelter, p) for p in out["cool"].geometry)
        assert nearest < 200

    def test_baseline_pins_the_comparison(self, engine):
        """Re-solving through a shelter must not silently move the Path A goalposts."""
        base = engine.solve("phoenix", (33.4485, -112.0962), (33.4576, -112.0705), 15.0, "pedestrian")
        rerouted = engine.solve(
            "phoenix",
            (33.4485, -112.0962),
            (33.4576, -112.0705),
            15.0,
            "pedestrian",
            via=[(33.4525, -112.0812)],
            baseline=base["standard"],
        )
        assert rerouted["standard"] is base["standard"]


class TestMetrics:
    def test_shade_and_dose_are_sane(self, engine):
        out = engine.solve("phoenix", (33.4485, -112.0962), (33.4576, -112.0705), 15.0, "pedestrian")
        for route in (out["standard"], out["cool"]):
            assert 0 <= route.shade_coverage_pct <= 100
            assert route.thermal_dose_f_min > 0
            assert route.duration_min > 0
            assert route.peak_exposure_index_f >= route.mean_exposure_index_f

    def test_longest_leg_never_exceeds_total_high_risk_time(self, engine, all_presets):
        for city_id, _pid, origin, dest, profile in all_presets:
            out = engine.solve(city_id, origin, dest, 15.0, profile)
            for route in (out["standard"], out["cool"]):
                assert route.longest_high_risk_leg_min <= route.high_plus_exposure_min + 1e-6

    def test_extreme_time_is_subset_of_high_plus_time(self, engine):
        out = engine.solve("dubai", (25.2117, 55.2795), (25.1975, 55.2796), 15.0, "pedestrian")
        for route in (out["standard"], out["cool"]):
            assert route.extreme_exposure_min <= route.high_plus_exposure_min + 1e-6

    def test_shelter_break_shortens_the_longest_leg(self, engine):
        """The entire justification for a shelter detour."""
        plain = engine.solve("dubai", (25.2117, 55.2795), (25.1975, 55.2796), 15.0, "pedestrian")
        with_stop = engine.solve(
            "dubai",
            (25.2117, 55.2795),
            (25.1975, 55.2796),
            15.0,
            "pedestrian",
            via=[(25.2020, 55.2790)],
            baseline=plain["standard"],
        )
        assert (
            with_stop["cool"].longest_high_risk_leg_min
            < plain["cool"].longest_high_risk_leg_min
        )

    def test_route_serialises_completely(self, engine):
        out = engine.solve("abu_dhabi", (24.4822, 54.3466), (24.4880, 54.3600), 15.0, "pedestrian")
        d = out["cool"].as_dict()
        for key in ("kind", "label", "geometry", "segments", "waypoints", "metrics"):
            assert key in d
        for key in ("distance_m", "duration_min", "thermal_stress_score", "risk_color"):
            assert key in d["metrics"]


class TestNoRegressions:
    """The cool route must never be worse than the direct route on a headline metric.

    Without this, the dashboard could confidently display a negative "saving" -- which is how
    the earlier mean-exposure objective silently shipped routes with *higher* heat-strain dose.
    """

    def test_no_metric_regresses_on_any_demo_corridor(self, engine, all_presets):
        failures = []
        for city_id, pid, origin, dest, profile in all_presets:
            c = engine.solve(city_id, origin, dest, 15.0, profile)["comparison"]
            for metric in (
                "thermal_load_reduction_f",
                "heat_stress_reduction_pct",
                "thermal_dose_reduction_pct",
                "peak_exposure_reduction_f",
            ):
                if c[metric] < 0:
                    failures.append(f"{city_id}/{pid}/{profile}: {metric}={c[metric]}")
        assert not failures, "cool route regressed:\n" + "\n".join(failures)

    def test_holds_across_the_whole_day(self, engine):
        failures = []
        for hour in (7, 10, 12, 15, 18, 21):
            c = engine.solve(
                "phoenix", (33.4485, -112.0962), (33.4576, -112.0705), float(hour), "pedestrian"
            )["comparison"]
            if c["thermal_load_reduction_f"] < 0 or c["thermal_dose_reduction_pct"] < 0:
                failures.append(f"hour {hour}: {c}")
        assert not failures, failures

    def test_cool_route_wins_materially_somewhere(self, engine, all_presets):
        """A guard that always returns zeros would pass the regression test above.

        The bar is 2.0 F, lowered from 3.0 when per-class canopy and surface estimates were
        replaced by measurement. That is not a relaxed standard, it is a corrected one: the
        old figure was achievable only because the data invented contrast. Sampling 200
        street midpoints in Phoenix at 15:00 (2026-08-25) puts the network's real p10-p90
        exposure spread at 3.0 F, so a 2.0 F saving is already most of what the city
        physically offers a walker. Raise this bar only if the cities gain canopy.
        """
        best = max(
            engine.solve(c, o, d, 15.0, p)["comparison"]["thermal_load_reduction_f"]
            for c, _pid, o, d, p in all_presets
        )
        assert best >= 2.0, f"best thermal-load saving was only {best} F"


class TestNegativeSavingsOnlyFromTheSentinel:
    """The "zero negative savings" claim is true only when the Sentinel stays out of it.

    A live Dubai route returns thermal_load_reduction_f of -0.2 with the Sentinel engaged: a
    mandated cooling stop raised mean exposure slightly while cutting the longest UNBROKEN
    high-risk leg from 49.1 to 33.3 minutes. That is the correct trade - continuous exposure
    is what causes heat illness, not average exposure - but the landing page stated the
    guarantee without the exception, so the page contradicted the running system.

    The reroute is an ORCHESTRATOR decision, not a routing-engine one, so these go through
    navigate() rather than solve().
    """

    def test_without_the_sentinel_savings_are_never_negative(self, orchestrator, all_presets):
        bad = []
        for city_id, pid, origin, dest, profile in all_presets:
            r = orchestrator.navigate(
                city_id=city_id, origin=origin, destination=dest,
                hour=15.0, profile_id=profile, allow_shelter_reroute=False,
            )
            c = r["comparison"]
            if c["thermal_load_reduction_f"] < 0 or c["thermal_dose_reduction_pct"] < 0:
                bad.append(f"{city_id}/{pid}/{profile}: {c['thermal_load_reduction_f']} F")
        assert not bad, "negative saving with no Sentinel involvement:\n" + "\n".join(bad)

    def test_when_the_sentinel_intervenes_it_shortens_the_unbroken_leg(self, orchestrator, all_presets):
        """A shelter stop is only justified if it buys what it claims to buy.

        Without this, "the Sentinel may raise mean exposure" would excuse any regression.
        """
        checked = 0
        for city_id, _pid, origin, dest, profile in all_presets:
            r = orchestrator.navigate(
                city_id=city_id, origin=origin, destination=dest,
                hour=15.0, profile_id=profile, allow_shelter_reroute=True,
            )
            sr = r.get("shelter_reroute") or {}
            if not sr.get("applied"):
                continue
            checked += 1
            assert sr["longest_leg_min_after"] < sr["longest_leg_min_before"], (
                f"{city_id}/{profile}: shelter stop did not shorten the unbroken leg"
            )
        assert checked > 0, "no preset exercised the Sentinel; this guard proved nothing"


class TestGraphCacheIsBounded:
    """The graph cache is an availability control, not a tidiness one.

    ``hour`` is a caller-supplied field on the public, unauthenticated cool-route endpoint and
    the cache key is (city, 30-minute bucket), so a client can mint 48 distinct keys per city
    from a number the OpenAPI schema advertises. Unbounded, 48 plain POSTs for one city took
    the process from 81 MB to 1360 MB. This host also runs other production services, and the
    OOM killer scores by RSS - so the memory Cryonav did not bound would have been paid for by
    somebody else's process.
    """

    def test_cache_never_exceeds_the_cap(self, engine: RoutingEngine):
        from routing_engine import MAX_CACHED_GRAPHS

        engine._graphs.clear()
        # Every distinct half-hour bucket in a day: the full space one city can be driven to.
        for i in range(48):
            engine.graph("phoenix", i / 2.0)
            assert len(engine._graphs) <= MAX_CACHED_GRAPHS, (
                f"cache grew to {len(engine._graphs)} after {i + 1} distinct hours"
            )
        assert len(engine._graphs) == MAX_CACHED_GRAPHS

    def test_eviction_is_least_recently_used(self, engine: RoutingEngine):
        """LRU rather than a per-city slot, because the slider sweeps buckets for ONE city.

        Without this, the obvious 'keep one graph per city' fix would evict on every drag and
        rebuild a 25k-node graph per frame.
        """
        from routing_engine import MAX_CACHED_GRAPHS

        engine._graphs.clear()
        first = engine.graph("phoenix", 0.0)
        for i in range(1, MAX_CACHED_GRAPHS):
            engine.graph("phoenix", i / 2.0)
        # Touch the oldest so it becomes the most recent, then overflow by one.
        assert engine.graph("phoenix", 0.0) is first
        engine.graph("phoenix", 20.0)
        assert ("phoenix", 0.0) in engine._graphs, "a just-used graph was evicted"
        assert ("phoenix", 0.5) not in engine._graphs, "the true LRU entry survived"

    def test_a_cached_graph_is_not_rebuilt(self, engine: RoutingEngine):
        """The bound must not cost correctness: a hit still returns the same object."""
        engine._graphs.clear()
        a = engine.graph("phoenix", 15.0)
        b = engine.graph("phoenix", 15.0)
        assert a is b
        assert len(engine._graphs) == 1
