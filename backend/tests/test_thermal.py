"""Physics kernel tests.

These guard the properties the whole product rests on: that the exposure index responds to
radiant load, that the diurnal curve peaks with the sun, and that risk banding is monotonic.
"""

import pytest

import thermal


class TestUnits:
    def test_f_c_roundtrip(self):
        for f in (-40.0, 32.0, 98.6, 112.0, 180.0):
            assert thermal.c_to_f(thermal.f_to_c(f)) == pytest.approx(f, abs=1e-9)

    def test_haversine_known_distance(self):
        # One degree of latitude is ~111.2 km anywhere on the globe.
        d = thermal.haversine_m((33.0, -112.0), (34.0, -112.0))
        assert 110_500 < d < 111_600


class TestHeatIndex:
    def test_below_threshold_uses_simple_form(self):
        # The Rothfusz regression is invalid below 80 F; NWS falls back to the Steadman mean.
        assert thermal.heat_index_f(70.0, 50.0) < 80.0

    def test_rises_with_humidity(self):
        dry = thermal.heat_index_f(100.0, 15.0)
        humid = thermal.heat_index_f(100.0, 60.0)
        assert humid > dry + 15

    def test_desert_adjustment_applies(self):
        """At very low RH the NWS subtracts a correction; without it Phoenix reads too hot."""
        assert thermal.heat_index_f(100.0, 10.0) < thermal.heat_index_f(100.0, 25.0)

    def test_monotonic_in_temperature(self):
        prev = -999.0
        for t in range(80, 116, 5):
            hi = thermal.heat_index_f(float(t), 30.0)
            assert hi > prev
            prev = hi


class TestHumidity:
    def test_dewpoint_roundtrip(self):
        for temp, rh in ((100.0, 20.0), (95.0, 55.0), (85.0, 80.0)):
            dp = thermal.dewpoint_f(temp, rh)
            assert thermal.humidity_from_dewpoint(temp, dp) == pytest.approx(rh, abs=0.5)

    def test_rh_falls_as_temperature_rises_at_fixed_dewpoint(self):
        """The property that keeps the heat index peaking with the sun rather than after it."""
        dp = 60.0
        assert thermal.humidity_from_dewpoint(110.0, dp) < thermal.humidity_from_dewpoint(90.0, dp)

    def test_dewpoint_never_exceeds_temperature(self):
        assert thermal.humidity_from_dewpoint(70.0, 90.0) == pytest.approx(100.0, abs=0.01)


class TestRadiantLoad:
    def test_shade_lowers_mean_radiant_temp(self):
        exposed = thermal.mean_radiant_temp_f(105.0, 165.0, sky_view_factor=1.0)
        shaded = thermal.mean_radiant_temp_f(105.0, 120.0, sky_view_factor=0.15)
        assert exposed > shaded + 25

    def test_exposure_index_adds_radiant_penalty(self):
        """Two points at identical air temperature must differ if their surfaces differ."""
        air, hi = 105.0, 102.0
        hot = thermal.exposure_index_f(air, hi, mrt_f=145.0)
        cool = thermal.exposure_index_f(air, hi, mrt_f=110.0)
        assert hot > cool
        assert hot - cool == pytest.approx(thermal.RADIANT_COUPLING * 35.0, abs=1e-6)

    def test_exposure_index_never_below_heat_index(self):
        assert thermal.exposure_index_f(100.0, 98.0, mrt_f=90.0) == pytest.approx(98.0)

    def test_wind_damps_globe_temperature(self):
        still = thermal.globe_temp_f(105.0, 150.0, wind_mph=0.0)
        breezy = thermal.globe_temp_f(105.0, 150.0, wind_mph=20.0)
        assert still > breezy


class TestRiskBanding:
    def test_bands_are_ordered(self):
        assert thermal.classify_risk(80.0) == "low"
        assert thermal.classify_risk(100.0) == "moderate"
        assert thermal.classify_risk(110.0) == "high"
        assert thermal.classify_risk(130.0) == "extreme"

    def test_band_boundaries_are_inclusive_lower(self):
        for level in ("moderate", "high", "extreme"):
            assert thermal.classify_risk(thermal.RISK_THRESHOLDS_F[level]) == level

    def test_stress_score_bounded_and_monotonic(self):
        assert thermal.thermal_stress_score(50.0) == 0.0
        assert thermal.thermal_stress_score(200.0) == 100.0
        assert thermal.thermal_stress_score(120.0) > thermal.thermal_stress_score(100.0)

    def test_stress_zero_at_comfort_baseline(self):
        """The score is anchored where thermal strain physically begins, so % change is meaningful."""
        assert thermal.thermal_stress_score(thermal.COMFORT_BASELINE_F) == 0.0

    def test_every_band_has_advisory_colour_and_ceiling(self):
        for level in thermal.RISK_LEVELS:
            assert level in thermal.RISK_COLORS
            assert level in thermal.RISK_ADVISORY
            assert thermal.SAFE_EXPOSURE_MINUTES[level] > 0

    def test_safe_exposure_shrinks_as_risk_rises(self):
        mins = [thermal.SAFE_EXPOSURE_MINUTES[l] for l in thermal.RISK_LEVELS]
        assert mins == sorted(mins, reverse=True)


class TestDiurnal:
    def test_air_temp_peaks_near_peak_hour(self):
        temps = {h: thermal.diurnal_air_temp_f(89.0, 112.0, h, peak_hour=15.0) for h in range(24)}
        assert max(temps, key=temps.get) == 15
        assert min(temps, key=temps.get) == 3

    def test_air_temp_respects_min_max(self):
        vals = [thermal.diurnal_air_temp_f(89.0, 112.0, h / 2, 15.0) for h in range(48)]
        assert min(vals) == pytest.approx(89.0, abs=0.5)
        assert max(vals) == pytest.approx(112.0, abs=0.5)

    def test_solar_factor_zero_at_night(self):
        assert thermal.solar_elevation_factor(3.0) == 0.0
        assert thermal.solar_elevation_factor(23.0) == 0.0
        assert thermal.solar_elevation_factor(15.0) == pytest.approx(1.0, abs=1e-9)

    def test_hydration_scales_with_exposure_and_is_bounded(self):
        assert thermal.hydration_ml_per_hour(85.0) == 240
        assert thermal.hydration_ml_per_hour(200.0) == 1200
        assert thermal.hydration_ml_per_hour(120.0) > thermal.hydration_ml_per_hour(100.0)
