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
    def test_graph_dimensions(self, engine):
        g = engine.graph("phoenix", 15.0)
        assert len(g.nodes) == g.resolution ** 2
        assert len(g.node_readings) == len(g.nodes)

    def test_graph_is_cached_per_half_hour_bucket(self, engine):
        assert engine.graph("phoenix", 15.0) is engine.graph("phoenix", 15.2)
        assert engine.graph("phoenix", 15.0) is not engine.graph("phoenix", 16.0)

    def test_every_node_is_connected(self, engine):
        g = engine.graph("phoenix", 15.0)
        assert all(len(adj) >= 3 for adj in g.adjacency)

    def test_nearest_node_snaps_within_a_block(self, engine):
        g = engine.graph("phoenix", 15.0)
        idx = g.nearest_node((33.4520, -112.0740))
        assert thermal.haversine_m((33.4520, -112.0740), g.nodes[idx]) < 200

    def test_nearest_node_clamps_out_of_bounds_input(self, engine):
        g = engine.graph("phoenix", 15.0)
        assert 0 <= g.nearest_node((0.0, 0.0)) < len(g.nodes)


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
        out = engine.solve("abu_dhabi", (24.4838, 54.3418), (24.4880, 54.3600), 15.0, "pedestrian")
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
        """A guard that always returns zeros would pass the regression test above."""
        best = max(
            engine.solve(c, o, d, 15.0, p)["comparison"]["thermal_load_reduction_f"]
            for c, _pid, o, d, p in all_presets
        )
        assert best >= 3.0, f"best thermal-load saving was only {best} F"
