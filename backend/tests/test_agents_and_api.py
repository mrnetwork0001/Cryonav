"""Agent-orchestration and HTTP-surface tests."""

import pytest
from fastapi.testclient import TestClient

import thermal
from main import app

PHX_ORIGIN = (33.4485, -112.0962)
PHX_DEST = (33.4576, -112.0705)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------------------


class TestOrchestration:
    def test_all_three_agents_appear_in_the_trace(self, orchestrator):
        out = orchestrator.navigate("phoenix", PHX_ORIGIN, PHX_DEST, 15.0, "delivery_worker")
        agents = {step["agent"] for step in out["agent_trace"]}
        assert agents == {"thermal_sensing", "cool_route_optimizer", "emergency_sentinel"}

    def test_trace_steps_are_ordered_and_described(self, orchestrator):
        out = orchestrator.navigate("phoenix", PHX_ORIGIN, PHX_DEST, 15.0)
        steps = out["agent_trace"]
        assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
        assert all(s["detail"] for s in steps)

    def test_sensing_agent_reports_feed_and_radiant_spike(self, orchestrator):
        out = orchestrator.navigate("phoenix", PHX_ORIGIN, PHX_DEST, 15.0)
        assert out["feed"]["status_code"] == 200
        assert out["sensing"]["resolution_mi2"] == 10.0
        assert out["sensing"]["elevation_m"] == 2.0
        assert out["risk_vector"]["asphalt_radiation_spike_f"] > 0

    def test_response_contract_is_complete(self, orchestrator):
        out = orchestrator.navigate("phoenix", PHX_ORIGIN, PHX_DEST, 15.0)
        for key in (
            "feed", "sensing", "ambient", "risk_vector", "routes", "comparison",
            "hotspots", "safety", "shelter_reroute", "agents", "agent_trace", "compute_ms",
        ):
            assert key in out, key
        assert set(out["routes"]) == {"standard", "cool"}

    def test_safety_block_present_even_when_reroute_disabled(self, orchestrator):
        """Regression: gating the Sentinel on the reroute flag left the UI with no verdict."""
        for allow in (True, False):
            out = orchestrator.navigate(
                "phoenix", PHX_ORIGIN, PHX_DEST, 15.0, "delivery_worker",
                allow_shelter_reroute=allow,
            )
            safety = out["safety"]
            for key in (
                "risk_band",
                "continuous_exposure_ceiling_min",
                "longest_high_risk_leg_min",
                "ceiling_exceeded",
                "advisory",
            ):
                assert key in safety, f"allow={allow} missing {key}"

    def test_reroute_disabled_never_adds_a_waypoint(self, orchestrator):
        out = orchestrator.navigate(
            "dubai", (25.2117, 55.2795), (25.1975, 55.2796), 15.0, "elderly_vulnerable",
            allow_shelter_reroute=False,
        )
        assert out["shelter_reroute"]["applied"] is False
        assert out["routes"]["cool"]["waypoints"] == []

    def test_applied_reroute_actually_improves_exposure(self, orchestrator):
        """The Sentinel must never 'help' by making the longest exposure leg worse."""
        out = orchestrator.navigate(
            "dubai", (25.2117, 55.2795), (25.1975, 55.2796), 15.0, "elderly_vulnerable"
        )
        reroute = out["shelter_reroute"]
        if reroute.get("applied"):
            assert reroute["longest_leg_min_after"] < reroute["longest_leg_min_before"]
            assert out["routes"]["cool"]["waypoints"]
        else:
            assert reroute.get("reason")

    def test_profile_changes_the_answer(self, orchestrator):
        a = orchestrator.navigate("dubai", (25.1858, 55.2540), (25.1892, 55.2672), 15.0, "delivery_worker")
        b = orchestrator.navigate("dubai", (25.1858, 55.2540), (25.1892, 55.2672), 15.0, "elderly_vulnerable")
        assert a["safety"]["continuous_exposure_ceiling_min"] != b["safety"]["continuous_exposure_ceiling_min"]


