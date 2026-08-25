/**
 * Documentation content for /docs.
 *
 * Structured blocks rather than markdown, so no parser ships to the browser and every block
 * type is styled deliberately by Docs.tsx. `**bold**` inside a paragraph, list item or table
 * cell is the one inline convention, because label-then-explanation is the shape most of this
 * content takes.
 *
 * HOW THIS WAS WRITTEN, because it matters for how it should be maintained. Each section was
 * drafted by reading the source files it describes, then fact-checked against those same files
 * in a second pass with instructions to DELETE any claim that could not be verified rather
 * than soften it. Every number here was read out of the repository, not recalled.
 *
 * The consequence for maintenance: when a constant or endpoint changes, this file is wrong
 * until it is updated. It is not generated at build time and nothing checks it. Treat a docs
 * edit as part of the change that made it necessary.
 *
 * Two blocks are exceptions and render from the running system instead. "live-cities" is
 * the coverage table, whose figures move whenever a city is onboarded or a tile recalibrated.
 * "live-contrast" is the two-street comparison that carries the product's central claim; it
 * moves with every daily calibration, and the frozen version was already wrong - it asserted
 * a 10 degree air gap where the live sample measured 0.2, which is a stronger statement of the
 * same thesis that no literal would ever have caught up with.
 *
 * Where something is simulated, modelled or limited, the sentence making the claim also
 * carries the qualification. Stating a capability in one place and its caveat in another is
 * how documentation ends up overstating a system.
 */

export interface Block {
  /**
   * "live-cities" renders the coverage table from the running API rather than from this file.
   *
   * That table was originally frozen prose, which meant onboarding a fifth city or
   * recalibrating a tile left the documentation quietly wrong while the landing page updated.
   * Prose belongs here; numbers the system already knows about itself do not.
   */
  kind: "h2" | "p" | "ul" | "table" | "code" | "note" | "live-cities" | "live-contrast";
  text?: string;
  items?: string[];
  headers?: string[];
  rows?: string[][];
  lang?: string;
}

export interface Section {
  slug: string;
  title: string;
  group: string;
  intro: string;
  blocks: Block[];
}

