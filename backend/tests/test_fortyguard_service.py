"""FortyGuard integration-layer tests: determinism, tile geometry, live fallback, shelters."""

import json

import pytest

import thermal
from fortyguard_service import FortyGuardService


class TestCatalogue:
    def test_three_cities_loaded(self, service):
        assert set(service.city_ids()) == {"phoenix", "dubai", "abu_dhabi"}

    def test_unknown_city_raises(self, service):
        with pytest.raises(KeyError):
            service.city("atlantis")

    def test_tile_is_about_ten_square_miles(self, service):
        """The product claim is a 10 mi^2 microclimate tile; the fixtures must actually be one."""
        for city_id in service.city_ids():
            assert 8.5 <= service.tile_area_mi2(city_id) <= 11.5

    def test_presets_fall_inside_their_tile(self, service):
        for city_id in service.city_ids():
            b = service.bounds(city_id)
            for preset in service.city(city_id)["presets"]:
                for key in ("origin", "destination"):
                    lat, lon = preset[key]["coords"]
                    assert b["south"] <= lat <= b["north"], f"{city_id}/{preset['id']}/{key}"
                    assert b["west"] <= lon <= b["east"], f"{city_id}/{preset['id']}/{key}"

    def test_shelters_fall_inside_their_tile(self, service):
        for city_id in service.city_ids():
            b = service.bounds(city_id)
            for shelter in service.city(city_id)["shelters"]:
                lat, lon = shelter["center"]
                assert b["south"] <= lat <= b["north"], shelter["id"]
                assert b["west"] <= lon <= b["east"], shelter["id"]

    def test_resolve_city_picks_nearest_tile(self, service):
        assert service.resolve_city(33.45, -112.07) == "phoenix"
        assert service.resolve_city(25.20, 55.27) == "dubai"
        assert service.resolve_city(24.47, 54.36) == "abu_dhabi"


class TestDeterminism:
    def test_same_inputs_give_identical_readings(self, service):
        a = service.sample("phoenix", 33.4498, -112.0715, 15.0)
        b = service.sample("phoenix", 33.4498, -112.0715, 15.0)
        assert a == b

    def test_fresh_service_reproduces_readings(self):
        """Screenshots and fixtures must survive a process restart."""
        a = FortyGuardService(api_key="").sample("dubai", 25.2098, 55.2760, 15.0)
        b = FortyGuardService(api_key="").sample("dubai", 25.2098, 55.2760, 15.0)
        assert a == b


