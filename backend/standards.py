"""
Published heat-safety standards used by Cryonav.

Every threshold in this module is a *citation*, not a design choice. Cryonav previously
invented its risk bands, exposure ceilings and hydration formula; an authenticity audit
correctly flagged them as "model choices, not cited medical guidance". This module replaces
them with the actual published values, and keeps the citation next to the number so the
provenance travels with the constant.

Where a standard is defined on a specific quantity (heat index vs WBGT vs air temperature),
that is stated explicitly - applying a WBGT limit to a heat-index number would be a category
error, and is the mistake this module exists to prevent.

SOURCES
-------
[NIOSH-2016] NIOSH, "Criteria for a Recommended Standard: Occupational Exposure to Heat and
    Hot Environments", DHHS (NIOSH) Publication No. 2016-106, revised 2016. US Government
    work, public domain.
[OSHA-HI]   OSHA, "Using the Heat Index: A Guide for Employers" (2012); the same table is
    reproduced as NIOSH-2016 Appendix C, Table C-1, and underlies the OSHA-NIOSH Heat
    Safety Tool app.
[NWS-HI]    NOAA/NWS Heat Index classification, "Likelihood of Heat Disorders with Prolonged
    Exposure or Strenuous Activity" (weather.gov). US Government work, public domain.
[GPS-SPS]   GPS.gov, "GPS Accuracy" - Standard Positioning Service performance.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

# --------------------------------------------------------------------------------------
# 1. Risk bands - [OSHA-HI] / [NIOSH-2016] Table C-1
# --------------------------------------------------------------------------------------
#
# Defined on the HEAT INDEX in degrees F. Verbatim band edges from Table C-1
# ("Heat index-associated protective measures for worksites"):
#
#     < 91 F            Lower (caution)     - basic health and safety planning
#     91 F to 103 F     Moderate            - implement precautions, heighten awareness
#     103 F to 115 F    High                - additional precautions to protect workers
#     > 115 F           Very high to extreme- even more aggressive protective measures
#
# Cryonav previously used 95 / 105 / 115, invented. These are the published edges.
#
# APPLICABILITY - these bands are retained for REFERENCE and cross-checking only; Cryonav
# does NOT band on them. Table C-1 carries its own warning, verbatim: "The presence of a
# radiant heat source may decrease the accuracy and usefulness of the above heat index."
# Cryonav's whole subject is radiant load, so a shade-defined heat-index table is the wrong
# instrument for it. Banding is done on NIOSH adjusted temperature instead (section 1b),
# which has a published sun term and is therefore radiant-aware by construction.
NIOSH_HEAT_INDEX_BANDS_F: Dict[str, float] = {
    "low": 0.0,        # Table C-1 "Lower (caution)"
    "moderate": 91.0,  # Table C-1 "Moderate"
    "high": 103.0,     # Table C-1 "High"
    "extreme": 115.0,  # Table C-1 "Very high to extreme"
}

#: Upper bound NWS places on the full-sun correction to the (shade-defined) heat index:
#: "exposure to full sunshine can increase heat index values by up to 15 F". Cryonav uses
#: it only as a sanity ceiling on the radiant term of its routing index -- an independent
#: check that the composite stays inside a published envelope. It is NOT a licence to band
#: on heat-index tiers; see the applicability note above.
NWS_FULL_SUN_ADJUSTMENT_MAX_F = 15.0

#: [NWS-HI] public-facing classification, for reference/display alongside the worksite
#: bands. Lower bound of each class, in heat-index degrees F.
NWS_HEAT_INDEX_CLASSES_F: Dict[str, float] = {
    "caution": 80.0,
    "extreme_caution": 90.0,
    "danger": 103.0,
    "extreme_danger": 125.0,
}


# --------------------------------------------------------------------------------------
# 1b. NIOSH adjusted temperature - [NIOSH-2016] Table 6-2, footnote †
# --------------------------------------------------------------------------------------
#
# THIS IS THE CORRECT INPUT TO TABLE 6-2, and the reason Cryonav can use that table
# rigorously rather than by analogy.
#
# Table 6-2 is indexed by ADJUSTED TEMPERATURE, not by heat index. Its footnote gives the
# recipe verbatim:
#
#     Full sun (no clouds):            Add 13 deg F
#     Partly cloudy/overcast:          Add  7 deg F
#     No shadows visible / in shade / at night:   no adjustment
#
#     Per relative humidity:  10% -8 | 20% -4 | 30% 0 | 40% +3 | 50% +6 | 60% +9
#
# Two things follow, and they matter:
#
#   1. The sun adjustment is exactly the quantity Cryonav already resolves per pixel. Sky
#      view factor IS "how much sun reaches this spot": SVF 1.0 in an open parking lot is
#      NIOSH's "full sun", SVF ~0 under closed canopy is NIOSH's "in the shade". So Cryonav
#      can compute a genuine NIOSH adjusted temperature per point, not an approximation.
#
#   2. The humidity adjustment is applied to AIR TEMPERATURE. Feeding a heat index (which
#      already contains a humidity term via Rothfusz) into this table would double-count
#      humidity. Cryonav therefore feeds air temperature, as the table requires.
#
# This is why the exposure ceilings below are read from adjusted temperature rather than
# from Cryonav's composite exposure index: NIOSH Table C-1 itself warns that "the presence
# of a radiant heat source may decrease the accuracy and usefulness of the above heat
# index", so a radiant-augmented index is the wrong instrument for a heat-index table.
NIOSH_FULL_SUN_ADJUSTMENT_F = 13.0
NIOSH_PARTLY_CLOUDY_ADJUSTMENT_F = 7.0

#: (relative humidity %, adjustment deg F) from the footnote, interpolated between rows.
NIOSH_RH_ADJUSTMENT_F: Tuple[Tuple[float, float], ...] = (
    (10.0, -8.0),
    (20.0, -4.0),
    (30.0, 0.0),
    (40.0, 3.0),
    (50.0, 6.0),
    (60.0, 9.0),
)

#: Table 6-2 assumes, verbatim: "workers are physically fit, well-rested, fully hydrated,
#: under age 40 ... 30% RH and natural ventilation with perceptible air movement".
NIOSH_TABLE_6_2_ASSUMPTIONS = (
    "physically fit, well-rested, fully hydrated, under age 40, normal work clothing, "
    "natural ventilation with perceptible air movement"
)


def niosh_rh_adjustment_f(humidity_pct: float) -> float:
    """Humidity term of the NIOSH adjusted temperature, interpolated across the footnote rows."""
    rows = NIOSH_RH_ADJUSTMENT_F
    if humidity_pct <= rows[0][0]:
        return rows[0][1]
    if humidity_pct >= rows[-1][0]:
        return rows[-1][1]
    for (r0, a0), (r1, a1) in zip(rows, rows[1:]):
        if r0 <= humidity_pct <= r1:
            f = (humidity_pct - r0) / (r1 - r0)
            return a0 + f * (a1 - a0)
    return 0.0


def niosh_adjusted_temp_f(
    air_temp_f: float,
    humidity_pct: float,
    sky_view_factor: float,
    solar_factor: float = 1.0,
    sky_clearness: float = 1.0,
) -> float:
    """Adjusted temperature for [NIOSH-2016] Table 6-2, per its own footnote recipe.

    ``sky_view_factor`` (0 shaded .. 1 open sky) and ``solar_factor`` (0 at night .. 1 at
    solar peak) together decide how much of NIOSH's sun adjustment applies -- shade and
    night both correctly yield zero. ``sky_clearness`` scales between the full-sun (+13)
    and overcast (+7) rows.
    """
    sun_exposure = max(0.0, min(1.0, sky_view_factor)) * max(0.0, min(1.0, solar_factor))
    clear = max(0.0, min(1.0, sky_clearness))
    per_sun = (
        NIOSH_PARTLY_CLOUDY_ADJUSTMENT_F
        + (NIOSH_FULL_SUN_ADJUSTMENT_F - NIOSH_PARTLY_CLOUDY_ADJUSTMENT_F) * clear
    )
    return air_temp_f + per_sun * sun_exposure + niosh_rh_adjustment_f(humidity_pct)


# --------------------------------------------------------------------------------------
# 2. Continuous-exposure ceilings - [NIOSH-2016] Table 6-2
# --------------------------------------------------------------------------------------
#
# Table 6-2, "Work/rest schedules for workers wearing normal work clothing", is indexed by
# adjusted temperature in F and gives minutes of work per hour for Light / Moderate / Heavy
# work. NIOSH classifies continuous normal walking as MODERATE work (~300 W), so Cryonav
# reads the moderate column:
#
#     90-99 F   Normal (no rest period required)
#     100 F     45 min work / 15 min rest
#     101 F     40 / 20
#     102 F     35 / 25
#     103 F     30 / 30
#     104 F     30 / 30
#     105 F     25 / 35
#     106 F     20 / 40
#     107 F     15 / 45
#     108-112 F Caution - high levels of heat stress
#
# Cryonav needs one continuous-exposure ceiling per risk band. Each band's ceiling is the
# work-minutes value at the band's own lower edge, which is the most permissive minute count
# the table allows anywhere inside that band - i.e. the conservative reading.
NIOSH_WORK_MINUTES_PER_HOUR: Tuple[Tuple[float, float], ...] = (
    (99.0, 60.0),   # <=99 F: continuous work permitted
    (100.0, 45.0),
    (101.0, 40.0),
    (102.0, 35.0),
    (103.0, 30.0),
    (104.0, 30.0),
    (105.0, 25.0),
    (106.0, 20.0),
    (107.0, 15.0),
)

#: Above the last tabulated row NIOSH marks the range "Caution - high levels of heat
#: stress" rather than giving a minute count. Cryonav continues the table's own trend
#: (5 min less per degree F) down to a floor, and labels the extrapolation as such.
NIOSH_TABLE_CEILING_F = 107.0
NIOSH_EXTRAPOLATION_MIN_PER_F = 5.0
NIOSH_MINIMUM_WORK_MINUTES = 5.0


def work_minutes_per_hour(heat_index_f: float) -> float:
    """Permitted continuous work minutes per hour for moderate work.

    [NIOSH-2016] Table 6-2, moderate-work column. Above 107 F the table stops giving
    minute counts and says "Caution"; the linear continuation below is Cryonav's, floored
    at 5 minutes, and is flagged by :func:`is_extrapolated`.
    """
    if heat_index_f > NIOSH_TABLE_CEILING_F:
        over = heat_index_f - NIOSH_TABLE_CEILING_F
        return max(
            NIOSH_MINIMUM_WORK_MINUTES,
            15.0 - over * NIOSH_EXTRAPOLATION_MIN_PER_F,
        )
    minutes = 60.0
    for edge_f, mins in NIOSH_WORK_MINUTES_PER_HOUR:
        if heat_index_f <= edge_f:
            return mins if edge_f != 99.0 else 60.0
        minutes = mins
    return minutes


def is_extrapolated(heat_index_f: float) -> bool:
    """True when :func:`work_minutes_per_hour` is past the end of the published table."""
    return heat_index_f > NIOSH_TABLE_CEILING_F


def band_from_adjusted_temp(adjusted_temp_f: float) -> str:
    """Risk band for a NIOSH adjusted temperature, using the published Table C-1 tiers.

    The tier EDGES (91 / 103 / 115 F) come from OSHA's heat-index employer guide
    (= NIOSH Table C-1). The QUANTITY they are applied to is NIOSH's adjusted temperature
    rather than the raw heat index -- and that pairing is what Table C-1's own caveat
    points to: it warns that "the presence of a radiant heat source may decrease the
    accuracy and usefulness of the above heat index". Adjusted temperature is the same
    kind of feels-like degrees F but carries an explicit, published sun term (+13 F full
    sun, 0 in shade) as well as humidity, so it is the radiant-aware member of the pair.
    Both halves are published; neither is tuned.

    Cannot simply tier on Table 6-2's work minutes instead: that column stops at 107 F and
    a Phoenix afternoon is routinely past it, so every street would collapse to one band
    and the differences the product exists to expose would vanish -- even though the
    underlying adjusted temperatures differ by ~10 F between asphalt and canopy.
    """
    if adjusted_temp_f >= NIOSH_HEAT_INDEX_BANDS_F["extreme"]:
        return "extreme"
    if adjusted_temp_f >= NIOSH_HEAT_INDEX_BANDS_F["high"]:
        return "high"
    if adjusted_temp_f >= NIOSH_HEAT_INDEX_BANDS_F["moderate"]:
        return "moderate"
    return "low"


#: Continuous-exposure ceiling per risk band, read from Table 6-2 at the adjusted
#: temperature where each band begins. Computed from the table so it cannot drift.
#: Continuous-exposure ceiling per band, read from Table 6-2 at the adjusted temperature
#: where each band begins (91 / 103 / 115 F), so the ceilings follow the citation exactly.
SAFE_EXPOSURE_MINUTES: Dict[str, float] = {
    band: work_minutes_per_hour(max(edge, 90.0))
    for band, edge in NIOSH_HEAT_INDEX_BANDS_F.items()
}


# --------------------------------------------------------------------------------------
# 3. Fluid replacement - [NIOSH-2016] Executive Summary, and [OSHA-HI]
# --------------------------------------------------------------------------------------
#
# NIOSH: "Workers in heat <2 hours and involved in moderate work activities should drink
# 1 cup (8 oz.) of water every 15-20 minutes". 8 US fl oz = 236.6 mL; one cup every
# 15 min = 946 mL/h, every 20 min = 710 mL/h. OSHA's employer guide gives "about 4 cups of
# water per hour" for the same conditions, which is the same 946 mL/h.
#
# NIOSH also caps total intake to avoid hyponatraemia: no more than 1.5 L/h, 12 L/day.
NIOSH_CUP_ML = 236.6
NIOSH_MODERATE_WORK_ML_PER_HOUR_LOW = 710.0   # 1 cup / 20 min
NIOSH_MODERATE_WORK_ML_PER_HOUR_HIGH = 946.0  # 1 cup / 15 min
#: NIOSH Table 8-1 and OSHA agree exactly: "Fluid intake should not exceed 1.5 qt/h"
#: = 6 cups/h = 1,419.5 mL/h. (An earlier draft used a rounded 1500, which is not the
#: published number.)
NIOSH_MAX_ML_PER_HOUR = 1419.5
#: Below this heat index NIOSH's "workers in heat" guidance does not yet apply; Cryonav
#: uses the low end of general hydration advice rather than inventing a curve.
HYDRATION_BASELINE_ML_PER_HOUR = 470.0        # 1 cup / 30 min


def hydration_ml_per_hour(heat_index_f: float, exertion_multiplier: float = 1.0) -> int:
    """Fluid replacement in mL/h, per [NIOSH-2016] and [OSHA-HI].

    Interpolates across NIOSH's own stated interval (one cup every 20 min -> every 15 min)
    as heat index rises through the moderate band, then holds at the 15-minute rate. Hard
    capped at NIOSH's 1.5 L/h hyponatraemia limit - a "drink more" formula without that
    ceiling would be unsafe advice, which is precisely why this is now a citation and not
    a curve someone chose.
    """
    lo_band = NIOSH_HEAT_INDEX_BANDS_F["moderate"]   # 91 F
    hi_band = NIOSH_HEAT_INDEX_BANDS_F["high"]       # 103 F
    if heat_index_f < lo_band:
        base = HYDRATION_BASELINE_ML_PER_HOUR
    elif heat_index_f >= hi_band:
        base = NIOSH_MODERATE_WORK_ML_PER_HOUR_HIGH
    else:
        frac = (heat_index_f - lo_band) / (hi_band - lo_band)
        base = (
            NIOSH_MODERATE_WORK_ML_PER_HOUR_LOW
            + frac
            * (NIOSH_MODERATE_WORK_ML_PER_HOUR_HIGH - NIOSH_MODERATE_WORK_ML_PER_HOUR_LOW)
        )
    # Round the recommendation to the 10 mL display grid (understating a fluid
    # recommendation is the unsafe direction), but clamp to the grid point BELOW the
    # hyponatraemia ceiling -- a safety cap that rounding can push past is not a cap.
    value = round(base * exertion_multiplier / 10.0) * 10
    ceiling = math.floor(NIOSH_MAX_ML_PER_HOUR / 10.0) * 10
    return int(min(value, ceiling))


# --------------------------------------------------------------------------------------
# 4. WBGT exposure limits - [NIOSH-2016] Section 8, p.93
# --------------------------------------------------------------------------------------
#
# Closed-form, verbatim:
#     RAL [C-WBGT] = 59.9 - 14.1 * log10(M)      (unacclimatised: Recommended Alert Limit)
#     REL [C-WBGT] = 56.7 - 11.5 * log10(M)      (acclimatised:  Recommended Exposure Limit)
# where M is metabolic rate in watts, for a standard 70 kg / 1.8 m^2 worker.
#
# These are defined on WBGT, which Cryonav already computes (thermal.wbgt_f) - so unlike
# the heat-index bands, no reinterpretation is required at all. This is the most rigorous
# limit in the module.
METABOLIC_WATTS_WALKING = 300.0  # NIOSH "moderate work"; continuous normal walking


def niosh_wbgt_limit_c(metabolic_watts: float = METABOLIC_WATTS_WALKING, acclimatised: bool = True) -> float:
    """NIOSH REL (acclimatised) or RAL (unacclimatised) in degrees C-WBGT."""
    m = max(metabolic_watts, 100.0)
    if acclimatised:
        return 56.7 - 11.5 * math.log10(m)
    return 59.9 - 14.1 * math.log10(m)


def niosh_wbgt_limit_f(metabolic_watts: float = METABOLIC_WATTS_WALKING, acclimatised: bool = True) -> float:
    """The same limit expressed in degrees F-WBGT, for comparison with Cryonav's wbgt_f."""
    return niosh_wbgt_limit_c(metabolic_watts, acclimatised) * 9.0 / 5.0 + 32.0


