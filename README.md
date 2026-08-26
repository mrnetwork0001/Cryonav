```
   ██████╗██████╗ ██╗   ██╗ ██████╗ ███╗   ██╗ █████╗ ██╗   ██╗
  ██╔════╝██╔══██╗╚██╗ ██╔╝██╔═══██╗████╗  ██║██╔══██╗██║   ██║
  ██║     ██████╔╝ ╚████╔╝ ██║   ██║██╔██╗ ██║███████║██║   ██║
  ██║     ██╔══██╗  ╚██╔╝  ██║   ██║██║╚██╗██║██╔══██║╚██╗ ██╔╝
  ╚██████╗██║  ██║   ██║   ╚██████╔╝██║ ╚████║██║  ██║ ╚████╔╝
   ╚═════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝  ╚═══╝
     ❄  H Y P E R L O C A L   T H E R M A L   N A V I G A T I O N  ❄
        powered by the FortyGuard Temperature API®
```

**Cryonav** is an open-source, agentic thermal-navigation and urban-climate-safety platform built for the **FortyGuard Hackathon '26 - "Building the World's Temperature AI."**

It answers a question no navigation app asks: *not how far, but how hot.*

**Live at [cryonav.xyz](https://cryonav.xyz)** - deployed on a shared VPS behind nginx with
Let's Encrypt TLS, co-existing with unrelated production services.

| | |
|---|---|
| Dashboard | [cryonav.xyz/app](https://cryonav.xyz/app) |
| Documentation | [cryonav.xyz/docs](https://cryonav.xyz/docs) |
| API reference | [cryonav.xyz/api/docs](https://cryonav.xyz/api/docs) |
| Health & provenance | [`/api/v1/health`](https://cryonav.xyz/api/v1/health) · [`/api/v1/meta`](https://cryonav.xyz/api/v1/meta) · [`/api/v1/facts`](https://cryonav.xyz/api/v1/facts) |

`/api/v1/facts` is worth a look: every figure this README and the site quote about Cryonav
itself is computed there at request time rather than written down, because the written-down
versions kept going stale.

---

## The problem

At 15:00 in downtown Phoenix in July, two walking routes between the same two points can differ by **20 °F of thermal load** - and every navigation app on the planet will hand you the hotter one, because they optimise metres and minutes.

Here is what Cryonav measures on two Phoenix streets 500 m apart, at the same moment
*(as of 2026-08-24, on that day's live FortyGuard calibration - rerun the command below for today's values)*:

| | Van Buren St × 7th Ave | Central Ave canopy spine |
|---|---|---|
| Air temperature @ 2 m | 113.8 °F | 113.7 °F |
| Asphalt surface temperature | **177.7 °F** | 127.7 °F |
| Mean radiant temperature | **155.4 °F** | 117.9 °F |
| **Exposure index (thermal load)** | **122.3 °F** | **110.3 °F** |
| Risk band | 🔴 EXTREME | 🟠 HIGH |

Since integrating FortyGuard's observed air raster, the air temperatures are **0.1 °F apart** -
which is the whole point. The observed 2 m air layer is well mixed and cannot tell these streets
apart; the **37 °F mean-radiant difference** streaming off the asphalt can, and that is where
heat illness actually comes from. A weather API sees two identical streets. A body doesn't.

*(Reproduce: `cd backend && .venv/bin/python -c "from fortyguard_service import FortyGuardService as F; print(F().sample('phoenix', 33.4520, -112.0825, 15.0))"` - values shift with the daily calibration.)*

Cryonav fuses the **FortyGuard Temperature API®** (observed hourly series at 2 m above ground level) with measured urban canopy and surface temperature, and routes around it. The "10 mi²" figure this line used to quote was Cryonav's own invention: `/v1/env_params` is a point query with no resolution parameter at all.

---

## What it does

Given an origin, a destination and a user profile, Cryonav returns **two routes**:

- **Path A - Standard Direct Route.** Minimises distance. Exactly what a conventional navigator returns, computed the same way, so the comparison is honest rather than a strawman.
- **Path B - Cryonav Cool Route.** Minimises *thermal dose* - minutes in the sun weighted by how punishing that sun is - subject to a per-profile detour budget.

Measured across all twelve demo corridors x three profiles (36 combinations, 15:00 local,
**2026-08-24 calibration** - these shift with each day's live data):

| Metric | Range across demo corridors |
|---|---|
| Thermal load reduction | **0 – 6.7 °F** |
| Heat-stress reduction | **0 – 21.9 %** |
| Heat-strain dose reduction | **0 – 27.4 %** |
| Shade coverage gained | **−0.1 – +46.9 %** |
| Added walking time | **−3.0 to +5.7 min** |

*(Real OpenStreetMap pedestrian network, real OSM urban form, live FortyGuard ambient data.)*

> **On the numbers.** The brief's headline claim is a 35–50 % exposure reduction. Cryonav does not reach it on its headline metrics, and does not round up to it: on mean thermal load the defensible reduction is **up to ~7 °F**; on heat-strain dose, **up to ~27 %** (2026-08-24 calibration). (These are measured against *live* FortyGuard ambient data, which is flatter through the afternoon than the earlier synthetic curve - so the honest numbers came down when real data arrived.)
>
> Several zeroes in those ranges are deliberate. When no admissible route beats the direct path on both detour budget and dose, Cryonav returns the direct path and reports zero saving rather than manufacturing a detour. And in Gulf-city afternoons *every* cell on the tile is already in the extreme band, so the band-time metric there is meaningless and can even read negative - a cooler route that takes longer spends more total minutes in a band that covers the whole city. The win in those cities shows up as thermal load and dose instead, which is why the dashboard leads with those.

### Coverage

Four cities, each a tile roughly 5 km on a side. Every layer below is fetched, not authored;
`scripts/` onboards a fifth in one pass.

| Tile | Green polygons | Heat-retaining polygons | Cooling shelters | FortyGuard raster |
|---|---|---|---|---|
| **Phoenix**, USA | 99 | 620 | 27 | yes, 2,407 tiles |
| **Dubai**, UAE | 115 | 129 | 52 | no US coverage |
| **Abu Dhabi**, UAE | 146 | 723 | 163 | no US coverage |
| **San Jose**, USA | 87 | 464 | 57 | yes, 1,920 tiles |

Totals: **65,893 routable OpenStreetMap nodes**, 299 shelters,
4,327 observed raster cells. Every data source is global except FortyGuard's
`/v1/heatmap` raster, which is US-only - so the Gulf tiles run the same physics over a modelled
spatial air field and are labelled as such wherever they appear.

---

## Agentic architecture

Three agents cooperate over a shared blackboard. The third can **revise** the second's output, which is what makes this a loop rather than a pipeline.

```
                        ┌──────────────────────────────────────┐
                        │        CryonavOrchestrator           │
                        │      (shared blackboard + trace)     │
                        └───────────────┬──────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
┌────────────────────┐        ┌────────────────────┐        ┌────────────────────────┐
│ 1. Thermal Sensing │        │ 2. Cool-Route      │        │ 3. Emergency Thermal   │
│                    │        │    Optimization    │        │    Sentinel            │
│ • reads the daily- │───────▶│ • dual A* search   │───────▶│ • continuous-exposure  │
│   calibrated       │ ambient│   A: distance      │ routes │   ceiling per profile  │
│   FortyGuard field │  + risk│   B: thermal dose  │        │ • trials shelters as   │
│ • classifies risk  │  vector│ • sweeps aversion  │        │   mandatory waypoints  │
│   low→extreme      │        │   ladder, keeps    │        │ • escalates: advisory  │
│ • flags asphalt    │        │   best admissible  │        │   → reroute → dispatch │
│   radiation spikes │        │ • scores Δ vs A    │        │                        │
└────────────────────┘        └─────────▲──────────┘        └───────────┬────────────┘
                                        │                               │
                                        └───────────────────────────────┘
                                    re-solve with shelter waypoint
                                   (Path A baseline stays pinned)
```

**Why the feedback edge matters.** The Sentinel does not simply append the nearest shelter. It trials up to three candidates as mandatory waypoints, keeps the one that most shortens the **longest unbroken high-risk leg**, and if none improves it, says so and escalates instead of inventing a detour. A 40-minute walk broken by an air-conditioned lobby is materially safer than an unbroken 25-minute one - and only the unbroken leg is comparable to published exposure guidance.

Every agent step is appended to a structured trace that the dashboard renders live, so the reasoning is shown rather than asserted.

---

## The physics

`backend/thermal.py` is a small urban-climate model, not decorative noise. The routing objective is:

```
exposure_index_f = heat_index_f + 0.32 × max(MRT − T_air, 0)
                   └── humidity ──┘   └─ the radiant term nobody else models ─┘
```

| Component | Method |
|---|---|
| Heat index | NWS Rothfusz regression, with both the low-RH (desert) and high-RH (Gulf) adjustments |
| Wet-bulb / WBGT | Stull (2011) approximation; outdoor WBGT = 0.7 T_w + 0.2 T_g + 0.1 T_a |
| Mean radiant temp | ISO 7726-style surface/air split weighted by sky view factor |
| Relative humidity | Derived from a **conserved daily dewpoint** (Magnus-Tetens), so RH falls as temperature rises |
| Urban heat island | Gaussian sources with `tanh` saturation, weighted toward **night** (desert daytime UHI is weak; the daytime hazard is radiant) |
| Canopy / arterials | Modelled as **linear corridors** - point-to-polyline distance - because urban thermal structure is ribbons, not blobs |

Three of those choices were forced by bugs the test suite caught, and each is documented at its call site:

- Scaling RH by a solar factor made the exposure index peak at **19:00** instead of 15:00. Fixed by conserving dewpoint.
- Modulating the UHI and canopy offsets too steeply made air temperature **rise after sunset** - the offsets swung harder than the diurnal curve they ride on.
- A **linear** thermal penalty could never justify a detour, so the "cool route" silently degenerated into the standard route. Heat-illness risk is convex in exposure; the penalty is now `surplus^2.5`.

### The live FortyGuard integration

Verified directly against `api.fortyguard.com` (run `./scripts/verify_fortyguard.sh` to reproduce):

| | Value | How it was confirmed |
|---|---|---|
| Auth header | **`api-key: <key>`** | `Authorization: Bearer` is silently ignored - the API replies "Missing required 'api-key' header" as if nothing were sent |
| Endpoint | **`POST /v1/heat_intelligence`** (underscore) | recovered from the docs Angular bundle; a hyphenated path 404s |
| Envelope | `{"error": bool, "status_code": int, "data"/"details": …}` | failure is signalled **in-body**, so an HTTP 200 with `error: true` is not success |
| Other endpoints | `/v1/env_params`, `/v1/heatmap`, `/v1/satellite`, `/v1/streetview`, `/v1/status/` | same source |
| Live status | `1.0.1-beta`, `mode: PROD` | unauthenticated `GET /health` |

Both the header name and the endpoint path were originally wrong in this codebase, and neither
failure was visible: auth is checked *before* routing, so every mistake returns the same 401.

**The enterprise endpoints are asynchronous.** `POST` returns an `activity_id`; the payload is
collected from `GET /v1/status/{activity_id}` once it flips from `Processing` to `Completed`.
Two endpoints matter here and they behave very differently:

| Endpoint | Required body | Settles in | Returns |
|---|---|---|---|
| `/v1/heat_intelligence` | `latitude`, `longitude`, `temperature`, `date`, `analysis[]` - literals `geographic`/`environmental`/`urban`/`events`/`anthropogenic` | ~145 s | a **PDF report** (S3 link) |
| `/v1/env_params` | `latitude`, `longitude`, `temperature`, `date_time{start_date, filter_type: 1‑4}` | ~5 s | **JSON, 24 h hourly series** |

Despite the name, `heat_intelligence` produces an analyst PDF and cannot drive routing.
**`env_params` is the real data source**: 15 hourly parameters including apparent temperature,
relative humidity, wet-bulb temperature, cloud cover, clear-sky GHI/DNI/DHI, elevation and air
quality.

One wrinkle: `env_params` publishes apparent temperature, wet-bulb and RH but no dry-bulb
series, and apparent temperature already folds humidity in - using it directly as air
temperature would double-count that term. Wet-bulb plus RH pins dry-bulb uniquely, so Cryonav
inverts for it (`dry_bulb_from_wet_bulb_f`). That recovers Phoenix's real curve (e.g. 90.2 → 114.1 °F peaking at 16:00 on 2026-08-24).

**Coverage is global.** The Temperature Dashboard®'s onboarding asks for a US state, which
looks like a coverage limit but is not one - it gates *dashboard* access, not the API. All three
tiles calibrate successfully against live data:

| Tile | Live ambient range (2026-08-24) | Peak | Elevation | Timezone |
|---|---|---|---|---|
| Phoenix | 90.2 – 114.1 °F | 16:00 | 332 m | GMT−7 |
| Dubai | 90.7 – 108.4 °F | 11:00 | 1 m | GMT+4 |
| Abu Dhabi | 93.8 – 111.0 °F | 12:00 | 6 m | GMT+4 |

Beyond `env_params`, the integration also **fetches and serves the `/v1/heatmap` raster**
(2,407 observed ~100 m tiles over Phoenix; US-only coverage; shown with its own observation
date and switchable on the map as "FortyGuard raster") and **caches the `/v1/heat_intelligence`
analyst PDF daily per city**, served at `GET /api/v1/cities/{id}/report.pdf` - downloaded
server-side because the upstream presigned link embeds the API key.

With `FORTYGUARD_API_KEY` unset the simulation serves everything - the full stack runs offline
with zero API spend. Readings are a pure function of `(city, lat, lon, hour, calibration-day)`:
exactly reproducible within a day, refreshed by the daily pull. With a key set the live call is attempted and **falls back to the
simulation on any failure, flagged as `degraded` with the real upstream status**; a demo should
not die on conference wifi, but it should never pretend a 401 was a 200.

---

## Quickstart

```bash
git clone <this-repo> && cd Cryonav
./scripts/setup.sh        # python venv + backend deps + npm install
./scripts/dev.sh          # backend :8008 + dashboard :5180
```

Open **http://localhost:5180**. No API key and no Mapbox token required - basemap tiles come from CARTO, thermal data from the built-in simulation.

```bash
cd backend && .venv/bin/pytest -q     # 156 tests
./scripts/smoke_test.sh               # 9 end-to-end API checks
./scripts/verify_fortyguard.sh        # probe the real FortyGuard API (works without a key)
python scripts/calibrate.py           # pull today's real ambient curve for every tile
```

To use the real upstream feed:

```bash
export FORTYGUARD_API_KEY=your_key_here     # optionally FORTYGUARD_BASE_URL
```

Ports are `8008` / `5180` (overridable via `CRYONAV_API_PORT` / `CRYONAV_WEB_PORT`) to avoid the very common `8000` / `5173` collisions.

**Requirements:** Python ≥ 3.9 (3.12 recommended), Node ≥ 18.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Service + FortyGuard feed status |
| `GET` | `/api/v1/meta` | Profiles, risk bands, agent roster, thresholds |
| `GET` | `/api/v1/cities` | Coverage tiles and demo corridors |
| `GET` | `/api/v1/cities/{id}/grid` | Heat grid (`source=model` \| `fortyguard` for the raw observed raster) |
| `GET` | `/api/v1/cities/{id}/layers` | Real OSM heat/canopy features, shelters + provenance |
| `GET` | `/api/v1/cities/{id}/report.pdf` | Cached daily FortyGuard analyst report |
| `POST` | `/api/v1/fortyguard/heat-intelligence` | FortyGuard proxy. The live path calls **`/v1/env_params`**, not `/v1/heat_intelligence` - the latter returns an analyst PDF and cannot drive a reading. Falls back to the calibrated field, labelled degraded. |
| `POST` | `/api/v1/navigate/cool-route` | **Path A vs Path B + full agent trace** |
| `GET` | `/api/v1/shelters/nearby` | Cooling centres, hydration, cooled transit |
| `POST` | `/api/v1/edge/jetson-kiosk` | Bandwidth-optimised edge payload |
| `POST` | `/api/v1/sentinel/monitor` | Live wearable/kiosk telemetry check |

Interactive docs at `http://localhost:8008/docs`.

```bash
curl -X POST localhost:8008/api/v1/navigate/cool-route \
  -H 'content-type: application/json' \
  -d '{"origin":{"lat":33.4485,"lon":-112.0962},
       "destination":{"lat":33.4576,"lon":-112.0705},
       "city_id":"phoenix","hour":15,"profile":"delivery_worker"}'
```

---

## NVIDIA Jetson edge deployment

Smart-city pedestrian kiosks and delivery-worker headsets sit on metered uplinks and small panels. `POST /api/v1/edge/jetson-kiosk` runs the identical routing core but returns a stripped payload: polylines decimated to the panel's usable resolution, per-segment telemetry and the agent trace dropped, and one pre-rendered instruction string so kiosk firmware never does unit conversion.

**Measured 2026-08-24: 2,070 bytes, ~272 ms warm server-side compute** for the full three-agent solve on the 25k-node OSM network. (Contrast: the full dashboard response is ~100 KB.)

```
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  MUNICIPAL EDGE TIER - NVIDIA Jetson Orin Nano (simulated; no TOPS quoted)│
   │                                                                          │
   │   ┌──────────────┐   ┌──────────────┐   ┌───────────────────────────┐   │
   │   │ Pedestrian   │   │ Delivery     │   │ Bus-shelter / crossing    │   │
   │   │ wayfinding   │   │ worker       │   │ signage kiosk             │   │
   │   │ kiosk        │   │ headset      │   │                           │   │
   │   └──────┬───────┘   └──────┬───────┘   └─────────────┬─────────────┘   │
   │          └──────────────────┼─────────────────────────┘                 │
   │                             ▼                                           │
   │              ┌────────────────────────────────┐                         │
   │              │  Cached thermal tile           │  ← offline_capable      │
   │              │  + OSM street graph (25k nodes)│    survives uplink loss │
   │              └───────────────┬────────────────┘                         │
   └──────────────────────────────┼──────────────────────────────────────────┘
                                  │  ~2 KB JSON  ·  ~272 ms
                                  ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  CRYONAV SERVICE TIER (FastAPI)                                          │
   │  Thermal Sensing  →  Cool-Route Optimizer  →  Emergency Sentinel         │
   └──────────────────────────────┬──────────────────────────────────────────┘
                                  ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  FortyGuard Temperature API®  ·  /v1/env_params + /v1/heatmap (daily)    │
   │  canopy 1.19 m · surface 30-70 m · ambient 2 m above ground level        │
   └─────────────────────────────────────────────────────────────────────────┘
```

The Jetson tier is **simulated** in this build - the endpoint, payload shape and telemetry are real and measured, the hardware is not present. `inference_ms` reports genuine server-side compute for the request, not a synthetic benchmark.

---

## Dashboard

Dark-mode glassmorphism UI (`#0B0F17`), built with Vite + React + TypeScript + Tailwind v4 + Leaflet.

- **Top metrics bar** - FortyGuard feed status (live or calibrated, 2 m AGL, latency), current temperature, surface temperature, WBGT, and a risk meter spanning comfort (88 °F) to survival limit (140 °F).
- **Map canvas** - thermal grid painted at one pixel per FortyGuard cell and scaled by the browser for free bilinear interpolation; Path A in rose, Path B in animated cyan, pulsing red markers on asphalt traps, cooling shelters, and an explicit dashed **coverage-tile boundary** so the map never implies data it does not have.
- **Exposure score card** - thermal load, heat stress, shade gain, time cost, A/B breakdown, and the Sentinel's verdict against the continuous-exposure ceiling.
- **1-click cooling-station reroute** - toggles the Sentinel's shelter-waypoint intervention.
- **Agent trace** - the actual step-by-step reasoning, timings included.

Scrub the time-of-day slider to watch the heat field build through the morning, peak at 15:00, and collapse after sunset - and watch the cool route's advantage grow and shrink with it.

---

## Layout

```
backend/
  thermal.py              physics kernel - heat index, WBGT, MRT, risk banding
  fortyguard_service.py   FortyGuard client + deterministic microclimate simulation
  routing_engine.py       street graph, convex thermal weighting, dual-path solver
  agents.py               the three agents + orchestrator + blackboard
  main.py                 FastAPI surface incl. Jetson edge endpoint
  urban.py                real OSM urban form: spatial index + terrain oracle
  tests/                  156 tests
frontend/
  src/components/         MapCanvas, TopMetricsBar, ExposureCard, ControlPanel, AgentTrace
  src/lib/api.ts          typed client + exposure colour ramp
data/                     streets/ urban/ shelters/ calibration/ reports/ (real fetched data)
data/cities.json          tile definitions, climate scenario, presets (terrain/shelter fallback only)
scripts/                  setup.sh · dev.sh · smoke_test.sh · verify_fortyguard.sh
docs/PROJECT_SPEC.md      original build brief
```

Add a city by editing `data/cities.json` - heat corridors, canopy corridors, shelters and demo presets are all data, not code.

---

## Honest limitations

- ~~The street network is synthetic~~ **Routes now run on the real OpenStreetMap pedestrian network** (Phoenix 25k nodes / 34k edges; Dubai and Abu Dhabi similar), fetched by `scripts/fetch_streets.py`, cached in `data/streets/`, largest-connected-component filtered, A*-searched. Map data © OpenStreetMap contributors (ODbL).
- ~~Canopy GIS is hand-authored~~ **Urban thermal form is now real OSM geometry**: 360 park/green polygons, 9,733 individual street trees (8,613 in Phoenix), covered walkways, tree rows, 1,472 surface-parking/industrial polygons and 2,748 lane-counted road ribbons (`scripts/fetch_urban.py`, cached in `data/urban/`). Per-class canopy density and surface-boost coefficients remain modelled - OSM records where a park is, not its leaf density - and are declared in each data file's `assumptions` block.
- ~~Cooling-shelter hours are static fixtures~~ **Phoenix shelters are the official Maricopa Association of Governments Heat Relief Network** (public ArcGIS feed; 27 active 2026 sites in the tile with per-day hours, attribution and MAG's accuracy disclaimer stored alongside). Gulf shelters are real OSM POIs - mosques, malls, cooled Dubai Metro stations, drinking water - with category-default hours/AC where OSM carries no tags (measured coverage: 2–6%), flagged `assumed` per field.
- **The Jetson tier is simulated**, as described above.
- **The upstream FortyGuard *response* schema is still unconfirmed.** The endpoint path, auth header and error envelope are verified against the live API, but auth gates every route so the per-location field names cannot be read without a key. `_reading_from_live` accepts several plausible spellings and `feed.live_fields` reports which ones actually arrived.
- **Observation vs model, per layer:** ambient hourly curves are live FortyGuard for all tiles; Phoenix's spatial 2 m air field additionally comes from the observed `/v1/heatmap` raster (dated on the map; Gulf tiles model it). The radiant/surface layer - what a body absorbs from canopy and asphalt - is Cryonav's physics over real OSM geometry, with per-class coefficients declared in the data files' `assumptions` blocks. Safety thresholds (risk bands, exposure ceilings, hydration) are cited to NIOSH 2016-106 and OSHA, and served with their citations at /api/v1/meta.

---

## Licence

MIT. Built for the FortyGuard Hackathon '26.
FortyGuard and Temperature API are trademarks of their respective owner; this project is an independent integration.