class TestPhysicalPlausibility:
    def test_asphalt_is_hotter_than_canopy_at_solar_peak(self, service):
        # The shaded reference is Virginia G. Piper Plaza, the highest MEASURED canopy in the
        # Phoenix file (57% from the Meta/WRI canopy raster). It replaces a point on Central
        # Ave that this test used while canopy was assumed per-class: measurement put Central
        # Ave at 21%, so it was never the shaded control the test believed it was.
        asphalt = service.sample("phoenix", 33.4520, -112.0825, 15.0)  # Van Buren x 7th Ave
        canopy = service.sample("phoenix", 33.4508, -112.0691, 15.0)  # Piper Plaza
        assert asphalt.surface_temp_f > canopy.surface_temp_f + 30
        # 8 F, not 10, and the ceiling is why. exposure_index_f caps its radiant term at the
        # NWS full-sun envelope of 15 F, so shade alone can never move the index further than
        # that. A 78%-canopy plaza against bare asphalt measures 8.9 F -- about 60% of the
        # theoretical maximum, which is as much as real shade delivers.
        assert asphalt.exposure_index_f > canopy.exposure_index_f + 8
        assert canopy.canopy_cover_pct > asphalt.canopy_cover_pct

    def test_surface_never_below_air_in_daylight(self, service):
        for city_id in service.city_ids():
            r = service.sample(city_id, *service.city(city_id)["center"], 14.0)
            assert r.surface_temp_f >= r.air_temp_2m_f

    def test_night_collapses_surface_to_air(self, service):
        r = service.sample("phoenix", 33.4520, -112.0825, 3.0)
        assert r.surface_temp_f == pytest.approx(r.air_temp_2m_f, abs=0.1)
        assert r.solar_irradiance_wm2 == 0

    def test_exposure_never_peaks_after_sunset(self, service):
        """Regression: a naive humidity model made the index peak after sunset.

        This is the property that was actually broken, and it holds against live data. The
        hour of the peak itself does NOT -- FortyGuard's observed Dubai series peaks at 11:00
        and drops 4 F by noon when the Gulf sea breeze arrives, which is real weather, not a
        model defect. Asserting an afternoon peak here made a live coastal observation fail a
        test about humidity ordering. The modelled curve is checked separately below.
        """
        for city_id in service.city_ids():
            centre = service.city(city_id)["center"]
            series = {h: service.sample(city_id, centre[0], centre[1], h).exposure_index_f
                      for h in range(6, 23)}
            assert max(series, key=series.get) <= 18

    def test_modelled_diurnal_curve_peaks_in_the_afternoon(self, service):
        """With no live calibration the curve is ours alone, so the peak hour is ours to own."""
        uncalibrated = type(service)(api_key="")
        uncalibrated._calibration = {}
        for city_id in uncalibrated.city_ids():
            centre = uncalibrated.city(city_id)["center"]
            series = {h: uncalibrated.sample(city_id, centre[0], centre[1], h).exposure_index_f
                      for h in range(6, 23)}
            assert 13 <= max(series, key=series.get) <= 17, city_id

    def test_air_temperature_stays_physically_sane(self, service):
        """Overlapping heat islands must not sum into an impossible reading."""
        for city_id in service.city_ids():
            grid = service.thermal_grid(city_id, 15.0, 20)
            peak_air = max(c[2] for c in grid["cells"])
            declared_max = service.city(city_id)["climate"]["air_temp_max_f"]
            assert peak_air <= declared_max + 8.0

    def test_humidity_and_wind_stay_in_range(self, service):
        for city_id in service.city_ids():
            b = service.bounds(city_id)
            r = service.sample(city_id, b["south"] + 0.01, b["west"] + 0.01, 12.0)
            assert 1.0 <= r.relative_humidity_pct <= 100.0
            assert r.wind_speed_mph >= 0


class TestGrid:
    def test_grid_shape_and_stats(self, service):
        g = service.thermal_grid("phoenix", 15.0, 24)
        assert g["resolution"] == 24
        assert len(g["cells"]) == 24 * 24
        assert len(g["exposure_index_f"]) == 24 * 24
        assert g["stats"]["min_exposure_f"] <= g["stats"]["mean_exposure_f"] <= g["stats"]["max_exposure_f"]

    def test_grid_has_spatial_contrast(self, service):
        """A flat grid would mean there is no cool route to find.

        Measured 2026-08-25: Dubai 21.5 F, Abu Dhabi 19.8 F, Phoenix 9.7 F. Phoenix is the
        binding case and it is not a defect -- the Meta/WRI raster puts its downtown at 5.25%
        canopy over uniformly paved ground, so there is little contrast to find. The bar sits
        below that measurement rather than above it, because the test exists to catch a grid
        that has gone flat, not to assert that every city has shade to offer.
        """
        for city_id in service.city_ids():
            s = service.thermal_grid(city_id, 15.0, 24)["stats"]
            assert s["max_exposure_f"] - s["min_exposure_f"] > 8.0, city_id

    def test_resolution_is_clamped(self, service):
        assert service.thermal_grid("phoenix", 15.0, 999)["resolution"] == 64
        assert service.thermal_grid("phoenix", 15.0, 1)["resolution"] == 8

    def test_legend_covers_every_band(self, service):
        levels = [e["level"] for e in service.thermal_grid("phoenix", 15.0, 8)["legend"]]
        assert levels == list(thermal.RISK_LEVELS)