class TestSentinelMonitor:
    def test_immobility_in_extreme_heat_dispatches(self, orchestrator):
        out = orchestrator.sentinel.monitor_transit(
            "phoenix", (33.4520, -112.0825), 15.0, dwell_minutes=25.0,
            profile_id="delivery_worker", moved_m=4.0, notify=False,
        )
        assert out["status"] == "dispatch"
        assert out["immobility_suspected"] is True
        # The escalation now reports what was actually delivered rather than naming a
        # contact it never called. With notify disabled it must say so plainly -- a dispatch
        # that silently claims an alert went out is the failure this guards.
        assert out["notification"] is not None
        assert out["notification"]["sent"] is False
        assert out["notification"]["reason"]

    def test_long_dwell_while_moving_reroutes_rather_than_dispatches(self, orchestrator):
        out = orchestrator.sentinel.monitor_transit(
            "phoenix", (33.4520, -112.0825), 15.0, dwell_minutes=25.0,
            profile_id="delivery_worker", moved_m=800.0,
        )
        assert out["status"] == "reroute"
        assert out["immobility_suspected"] is False

    def test_short_dwell_is_ok(self, orchestrator):
        out = orchestrator.sentinel.monitor_transit(
            "phoenix", (33.4560, -112.0740), 15.0, dwell_minutes=1.0, moved_m=100.0
        )
        assert out["status"] == "ok"

    def test_escalation_is_monotonic_in_dwell_time(self, orchestrator):
        ranks = {"ok": 0, "advisory": 1, "reroute": 2, "dispatch": 3}
        seen = [
            ranks[
                orchestrator.sentinel.monitor_transit(
                    "phoenix", (33.4520, -112.0825), 15.0, dwell_minutes=d, moved_m=500.0
                )["status"]
            ]
            for d in (0.0, 5.0, 12.0, 30.0)
        ]
        assert seen == sorted(seen)

    def test_reports_hydration_and_shelters(self, orchestrator):
        out = orchestrator.sentinel.monitor_transit(
            "phoenix", (33.4520, -112.0825), 15.0, dwell_minutes=10.0, moved_m=200.0
        )
        assert out["hydration_ml_per_hour"] >= 240
        assert out["nearest_shelters"]


# --------------------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------------------