export const DOCS: Section[] = [
  {
    "group": "GETTING STARTED",
    "slug": "welcome",
    "title": "Welcome to Cryonav",
    "intro": "Cryonav is an open-source thermal-navigation engine that routes pedestrians by the heat a body actually absorbs rather than by distance or travel time. It reads the FortyGuard Temperature API at 2 m above ground, fuses that with real OpenStreetMap street and urban-form geometry, and returns two routes for the same origin and destination so the trade-off between exposure and detour is visible rather than asserted.",
    "blocks": [
      {
        "kind": "h2",
        "text": "The problem"
      },
      {
        "kind": "p",
        "text": "Every navigation app optimises metres and minutes. A weather feed sampled at 2 m above ground is nearly useless for separating a bare asphalt arterial from a shaded one, because the well-mixed air layer looks similar over both; the radiant load streaming off the surface does not. Here are two Phoenix streets 500 m apart, at the same moment, 15:00 local, as shown on the Cryonav landing page."
      },
      {
        "kind": "live-contrast",
        "text": "Sampled from /api/v1/facts when this page loads."
      },
      {
        "kind": "p",
        "text": "The gaps are shown live in the table below rather than stated here, because they move with each day's calibration and a second copy in prose could only drift away from the first. The index Cryonav routes on is the heat index plus 0.32 x max(MRT - T_air, 0), with that radiant term capped at the 15 °F the NWS publishes as the maximum full-sun correction. These are figures from this repository's own thermal model over FortyGuard microclimate data, not direct observations of each street: FortyGuard supplies the ambient curve, canopy is measured from the Meta / WRI canopy-height map at 1.19 m, the surface anomaly is measured from Landsat Collection 2 surface temperature at 30 m and from NASA ECOSTRESS at 70 m for the afternoon overpass Landsat never samples, and the mean-radiant step over that geometry is Cryonav's own model. The numbers also move with each day's calibration, and the direction of that movement matters - a later run on the 2026-08-24 calibration, using FortyGuard's observed /v1/heatmap raster for Phoenix's spatial air field, put the same two streets 0.1 °F apart on air temperature and 37 °F apart on mean radiant temperature. The observed air layer genuinely cannot tell the streets apart. That is the thesis, not a caveat against it."
      },
      {
        "kind": "note",
        "text": "Reproduce the sample for yourself: cd backend && .venv/bin/python -c \"from fortyguard_service import FortyGuardService as F; print(F().sample('phoenix', 33.4520, -112.0825, 15.0))\""
      },
      {
        "kind": "h2",
        "text": "What it returns"
      },
      {
        "kind": "p",
        "text": "Given an origin, a destination and a user profile, three cooperating agents produce Path A, a standard shortest-distance route computed the same way a conventional navigator would, and Path B, a route minimising thermal dose within a per-profile detour budget. A third agent, the Emergency Thermal Sentinel, checks the longest unbroken high-risk leg against a per-profile exposure ceiling and can send the optimiser back to re-solve with a real cooling shelter pinned as a mandatory waypoint. Every step lands in a structured trace the dashboard renders live."
      },
      {
        "kind": "p",
        "text": "Measured across nine demo corridors and three profiles (27 combinations, 15:00 local, 2026-08-24 calibration, over the three tiles onboarded at the time; San Jose was added afterwards and is not in that run): thermal load reduction 0 to 6.7 °F, heat-stress reduction 0 to 21.9 %, heat-strain dose reduction 0 to 27.4 %, shade coverage gained -0.1 to +46.9 %, added walking time -3.0 to +5.7 min. The original brief asked for a 35-50 % exposure reduction; Cryonav does not reach that on its headline metrics and does not round up to it. The zeroes in those ranges are deliberate - when no admissible route beats the direct path on both detour budget and dose, Cryonav returns the direct path and reports zero saving rather than manufacturing a detour."
      },
      {
        "kind": "h2",
        "text": "Where everything lives"
      },
      {
        "kind": "table",
        "headers": [
          "What",
          "Where",
          "Notes"
        ],
        "rows": [
          [
            "Live site",
            "https://cryonav.xyz",
            "Landing page. Every figure on it is either fetched live from the backend at page load or a recorded measurement from this repo, with the status pill flipping to OFFLINE when the backend is unreachable."
          ],
          [
            "Dashboard",
            "/app",
            "Map canvas, time-of-day slider, Path A vs Path B, exposure score card, shelter reroute toggle, live agent trace."
          ],
          [
            "API health",
            "/api/v1/health",
            "Version, FortyGuard mode and live flag, the endpoint the live path actually calls, last upstream status, and per-city calibration summary."
          ],
          [
            "API reference",
            "/api/docs",
            "FastAPI interactive docs, with the schema at /api/openapi.json. nginx and Caddy proxy /api/ wholesale to the backend on 127.0.0.1:8008."
          ],
          [
            "Documentation",
            "/docs",
            "This site. Served by the frontend SPA, not by the backend."
          ],
          [
            "Provenance",
            "/api/v1/meta",
            "Profiles and their detour budgets, risk bands with colours and safe-exposure minutes, agent roster, thresholds, the citation list behind each threshold, and per-city observed-data provenance."
          ],
          [
            "Source",
            "github.com/mrnetwork0001/Cryonav",
            "MIT licence. Map data © OpenStreetMap contributors (ODbL)."
          ],
          [
            "Built for",
            "FortyGuard Hackathon '26, \"Building the World's Temperature AI\"",
            "fortyguard.com/hackathon26."
          ]
        ]
      },
      {
        "kind": "note",
        "text": "The interactive API reference is at /api/docs, not /docs. Swagger UI moved under /api when this documentation site took the /docs path, and the published nginx config redirects a bare /openapi.json to /api/openapi.json. If you are linking to the API reference from elsewhere, link /api/docs."
      },
      {
        "kind": "h2",
        "text": "What is simulated, and where that is declared"
      },
      {
        "kind": "ul",
        "items": [
          "**The Jetson edge tier** - POST /api/v1/edge/jetson-kiosk runs the identical routing core and reports genuine server-side compute and payload size for the request, but no Jetson hardware is present. The runtime field says so in the response: \"NVIDIA Jetson Orin Nano (simulated)\". No TOPS figure is quoted, because quoting a benchmark for a device that is not there would be a claim about hardware rather than about the payload.",
          "**How much of a live reading is live** - the per-request live path is POST /v1/env_params, an asynchronous job: the POST returns an activity_id and the payload is collected from GET /v1/status/{id}. Each point therefore costs seconds, so only the first four points of a request are fetched live (MAX_LIVE_POINTS = 4, with a 25 s poll ceiling) and the rest come from the day's calibrated field. feed.live_fields and the feed detail state which metrics arrived and how much was modelled locally, so a partially live answer never presents itself as fully live.",
          "**Offline operation** - with FORTYGUARD_API_KEY unset, the deterministic simulation serves everything and the full stack runs with zero API spend. With a key set, a failed live call falls back to the simulation and is flagged degraded with the real upstream status, so a 401 renders as a red DEGRADED pill rather than a green 200.",
          "**Modelled layers** - ambient hourly curves are live FortyGuard env_params for all four tiles, and the US tiles (Phoenix, 2,407 cells; San Jose, 1,920) additionally take their spatial 2 m air field from the observed /v1/heatmap raster at ~100 m, which the Gulf tiles model because that raster's coverage is US-only. Canopy and surface anomaly are no longer per-class estimates: each urban data file carries canopy, surface_temperature and surface_temperature_peak blocks naming the product, resolution, licence and measurement time, and its assumptions block now reads \"No per-class estimates remain: canopy and surface temperature are both measured.\" What stays Cryonav's own is the physics over those inputs - sky view factor, mean radiant temperature, the composite exposure index and the convex routing penalty. Risk bands, continuous-exposure ceilings and hydration figures are taken from NIOSH 2016-106 and the OSHA heat-index employer guide, and every one of them is cited in /api/v1/meta."
        ]
      }
    ]
  },
  {
    "slug": "how-it-works",
    "title": "How It Works",
    "group": "GETTING STARTED",
    "intro": "One POST to /api/v1/navigate/cool-route runs three agents over a shared blackboard: a sensing pass, a dual route solve, and a safety check that can send the solve back for another attempt. This page follows a single request through all three.",
    "blocks": [
      {
        "kind": "h2",
        "text": "The request"
      },
      {
        "kind": "code",
        "lang": "http",
        "text": "POST /api/v1/navigate/cool-route\n\n{\n  \"origin\":      {\"lat\": ..., \"lon\": ...},\n  \"destination\": {\"lat\": ..., \"lon\": ...},\n  \"city_id\": null,              // resolved from origin when omitted\n  \"hour\": 15.0,                 // 0 <= hour < 24\n  \"profile\": \"pedestrian\",      // pedestrian | delivery_worker | elderly_vulnerable\n  \"allow_shelter_reroute\": true\n}"
      },
      {
        "kind": "p",
        "text": "An unknown profile string falls back to pedestrian rather than erroring. An unroutable pair returns 422 - origin and destination snapping to the same street node, no walkable path, or a point more than 500 m from any node in the network (MAX_SNAP_M). The engine refuses to snap further than that because routing from a snap 2 km away silently answers a different question."
      },
      {
        "kind": "h2",
        "text": "The blackboard"
      },
      {
        "kind": "p",
        "text": "CryonavOrchestrator.navigate builds one Blackboard holding the city, hour, resolved profile, origin and destination, plus two mutable stores: facts, a dictionary each agent reads and writes, and trace, an append-only list. Agents do not call each other. They read what earlier agents left in facts and may overwrite it. Every write to trace is a record with a step number, agent name, action, human-readable detail, structured data, elapsed_ms and a UTC timestamp - the trace is returned as agent_trace so the reasoning is inspectable rather than asserted."
      },
      {
        "kind": "h2",
        "text": "Step 1 - ThermalSensingAgent"
      },
      {
        "kind": "p",
        "text": "It probes three points: origin, destination, and the corridor midpoint, so the feed status describes the geography the user is about to walk rather than an arbitrary point. It calls heat_intelligence with prefer_live=False. This is deliberate and worth stating plainly: the upstream FortyGuard heat_intelligence endpoint is an async PDF-report generator, so a synchronous call per navigation would submit a billable job and still have to serve the response locally. Live FortyGuard data enters the system through a calibrated daily pull (scripts/calibrate.py, writing env_params and a heatmap) - the per-request readings are modelled from that calibration, not fetched live. The agent writes ambient conditions and a risk_vector: peak risk level, the asphalt radiation spike (surface minus 2 m air), asphalt_trap_detected at a spike of 35 F or more, and acute_danger_zone at peak air temperature of 110 F or above."
      },
      {
        "kind": "h2",
        "text": "Step 2 - CoolRouteOptimizationAgent"
      },
      {
        "kind": "p",
        "text": "It calls RoutingEngine.solve, which builds or reuses a street graph cached in 30-minute hour buckets. Where a city has cached OpenStreetMap pedestrian data in data/streets/ it is used - the Phoenix graph has around 25k nodes - otherwise a synthetic 28 x 28 lattice stands in, giving roughly 180 m blocks. Every edge carries a microclimate reading sampled mid-edge rather than at its junctions."
      },
      {
        "kind": "p",
        "text": "Path A is A* with aversion 0, which is pure distance - literally what a standard navigator optimises, which is what makes the baseline honest rather than a strawman. Path B is searched, not computed. Thermal aversion steps down a five-rung ladder from the profile's ideal (x1, x0.75, x0.5, x0.3, x0.15). Edge cost above zero aversion is walking time multiplied by one plus the aversion times a convex penalty: exposure surplus above the 88 F comfort baseline, divided by 28 F, raised to the power 2.5. The exponent matters - under a linear penalty the cost ratio between shaded and unshaded ground is too small to ever justify leaving the straight line, and the cool route degenerates into the direct one."
      },
      {
        "kind": "p",
        "text": "A candidate is admissible only if it fits the profile's detour budget, lowers thermal dose, and does not raise peak exposure. Among admissible candidates the engine keeps the one with the lowest dose, not the highest aversion that happened to fit. Rejected candidates and their reasons are returned in search_trace. If nothing is admissible, the direct path is returned labelled \"Cryonav Cool Route (direct path already optimal)\" rather than inventing a detour that would make the user hotter."
      },
      {
        "kind": "table",
        "headers": [
          "Profile",
          "max_detour_ratio",
          "thermal_aversion",
          "base_walk_speed_mps",
          "safe_exposure_scale"
        ],
        "rows": [
          [
            "pedestrian",
            "1.40",
            "2.2",
            "1.35",
            "1.0"
          ],
          [
            "delivery_worker",
            "1.25",
            "2.9",
            "1.45",
            "0.75"
          ],
          [
            "elderly_vulnerable",
            "1.30",
            "4.2",
            "1.05",
            "0.55"
          ]
        ]
      },
      {
        "kind": "p",
        "text": "The elderly / vulnerable budget is deliberately tighter than the healthy pedestrian one despite far higher heat aversion. At 1.05 m/s a 40% detour is fifteen extra minutes on foot, and for that profile time on feet is itself the hazard."
      },
      {
        "kind": "h2",
        "text": "Step 3 - EmergencyThermalSentinelAgent, and the edge that closes the loop"
      },
      {
        "kind": "p",
        "text": "The Sentinel classifies the chosen route's mean exposure into a risk band, then reads a continuous-exposure ceiling for that band from NIOSH Table 6-2 (evaluated at each band's lower edge - 91 / 103 / 115 F, with the low band floored at 90 F) and scales it by the profile's safe_exposure_scale. It compares that ceiling against the route's longest unbroken high-risk leg, not the route total - a 40-minute walk broken by an air-conditioned lobby is materially safer than an unbroken 25-minute one, and only the unbroken leg is comparable to published guidance."
      },
      {
        "kind": "p",
        "text": "If the ceiling holds, the agent records \"clear\" and the run ends. If it is exceeded, the Sentinel can overrule the optimiser. It pulls up to five air-conditioned shelters within 1.8 km of the route's midpoint vertex and re-runs RoutingEngine.solve for each of the top three, this time with that shelter pinned as a mandatory waypoint and Path A pinned to the original baseline so the scoreboard does not compare a detour against itself. Trialling rather than assuming matters: a shelter beside the route splits it evenly, while a nearer one may only add a dead-end spur. Under a mandated stop the detour is measured against the shortest path that also visits the waypoint, and the dose and peak guards are dropped, because breaking a continuous exposure leg is the objective and it legitimately costs dose."
      },
      {
        "kind": "p",
        "text": "The trial that most shortens the longest unbroken leg replaces bb.facts[\"cool_route\"] and bb.facts[\"comparison\"] outright, and is relabelled \"Cryonav Cool Route + Cooling Shelter\". That overwrite is the feedback edge. The optimiser's answer is a proposal, not a verdict, and a downstream agent revises it - which is what makes this an agent loop rather than a three-stage pipeline."
      },
      {
        "kind": "note",
        "text": "The Sentinel degrades explicitly rather than silently. With allow_shelter_reroute false it records reroute_suppressed and still returns the safety verdict. With no air-conditioned shelter in range, or none that shortens the leg, it escalates (no_shelter_in_range or no_shelter_improves_exposure) and advises postponing transit or arranging vehicle pickup."
      },
      {
        "kind": "h2",
        "text": "The response"
      },
      {
        "kind": "p",
        "text": "navigate returns both routes with full geometry, per-segment readings and metrics, plus the comparison scoreboard (thermal load and peak reduction, thermal dose reduction as a percentage, high-risk and extreme minutes avoided, shade gain, added distance and minutes, detour ratio), the feed and sensing provenance, ambient conditions, risk_vector, corridor hotspots, the safety verdict, shelter_reroute, nearby_shelters, optimizer_search, the agent roster, the full agent_trace and compute_ms."
      },
      {
        "kind": "ul",
        "items": [
          "**Separately** - the Sentinel also exposes monitor_transit (POST /api/v1/sentinel/monitor) for live position reports from a wearable or kiosk, returning ok / advisory / reroute / dispatch. Dispatch fires on immobility (under 25 m of movement over at least 8 minutes) inside an acute-danger zone, and the response reports whether the notification was actually delivered rather than claiming a message went out when it did not."
        ]
      }
    ]
  },
  {
    "group": "THE PHYSICS",
    "slug": "exposure-index",
    "title": "The Exposure Index",
    "intro": "The exposure index is the single scalar Cryonav's routing engine minimises: perceived thermal load on a body standing 2 m above a given point, expressed in degrees Fahrenheit. It is the shade heat index plus the radiant surplus that a weather app discards, and backend/thermal.py is the kernel that computes it.",
    "blocks": [
      {
        "kind": "h2",
        "text": "The definition"
      },
      {
        "kind": "p",
        "text": "The whole composite is two statements. It takes air temperature, a heat index, and a mean radiant temperature, and returns one number in degrees F."
      },
      {
        "kind": "code",
        "lang": "python",
        "text": "def exposure_index_f(air_f: float, hi_f: float, mrt_f: float) -> float:\n    adjustment = min(\n        RADIANT_COUPLING * max(mrt_f - air_f, 0.0),\n        standards.NWS_FULL_SUN_ADJUSTMENT_MAX_F,\n    )\n    return hi_f + adjustment"
      },
      {
        "kind": "p",
        "text": "RADIANT_COUPLING is 0.32. The comment above it is explicit about where that came from: UTCI field studies report sun-versus-shade differences of 15-20 deg C at identical air temperature, and 0.32 * (MRT - Tair) reproduces about 11 deg C of that. It is a modelled coupling coefficient chosen to sit on the conservative side of the published range rather than to flatter the cool route."
      },
      {
        "kind": "h2",
        "text": "Why air temperature alone is insufficient"
      },
      {
        "kind": "p",
        "text": "The 2 m air layer is well mixed. When Cryonav has the real FortyGuard /v1/heatmap raster cached (roughly 100 m tiles), its observed spatial spread is a few tenths of a degree C across a city - which is physically correct, and which is exactly why air temperature cannot separate one block from the next. The module docstring states the case in its own terms: a pedestrian on unshaded asphalt at 112 deg F air exchanges radiation with a 165 deg F surface, while the same pedestrian 40 m away under a mesquite canopy sees a 118 deg F surface. Same air, different physiological load. The cached raster carries air temperature only (per-tile average, min and max), and the sampling comment is explicit that when it is present the modelled air offsets are dropped entirely to avoid double-counting, while the surface and radiant terms stay Cryonav's own either way."
      },
      {
        "kind": "h2",
        "text": "The humidity term: NWS Rothfusz"
      },
      {
        "kind": "p",
        "text": "heat_index_f() implements the full NWS Rothfusz regression with both official corrections. Below the NWS validity threshold - when the mean of the simple Steadman estimate and air temperature falls under 80 deg F - it returns the Steadman average instead, matching what the Weather Service actually publishes."
      },
      {
        "kind": "ul",
        "items": [
          "**Desert adjustment** - when RH < 13% and 80 <= T <= 112 deg F, subtract ((13 - RH) / 4) * sqrt((17 - |T - 95|) / 17). This is the term the comment flags as mattering enormously in Phoenix, where afternoon RH sits around 15%.",
          "**Gulf-coast adjustment** - when RH > 85% and 80 <= T <= 87 deg F, add ((RH - 85) / 10) * ((87 - T) / 5). This is the term that matters for Dubai and Abu Dhabi humid heat."
        ]
      },
      {
        "kind": "h2",
        "text": "The radiant term: ISO 7726-style MRT"
      },
      {
        "kind": "p",
        "text": "mean_radiant_temp_f() splits the hemisphere a standing body sees between sky/hot surface and canopy using a sky view factor: coupling = 0.20 + 0.45 * SVF, then MRT = air + (surface - air) * coupling. Run the module docstring's own surface numbers through it. In the open (SVF 1.0, surface 165 deg F, air 112 deg F) the coupling is 0.65, giving MRT 146.45 deg F and a radiant term of 0.32 * 34.45 = 11.02 deg F. Under a canopy dense enough to leave SVF 0.15, with the docstring's 118 deg F shaded surface, the coupling is 0.2675, giving MRT 113.6 deg F and a radiant term of 0.51 deg F. Roughly 10.5 deg F of separation between two points at the same air temperature, produced entirely by geometry and surface."
      },
      {
        "kind": "h2",
        "text": "The full-sun cap"
      },
      {
        "kind": "p",
        "text": "The radiant adjustment is capped at NWS_FULL_SUN_ADJUSTMENT_MAX_F = 15.0. NWS states that exposure to full sunshine can increase the (shade-defined) heat index by up to 15 deg F. Capping there keeps the composite inside an envelope a citation supports, and that is what licenses banding route-level exposure means against published heat-index tiers at all. A regression test feeds an absurd MRT of 400 deg F and asserts the index still exceeds the heat index by no more than 15 deg F."
      },
      {
        "kind": "note",
        "text": "Per-point risk bands are not read off the exposure index. NIOSH Table C-1 warns that a radiant heat source degrades the usefulness of a heat-index table, so individual readings band on NIOSH adjusted temperature (standards.niosh_adjusted_temp_f, tiered by standards.band_from_adjusted_temp), which has its own published sun term of +13 deg F full sun / +7 deg F partly cloudy or overcast, driven by the same sky view factor. Route-level means are the case that does band on the composite index, via thermal.classify_risk."
      },
      {
        "kind": "h2",
        "text": "WBGT, wet bulb, and conserved dewpoint"
      },
      {
        "kind": "p",
        "text": "Alongside the routing index, each reading carries an outdoor WBGT at the standard 0.7 * Tw + 0.2 * Tg + 0.1 * Ta weighting. Tw is the Stull (2011) approximation, evaluated in Celsius and converted back. Tg is a black-globe temperature damped by wind through a ventilation factor of 1 / (1 + 0.09 * wind_mph), clamped to [0.25, 1.0]. Humidity is derived from a conserved dewpoint rather than scaled by a solar factor: absolute moisture barely moves over a day, so RH collapses through the afternoon and rebounds overnight on its own. That ordering is what keeps the heat index peaking with the sun instead of spuriously spiking after sunset."
      },
      {
        "kind": "h2",
        "text": "The anchors"
      },
      {
        "kind": "table",
        "headers": [
          "Constant",
          "Value",
          "Role"
        ],
        "rows": [
          [
            "RADIANT_COUPLING",
            "0.32",
            "Fraction of (MRT - air) added to the heat index"
          ],
          [
            "COMFORT_BASELINE_F",
            "88.0",
            "Physiological zero; floor of the 0-100 stress score"
          ],
          [
            "SURVIVAL_LIMIT_F",
            "140.0",
            "Ceiling of the stress score"
          ],
          [
            "NWS_FULL_SUN_ADJUSTMENT_MAX_F",
            "15.0",
            "Hard cap on the radiant term"
          ]
        ]
      },
      {
        "kind": "p",
        "text": "COMFORT_BASELINE_F = 88.0 is the exposure index below which a body sheds heat comfortably and walking carries no thermal cost. It is the anchor both the stress score and the routing penalty use; the code comment is direct that an arbitrary zero would make any \"% stress reduction\" figure meaningless. SURVIVAL_LIMIT_F = 140.0 is the index at which continuous outdoor exertion is described as life-threatening for a healthy adult. The stress score is a linear map of the 52-degree window between them onto 0-100, clamped at both ends."
      }
    ]
  },
  {
    "group": "THE PHYSICS",
    "slug": "standards",
    "title": "Risk Bands and Standards",
    "intro": "Every safety threshold in Cryonav is a citation rather than a chosen number, and the citation is stored next to the constant so the provenance travels with it. This page gives the actual published values, where they come from, and the one place the project deliberately departs from a published table - and why.",
    "blocks": [
      {
        "kind": "p",
        "text": "The whole citation layer lives in one file, /Users/mrnetwork/Cryonav/backend/standards.py. Its own header is blunt about the history: Cryonav previously invented its risk bands, exposure ceilings and hydration formula, and an authenticity audit flagged them as \"model choices, not cited medical guidance\". The module replaced them with published values. It also records, for each constant, which quantity the standard is defined on - heat index, WBGT, or air temperature - because applying a WBGT limit to a heat-index number is a category error, and preventing that is the reason the module exists."
      },
      {
        "kind": "h2",
        "text": "The bands, and the caveat that reshaped them"
      },
      {
        "kind": "p",
        "text": "The tier edges come from OSHA's \"Using the Heat Index: A Guide for Employers\" (2012), reproduced as NIOSH 2016-106 Appendix C, Table C-1: below 91 F is lower/caution, 91 to 103 F moderate, 103 to 115 F high, above 115 F very high to extreme. Cryonav previously used 95 / 105 / 115, which were invented."
      },
      {
        "kind": "note",
        "text": "Table C-1 carries its own warning, verbatim: \"The presence of a radiant heat source may decrease the accuracy and usefulness of the above heat index.\" Cryonav's entire subject is radiant load, so a shade-defined heat-index table is the wrong instrument for it."
      },
      {
        "kind": "p",
        "text": "The response was to keep the published edges but apply them to a different published quantity. band_from_adjusted_temp() bands on NIOSH adjusted temperature, which carries an explicit sun term and is therefore radiant-aware by construction. Both halves are published; neither is tuned. The edges exist once, as NIOSH_HEAT_INDEX_BANDS_F, and thermal.RISK_THRESHOLDS_F copies that same dict, so no second copy of the numbers can drift. Banding on Table 6-2's work minutes instead was rejected for a stated reason: that column stops at 107 F and a Phoenix afternoon is routinely past it, so every street would collapse into one band even though adjusted temperatures between asphalt and canopy differ by roughly 10 F."
      },
      {
        "kind": "h2",
        "text": "Adjusted temperature - Table 6-2, footnote"
      },
      {
        "kind": "p",
        "text": "The footnote recipe is applied to air temperature, not to a heat index, because feeding in a heat index would double-count humidity via the Rothfusz term. Sun: +13 F full sun, +7 F partly cloudy or overcast, no adjustment in shade or at night. Humidity, interpolated between rows:"
      },
      {
        "kind": "table",
        "headers": [
          "Relative humidity",
          "Adjustment"
        ],
        "rows": [
          [
            "10%",
            "-8 F"
          ],
          [
            "20%",
            "-4 F"
          ],
          [
            "30%",
            "0 F"
          ],
          [
            "40%",
            "+3 F"
          ],
          [
            "50%",
            "+6 F"
          ],
          [
            "60%",
            "+9 F"
          ]
        ]
      },
      {
        "kind": "p",
        "text": "The sun term is the quantity Cryonav already resolves per pixel: sky view factor is how much sky, and therefore how much sun, reaches a point. SVF 1.0 in an open parking lot is NIOSH's full sun; SVF near zero under closed canopy is NIOSH's shade. niosh_adjusted_temp_f() multiplies sky view factor by a solar factor so night correctly yields zero, and scales between the +7 and +13 rows by sky clearness. Table 6-2 assumes workers who are physically fit, well-rested, fully hydrated, under age 40, in normal work clothing, with natural ventilation and perceptible air movement - a modelled pedestrian is not guaranteed to match that."
      },
      {
        "kind": "h2",
        "text": "Work/rest minutes and the extrapolation flag"
      },
      {
        "kind": "p",
        "text": "Cryonav reads the moderate-work column, because NIOSH classifies continuous normal walking as moderate work at about 300 W: 60 minutes per hour up to 99 F, then 45 at 100 F, 40 at 101, 35 at 102, 30 at 103 and 104, 25 at 105, 20 at 106, 15 at 107."
      },
      {
        "kind": "p",
        "text": "Above 107 F the table stops giving minute counts and says only \"Caution - high levels of heat stress\". Cryonav continues the table's own trend of 5 minutes less per degree F, floors the result at 5 minutes, and labels that region: is_extrapolated() returns true for anything above 107 F. Per-band ceilings are computed from the table rather than typed in, read at each band's lower edge with a floor of 90 F (so 90, 91, 103 and 115 F), which yields 60, 60, 30 and 5 minutes - the last value coming from the flagged extrapolation, not from NIOSH."
      },
      {
        "kind": "h2",
        "text": "WBGT limits - the one that needs no reinterpretation"
      },
      {
        "kind": "p",
        "text": "NIOSH 2016-106 Section 8, p.93 gives closed forms for a standard 70 kg / 1.8 m^2 worker, where M is metabolic rate in watts. These are defined on WBGT, which thermal.wbgt_f() already computes, so no reinterpretation is required at all."
      },
      {
        "kind": "code",
        "lang": "python",
        "text": "RAL = 59.9 - 14.1 * log10(M)   # unacclimatised: Recommended Alert Limit\nREL = 56.7 - 11.5 * log10(M)   # acclimatised:  Recommended Exposure Limit\n\n# M = 300 W (walking) -> REL 28.2 C-WBGT (82.8 F), RAL 25.0 C-WBGT (77.0 F)"
      },
      {
        "kind": "h2",
        "text": "Hydration, with a ceiling"
      },
      {
        "kind": "ul",
        "items": [
          "**Rate** - NIOSH: one 8 oz cup every 15 to 20 minutes for moderate work in heat under 2 hours. That is 710 mL/h at the 20-minute rate and 946 mL/h at the 15-minute rate; OSHA's \"about 4 cups per hour\" is the same 946.",
          "**Interpolation** - hydration_ml_per_hour() moves across NIOSH's own stated interval as the index rises through the moderate band (91 to 103 F), then holds at the 15-minute rate.",
          "**Ceiling** - 1,419.5 mL/h, NIOSH Table 8-1's \"fluid intake should not exceed 1.5 qt/h\". An earlier draft used a rounded 1500, which is not the published number. Output is rounded to a 10 mL grid but clamped to the grid point below the cap, since a safety cap that rounding can push past is not a cap.",
          "**Below the guidance** - under 91 F, NIOSH's \"workers in heat\" advice does not yet apply, so the code uses 470 mL/h (one cup per 30 min) from general hydration advice rather than inventing a curve."
        ]
      },
      {
        "kind": "p",
        "text": "One further citation sits outside heat: GPS.gov puts smartphone open-sky accuracy at a 4.9 m radius, degrading near buildings. The immobility detector's displacement gate is a separate constant in agents.py, IMMOBILITY_RADIUS_M = 25 m over an eight-minute dwell window, comfortably clear of that noise floor. The full CITATIONS map - value, source, the quantity it applies to, and a URL - is served verbatim at GET /api/v1/meta, alongside the evaluated WBGT limits, so a reader can check the numbers against the source rather than taking the app's word for them."
      }
    ]
  },
  {
    "group": "DATA",
    "slug": "data-sources",
    "title": "Data Sources and Provenance",
    "intro": "Cryonav's routing claims rest on six measured layers, each fetched by a script in scripts/ and written into the committed city files under data/. This page names each source, its resolution and licence, and what it replaced. Where a value is still assumed rather than measured, that is stated alongside the claim it qualifies.",
    "blocks": [
      {
        "kind": "h2",
        "text": "The six layers"
      },
      {
        "kind": "table",
        "headers": [
          "Layer",
          "Source",
          "What it provides",
          "Resolution",
          "Licence"
        ],
        "rows": [
          [
            "Urban form",
            "OpenStreetMap via Overpass (scripts/fetch_urban.py)",
            "Green polygons, hot-surface polygons, individual trees, tree rows, covered ways, water, major-road ribbons with real lane counts",
            "Vector; rings decimated to ~12 m point spacing, roads to ~15 m",
            "ODbL, (c) OpenStreetMap contributors"
          ],
          [
            "Pedestrian network",
            "OpenStreetMap via Overpass (scripts/fetch_streets.py)",
            "The routable walking graph: 25,072 nodes and 34,387 edges for Phoenix, largest connected component only",
            "Vector; Douglas-Peucker at 5.0 m",
            "ODbL, (c) OpenStreetMap contributors"
          ],
          [
            "Canopy",
            "Meta / WRI Canopy Height Maps v6, alsgedi_global_v6_float/chm, on AWS Open Data",
            "Canopy height in metres; Cryonav counts pixels at or above 3 m as canopy",
            "1.194 m per pixel in EPSG:3857 for the Phoenix window (scaled by cos(latitude) to true ground metres when buffering)",
            "CC-BY-4.0"
          ],
          [
            "Morning surface temperature",
            "Landsat Collection 2 Level-2 ST_B10 (lwir11), USGS/NASA, via Microsoft Planetary Computer",
            "Per-pixel mean surface temperature from the six clearest summer scenes",
            "30 m",
            "Public domain"
          ],
          [
            "Peak-hour surface temperature",
            "ECOSTRESS ECO_L2T_LSTE v003 (C3998139651-LPCLOUD), NASA/JPL via LP DAAC",
            "Surface temperature in the 13:00-17:00 local window",
            "70 m",
            "NASA open data; requires a free Earthdata Login"
          ],
          [
            "Cooling refuges",
            "Maricopa Association of Governments Heat Relief Network ArcGIS feature service (Phoenix); OSM POIs (Dubai, Abu Dhabi)",
            "27 Phoenix sites for the 2026 season: 11 cooling centres, 16 hydration stations, with per-day hours, address, phone and wheelchair access",
            "Point",
            "MAG attribution and disclaimer carried in the file; ODbL for the OSM stand-ins"
          ]
        ]
      },
      {
        "kind": "h2",
        "text": "Canopy: measured pixels, not a class lookup"
      },
      {
        "kind": "p",
        "text": "OpenStreetMap knows a polygon is tagged leisure=park. It carries no canopy density. The first version of fetch_urban.py filled that gap with a table - park 0.60, garden 0.65, forest 0.85, grass 0.25 - applied to every polygon of that class in every city. The routing engine's central claim is that it can find you shade, and that claim was resting on the number 0.60."
      },
      {
        "kind": "p",
        "text": "scripts/fetch_canopy.py replaces it by counting pixels. 38 of Phoenix's 39 park polygons now measure a mean canopy fraction of 16.2%, against the 60% the table asserted; the 39th falls outside the measured window, keeps the table's 0.60 and is flagged canopy_measured=false so it cannot be mistaken for a measurement. Harmon Park, 46,376 m2, measures 4.2% canopy with a mean vegetation height of 0.36 m. The highest measured park in the tile reaches 57.4%; the lowest is 0.0%. The whole 25,210,405-pixel city window measures 5.25% canopy."
      },
      {
        "kind": "p",
        "text": "The same change applies to trees and paths. OSM gives a trunk position and nothing about the crown; the old model gave every tree the same weight (0.35 for anything tagged leaf_type=palm, 1.0 otherwise). Measuring an 8 m disc around each of Phoenix's 8,613 trees gives a mean crown cover of 16.7%, and 4,014 of those trees measure exactly zero canopy above 3 m within 8 m of the trunk. For linear features the script samples a corridor 10 m either side of the walking line rather than the whole polygon, because a pedestrian is shaded by canopy overhanging the footway and not by trees across a six-lane road: Phoenix's 868 road ribbons average 2.0% canopy in that corridor."
      },
      {
        "kind": "h2",
        "text": "Why anomalies reference the city's own road network"
      },
      {
        "kind": "p",
        "text": "The surface-temperature layer also replaced a table - parking +16 F, industrial +14 F, retail +11 F, commercial +9 F, railway +12 F. The reference the replacement uses is forced by how the value is consumed. backend/fortyguard_service.py adds an asphalt spike of (asphalt_uplift_f + surface_boost_f) * solar * clearness * sky_view_factor to the air temperature, and asphalt_uplift_f is already 52.0 F for Phoenix in data/cities.json. It describes a generic sunlit road. So surface_boost_f can only mean \"hotter than a typical road\"; anything else double-counts. Referencing the median of all city pixels would fold parks and water into the baseline and inflate every boost."
      },
      {
        "kind": "p",
        "text": "The baseline is therefore the median surface temperature of the pixels the city's own road geometry crosses: 57.32 C over 8,090 road pixels for Phoenix under Landsat. Measured against it, the median Phoenix car park runs 0.66 F cooler than a typical road at Landsat's hour, not 16 F hotter, and the largest boost applied to any polygon in the tile is 4.37 F. Only positive anomalies become a boost; a car park cooler than the road baseline contributes nothing rather than a negative boost the terrain model was never built to take. 139 of 620 hot polygons are smaller than two 30 m pixels and take the median of measured polygons of the same class in the same city, labelled lst_source=city_class_median so the distinction survives into the API."
      },
      {
        "kind": "h2",
        "text": "What ECOSTRESS adds that Landsat cannot"
      },
      {
        "kind": "p",
        "text": "Landsat-8 and Landsat-9 are sun-synchronous. They cross at the same local solar time on every pass, permanently. All six Phoenix scenes in the surface_temperature block are timestamped between 18:03:17Z and 18:04:15Z - 11:03 local. No number of additional Landsat scenes moves that clock. Cryonav's design hour, peak_hour in data/cities.json, is 15.5. Asphalt and concrete have different thermal inertia, so a morning ranking of surfaces is correlated with the afternoon ranking but is not the same ranking: the 49 Phoenix retail polygons measured in both windows sit at a median +0.39 F at 11:03 and a median -1.03 F in the afternoon, a sign flip."
      },
      {
        "kind": "p",
        "text": "ECOSTRESS flies on the International Space Station, whose precessing orbit samples the same ground across the whole day. Five passes survived quality filtering for Phoenix, at local times 13:52, 15:26, 15:58, 16:59 and 17:33. Each granule is referenced to its own road-network median - 46.03 C to 58.25 C across the five - and the anomalies are averaged rather than the temperatures, so granules on different UTM grids and different days all contribute. Where an ECOSTRESS value exists it supersedes the Landsat one in boost_f (385 of 620 Phoenix hot polygons carry boost_source=ecostress_peak). On hot polygons the Landsat number stays in lst_anomaly_f beside the afternoon lst_peak_anomaly_f; on road ribbons, where the peak value overwrites lst_anomaly_f outright, the morning figure is preserved as lst_anomaly_morning_f. Either way the divergence stays inspectable."
      },
      {
        "kind": "note",
        "text": "Limits, stated with the claims they qualify. ECOSTRESS needs a free NASA Earthdata Login; without credentials fetch_ecostress.py exits with instructions and writes nothing, and the product remains fully measured on Landsat alone. At 70 m a city block is one or two pixels, and the script accepts a single-pixel measurement. Shelter indoor temperatures (72 F for Phoenix cooling centres) are assumed and flagged indoor_temp_assumed. MAG aggregates partner-submitted sites and disclaims accuracy; that disclaimer is stored in data/shelters/phoenix.json. Dubai and Abu Dhabi have no official machine-readable refuge network, so mosques, malls, souks and metro stations stand in with air-conditioning and hours assumed by category - measured OSM coverage is 2-6% for opening_hours and roughly 0% for air_conditioning."
      }
    ]
  },
  {
    "group": "DATA",
    "slug": "cities",
    "title": "Cities and Coverage",
    "intro": "Cryonav runs on four cities, each defined as a single coverage tile of about 5 km on a side and backed by fetched files rather than fixtures. This page lists what has actually been measured in each tile, and the sequence of scripts that produces it for a fifth.",
    "blocks": [
      {
        "kind": "h2",
        "text": "The four live tiles"
      },
      {
        "kind": "p",
        "text": "Each city is one entry in data/cities.json giving a centre and a tile_half_extent_deg of 0.0225 latitude by 0.0248 to 0.0269 longitude - roughly 5 km square. The fetch scripts work from that bounding box and write one file per city into data/streets/, data/urban/, data/shelters/ and data/calibration/. The figures below are read from those files."
      },
      {
        "kind": "live-cities",
        "text": "Fetched from /api/v1/cities and /api/v1/meta when this page loads."
      },
      {
        "kind": "note",
        "text": "Street segments are edges in the routed graph after degree-2 chains are collapsed and the largest connected component is kept; nodes are the junctions A* searches over. Both come from OpenStreetMap via Overpass, cached and committed so routing works offline."
      },
      {
        "kind": "h2",
        "text": "What the canopy fraction actually measures"
      },
      {
        "kind": "p",
        "text": "Canopy fraction is counted pixels of vegetation at least 3 m tall in the Meta / WRI Canopy Height Maps v6 at 1.194 m ground sample, over a window of 21.3 to 25.2 million pixels per city. It is not a per-class estimate. The difference matters: Phoenix's 39 park polygons average 16.2% canopy, and Margaret T. Hance Park - 13.7 hectares - measures 14.1%, against the 74% the hand-authored fixture in cities.json assigned it. Civic Space Park measures 28.5% against a fixture of 61%. Those fixtures now serve only as fallback when a fetched file is absent."
      },
      {
        "kind": "p",
        "text": "Coverage of the measurement is not total, and the files say where. One of Phoenix's 1,635 flagged features falls back to a class default with canopy_measured false. Surface temperature is measured for 1,407 of Phoenix's 1,588 thermally sampled features from six Landsat Collection 2 scenes; 1,299 features additionally carry an ECOSTRESS anomaly from the 13:00-17:00 local window. San Jose's three clearest Landsat scenes date from 2024, and none of its six is from 2026. Anything unmeasured stays flagged rather than being filled in."
      },
      {
        "kind": "h2",
        "text": "Shelters"
      },
      {
        "kind": "p",
        "text": "Phoenix's 27 sites are the official Maricopa Association of Governments Heat Relief Network ArcGIS feed, with real per-day hours; air-conditioning is assumed on 16 of them and indoor temperature on all 27. The other three cities use OpenStreetMap POIs, where the assumption load is much heavier - all 163 Abu Dhabi sites have assumed air-conditioning and 160 have assumed hours, because OSM carries opening_hours on 2-6% of them and air_conditioning on almost none. Every assumed field is flagged individually as ac_assumed, hours_assumed or indoor_temp_assumed."
      },
      {
        "kind": "h2",
        "text": "Onboarding a new city"
      },
      {
        "kind": "ul",
        "items": [
          "**1. Add the entry** - a city block in data/cities.json with id, name, region, country_code, centre, tile_half_extent_deg, timezone, a climate block and presets. The heat_islands, canopy_zones, water_bodies and shelters arrays must be present but may be empty. Everything below reads the bbox from it.",
          "**2. scripts/fetch_streets.py** - Overpass walkable network into data/streets/.",
          "**3. scripts/fetch_urban.py** - parks, gardens and green polygons, individual street trees, tree rows, covered ways, water, plus parking, industrial, commercial, retail and railway land and lane-counted road ribbons, into data/urban/.",
          "**4. scripts/fetch_shelters.py** - cooling refuges into data/shelters/.",
          "**5. scripts/fetch_canopy.py** - measures canopy from the Meta / WRI rasters and rewrites data/urban/.",
          "**6. scripts/fetch_lst.py** - Landsat surface-temperature anomalies, rewrites data/urban/ again.",
          "**7. scripts/fetch_ecostress.py** - peak-hour surface temperature. Needs a free NASA Earthdata login. On road ribbons it overwrites lst_anomaly_f and keeps the Landsat value as lst_anomaly_morning_f; on hot polygons it supersedes boost_f. Either way it must run after step 6.",
          "**8. scripts/calibrate.py** - FortyGuard /v1/env_params 24 h ambient curve into data/calibration/, plus the /v1/heatmap raster where one exists."
        ]
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "python scripts/fetch_streets.py san_jose\npython scripts/fetch_urban.py san_jose\npython scripts/fetch_shelters.py san_jose\nbackend/.venv/bin/python scripts/fetch_canopy.py san_jose\nbackend/.venv/bin/python scripts/fetch_lst.py san_jose\nbackend/.venv/bin/python scripts/fetch_ecostress.py san_jose\nFORTYGUARD_API_KEY=... python scripts/calibrate.py san_jose"
      },
      {
        "kind": "p",
        "text": "Steps 5 to 7 each rewrite data/urban/<city>.json in place and are ordered. A newly added city's cities.json fixture arrays can stay empty - San Jose's heat_islands, canopy_zones and shelters lists are all empty and its climate block is labelled \"September heat event (placeholder until calibrated)\" - because the served layers come from the fetched files, not the fixture."
      },
      {
        "kind": "h2",
        "text": "Global sources, one US-only exception"
      },
      {
        "kind": "p",
        "text": "Every data source is global: OpenStreetMap via Overpass, Meta / WRI Canopy Height Maps v6, Landsat Collection 2 Level-2 surface temperature via the Microsoft Planetary Computer, ECOSTRESS ECO_L2T_LSTE v003 via NASA LP DAAC, and FortyGuard's /v1/env_params - which calibrated successfully for all four cities, including both Gulf tiles. The single exception is FortyGuard's /v1/heatmap raster, which is US-only. Phoenix returns 2,407 tiles and San Jose 1,920; Dubai and Abu Dhabi return an empty feature collection, and the client raises a specific error saying so rather than a parse failure. Where the raster is missing, the spatial air-temperature field is modelled from the ambient curve and the OSM urban form instead of observed, and the map labels it accordingly."
      }
    ]
  },
  {
    "group": "API",
    "slug": "rest-api",
    "title": "REST API Reference",
    "intro": "Cryonav exposes a FastAPI surface under /api/v1, version 1.0.0, with interactive docs at /api/docs. Every endpoint is synchronous and returns JSON, except the cached FortyGuard report, which returns a PDF.",
    "blocks": [
      {
        "kind": "p",
        "text": "Allowed browser origins come from CRYONAV_CORS_ORIGINS; unset, it permits localhost and 127.0.0.1 on ports 5180 and 5173, plus localhost on 4173. On startup, when an API key is configured and CRYONAV_AUTO_CALIBRATE has not been turned off, the app re-pulls any city calibration whose cached date is not today in a background thread. A second background thread warms each city's street graph at hour 15. Graphs are cached in 30-minute buckets, so a request landing in a different bucket still builds its own."
      },
      {
        "kind": "table",
        "headers": [
          "Method",
          "Path",
          "What it returns"
        ],
        "rows": [
          [
            "GET",
            "/api/v1/health",
            "Feed mode (fortyguard_calibrated when an API key is present, otherwise cryonav_simulation), the live flag, the endpoint the live path actually calls (/v1/env_params), sensing elevation 2.0 m, last feed status, city list and per-city calibration summaries."
          ],
          [
            "GET",
            "/api/v1/meta",
            "The three routing profiles with max_detour_ratio (pedestrian 1.40, delivery_worker 1.25, elderly_vulnerable 1.30), the four risk bands with colours and safe-exposure minutes, agent roster, thresholds including extreme_air_temp_f 110.0, machine-readable citations for the published standards behind the risk bands, adjusted temperature, exposure ceilings, hydration figures, WBGT limit and GPS-accuracy gate, NIOSH WBGT limits, and per-city data provenance read out of the data files."
          ],
          [
            "GET",
            "/api/v1/cities",
            "Coverage tiles and their metadata."
          ],
          [
            "GET",
            "/api/v1/cities/{city_id}/grid",
            "Heat grid for the overlay. source=model (default) is Cryonav's modelled exposure-index field, the composite routes are optimised on; source=fortyguard is the raw /v1/heatmap raster, observed daily-average air temperature per roughly 100 m tile with no Cryonav modelling on top, and 404s when no raster is cached for that tile. hour 0-23.99, resolution 8-64 (default 28)."
          ],
          [
            "GET",
            "/api/v1/cities/{city_id}/layers",
            "Urban-morphology layers from real OpenStreetMap geometry when a fetched urban file exists, plus shelters and a shelter_source field. Falls back to source: hand_authored_fixture when it does not."
          ],
          [
            "GET",
            "/api/v1/cities/{city_id}/report.pdf",
            "The cached daily FortyGuard analyst report, downloaded server-side so the key-bearing upstream link is never exposed. X-Report-Date header. 404 when nothing is cached."
          ],
          [
            "POST",
            "/api/v1/fortyguard/heat-intelligence",
            "1-256 locations, optional city_id, hour, prefer_live. Returns feed status, a sensing block, per-point readings and a summary (mean_air_temp_2m_f, max_surface_temp_f, mean_exposure_index_f, peak_risk_level, peak_risk_at, advisory)."
          ],
          [
            "POST",
            "/api/v1/navigate/cool-route",
            "Standard route versus cool route with the full thermal scoreboard and agent trace."
          ],
          [
            "GET",
            "/api/v1/shelters/nearby",
            "Cooling centres, hydration stations, mall refuges and cooled transit. Pass city_id, or lat and lon. radius_m 100-20000 (default 3000), limit 1-50 (default 10), require_ac."
          ],
          [
            "POST",
            "/api/v1/sentinel/monitor",
            "Escalation decision for a live position report."
          ],
          [
            "POST",
            "/api/v1/edge/jetson-kiosk",
            "Bandwidth-stripped route payload for kiosks and wearables."
          ]
        ]
      },
      {
        "kind": "h2",
        "text": "prefer_live on heat-intelligence, and why it is false"
      },
      {
        "kind": "p",
        "text": "prefer_live defaults to false at the API boundary. The upstream FortyGuard call is an asynchronous job queue: the POST returns an activity_id and the payload is collected by polling /v1/status/{id}. Its latency is not bounded, and the repository records the same two-point call measured at 22 s and then at over 120 s minutes apart. A synchronous HTTP endpoint cannot depend on that, so live is opt-in, only the first 4 points are fetched live (MAX_LIVE_POINTS), and a poll is abandoned after 25 s (LIVE_POLL_TIMEOUT_S). Series are memoised per coordinate rounded to 3 decimal places, about 110 m, per date, so a repeat is instant. sensing.live_points reports how many points were genuinely live; the remainder come from the calibrated local field. When the upstream fails, the feed reports the real upstream status code with degraded set, rather than presenting a fallback as a green 200."
      },
      {
        "kind": "h2",
        "text": "cool-route"
      },
      {
        "kind": "p",
        "text": "Body: origin and destination as {lat, lon}, optional city_id (auto-resolved from the origin when omitted), hour 0-23.99, profile, and allow_shelter_reroute (default true). The response carries routes.standard and routes.cool, each with geometry, per-segment telemetry, waypoints and a metrics block: distance_m, distance_km, duration_min, mean and peak exposure_index_f, shade_coverage_pct, thermal_dose_f_min, thermal_stress_score, extreme_exposure_min, longest_high_risk_leg_min, hydration_ml, risk_level. Alongside them sit comparison (thermal_load_reduction_f, heat_stress_reduction_pct, added_minutes), network.source and node count, ambient, hotspots, safety, shelter_reroute, nearby_shelters, agent_trace and compute_ms."
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "curl -X POST localhost:8008/api/v1/navigate/cool-route \\\n  -H 'content-type: application/json' \\\n  -d '{\"origin\":{\"lat\":33.4485,\"lon\":-112.0962},\n       \"destination\":{\"lat\":33.4576,\"lon\":-112.0705},\n       \"city_id\":\"phoenix\",\"hour\":15,\"profile\":\"delivery_worker\"}'"
      },
      {
        "kind": "h2",
        "text": "Sentinel monitor contract"
      },
      {
        "kind": "p",
        "text": "POST /api/v1/sentinel/monitor takes position, optional city_id, hour, profile, dwell_minutes (0-600), moved_m and accuracy_m (both optional, both non-negative), and notify. It returns one of four statuses. Immobility is true only when moved_m is supplied, is under 25 m, and dwell_minutes is at least 8. Acute danger is air_temp_2m_f at or above 110 F, or a risk band of extreme. Immobile and acute gives dispatch; dwell at or over the profile-scaled exposure ceiling while acute gives reroute; dwell at or over 70 percent of that ceiling gives advisory; otherwise ok."
      },
      {
        "kind": "ul",
        "items": [
          "**accuracy_m** - reported GPS horizontal accuracy. It is echoed back as position_accuracy_m and written into the alert body as a plus-or-minus metre figure. It does not change the escalation decision.",
          "**notify** - defaults to true. It only has an effect on a dispatch verdict, the one case that produces an outbound message. Set it false to evaluate escalation without sending, and the response returns {\"sent\": false, \"channel\": \"ntfy\", \"reason\": \"notification suppressed by caller\"}. For any non-dispatch status, notification is null.",
          "**What dispatch actually does** - it publishes to an ntfy topic notifying a user-nominated contact, not emergency services. There is no public API by which a civilian application can place a 911 call. If CRYONAV_NTFY_TOPIC is unset, the response says sent: false with that reason rather than implying a message went out."
        ]
      },
      {
        "kind": "h2",
        "text": "Edge payload"
      },
      {
        "kind": "p",
        "text": "POST /api/v1/edge/jetson-kiosk runs the identical routing core, then decimates both polylines to max_polyline_points (4-128, default 24), drops segments and the agent trace, and pre-renders one instruction string. The edge block reports inference_ms as the real server-side compute for that request and payload_bytes as the uplink cost. The hardware is not present: runtime reads \"NVIDIA Jetson Orin Nano (simulated)\" and no TOPS figure is quoted. offline_capable is computed, not asserted, by checking that the payload contains no http reference and that both the instruction and the route polyline are present."
      },
      {
        "kind": "note",
        "text": "Errors: 400 for a heat-intelligence request the service rejects, or a shelter query missing both city_id and coordinates; 404 for an unknown city_id; 422 for a route the engine cannot solve."
      }
    ]
  },
  {
    "slug": "edge",
    "title": "Edge Kiosk Endpoint",
    "group": "API",
    "intro": "POST /api/v1/edge/jetson-kiosk runs the same three-agent solve as the dashboard endpoint and returns a stripped payload sized for a pedestrian kiosk on a metered uplink. The Jetson hardware is not present in this build; the endpoint and its telemetry are real, the device is simulated.",
    "blocks": [
      {
        "kind": "h2",
        "text": "Request"
      },
      {
        "kind": "p",
        "text": "The handler is backend/main.py lines 516-638. It resolves the city, then calls the same orchestrator.navigate used by /api/v1/navigate/cool-route, with allow_shelter_reroute forced to True - an edge caller cannot switch the Sentinel's shelter intervention off."
      },
      {
        "kind": "table",
        "headers": [
          "Field",
          "Default",
          "Bounds"
        ],
        "rows": [
          [
            "origin, destination",
            "required",
            "lat/lon"
          ],
          [
            "city_id",
            "resolved from origin",
            "404 if unknown"
          ],
          [
            "hour",
            "15.0",
            "0 <= hour < 24"
          ],
          [
            "profile",
            "pedestrian",
            "pedestrian | delivery_worker | elderly_vulnerable"
          ],
          [
            "device_id",
            "jetson-kiosk-001",
            "max 64 chars"
          ],
          [
            "max_polyline_points",
            "24",
            "4 to 128"
          ]
        ]
      },
      {
        "kind": "h2",
        "text": "What the payload drops, and what that saves"
      },
      {
        "kind": "p",
        "text": "Three things are stripped relative to the dashboard response: both polylines are uniformly decimated by _decimate (which keeps the first and last vertex exactly), per-segment telemetry and the agent trace are dropped entirely, and the guidance is flattened into one pre-rendered instruction string so kiosk firmware never does string assembly or unit conversion. The test suite pins the omissions: agent_trace, segments, hotspots and optimizer_search must not appear in the response (backend/tests/test_agents_and_api.py)."
      },
      {
        "kind": "p",
        "text": "Measured on 2026-08-25 against the Phoenix demo corridor (33.4485,-112.0962 to 33.4576,-112.0705, hour 15, defaults otherwise). The cool route's full geometry is 177 vertices and the standard route's is 151; both come back as 24. The same request to /api/v1/navigate/cool-route returns 102,160 bytes of compact JSON; the edge response is 2,376 bytes on the wire, and 1,423 reported bytes if the caller asks for max_polyline_points=8. A test asserts the reported figure stays under 8,192. Ten warm calls in one process ran 254.02 ms to 295.26 ms, median 262.09 ms; the first call after start took 5,868 ms while the street graph and rasters loaded. The dashboard endpoint's own compute_ms for the same request was 265.63 ms - the edge saving is bandwidth, not compute, because all three agents still run server-side and their output is discarded before serialisation. The README quotes 2,070 bytes and ~272 ms from a 2026-08-24 run; the byte count moves with the route chosen and that day's calibration."
      },
      {
        "kind": "h2",
        "text": "Real response"
      },
      {
        "kind": "p",
        "text": "Captured from the run above - the warm call nearest the median. The two polyline arrays are elided for length: each carries 24 [lat, lon] pairs."
      },
      {
        "kind": "code",
        "lang": "json",
        "text": "{\n  \"device_id\": \"jetson-kiosk-001\",\n  \"city_id\": \"phoenix\",\n  \"feed\": {\n    \"source\": \"fortyguard_calibrated\",\n    \"status\": 200,\n    \"resolution\": {\n      \"fortyguard_ambient\": \"point query, 24 h hourly series (no spatial parameter)\",\n      \"fortyguard_raster_m\": 100,\n      \"canopy_m\": 1.19,\n      \"surface_temp_m\": 70\n    },\n    \"elevation_m\": 2.0\n  },\n  \"now\": { \"air_f\": 112.3, \"surface_f\": 161.5, \"risk\": \"extreme\", \"color\": \"#EF4444\" },\n  \"route\": {\n    \"polyline\": [[33.448687, -112.096163], \"... 24 points total ...\", [33.457627, -112.070604]],\n    \"distance_m\": 4269,\n    \"minutes\": 68.6,\n    \"risk\": \"extreme\",\n    \"shade_pct\": 26.1\n  },\n  \"standard_route\": {\n    \"polyline\": [[33.448687, -112.096163], \"... 24 points total ...\", [33.457627, -112.070604]],\n    \"distance_m\": 3349,\n    \"minutes\": 54.7,\n    \"risk\": \"extreme\"\n  },\n  \"savings\": { \"thermal_load_f\": 1.6, \"heat_stress_pct\": 5.6, \"added_min\": 13.8 },\n  \"shelter\": {\n    \"name\": \"20 W Jackson\",\n    \"type\": \"cooling_center\",\n    \"coords\": [33.44517, -112.074518],\n    \"indoor_f\": 72,\n    \"walk_min\": 9.6\n  },\n  \"instruction\": \"COOL ROUTE: 4.27 km, 69 min. 1.6 F cooler than the direct route. Beyond NIOSH's tabulated range. Asphalt thermal trap - reroute through shade or shelter immediately. Carry 1085 ml water.\",\n  \"hydration_ml\": 1085,\n  \"edge\": {\n    \"runtime\": \"NVIDIA Jetson Orin Nano (simulated)\",\n    \"accelerator\": \"Ampere-class embedded GPU (device not present; payload shaped for it)\",\n    \"inference_ms\": 263.6,\n    \"payload_bytes\": 2250,\n    \"offline_capable\": true,\n    \"no_external_references\": true,\n    \"instruction_prerendered\": true,\n    \"cached_tile_mi2\": 9.6\n  }\n}"
      },
      {
        "kind": "h2",
        "text": "offline_capable is derived, not asserted"
      },
      {
        "kind": "p",
        "text": "The claim the field makes is narrow: once this response lands, the kiosk needs no further network to guide the walk. The handler tests that claim against the payload it just built rather than hardcoding it. It serialises the payload, checks that no field contains \"http://\" or \"https://\" (nothing inside is a reference to dereference later), and checks that the instruction string and the route polyline are both non-empty (firmware can draw and read without a second call). offline_capable is the conjunction of the two; both halves are also published separately as no_external_references and instruction_prerendered, so a caller can see which condition failed."
      },
      {
        "kind": "code",
        "lang": "python",
        "text": "_blob = json.dumps(payload, separators=(\",\", \":\"))\n_self_contained = \"http://\" not in _blob and \"https://\" not in _blob\n_renders_without_lookup = bool(payload.get(\"instruction\")) and bool(\n    payload.get(\"route\", {}).get(\"polyline\")\n)\n...\n\"offline_capable\": _self_contained and _renders_without_lookup,"
      },
      {
        "kind": "p",
        "text": "The in-code comment records why: the field used to be a literal True, which would have kept claiming offline capability even if a later change embedded a tile URL. The check has limits worth knowing - it is a substring scan, so a protocol-relative or bare-host reference would pass it, and it runs over the payload before the edge block is attached."
      },
      {
        "kind": "note",
        "text": "payload_bytes is len(str(payload).encode(\"utf-8\")) - the Python repr of the dict, taken before the edge block is added. On the run above that gives 2,250, against 2,085 bytes for the same payload as compact JSON and 2,376 for the complete response including edge telemetry. Treat it as an uplink-cost indicator good to within about 8 percent, not as the exact byte count on the wire."
      },
      {
        "kind": "h2",
        "text": "The hardware is simulated"
      },
      {
        "kind": "p",
        "text": "No Jetson is in the loop. runtime is labelled \"NVIDIA Jetson Orin Nano (simulated)\" and accelerator states outright that the device is not present and the payload is merely shaped for it. No TOPS figure is quoted: a comment in the handler notes that the number previously published there, 32 TOPS, was the pre-Super devkit spec, and that naming the class of device is honest while quoting its benchmark is not. inference_ms is genuine wall-clock server-side compute for the request in the FastAPI process on ordinary developer hardware, measured with time.perf_counter around the solve - it is not an on-device measurement and not a synthetic benchmark. cached_tile_mi2 reports 9.6 mi2 for Phoenix, which is the area of that city's data bounding box (sensing.tile_area_mi2), not a measurement of anything held on a device."
      }
    ]
  },
  {
    "group": "OPERATE",
    "slug": "deploy",
    "title": "Self-Hosting and Deployment",
    "intro": "Cryonav is designed to be installed onto a VPS that is already running something else. The deployment scripts in deploy/ assume the box has production traffic on it and are written so that the worst outcome of a failed Cryonav install is that Cryonav does not get published, rather than that your other sites go down.",
    "blocks": [
      {
        "kind": "h2",
        "text": "1. Preflight, which is read-only"
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "ssh user@host 'bash -s' < deploy/preflight.sh\n# or paste deploy/preflight-inline.sh into a terminal on the VPS"
      },
      {
        "kind": "p",
        "text": "deploy/preflight-inline.sh installs nothing, starts nothing, stops nothing and writes nothing outside /tmp. It reports the host, free memory (warning below 400 MB available, where the venv build may struggle), who owns ports 80 and 443, whether 8008 and 5180 are free, which web servers and container runtimes exist, pm2/supervisor/node processes, the python3 version against a 3.9 floor, firewall state, and any prior Cryonav traces at /opt/cryonav, /etc/cryonav/env and the systemd unit."
      },
      {
        "kind": "p",
        "text": "Two details are deliberate. Port ownership is gated on the exit status of ss or netstat, not on whether output appeared, so a host with genuinely nothing listening reads \"free\" while a missing binary or a refused sudo reads UNKNOWN - UNKNOWN never collapses into free. And it does not run docker ps when the daemon is stopped, because connecting to /run/docker.sock socket-activates dockerd and restarts every container marked restart=always, which would break the script's promise to start nothing."
      },
      {
        "kind": "h2",
        "text": "2. Build the bundle"
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "scripts/bundle.sh              # -> ~/Desktop/cryonav-bundle.tar.gz\nscripts/bundle.sh --release    # ...and replace the asset on the v1.0.0 release"
      },
      {
        "kind": "p",
        "text": "The frontend is built locally, so the server needs no Node and no git credentials. bundle.sh excludes .git, backend/.venv, frontend/node_modules, .env, __pycache__ and build caches, then verifies rather than assumes: it aborts if LIBARCHIVE.xattr headers survived, if .env is inside the archive, if frontend/dist/index.html is missing, or if any value of 12 characters or more from your local .env appears anywhere in the extracted tree."
      },
      {
        "kind": "h2",
        "text": "3. Install on the VPS"
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "sudo -v\ntar xzf /tmp/cryonav-bundle.tar.gz -C /tmp && cp -a /tmp/Cryonav/. /opt/cryonav/\nbash /opt/cryonav/deploy/install-on-vps.sh [domain]"
      },
      {
        "kind": "p",
        "text": "The installer prints its full blast radius and asks for confirmation before touching anything. It aborts with exit 40 if port 8008 is held by a process that is not uvicorn and cryonav-api is not active, and exits 41 if the API does not answer /api/v1/health on 127.0.0.1:8008 within 30 seconds, dumping the last 40 journal lines. It exports NEEDRESTART_MODE=l and NEEDRESTART_SUSPEND=1 so that apt cannot bounce a running daemon, and it works out what is actually missing first - if nothing is, apt is never invoked at all. The venv check is a real python3 -m venv build, not python3 -m venv --help, which succeeds on Debian boxes where ensurepip is absent."
      },
      {
        "kind": "p",
        "text": "The web edge is decided, not assumed. If nginx, apache or anything other than Caddy owns 80/443, the strategy is \"no\": nothing web-related is touched, the API stays on loopback, and you are pointed at deploy/nginx-cryonav.conf.example. If Caddy owns the edge but its Caddyfile is not Cryonav's, the strategy is \"stage\": a site block is written to /etc/caddy/cryonav.caddy for you to import by hand."
      },
      {
        "kind": "h2",
        "text": "4. Publish through an existing nginx"
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "sudo CERTBOT_EMAIL=you@example.com \\\n  bash /opt/cryonav/deploy/nginx-publish.sh cryonav.example.com"
      },
      {
        "kind": "p",
        "text": "This runs in two stages because a first install cannot do it in one: the HTTPS vhost references a certificate that does not exist yet, and the certificate cannot be issued until nginx already serves the domain. Stage 1 installs an HTTP-only vhost serving the app and /.well-known/acme-challenge/. Stage 2 obtains the certificate with certbot certonly --webroot - never --nginx, which would edit nginx configuration to complete its challenge - then swaps in the HTTPS vhost."
      },
      {
        "kind": "p",
        "text": "Every apply runs nginx -t first and reloads only on success. On failure it removes its own symlink, restores any backup, re-validates and reloads your original configuration, so a bad Cryonav config never reaches a running nginx. It refuses to start at all if nginx -t is already failing. Reload is used rather than restart, so in-flight requests on your other sites finish; the script's own comment records 400/400 requests to a co-hosted vhost returning 200 across a reload, measured on a replica rather than on production. After stage 1 applies, a later failure such as an unissued certificate leaves HTTP live instead of tearing it down. The nginx version is parsed to choose between http2 on; and listen 443 ssl http2;, since the former needs 1.25.1 or newer."
      },
      {
        "kind": "h2",
        "text": "Environment variables"
      },
      {
        "kind": "p",
        "text": "All of them are optional. With none set the stack starts and runs entirely on the deterministic microclimate simulation - it will not fail, it will simply not be using live data. Runtime values belong in /etc/cryonav/env, which is root-owned and 0600 and is read by both service units."
      },
      {
        "kind": "table",
        "headers": [
          "Variable",
          "Effect if unset"
        ],
        "rows": [
          [
            "FORTYGUARD_API_KEY",
            "Simulation only; no live FortyGuard path"
          ],
          [
            "FORTYGUARD_BASE_URL",
            "Falls back to the service default base URL"
          ],
          [
            "CRYONAV_CORS_ORIGINS",
            "Defaults to localhost/127.0.0.1 dev origins on 5180, 5173, 4173"
          ],
          [
            "CRYONAV_NTFY_TOPIC",
            "Sentinel still detects immobility but sends nothing, and says so in the API"
          ],
          [
            "CRYONAV_NTFY_SERVER",
            "Defaults to the ntfy.sh public server"
          ],
          [
            "CRYONAV_AUTO_CALIBRATE",
            "Defaults to 1; startup calibration runs only when the service is live"
          ],
          [
            "CERTBOT_EMAIL",
            "nginx-publish.sh registers with --register-unsafely-without-email"
          ],
          [
            "EARTHDATA_TOKEN / _USERNAME / _PASSWORD",
            "Only scripts/fetch_ecostress.py needs these; never required at runtime"
          ]
        ]
      },
      {
        "kind": "note",
        "text": "The ntfy topic name is itself the secret - anyone who knows it can read your alerts, so generate a random one rather than picking a readable string."
      },
      {
        "kind": "h2",
        "text": "5. Uninstall"
      },
      {
        "kind": "code",
        "lang": "bash",
        "text": "sudo bash /opt/cryonav/deploy/uninstall-from-vps.sh\nsudo KEEP_ENV=1 bash /opt/cryonav/deploy/uninstall-from-vps.sh   # keep your API keys"
      },
      {
        "kind": "p",
        "text": "Installing is not a one-way door. The uninstaller removes only what the installer created, by name: the three systemd units, the cryonav system user, /opt/cryonav, /etc/cryonav, and the nginx vhost named cryonav - and that last one only if the file identifies itself as ours or is a symlink, so a vhost someone else wrote and happened to name cryonav survives. nginx is reloaded, never restarted, and only after nginx -t passes. It deliberately leaves python3-venv, pip and curl in place because other software may depend on them, and leaves every other vhost, all TLS certificates, docker, Caddy and firewall rules untouched."
      },
      {
        "kind": "h2",
        "text": "Runtime shape"
      },
      {
        "kind": "p",
        "text": "uvicorn runs as the cryonav user on 127.0.0.1:8008 with 2 workers, never exposed directly, under NoNewPrivileges, PrivateTmp, ProtectSystem=strict and ProtectHome, with /opt/cryonav/data as its only declared writable path. Request-time upstream calls are opt-in rather than absent: prefer_live defaults to false on POST /api/v1/fortyguard/heat-intelligence, so ordinary traffic is served from the calibrated local field and touches FortyGuard only when a caller explicitly asks for live. The scheduled pull is cryonav-calibrate.timer at 05:30 UTC daily with a 15-minute randomised delay, which pulls the calibration and then restarts the API to load it, since calibration is read once at startup; with CRYONAV_AUTO_CALIBRATE on and a live service, startup will also re-pull when the cached calibration is not today's."
      },
      {
        "kind": "p",
        "text": "Street graphs are built off the request path where possible: a startup thread warms each city at the default hour. They are cached in 30-minute hour buckets, so the first request for a bucket that has not been built yet still pays the build inline, which is why both vhosts set proxy_read_timeout 120s."
      }
    ]
  },
  {
    "group": "TRUST",
    "slug": "trust",
    "title": "Trust Model and Limitations",
    "intro": "Cryonav's posture is that a number you cannot reproduce is not a number. This page lists what the test suite mechanically enforces, and then every place the system is simulated, modelled, bounded or scripted.",
    "blocks": [
      {
        "kind": "h2",
        "text": "What the test suite enforces"
      },
      {
        "kind": "p",
        "text": "There are 142 test functions across four modules in backend/tests/ (the README's \"130 tests\" figure is stale). conftest.py builds the session fixture as FortyGuardService(api_key=\"\"), so the default run exercises the deterministic simulation path and touches no network. The guarantees below are assertions, not descriptions."
      },
      {
        "kind": "table",
        "headers": [
          "Guarantee",
          "How it is enforced"
        ],
        "rows": [
          [
            "Published constants are citations, not preferences",
            "test_thermal.py pins the risk bands to 91 / 103 / 115 F and NIOSH Table 6-2 work minutes to 60 / 45 / 30 / 15 at 95 / 100 / 103 / 107 F. Above 107 F, standards.is_extrapolated must return True. Every entry in standards.CITATIONS must carry a source, an applies_to and a url."
          ],
          [
            "The radiant term cannot inflate the index",
            "exposure_index_f is heat_index + 0.32 x max(MRT - T_air, 0), hard-capped at the NWS full-sun envelope of 15 F. Fed an absurd MRT of 400 F it must still exceed the heat index by no more than that envelope, which is what licenses applying published heat-index bands to a composite index."
          ],
          [
            "Hydration advice is capped",
            "hydration_ml_per_hour returns 470 mL/h below the workers-in-heat band and 950 mL/h at and above 103 F, and may never exceed the NIOSH hyponatraemia cap, which the module carries as the published 1.5 qt/h rather than a rounded 1.5 L/h: NIOSH_MAX_ML_PER_HOUR = 1,419.5."
          ],
          [
            "The cool route is never worse",
            "Across every city x preset x profile combination, thermal load, heat stress, dose and peak reductions must all be non-negative; the cool route may never undercut the direct route's distance, and its detour ratio must stay inside the profile's budget."
          ],
          [
            "...and never trivially zero",
            "A guard returning zeros everywhere would pass the above, so a separate test requires the best thermal-load saving across the demo set to reach 2.0 F. Its docstring records why the bar is 2.0 and not 3.0: sampling 200 Phoenix street midpoints at 15:00 puts the network's real p10-p90 exposure spread at 3.0 F."
          ],
          [
            "The street graph is real and whole",
            "Phoenix, Dubai and Abu Dhabi must each load with source == \"openstreetmap\" and over 5,000 nodes. The Phoenix graph must form a single connected component under flood fill and carry a polyline on every edge. A point further than MAX_SNAP_M = 500 m off-network raises rather than silently snapping."
          ],
          [
            "Readings are reproducible",
            "Identical inputs return byte-identical readings, and a freshly constructed service reproduces them across a process restart."
          ],
          [
            "The grid has not gone flat",
            "Every city's exposure spread must exceed 8 F. The docstring records the 2026-08-25 measurement: Dubai 21.5 F, Abu Dhabi 19.8 F, Phoenix 9.7 F, with Phoenix binding because the Meta/WRI raster puts its downtown at 5.25% canopy."
          ],
          [
            "Escalation is ordered and honest",
            "Sentinel status must be monotonic in dwell time. A dispatch issued with notify disabled must return notification.sent == False plus a reason. An applied shelter reroute must strictly shorten the longest unbroken high-risk leg, or the Sentinel must decline and say why."
          ],
          [
            "The wire contract is asserted, not assumed",
            "The live POST must reach /v1/env_params with flat latitude and longitude plus a date_time object, carry an api-key header, carry no Authorization header, and contain neither \"locations\" nor \"resolution_mi2\" - the exact shape that used to 422 on every call behind a green feed pill."
          ],
          [
            "The edge payload stays small",
            "Under 8,192 bytes, polyline decimated to the requested budget while retaining both endpoints, and agent_trace, segments, hotspots and optimizer_search all absent."
          ]
        ]
      },
      {
        "kind": "h2",
        "text": "Degraded-feed posture"
      },
      {
        "kind": "p",
        "text": "An upstream failure never renders as health. TestUpstreamFailureModes carries fifteen tests over the live path, and each failure mode below is in there because it previously produced misleading output."
      },
      {
        "kind": "ul",
        "items": [
          "**401** - feed.status_code and upstream_status_code both read 401, ok is False, degraded is True, and the upstream message lands in feed.detail. The dashboard renders that status in rose as \"401 UPSTREAM FAIL\", never \"200 OK\".",
          "**429** - surfaces as 429 and degraded, not as a quiet fallback.",
          "**HTTP 200 with error: true** - FortyGuard signals failure in-body, so a 200 carrying that envelope is treated as the 401 it is.",
          "**Non-JSON, unknown envelope, missing activity_id** - each degrades with a detail naming what was missing, so an operator can tell a malformed response from an auth failure without a debugger.",
          "**Short series** - a parameter array with fewer than 24 hourly samples is refused rather than padded, because padding would mislabel hours.",
          "In every case the request is still answered from the calibrated local field. The data keeps flowing; the claim of liveness does not."
        ]
      },
      {
        "kind": "p",
        "text": "Provenance is reported per field. A successful live call sets live_fields to exactly air_temperature_2m, relative_humidity and solar_irradiance, with detail reading \"3/5 metrics present\" - env_params carries no surface temperature and no wind, and the response says which two were modelled rather than implying all five were observed."
      },
      {
        "kind": "h2",
        "text": "Limitations"
      },
      {
        "kind": "ul",
        "items": [
          "**The Jetson hardware is simulated.** The endpoint, payload shape and telemetry are real; the device is not present. main.py reports runtime \"NVIDIA Jetson Orin Nano (simulated)\" and accelerator \"Ampere-class embedded GPU (device not present; payload shaped for it)\". No TOPS figure is quoted, deliberately. inference_ms is genuine server-side compute for that request, and offline_capable is computed from the payload rather than hardcoded true.",
          "**Gulf cities have no FortyGuard raster layer.** /v1/heatmap coverage appears to be US-only, and the code says exactly that. The cached rasters are Phoenix (2,407 tiles, 100 m cells) and San Jose (1,920 tiles), both dated 2026-08-25. A Gulf area of interest returns an empty FeatureCollection, and the code raises a coverage error saying so rather than a schema error; raster_grid(\"dubai\") raises KeyError and the map control disables the layer. Dubai and Abu Dhabi therefore run the same physics over a modelled spatial air field, with live ambient curves from env_params, which is global.",
          "**The live per-request FortyGuard path is opt-in.** The API's prefer_live field defaults to False. The upstream is an asynchronous job queue with unbounded latency: the same two-point call was measured at 22 s and then at over 120 s minutes apart. When enabled, it is capped at MAX_LIVE_POINTS = 4, abandoned after LIVE_POLL_TIMEOUT_S = 25.0, and memoised per coordinate per day. sensing.live_points reports how many points were genuinely live. The routing agent calls with prefer_live=False on purpose - heat_intelligence is a PDF report generator that cannot drive routing.",
          "**Emergency escalation notifies a nominated contact and cannot call emergency services.** backend/notify.py publishes to an ntfy topic the user configures. There is no public API by which a civilian application can file an emergency call; Twilio states verbatim that it should not be relied on for delivery to 911 or E911. With CRYONAV_NTFY_TOPIC unset the Sentinel still detects immobility - moved under 25 m across 8 minutes with air temperature at or above 110 F - and the API says plainly that nothing was sent.",
          "**The replay walker is scripted.** The dashboard's transit playback drives the whole route in about 32 s of wall time, freezes the walker at 62% of the path, and holds 11 simulated minutes of immobility. Positions are synthetic, jittered with Gaussian noise at a stated 12 m accuracy. What is scripted is only that the walker stops: both replay and live GPS post to the same /api/v1/sentinel/monitor endpoint through the same displacement estimator, and every verdict on screen is the backend's.",
          "**Coefficients that remain estimates are labelled.** Canopy is measured from Meta/WRI Canopy Height Maps v6 at 1.194 m with a 3 m height threshold (Phoenix 5.25%, Dubai 2.17%, Abu Dhabi 3.26%, San Jose 12.18% city-wide). Surface anomalies are Landsat ST_B10 at 30 m, superseded where available by ECOSTRESS at 70 m in the 13:00-17:00 local window - the Landsat overpass is around 10:00, so its afternoon spread is understated, and the data file says so. Gulf shelter hours and air-conditioning fall back to category defaults flagged assumed per field."
        ]
      },
      {
        "kind": "note",
        "text": "Concretely, on the measurement rather than the adjective: across the 39 Phoenix parks in the urban file, 38 of them measured directly from the raster, the mean canopy is 17.3%, while Coffelt-Lamoreaux Park at 0.9 hectares measures 60.0% and the surrounding city measures 5.25%. That gap is the whole product, and it is also why Phoenix is the binding case in the demo set: the least contrast to route through."
      }
    ]
  }
];