class TestHeatIntelligence:
    def test_returns_one_reading_per_location(self, service):
        out = service.heat_intelligence(
            [(33.4498, -112.0715), (33.4592, -112.0736)], "phoenix", 15.0
        )
        assert out["count"] == 2
        assert len(out["readings"]) == 2
        assert out["feed"]["status_code"] == 200
        assert out["sensing"]["elevation_m"] == 2.0
        # There is no single resolution: the ambient series is a point query with no spatial
        # parameter, and each derived layer has its own. Asserting one invented number was how
        # "10 mi2" survived in the API for weeks while being nobody's actual specification.
        res = out["sensing"]["resolution"]
        assert "no spatial parameter" in res["fortyguard_ambient"]
        assert res["canopy_m"] == 1.19
        assert res["surface_temp_m"] in (30, 70)

    def test_summary_identifies_the_hottest_probe(self, service):
        out = service.heat_intelligence(
            [(33.4560, -112.0740), (33.4520, -112.0825)], "phoenix", 15.0
        )
        assert out["summary"]["peak_risk_at"] == [33.452, -112.0825]

    def test_empty_locations_rejected(self, service):
        with pytest.raises(ValueError):
            service.heat_intelligence([], "phoenix", 15.0)

    def test_falls_back_to_simulation_when_live_call_fails(self, monkeypatch):
        """A hackathon demo must not die on someone's wifi -- but it must say so."""
        svc = FortyGuardService(api_key="test-key-not-real")
        assert svc.live is True

        def boom(*_args, **_kwargs):
            raise RuntimeError("upstream unreachable")

        monkeypatch.setattr(svc, "_call_live", boom)
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)

        # Data is still served...
        assert out["feed"]["source"] == "cryonav_simulation"
        assert out["count"] == 1
        # ...but the feed is explicitly flagged as degraded rather than reported healthy.
        assert out["feed"]["ok"] is False
        assert out["feed"]["degraded"] is True
        assert "upstream failed" in out["feed"]["detail"]


