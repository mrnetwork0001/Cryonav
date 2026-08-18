"""FortyGuard integration-layer tests: determinism, tile geometry, live fallback, shelters."""

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
        asphalt = service.sample("phoenix", 33.4520, -112.0825, 15.0)  # Van Buren x 7th Ave
        canopy = service.sample("phoenix", 33.4560, -112.0740, 15.0)  # Central Ave spine
        assert asphalt.surface_temp_f > canopy.surface_temp_f + 30
        assert asphalt.exposure_index_f > canopy.exposure_index_f + 10
        assert canopy.canopy_cover_pct > asphalt.canopy_cover_pct

    def test_surface_never_below_air_in_daylight(self, service):
        for city_id in service.city_ids():
            r = service.sample(city_id, *service.city(city_id)["center"], 14.0)
            assert r.surface_temp_f >= r.air_temp_2m_f

    def test_night_collapses_surface_to_air(self, service):
        r = service.sample("phoenix", 33.4520, -112.0825, 3.0)
        assert r.surface_temp_f == pytest.approx(r.air_temp_2m_f, abs=0.1)
        assert r.solar_irradiance_wm2 == 0

    def test_exposure_peaks_in_the_afternoon_not_the_evening(self, service):
        """Regression: a naive humidity model made the index peak after sunset."""
        for city_id in service.city_ids():
            centre = service.city(city_id)["center"]
            series = {h: service.sample(city_id, centre[0], centre[1], h).exposure_index_f
                      for h in range(6, 23)}
            assert 13 <= max(series, key=series.get) <= 17

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
        """A flat grid would mean there is no cool route to find."""
        for city_id in service.city_ids():
            s = service.thermal_grid(city_id, 15.0, 24)["stats"]
            assert s["max_exposure_f"] - s["min_exposure_f"] > 10.0

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
        assert out["sensing"]["resolution_mi2"] == 10.0

    def test_summary_identifies_the_hottest_probe(self, service):
        out = service.heat_intelligence(
            [(33.4560, -112.0740), (33.4520, -112.0825)], "phoenix", 15.0
        )
        assert out["summary"]["peak_risk_at"] == [33.452, -112.0825]

    def test_empty_locations_rejected(self, service):
        with pytest.raises(ValueError):
            service.heat_intelligence([], "phoenix", 15.0)

    def test_falls_back_to_simulation_when_live_call_fails(self, monkeypatch):
        """A hackathon demo must not die on someone's wifi."""
        svc = FortyGuardService(api_key="test-key-not-real")
        assert svc.live is True

        def boom(*_args, **_kwargs):
            raise RuntimeError("upstream unreachable")

        monkeypatch.setattr(svc, "_call_live", boom)
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0)

        assert out["feed"]["source"] == "cryonav_simulation"
        assert out["feed"]["ok"] is True
        assert "unavailable" in out["feed"]["detail"]
        assert out["count"] == 1

    def test_prefer_live_false_skips_upstream(self, monkeypatch):
        svc = FortyGuardService(api_key="test-key-not-real")
        monkeypatch.setattr(
            svc, "_call_live", lambda *a, **k: pytest.fail("should not call upstream")
        )
        out = svc.heat_intelligence([(33.4498, -112.0715)], "phoenix", 15.0, prefer_live=False)
        assert out["feed"]["source"] == "cryonav_simulation"


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
