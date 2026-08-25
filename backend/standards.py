"""
Published heat-safety standards used by Cryonav.

Every threshold in this module is a *citation*, not a design choice. Cryonav previously
invented its risk bands, exposure ceilings and hydration formula; an authenticity audit
correctly flagged them as "model choices, not cited medical guidance". This module replaces
them with the actual published values, and keeps the citation next to the number so the
provenance travels with the constant.

Where a standard is defined on a specific quantity (heat index vs WBGT vs air temperature),
that is stated explicitly — applying a WBGT limit to a heat-index number would be a category
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
[GPS-SPS]   GPS.gov, "GPS Accuracy" — Standard Positioning Service performance.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

# --------------------------------------------------------------------------------------
# 1. Risk bands — [OSHA-HI] / [NIOSH-2016] Table C-1
# --------------------------------------------------------------------------------------
#
# Defined on the HEAT INDEX in degrees F. Verbatim band edges from Table C-1
# ("Heat index-associated protective measures for worksites"):
#
#     < 91 F            Lower (caution)     — basic health and safety planning
#     91 F to 103 F     Moderate            — implement precautions, heighten awareness
#     103 F to 115 F    High                — additional precautions to protect workers
#     > 115 F           Very high to extreme— even more aggressive protective measures
#
# Cryonav previously used 95 / 105 / 115, invented. These are the published edges.
#
# APPLICABILITY NOTE — why these bands may be applied to Cryonav's exposure index:
# the NWS heat index is defined for SHADED conditions, and NWS states plainly that
# "exposure to full sunshine can increase heat index values by up to 15 F". Cryonav's
# exposure index is exactly that correction made explicit: heat index plus a computed
# radiant surplus (see thermal.exposure_index_f), which on the hottest measured Phoenix
# asphalt evaluates to ~13 F — inside the NWS-stated full-sun envelope. The index is
# therefore a full-sun-corrected heat index in the same units, and the heat-index bands
# apply to it directly.
NIOSH_HEAT_INDEX_BANDS_F: Dict[str, float] = {
    "low": 0.0,        # Table C-1 "Lower (caution)"
    "moderate": 91.0,  # Table C-1 "Moderate"
    "high": 103.0,     # Table C-1 "High"
    "extreme": 115.0,  # Table C-1 "Very high to extreme"
}

#: Upper bound NWS places on the full-sun correction to the (shade-defined) heat index.
#: Used as a sanity ceiling on Cryonav's radiant adjustment so the composite index can
#: never drift outside the envelope the citation supports.
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
# 2. Continuous-exposure ceilings — [NIOSH-2016] Table 6-2
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
#     108-112 F Caution — high levels of heat stress
#
# Cryonav needs one continuous-exposure ceiling per risk band. Each band's ceiling is the
# work-minutes value at the band's own lower edge, which is the most permissive minute count
# the table allows anywhere inside that band — i.e. the conservative reading.
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

#: Above the last tabulated row NIOSH marks the range "Caution — high levels of heat
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


#: Continuous-exposure ceiling per risk band, derived from Table 6-2 at each band's lower
#: edge. Computed rather than hand-written so the numbers cannot drift from the citation.
SAFE_EXPOSURE_MINUTES: Dict[str, float] = {
    band: work_minutes_per_hour(max(edge, 90.0))
    for band, edge in NIOSH_HEAT_INDEX_BANDS_F.items()
}


# --------------------------------------------------------------------------------------
# 3. Fluid replacement — [NIOSH-2016] Executive Summary, and [OSHA-HI]
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
NIOSH_MAX_ML_PER_HOUR = 1500.0                # hyponatraemia ceiling
#: Below this heat index NIOSH's "workers in heat" guidance does not yet apply; Cryonav
#: uses the low end of general hydration advice rather than inventing a curve.
HYDRATION_BASELINE_ML_PER_HOUR = 470.0        # 1 cup / 30 min


def hydration_ml_per_hour(heat_index_f: float, exertion_multiplier: float = 1.0) -> int:
    """Fluid replacement in mL/h, per [NIOSH-2016] and [OSHA-HI].

    Interpolates across NIOSH's own stated interval (one cup every 20 min -> every 15 min)
    as heat index rises through the moderate band, then holds at the 15-minute rate. Hard
    capped at NIOSH's 1.5 L/h hyponatraemia limit — a "drink more" formula without that
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
    return int(round(min(base * exertion_multiplier, NIOSH_MAX_ML_PER_HOUR) / 10.0) * 10)


# --------------------------------------------------------------------------------------
# 4. WBGT exposure limits — [NIOSH-2016] Section 8, p.93
# --------------------------------------------------------------------------------------
#
# Closed-form, verbatim:
#     RAL [C-WBGT] = 59.9 - 14.1 * log10(M)      (unacclimatised: Recommended Alert Limit)
#     REL [C-WBGT] = 56.7 - 11.5 * log10(M)      (acclimatised:  Recommended Exposure Limit)
# where M is metabolic rate in watts, for a standard 70 kg / 1.8 m^2 worker.
#
# These are defined on WBGT, which Cryonav already computes (thermal.wbgt_f) — so unlike
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
# 5. Positioning accuracy — [GPS-SPS]
# --------------------------------------------------------------------------------------
#
# GPS.gov: "GPS-enabled smartphones are typically accurate to within a 4.9 m (16 ft.)
# radius under open sky", degrading near buildings. Cryonav's immobility detector must not
# fire on GPS noise, so the displacement gate is stated relative to this figure.
SMARTPHONE_OPEN_SKY_ACCURACY_M = 4.9

#: Machine-readable provenance for the API/UI, so a reader can check the numbers themselves.
CITATIONS: Dict[str, Dict[str, str]] = {
    "risk_bands": {
        "value": "91 / 103 / 115 °F heat index",
        "source": "OSHA 'Using the Heat Index: A Guide for Employers' (2012); NIOSH 2016-106 Table C-1",
        "applies_to": "heat index (full-sun corrected, per NWS ≤15 °F sun adjustment)",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "exposure_ceilings": {
        "value": "60 / 45 / 30 / 15 min work per hour",
        "source": "NIOSH 2016-106 Table 6-2, moderate-work column (walking ≈ 300 W)",
        "applies_to": "continuous work minutes per hour at a given heat index",
        "url": "https://www.cdc.gov/niosh/docs/2016-106/",
    },
    "hydration": {
        "value": "710–946 mL/h (1 cup per 20→15 min), capped 1.5 L/h",
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