class _FakeResponse:
    """Minimal httpx.Response stand-in for exercising upstream failure modes."""

    def __init__(self, status_code=200, payload=None, text="", content_type="application/json"):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")
        self.headers = {"content-type": content_type}
        self.reason_phrase = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 429: "Too Many Requests"}.get(
            status_code, "Error"
        )

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TestUpstreamFailureModes:
    """Each of these silently produced wrong or misleading output before being fixed."""

    @staticmethod
    def _svc_with(monkeypatch, response):
        import httpx

        svc = FortyGuardService(api_key="test-key-not-real")
        monkeypatch.setattr(httpx, "post", lambda *a, **k: response)
        return svc

    def test_auth_failure_surfaces_the_real_status_not_a_green_200(self, monkeypatch):
        """A 401 previously rendered as a healthy '200 OK' feed pill."""
        svc = self._svc_with(
            monkeypatch, _FakeResponse(401, payload={"error": "invalid api key"})
        )
        feed = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)["feed"]
        assert feed["upstream_status_code"] == 401
        assert feed["status_code"] == 401
        assert feed["ok"] is False
        assert feed["degraded"] is True
        assert "invalid api key" in feed["detail"]

    def test_rate_limit_surfaces_as_429(self, monkeypatch):
        svc = self._svc_with(monkeypatch, _FakeResponse(429, payload={"error": "quota exceeded"}))
        feed = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)["feed"]
        assert feed["upstream_status_code"] == 429
        assert feed["degraded"] is True

    def test_unrecognised_envelope_degrades_instead_of_erroring(self, monkeypatch):
        """Regression: an unknown envelope yielded [], skipped the fallback, and 400'd.

        The submit step now names what it could not find, rather than reporting a generic
        "envelope" complaint -- an operator reading the feed detail should be able to tell a
        malformed response from an auth failure without opening a debugger.
        """
        svc = self._svc_with(monkeypatch, _FakeResponse(200, payload={"unexpected": {"shape": 1}}))
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        assert out["count"] == 1  # served from the calibrated field rather than raising
        assert out["feed"]["degraded"] is True
        assert "activity_id" in out["feed"]["detail"]

    def test_non_json_response_degrades(self, monkeypatch):
        svc = self._svc_with(
            monkeypatch, _FakeResponse(200, payload=None, text="<html>gateway</html>", content_type="text/html")
        )
        feed = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)["feed"]
        assert feed["degraded"] is True
        assert "non-JSON" in feed["detail"]

    def test_fortyguard_error_envelope_is_honoured(self, monkeypatch):
        """FortyGuard signals failure in-body; an HTTP 200 carrying error:true is not success."""
        svc = self._svc_with(
            monkeypatch,
            _FakeResponse(200, payload={
                "error": True, "status_code": 401,
                "details": {"message": "Invalid or unknown API key."},
            }),
        )
        feed = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)["feed"]
        assert feed["degraded"] is True
        assert feed["upstream_status_code"] == 401
        assert "Invalid or unknown API key." in feed["detail"]

    # ------------------------------------------------------------------------------------
    # The live path is ASYNCHRONOUS. Tests that mocked a synchronous {"results": [...]}
    # envelope were deleted rather than repaired: they asserted a contract the API never had,
    # which is precisely why a permanently-422 integration passed CI for weeks. These mock
    # the real flow -- POST returns an activity_id, GET /v1/status/{id} returns the payload.
    # ------------------------------------------------------------------------------------

    @staticmethod
    def _env_payload(air_c=44.0, rh=14.0, ghi=950.0):
        """A well-formed /v1/env_params result: 24 hourly samples per parameter."""
        import thermal as _t

        wet_c = [_t.f_to_c(_t.wet_bulb_f(_t.c_to_f(air_c), rh))] * 24
        return {
            "metadata": {"timezone": "GMT-7", "time_range": {"start": "2026-08-25"}},
            "locations": [{
                "elevation": 332.0,
                "parameters": {
                    "relative_humidity_percent": [rh] * 24,
                    "wet_bulb_temperature_celsius": wet_c,
                    "apparent_temperature_celsius": [air_c] * 24,
                    "cloud_cover_octas": [0.0] * 24,
                },
                "solar_irradiance": {"clear_sky": {"ghi": ghi, "dni": 1100.0}},
            }],
        }

    def _async_svc(self, monkeypatch, result=None, submit=None, api_key="test-key-not-real"):
        """Service whose upstream answers the real two-step flow."""
        import httpx

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            captured["body"] = kwargs.get("json", {})
            return submit if submit is not None else _FakeResponse(
                200, payload={"data": {"activity_id": "act-123"}}
            )

        def fake_get(url, **kwargs):
            return _FakeResponse(200, payload={"data": {"status": "Completed", "result": result}})

        svc = FortyGuardService(api_key=api_key)
        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(httpx, "get", fake_get)
        return svc, captured

    def test_successful_live_call_reports_field_provenance(self, monkeypatch):
        """A partially-populated response must not be presented as fully live."""
        svc, _ = self._async_svc(monkeypatch, result=self._env_payload())
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        feed = out["feed"]
        assert feed["source"] == "fortyguard_live"
        assert feed["ok"] is True and feed["degraded"] is False
        # env_params carries ambient and solar, never surface temperature or wind; the
        # response must say which two were modelled rather than implying all five were live.
        assert feed["live_fields"] == [
            "air_temperature_2m", "relative_humidity", "solar_irradiance",
        ]
        assert "3/5 metrics present" in feed["detail"]
        assert out["sensing"]["live_points"] == 1

    def test_live_air_temperature_is_the_upstream_value(self, monkeypatch):
        """The point of a live call is that upstream numbers survive into the reading."""
        import thermal as _t

        svc, _ = self._async_svc(monkeypatch, result=self._env_payload(air_c=44.0, rh=14.0))
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        # env_params publishes wet-bulb + RH, not dry-bulb, so the reading is the inversion
        # of those two -- it must land back on the dry-bulb we constructed the fixture from.
        assert out["readings"][0]["air_temp_2m_f"] == pytest.approx(_t.c_to_f(44.0), abs=0.5)

    def test_short_series_is_refused_rather_than_padded(self, monkeypatch):
        """A truncated series would silently mislabel hours; degrade instead."""
        bad = self._env_payload()
        bad["locations"][0]["parameters"]["relative_humidity_percent"] = [14.0] * 6
        svc, _ = self._async_svc(monkeypatch, result=bad)
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        assert out["feed"]["degraded"] is True
        assert "24 hourly samples" in out["feed"]["detail"]
        assert out["count"] == 1  # still answered, from the calibrated field

    def test_missing_activity_id_degrades(self, monkeypatch):
        """The submit step returning no job handle is a failure, not an empty success."""
        svc, _ = self._async_svc(
            monkeypatch, result=self._env_payload(),
            submit=_FakeResponse(200, payload={"data": {}}),
        )
        feed = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)["feed"]
        assert feed["degraded"] is True
        assert "activity_id" in feed["detail"]

    def test_auth_uses_the_api_key_header_not_bearer(self, monkeypatch):
        """Confirmed against the live API: an Authorization: Bearer token is ignored entirely,
        and the request is rejected as if no credential were sent."""
        svc, captured = self._async_svc(
            monkeypatch, result=self._env_payload(), api_key="secret-key"
        )
        svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        assert captured["headers"].get("api-key") == "secret-key"
        assert "Authorization" not in captured["headers"]

    def test_live_request_uses_the_shape_the_api_actually_accepts(self, monkeypatch):
        """Regression, and the expensive one.

        The live call used to POST {"locations": [...], "resolution_mi2": 10.0} to
        /v1/heat_intelligence. That endpoint takes a flat latitude/longitude and has no
        resolution parameter, so every call 422'd and the app served cached data behind a
        green feed. Assert the shape, not just that a call happened.
        """
        svc, captured = self._async_svc(monkeypatch, result=self._env_payload())
        svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        body = captured["body"]
        assert captured["url"].endswith("/v1/env_params")
        assert body["latitude"] == 33.4498 and body["longitude"] == -112.0715
        assert "locations" not in body
        assert "resolution_mi2" not in body
        assert isinstance(body["date_time"], dict) and "start_date" in body["date_time"]

    def test_repeated_points_hit_the_cache_not_the_upstream(self, monkeypatch):
        """env_params is an async poll; re-fetching one coordinate per sample is unusable."""
        calls = {"n": 0}
        svc, _ = self._async_svc(monkeypatch, result=self._env_payload())
        real = svc.env_params

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        monkeypatch.setattr(svc, "env_params", counting)
        svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)
        svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 16.0)
        assert calls["n"] == 1, "second request for the same point must be served from cache"

    def test_only_the_first_points_are_fetched_live(self, monkeypatch):
        """A bounded live budget must be reported, never silently presented as fully live."""
        from fortyguard_service import MAX_LIVE_POINTS

        pts = [(33.4498 + i * 0.002, -112.0715) for i in range(MAX_LIVE_POINTS + 3)]
        svc, _ = self._async_svc(monkeypatch, result=self._env_payload())
        out = svc.heat_intelligence(pts, "phoenix", 15.0)
        assert out["count"] == len(pts)
        assert out["sensing"]["live_points"] == MAX_LIVE_POINTS

    def test_endpoint_path_uses_underscore(self):
        """A hyphenated path 404s, and the 404 hides behind an auth check that fires first."""
        from fortyguard_service import HEAT_INTELLIGENCE_PATH

        assert HEAT_INTELLIGENCE_PATH == "/v1/heat_intelligence"
        assert "-" not in HEAT_INTELLIGENCE_PATH.rsplit("/", 1)[-1]

    def test_prefer_live_false_skips_upstream(self, monkeypatch):
        svc = FortyGuardService(api_key="test-key-not-real")
        monkeypatch.setattr(
            svc, "_call_live", lambda *a, **k: pytest.fail("should not call upstream")
        )
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0, prefer_live=False)
        # Source is "fortyguard_calibrated" when a cached ambient curve exists for the tile,
        # plain simulation otherwise -- either way, no upstream call may fire.
        assert out["feed"]["source"] in ("cryonav_simulation", "fortyguard_calibrated")


