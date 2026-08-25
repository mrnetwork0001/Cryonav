"""
Cryonav thermal physics kernel.

Everything downstream of the FortyGuard Temperature API(R) reduces to one question:
*how much heat does a human body actually absorb standing 2 m above this pixel of city?*

Air temperature alone answers that badly. A pedestrian on unshaded asphalt at 112 deg F air
is exchanging radiation with a 165 deg F surface; the same pedestrian 40 m away under a mesquite
canopy sees a 118 deg F surface. Same air temperature, radically different physiological load.

This module turns raw FortyGuard readings into the composite `exposure_index_f` that the
routing engine minimises, plus the human-readable risk bands the dashboard renders.

References used for the approximations:
  * NWS Rothfusz regression for heat index (with the low-RH and high-RH adjustments).
  * Stull (2011) wet-bulb temperature approximation from T and RH.
  * ISO 7726 style mean radiant temperature from surface/air split by sky view factor.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import standards

# --------------------------------------------------------------------------------------
# Risk banding
# --------------------------------------------------------------------------------------

RISK_LEVELS = ("low", "moderate", "high", "extreme")

#: Lower bound (inclusive) of `exposure_index_f` for each risk band -- PUBLISHED, not tuned.
#: OSHA "Using the Heat Index: A Guide for Employers" (2012), reproduced as NIOSH 2016-106
#: Table C-1. See standards.py for the verbatim table and why heat-index bands legitimately
#: apply to Cryonav's full-sun-corrected index.
RISK_THRESHOLDS_F: Dict[str, float] = dict(standards.NIOSH_HEAT_INDEX_BANDS_F)

#: Colour tokens shared with the frontend so the map legend and the API never drift apart.
RISK_COLORS: Dict[str, str] = {
    "low": "#22D3EE",
    "moderate": "#FACC15",
    "high": "#FB923C",
    "extreme": "#EF4444",
}

#: Human-facing guidance surfaced on kiosks and the Jetson edge payload.
#: Human-facing guidance surfaced on kiosks and the Jetson edge payload. Minute figures
#: quote NIOSH 2016-106 Table 6-2 (moderate work) rather than inventing round numbers.
RISK_ADVISORY: Dict[str, str] = {
    "low": "Safe for continuous outdoor transit (NIOSH: no rest period required).",
    "moderate": "Hydrate before departure; prefer shaded side of street.",
    "high": "NIOSH limits moderate work to 30 min per hour at this heat index; use canopy routing.",
    "extreme": "Beyond NIOSH's tabulated range. Asphalt thermal trap - reroute through shade or shelter immediately.",
}

#: Continuous-exposure ceiling in minutes before the Sentinel escalates, per band.
#: NIOSH 2016-106 Table 6-2 (work/rest schedules), moderate-work column -- NIOSH classifies
#: continuous normal walking as moderate work. Derived in standards.py from the table itself
#: so these can never drift away from the citation.
SAFE_EXPOSURE_MINUTES: Dict[str, float] = dict(standards.SAFE_EXPOSURE_MINUTES)

# How strongly excess radiant load above air temperature is felt by a standing body.
# UTCI field studies report sun-vs-shade differences of 15-20 deg C at identical air
# temperature; 0.32 * (MRT - Tair) reproduces about 11 deg C of that, which keeps the model
# on the conservative side of the published range rather than flattering the cool route.
RADIANT_COUPLING = 0.32

#: Exposure index below which a body sheds heat comfortably and walking carries no thermal
#: cost. This is the physiological zero the stress score and the routing penalty both anchor
#: to -- an arbitrary zero point would make "% stress reduction" a meaningless number.
COMFORT_BASELINE_F = 88.0

#: Exposure index at which continuous outdoor exertion is life-threatening for a healthy adult.
SURVIVAL_LIMIT_F = 140.0

# Normalisation window for the 0-100 thermal stress score, in exposure-index degrees F.
STRESS_FLOOR_F = COMFORT_BASELINE_F
STRESS_CEILING_F = SURVIVAL_LIMIT_F

EARTH_RADIUS_M = 6_371_008.8


# --------------------------------------------------------------------------------------
# Unit helpers
# --------------------------------------------------------------------------------------


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------


def haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in metres between two ``(lat, lon)`` pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(clamp(h, 0.0, 1.0)))


# --------------------------------------------------------------------------------------
# Atmospheric approximations
# --------------------------------------------------------------------------------------


def heat_index_f(temp_f: float, humidity_pct: float) -> float:
    """NWS Rothfusz heat index with both official adjustment terms.

    Below 80 deg F the regression is invalid, so the simple Steadman average is used instead --
    matching what the National Weather Service actually publishes.
    """
    rh = clamp(humidity_pct, 0.0, 100.0)
    simple = 0.5 * (temp_f + 61.0 + ((temp_f - 68.0) * 1.2) + (rh * 0.094))
    if (simple + temp_f) / 2.0 < 80.0:
        return simple

    hi = (
        -42.379
        + 2.04901523 * temp_f
        + 10.14333127 * rh
        - 0.22475541 * temp_f * rh
        - 0.00683783 * temp_f * temp_f
        - 0.05481717 * rh * rh
        + 0.00122874 * temp_f * temp_f * rh
        + 0.00085282 * temp_f * rh * rh
        - 0.00000199 * temp_f * temp_f * rh * rh
    )

    # Desert correction: matters enormously for Phoenix at 15% RH.
    if rh < 13.0 and 80.0 <= temp_f <= 112.0:
        hi -= ((13.0 - rh) / 4.0) * math.sqrt((17.0 - abs(temp_f - 95.0)) / 17.0)
    # Gulf-coast correction: matters for Dubai / Abu Dhabi humid heat.
    elif rh > 85.0 and 80.0 <= temp_f <= 87.0:
        hi += ((rh - 85.0) / 10.0) * ((87.0 - temp_f) / 5.0)

    return hi


def saturation_vapor_pressure_hpa(temp_f: float) -> float:
    """Magnus-Tetens saturation vapour pressure."""
    t = f_to_c(temp_f)
    return 6.112 * math.exp(17.67 * t / (t + 243.5))


def dewpoint_f(temp_f: float, humidity_pct: float) -> float:
    """Invert Magnus-Tetens to recover dewpoint from temperature and relative humidity."""
    rh = clamp(humidity_pct, 1.0, 100.0)
    e = (rh / 100.0) * saturation_vapor_pressure_hpa(temp_f)
    ln_ratio = math.log(max(e, 1e-6) / 6.112)
    td_c = 243.5 * ln_ratio / (17.67 - ln_ratio)
    return c_to_f(td_c)


def humidity_from_dewpoint(temp_f: float, dew_f: float) -> float:
    """Relative humidity at ``temp_f`` for a conserved dewpoint.

    Over a single day the absolute moisture content of the air barely moves, so RH is very
    nearly a pure function of temperature: it collapses through the afternoon and rebounds
    overnight. Modelling it this way (rather than scaling RH by a solar factor) is what keeps
    the heat index peaking with the sun instead of spuriously spiking after sunset.
    """
    e = saturation_vapor_pressure_hpa(min(dew_f, temp_f))
    es = saturation_vapor_pressure_hpa(temp_f)
    return clamp(100.0 * e / max(es, 1e-6), 1.0, 100.0)


def wet_bulb_f(temp_f: float, humidity_pct: float) -> float:
    """Stull (2011) wet-bulb approximation, evaluated in Celsius and returned in Fahrenheit."""
    t = f_to_c(temp_f)
    rh = clamp(humidity_pct, 1.0, 100.0)
    tw = (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )
    return c_to_f(tw)


def mean_radiant_temp_f(air_f: float, surface_f: float, sky_view_factor: float) -> float:
    """Mean radiant temperature seen by a standing body.

    ``sky_view_factor`` is the fraction of the hemisphere that is open sky / hot surface
    rather than canopy. Fully shaded (0.0) collapses MRT toward air temperature; fully
    exposed (1.0) pulls it most of the way toward the surface radiant temperature.
    """
    coupling = 0.20 + 0.45 * clamp(sky_view_factor, 0.0, 1.0)
    return air_f + (surface_f - air_f) * coupling


def globe_temp_f(air_f: float, mrt_f: float, wind_mph: float) -> float:
    """Black-globe temperature, damped by convective cooling from wind."""
    ventilation = 1.0 / (1.0 + 0.09 * max(wind_mph, 0.0))
    return air_f + (mrt_f - air_f) * clamp(ventilation, 0.25, 1.0)


def wbgt_f(air_f: float, humidity_pct: float, mrt_f: float, wind_mph: float) -> float:
    """Outdoor Wet Bulb Globe Temperature: 0.7*Tw + 0.2*Tg + 0.1*Ta."""
    tw = wet_bulb_f(air_f, humidity_pct)
    tg = globe_temp_f(air_f, mrt_f, wind_mph)
    return 0.7 * tw + 0.2 * tg + 0.1 * air_f


# --------------------------------------------------------------------------------------
# Composite exposure
# --------------------------------------------------------------------------------------


def exposure_index_f(air_f: float, hi_f: float, mrt_f: float) -> float:
    """The single scalar Cryonav routes on: perceived thermal load at 2 m AGL, in deg F.

    Structurally this is "heat index, plus the radiant penalty a weather app throws away".
    The humidity term comes from ``hi_f``; the term nobody else models is ``mrt_f - air_f``,
    the surplus radiation streaming off 175 deg F asphalt into a pedestrian's body.

    This is what makes a "cool route" possible. Two adjacent city blocks can share an air
    temperature to within 2 deg F yet differ by 20 deg F here, purely from canopy and surface.
    """
    # NWS states the shade-defined heat index rises by "up to 15 F" in full sunshine.
    # Capping the radiant term there keeps the composite inside the envelope the citation
    # supports -- and is what licenses applying published heat-index bands to this index.
    adjustment = min(
        RADIANT_COUPLING * max(mrt_f - air_f, 0.0),
        standards.NWS_FULL_SUN_ADJUSTMENT_MAX_F,
    )
    return hi_f + adjustment


def thermal_stress_score(exposure_f: float) -> float:
    """Map exposure index onto a 0-100 physiological stress score."""
    span = STRESS_CEILING_F - STRESS_FLOOR_F
    return round(clamp((exposure_f - STRESS_FLOOR_F) / span * 100.0, 0.0, 100.0), 1)


def classify_risk(exposure_f: float) -> str:
    """Bucket an exposure index into ``low`` / ``moderate`` / ``high`` / ``extreme``."""
    if exposure_f >= RISK_THRESHOLDS_F["extreme"]:
        return "extreme"
    if exposure_f >= RISK_THRESHOLDS_F["high"]:
        return "high"
    if exposure_f >= RISK_THRESHOLDS_F["moderate"]:
        return "moderate"
    return "low"


def risk_rank(level: str) -> int:
    try:
        return RISK_LEVELS.index(level)
    except ValueError:
        return 0


def solar_elevation_factor(hour: float, peak_hour: float = 15.0) -> float:
    """Normalised 0-1 solar loading curve.

    Zero before ~05:30 and after ~19:30, peaking at ``peak_hour``. Used to drive both
    asphalt surface heating and the diurnal air-temperature swing.
    """
    sunrise, sunset = 5.5, 19.5
    if hour <= sunrise or hour >= sunset:
        return 0.0
    # Skew the sine so its crest lands on `peak_hour` rather than solar noon.
    if hour <= peak_hour:
        phase = (hour - sunrise) / max(peak_hour - sunrise, 1e-6) * (math.pi / 2)
    else:
        phase = math.pi / 2 + (hour - peak_hour) / max(sunset - peak_hour, 1e-6) * (math.pi / 2)
    return clamp(math.sin(phase), 0.0, 1.0)


def diurnal_air_temp_f(t_min_f: float, t_max_f: float, hour: float, peak_hour: float = 15.0) -> float:
    """Sinusoidal diurnal air-temperature curve peaking at ``peak_hour``."""
    mid = (t_max_f + t_min_f) / 2.0
    amp = (t_max_f - t_min_f) / 2.0
    trough_hour = (peak_hour + 12.0) % 24.0
    phase = 2.0 * math.pi * (hour - trough_hour) / 24.0
    return mid - amp * math.cos(phase)


def hydration_ml_per_hour(exposure_f: float, profile_multiplier: float = 1.0) -> int:
    """Fluid replacement in mL/h -- NIOSH 2016-106 / OSHA, not an invented curve.

    Delegates to :func:`standards.hydration_ml_per_hour`, which interpolates across NIOSH's
    own stated interval (one cup every 20 min rising to every 15 min) and hard-caps at
    NIOSH's 1.5 L/h hyponatraemia limit. The exposure index is passed rather than the shade
    heat index because a walker in full sun is in the corrected environment the guidance
    describes.
    """
    return standards.hydration_ml_per_hour(exposure_f, profile_multiplier)