class TestApi:
    def test_root_lists_endpoints(self, client):
        body = client.get("/").json()
        assert body["service"] == "Cryonav"
        assert any("cool-route" in e for e in body["endpoints"])

    def test_health(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["fortyguard"]["resolution_mi2"] == 10.0
        assert body["fortyguard"]["elevation_m"] == 2.0

    def test_meta_exposes_profiles_bands_and_agents(self, client):
        body = client.get("/api/v1/meta").json()
        assert len(body["profiles"]) == 3
        assert [b["level"] for b in body["risk_levels"]] == list(thermal.RISK_LEVELS)
        assert len(body["agents"]) == 3

    def test_cities_and_layers(self, client):
        cities = client.get("/api/v1/cities").json()
        assert cities["count"] == 3
        layers = client.get("/api/v1/cities/phoenix/layers").json()
        assert layers["heat_corridors"] and layers["canopy_corridors"]

    def test_grid_endpoint(self, client):
        body = client.get("/api/v1/cities/phoenix/grid?hour=15&resolution=16").json()
        assert body["resolution"] == 16
        assert len(body["cells"]) == 256

    def test_unknown_city_404s(self, client):
        assert client.get("/api/v1/cities/atlantis/grid").status_code == 404
        assert client.get("/api/v1/cities/atlantis/layers").status_code == 404

    def test_heat_intelligence_endpoint(self, client):
        r = client.post(
            "/api/v1/fortyguard/heat-intelligence",
            json={"locations": [{"lat": 33.4498, "lon": -112.0715}], "city_id": "phoenix", "hour": 15},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_heat_intelligence_rejects_empty_locations(self, client):
        r = client.post("/api/v1/fortyguard/heat-intelligence", json={"locations": []})
        assert r.status_code == 422

    def test_cool_route_endpoint(self, client):
        r = client.post(
            "/api/v1/navigate/cool-route",
            json={
                "origin": {"lat": PHX_ORIGIN[0], "lon": PHX_ORIGIN[1]},
                "destination": {"lat": PHX_DEST[0], "lon": PHX_DEST[1]},
                "city_id": "phoenix",
                "hour": 15,
                "profile": "delivery_worker",
                "allow_shelter_reroute": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        # A mandated shelter stop may legitimately cost mean exposure in exchange for breaking
        # the continuous high-risk leg -- so non-negative savings are only guaranteed when the
        # Sentinel did NOT rewrite the route. When it did, the trade must have been worth it.
        if body["shelter_reroute"].get("applied"):
            assert (
                body["shelter_reroute"]["longest_leg_min_after"]
                < body["shelter_reroute"]["longest_leg_min_before"]
            )
        else:
            assert body["comparison"]["thermal_load_reduction_f"] >= 0
        assert body["routes"]["cool"]["metrics"]["distance_m"] > 0

    def test_cool_route_rejects_coincident_points(self, client):
        r = client.post(
            "/api/v1/navigate/cool-route",
            json={
                "origin": {"lat": 33.452, "lon": -112.074},
                "destination": {"lat": 33.452, "lon": -112.074},
                "city_id": "phoenix",
            },
        )
        assert r.status_code == 422

    def test_cool_route_validates_coordinates(self, client):
        r = client.post(
            "/api/v1/navigate/cool-route",
            json={
                "origin": {"lat": 999, "lon": 0},
                "destination": {"lat": 33.45, "lon": -112.07},
            },
        )
        assert r.status_code == 422

    def test_shelters_endpoint_requires_a_locus(self, client):
        assert client.get("/api/v1/shelters/nearby").status_code == 400
        r = client.get("/api/v1/shelters/nearby?city_id=phoenix&lat=33.452&lon=-112.074&limit=3")
        assert r.status_code == 200
        assert len(r.json()["shelters"]) <= 3

    def test_sentinel_endpoint(self, client):
        r = client.post(
            "/api/v1/sentinel/monitor",
            json={
                "position": {"lat": 33.4520, "lon": -112.0825},
                "city_id": "phoenix",
                "hour": 15,
                "dwell_minutes": 25,
                "moved_m": 3,
                "profile": "delivery_worker",
            },
        )
        assert r.json()["status"] == "dispatch"


class TestJetsonEdge:
    def _post(self, client, **overrides):
        body = {
            "origin": {"lat": PHX_ORIGIN[0], "lon": PHX_ORIGIN[1]},
            "destination": {"lat": PHX_DEST[0], "lon": PHX_DEST[1]},
            "city_id": "phoenix",
            "hour": 15,
        }
        body.update(overrides)
        return client.post("/api/v1/edge/jetson-kiosk", json=body)

    def test_returns_edge_telemetry(self, client):
        body = self._post(client).json()
        assert body["edge"]["offline_capable"] is True
        assert body["edge"]["inference_ms"] > 0
        assert body["edge"]["payload_bytes"] > 0

    def test_payload_stays_small_enough_for_a_metered_uplink(self, client):
        assert self._post(client).json()["edge"]["payload_bytes"] < 8192

    def test_polyline_is_decimated_to_the_requested_budget(self, client):
        body = self._post(client, max_polyline_points=8).json()
        assert len(body["route"]["polyline"]) <= 8
        assert len(body["standard_route"]["polyline"]) <= 8

    def test_decimation_keeps_both_endpoints(self, client):
        full = client.post(
            "/api/v1/navigate/cool-route",
            json={
                "origin": {"lat": PHX_ORIGIN[0], "lon": PHX_ORIGIN[1]},
                "destination": {"lat": PHX_DEST[0], "lon": PHX_DEST[1]},
                "city_id": "phoenix",
                "hour": 15,
            },
        ).json()["routes"]["cool"]["geometry"]
        thin = self._post(client, max_polyline_points=6).json()["route"]["polyline"]
        assert thin[0] == full[0]
        assert thin[-1] == full[-1]

    def test_omits_heavy_dashboard_payloads(self, client):
        body = self._post(client).json()
        for heavy in ("agent_trace", "segments", "hotspots", "optimizer_search"):
            assert heavy not in body

    def test_instruction_is_human_readable(self, client):
        instruction = self._post(client).json()["instruction"]
        assert "COOL ROUTE" in instruction
        assert "ml water" in instruction