def wbgt_exceedance_f(wbgt_f_value: float, acclimatised: bool = True) -> float:
    """Degrees F by which a measured WBGT exceeds the NIOSH limit for walking (0 if under)."""
    return max(0.0, wbgt_f_value - niosh_wbgt_limit_f(acclimatised=acclimatised))


# --------------------------------------------------------------------------------------
# 5. Positioning accuracy - [GPS-SPS]
# --------------------------------------------------------------------------------------
#
# GPS.gov: "GPS-enabled smartphones are typically accurate to within a 4.9 m (16 ft.)
# radius under open sky", degrading near buildings. Cryonav's immobility detector must not
# fire on GPS noise, so the displacement gate is stated relative to this figure.
SMARTPHONE_OPEN_SKY_ACCURACY_M = 4.9

#: Machine-readable provenance for the API/UI, so a reader can check the numbers themselves.
CITATIONS: Dict[str, Dict[str, str]] = {
    "risk_bands": {
        "value": "NIOSH Table 6-2 work/rest tiers on adjusted temperature",
        "source": "NIOSH 2016-106 Table 6-2 (+ footnote †); band edges cross-checked against OSHA/NIOSH Table C-1 heat-index tiers",
        "applies_to": (
            "NIOSH adjusted temperature = air temp + sun adjustment (sky view factor) "
            "+ RH adjustment. NOT the heat index: NIOSH Table C-1 warns that a radiant "
            "heat source reduces the heat index's accuracy, so Cryonav bands on the "
            "radiant-aware adjusted temperature instead."
        ),
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "adjusted_temperature": {
        "value": "sun +13 °F full / +7 °F overcast / 0 shaded; RH 10%→−8 … 60%→+9 °F",
        "source": "NIOSH 2016-106 Table 6-2, footnote †",
        "applies_to": "air temperature (humidity applied here, so never feed a heat index in)",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "exposure_ceilings": {
        "value": "60 / 45 / 30 / 15 min work per hour",
        "source": "NIOSH 2016-106 Table 6-2, moderate-work column (walking ≈ 300 W)",
        "applies_to": "continuous work minutes per hour at a given heat index",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "hydration": {
        "value": "710–946 mL/h (1 cup per 20→15 min), capped 1,419.5 mL/h (1.5 qt/h)",
        "source": "NIOSH 2016-106 Executive Summary; OSHA heat-index employer guide",
        "applies_to": "moderate work in heat, <2 hours",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "wbgt_limit": {
        "value": "REL = 56.7 − 11.5·log₁₀(M); RAL = 59.9 − 14.1·log₁₀(M) °C-WBGT",
        "source": "NIOSH 2016-106 Section 8 p.93",
        "applies_to": "WBGT, metabolic rate M in watts (walking ≈ 300 W)",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "gps_accuracy": {
        "value": "4.9 m open-sky radius",
        "source": "GPS.gov Standard Positioning Service performance",
        "applies_to": "smartphone position fixes, degraded near buildings",
        "url": "https://www.gps.gov/systems/gps/performance/accuracy/",
    },
}