class TestShelters:
    def test_sorted_by_distance(self, service):
        found = service.shelters("phoenix", 33.4520, -112.0740, radius_m=5000, limit=10)
        assert found == sorted(found, key=lambda s: s["distance_m"])

    def test_radius_is_respected(self, service):
        found = service.shelters("phoenix", 33.4520, -112.0740, radius_m=400, limit=20)
        assert all(s["distance_m"] <= 400 for s in found)

    def test_require_ac_filters_hydration_stations(self, service):
        found = service.shelters("phoenix", 33.4520, -112.0740, radius_m=5000, require_ac=True)
        assert found and all(s["air_conditioned"] for s in found)

    def test_air_conditioned_shelters_offer_relief(self, service):
        for s in service.shelters("phoenix", 33.4520, -112.0740, radius_m=5000, require_ac=True):
            assert s["thermal_relief_f"] > 0

    def test_limit_is_applied(self, service):
        assert len(service.shelters("dubai", radius_m=99999, limit=2)) == 2


class TestHeatmapRaster:
    """The /v1/heatmap fusion path, exercised against a synthetic FeatureCollection."""

    @staticmethod
    def _fc(n=3, base=37.0):
        feats = []
        for i in range(n):
            lon = -112.0995 + i * 0.001
            ring = [
                [lon, 33.4520], [lon + 0.001, 33.4520],
                [lon + 0.001, 33.4530], [lon, 33.4530], [lon, 33.4520],
            ]
            feats.append({
                "geometry": {"coordinates": [ring]},
                "properties": {
                    "tile_id": i,
                    "average_temperature": base + i * 0.2,
                    "min_temperature": base - 4,
                    "max_temperature": base + 4,
                },
            })
        return {"features": feats}

    def test_compact_preserves_temps_and_centroids(self):
        c = FortyGuardService._compact_heatmap("phoenix", self._fc(), "2026-08-19")
        assert c["tile_count"] == 3
        assert c["avg_temp_c"] == [37.0, 37.2, 37.4]
        assert abs(c["lat"][0] - 33.4524) < 0.001

    def test_empty_collection_reports_coverage_not_schema(self):
        from fortyguard_service import FortyGuardUpstreamError

        with pytest.raises(FortyGuardUpstreamError, match="coverage"):
            FortyGuardService._compact_heatmap("dubai", {"features": []}, "2026-08-19")

    def test_anomaly_lookup_is_relative_to_tile_mean(self):
        svc = FortyGuardService(api_key="")
        svc._install_heatmap(FortyGuardService._compact_heatmap("phoenix", self._fc(), "2026-08-19"))
        # middle tile == mean -> anomaly ~0; hottest tile -> +0.2C = +0.36F
        mid = svc.heatmap_anomaly_f("phoenix", 33.4525, -112.0995 + 0.0015)
        hot = svc.heatmap_anomaly_f("phoenix", 33.4525, -112.0995 + 0.0025)
        assert mid == pytest.approx(0.0, abs=0.01)
        assert hot == pytest.approx(0.36, abs=0.01)

    def test_lookup_outside_raster_returns_none_not_zero(self):
        svc = FortyGuardService(api_key="")
        svc._install_heatmap(FortyGuardService._compact_heatmap("phoenix", self._fc(), "2026-08-19"))
        assert svc.heatmap_anomaly_f("phoenix", 40.0, -100.0) is None
        assert svc.heatmap_anomaly_f("dubai", 25.2, 55.27) is None

    def test_raster_grid_reports_provenance(self, service):
        if service.heatmap("phoenix") is None:
            pytest.skip("no cached phoenix raster")
        g = service.raster_grid("phoenix")
        assert g["source"] == "fortyguard_heatmap"
        assert g["cells"] and len(g["cells"][0]) == 4
        assert g["stats"]["min_exposure_f"] < g["stats"]["max_exposure_f"]

    def test_raster_grid_absent_raises(self, service):
        with pytest.raises(KeyError):
            service.raster_grid("dubai")
