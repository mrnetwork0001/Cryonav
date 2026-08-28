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

At 15:00 in downtown Phoenix, two points a kilometre apart sit **more than 20 °F apart in the heat a body actually absorbs**, while the weather report puts them within a fifth of a degree of each other - and every navigation app on the planet will route you through the hotter one, because they optimise metres and minutes.

Here is what Cryonav measures at two Phoenix locations, at the same moment:

| | Van Buren St x 7th Ave | Virginia G. Piper Plaza |
|---|---|---|
| Measured canopy | 0.0 % | **79.2 %** |
| Air temperature @ 2 m | 112.6 °F | 112.8 °F |
| Surface temperature | **153.5 °F** | 123.9 °F |
| Mean radiant temperature | **139.2 °F** | 116.4 °F |
| **Exposure index (thermal load)** | **118.5 °F** | **111.3 °F** |
| Risk band | EXTREME | HIGH |

The air layer separates them by **0.2 °F**, and separates them the *wrong way* -
the shaded plaza reads marginally hotter. That is the whole point. The observed
2 m air layer is well mixed and cannot tell these places apart; the **22.8 °F
mean-radiant difference** streaming off the asphalt can, and that is where heat illness
actually comes from. A weather API sees two identical spots. A body does not.

Those figures are a reading, not a constant. They were sampled at 15:00 on 2026-08-27 and
they move with the weather; `/api/v1/facts` recomputes them on every request, and it - not
this table - is the source of truth.

*(Reproduce: `curl -s https://cryonav.xyz/api/v1/facts | python3 -m json.tool`)*

Cryonav fuses the **FortyGuard Temperature API®** (observed hourly series at 2 m above ground level) with measured urban canopy and surface temperature, and routes around it. The "10 mi²" figure this line used to quote was Cryonav's own invention: `/v1/env_params` is a point query with no resolution parameter at all.

---

## What it does

Given an origin, a destination and a user profile, Cryonav returns **two routes**:

- **Path A - Standard Direct Route.** Minimises distance. Exactly what a conventional navigator returns, computed the same way, so the comparison is honest rather than a strawman.
- **Path B - Cryonav Cool Route.** Minimises *thermal dose* - minutes in the sun weighted by how punishing that sun is - subject to a per-profile detour budget.

Measured across all twelve demo corridors x three profiles - 36 combinations, 15:00 local,
2026-08-27 calibration. Regenerate any time with
[`scripts/bench/corridor_sweep.py`](scripts/bench/corridor_sweep.py), which drives the
deployed API and prints this table; these shift with each day's live data.

**Thermal routing alone** (`--no-shelter`) - what the Cool Route agent achieves on its own:

| Metric | Range across demo corridors |
|---|---|
| Thermal load reduction | **0.0 – 3.4 °F** |
| Heat-stress reduction | **0.0 – 11.4 %** |
| Heat-strain dose reduction | **0.0 – 10.1 %** |
| Shade coverage gained | **−0.2 – +35.0 %** |
| Added walking time | **−1.1 to +2.6 min** |

Nothing here is negative on load, stress or dose, and that is a guarantee rather than luck:
when no admissible route beats the direct path, Cryonav returns the direct path. Ten of the 36
combinations do exactly that.

**With the Sentinel's shelter reroute on** - the mode the dashboard defaults to:

| Metric | Range across demo corridors |
|---|---|
| Thermal load reduction | **−0.5 – 4.7 °F** |
| Heat-stress reduction | **−1.3 – 12.7 %** |
| Heat-strain dose reduction | **−30.8 – 6.4 %** |
| Shade coverage gained | **−0.8 – +35.0 %** |
| Added walking time | **−0.1 to +47.9 min** |

The negatives are the point, not a regression. A mandated stop inside an air-conditioned refuge
raises total dose and total minutes while breaking the longest *unbroken* high-risk leg, and
continuous exposure is what causes heat illness. The 47.9-minute case is Safa Park → Burj Park
for an elderly walker in a Dubai afternoon, where the nearest refuge is genuinely far - Cryonav
offers it and says what it costs, rather than hiding the trade.

*(Real OpenStreetMap pedestrian network, real OSM urban form, live FortyGuard ambient data.)*

> **On the numbers.** The brief's headline claim is a 35–50 % exposure reduction. Cryonav does not reach it on its headline metrics, and does not round up to it: on 2026-08-27 the defensible figures are **up to 3.4 °F** of mean thermal load and **up to 11.4 %** of heat stress from thermal routing alone, rising to **4.7 °F** when the Sentinel may insert a refuge. (These are measured against *live* FortyGuard ambient data, which is flatter through the afternoon than the earlier synthetic curve - so the honest numbers came down when real data arrived, and they move again with every day's calibration. Re-run the sweep rather than trusting this paragraph.)
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

## The six measured layers

Nothing in the terrain model is inferred from an OpenStreetMap tag. Every layer is fetched by
a script in `scripts/` and written into the committed city files, with its source, resolution,
licence and measurement time recorded alongside the values and served at `/api/v1/meta`.

| Layer | Source | Resolution | Licence |
|---|---|---|---|
| Ambient temperature | FortyGuard `/v1/env_params` | point query, 24 h hourly | commercial API |
| Canopy | Meta / WRI Canopy Height Maps v6 | **1.194 m** | CC-BY-4.0 |
| Surface temperature | USGS/NASA Landsat C2 L2 `ST_B10` | 30 m | public domain |
| Peak-hour surface | NASA ECOSTRESS `ECO_L2T_LSTE` v003 | 70 m | NASA open data |
| Street network, urban form, shelters | OpenStreetMap | vector | ODbL |
| Safety thresholds | NIOSH 2016-106 / OSHA | published tables | public |

**Why canopy had to be measured.** The router's entire claim is that it can find you shade, and
that rested on a lookup table saying "park = 60% canopy" for every park on earth. Measurement
puts the 39 Phoenix parks at a mean of **15.6%**. Coffelt-Lamoreaux Park is the
cautionary one: it straddled the edge of the raster window, kept the 60% default, and so ranked
as the second-shadiest polygon in the tile. Measured, it is **1.7%** - a
bare lawn, and one the router would have offered as shade. The window is now padded past the
city bbox, every polygon in every city is measured, and `urban.py` refuses to let an unmeasured
canopy influence a route at all.

**Why two surface-temperature sources.** Landsat crosses at about 10:00 local; Cryonav's design
hour is 15:00. Asphalt and concrete have different thermal inertia, so the morning ranking of
surfaces is not the afternoon ranking - only correlated with it. ECOSTRESS flies on the ISS,
whose precessing orbit makes it the only thermal instrument sampling the same ground across the
whole day, and it covers the 13:00-17:00 window Landsat structurally never sees. Measured
against the road median, commercial and parking surfaces sit ~11 °F below roads at the Landsat
overpass and only ~1.7 °F below by mid-afternoon. That lag is why the second source was worth
the trouble.

Anomalies are referenced to each city's **own road-network median** rather than to an absolute
temperature, because the sampler's formula already describes a generic sunlit road; anything
else would double-count. Negative anomalies are clamped away, since a road measuring cooler
than the median is a shaded road, and sky-view-factor already applies that shade.

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

## Acting on the world

Two parts of Cryonav do something rather than describe something, and both were built to be
real or not shipped at all.

### Emergency dispatch

When the Sentinel sees immobility in extreme heat - no meaningful movement in eight minutes
while the air is at or above 110 °F - it sends an actual push notification to a
user-nominated contact, carrying position, GPS accuracy, the current readings and the nearest
air-conditioned refuge with its walking distance. Measured delivery from the deployed server:
**116 ms**.

It does **not** claim to call emergency services. No public API lets a civilian application
file an emergency call, and vendors say so explicitly - Twilio, verbatim: *"You should not rely
on Twilio Programmable SMS if you require delivery of SMS communications to emergency services
such as 911 or E911."* Notifying a nominated contact is the legitimate, implementable version.

Transport is [ntfy](https://ntfy.sh): open-source, no account, no per-message cost, and
self-hostable, so a municipality could run its own rather than depend on a third party. With
`CRYONAV_NTFY_TOPIC` unset the Sentinel still detects immobility and the API states plainly
that nothing was sent, rather than implying an alert went out.

### Live GPS telemetry

The dashboard's Sentinel panel can read the device's own GPS through `watchPosition`, feeding
real fixes to the same endpoint a wearable would call.

Consumer GPS degrades badly between tall buildings - exactly where a heat casualty is most
likely to be - so displacement is estimated by **median-of-thirds** rather than by comparing
the first fix to the last. The window is split into three equal-time thirds, each reduced to a
component-wise median, and displacement is the largest separation among those anchors.

Monte Carlo over 20,000 motionless walkers, 8-minute window at 1 Hz, 25 m threshold
(`scripts/bench/displacement_montecarlo.mjs`, which imports the shipped estimator):

| GPS accuracy | naive first-vs-last | median-of-thirds |
|---|---|---|
| 10 m | misses **22.0 %** of collapses | misses 0.0 % |
| 20 m | misses **69.1 %** | misses 0.0 % |
| 40 m | misses **91.2 %** | misses 0.0 % |

A low miss-rate is worthless if bought by never reporting movement, so the control matters:
false-immobility is 0.0 % at a normal walk and at a slow shuffle, at both 10 m and 40 m
accuracy. Live GPS needs HTTPS, since browsers gate the Geolocation API on a secure context.

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

**Measured 2026-08-27 against the deployed server: 2,379 bytes, ~1.0 s warm server-side compute** for the full three-agent solve on the 25k-node OSM network. (Contrast: the full dashboard response for the same corridor is 102,733 bytes - the edge payload is 1/43rd of it.) The compute figure is the median round-trip to `/api/v1/edge/jetson-kiosk` (1.66 s) minus the median round-trip to `/api/v1/health` (0.63 s), which does no routing - so it excludes the network path rather than pretending there is none. An earlier revision quoted 272 ms; that was measured on a laptop, not on the shared VPS that actually serves it.

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

Everything that was hand-authored at the start has since been replaced by measurement:
the street network, the urban thermal form, the canopy, the surface temperature and the
cooling shelters are all fetched from named sources and cached in `data/`. What follows is
what is *still* true, and most of it was found by auditing the running system rather than
by reading the code.

**793 fields are still assumed, and they are counted.** OpenStreetMap records that a
building is a mall; it does not record whether the mall is air-conditioned or how cold it
is kept. Where a tag is absent the fetcher writes a category default and flags the field
`ac_assumed` or `indoor_temp_assumed` instead of inventing a value silently. `/api/v1/facts`
reports the running total. It used to report zero - not because there were none, but because
the counter read only the urban assumption blocks, which had been emptied when canopy and
surface became measured, while 793 shelter fields sat flagged in the same repo. A declared,
counted assumption is honest; a zero that skips them is not.

**Per-class canopy and surface coefficients are modelled.** The 1.194 m canopy raster gives
real cover fraction per polygon, but how much a given cover fraction cuts mean radiant
temperature is a coefficient, declared in each data file's `assumptions` block. A park whose
canopy could not be measured is now refused as shade outright rather than falling back to a
default - which is how an audit found Coffelt-Lamoreaux Park, a 1.7 %-canopy lawn ranked
second-shadiest of 99 Phoenix green polygons because it straddled the raster window edge and
kept the 60 % class default.

**The Sentinel can raise mean exposure, and this is deliberate.** One live Dubai route
returns a saving of -0.2 °F: the Sentinel mandates a cooling stop at a real OSM mosque, which
lifts mean exposure slightly while cutting the longest *unbroken* high-risk leg from 49.1 to
33.3 minutes. Continuous exposure is what causes heat illness, not average exposure. Two tests
pin both halves - no preset produces a negative saving without the Sentinel, and whenever the
Sentinel does intervene it provably shortens the unbroken leg. Without the second test,
"the Sentinel may raise mean exposure" would excuse any regression.

**Live upstream calls are off by default.** `/v1/env_params` is asynchronous - a POST returns
an `activity_id` and the result is collected from `/v1/status/{id}` - and measured round-trip
went from 22 s to over 120 s during development. Routes therefore serve from the daily
calibration by default, which is real observation, just fetched on a schedule rather than in
the request. `prefer_live=true` still makes the call, capped at four points, and the response
says which path served it.

**Two of six layers do not cover the Gulf.** The FortyGuard `/v1/heatmap` raster and the
Landsat/ECOSTRESS surface products vary in coverage; Phoenix and San Jose carry the observed
raster, Dubai and Abu Dhabi model that layer. The response declares which per tile rather
than presenting them as equivalent.

**ECOSTRESS passes are rejected by physics, not by a cloud mask.** A pass whose scene minimum
falls below the city's calibrated minimum air temperature is reading cloud-top, not ground, so
it is discarded. This is a floor test, not a per-pixel mask: a partly-clouded scene whose
minimum still sits above the floor is accepted whole.

**The Jetson tier is simulated.** The edge payload, its size and its solve are real and measured
on the deployed VPS; the hardware is not present, and the README quotes no TOPS figure for a
board nobody here has run.

**`tests` counts test functions, not passing ones.** The label says "tests in the suite" for
that reason. The suite runs in CI; the counter reads the source.

**The suite no longer asserts against the weather.** Two tests once compared absolute degrees
to the calibrated field and failed the day Phoenix's observed peak moved 15:00 → 16:00.
Nothing had regressed. Assertions about the model now run against the modelled field, and a
paired test checks the converse - that calibration genuinely changes the reading - because if
it did not, it would not be worth fetching.

---

## Licence

Cryonav's source is **MIT** - see [LICENSE](LICENSE). Built for the FortyGuard Hackathon '26.

The MIT grant covers the code, not the datasets cached under `data/`, which keep their own
terms and attribution obligations: OpenStreetMap is **ODbL** (share-alike, attributed on every
map view), the Meta/WRI canopy raster is **CC-BY-4.0**, Landsat is public domain, ECOSTRESS is
NASA open data, and the Phoenix shelters come from MAG's public feed with their accuracy
disclaimer preserved. Each data file names its own licence in a `license` field, and
[LICENSE](LICENSE) sets out what each one requires of a redistributor.

No FortyGuard data or credential is redistributed here: the API key lives only in an untracked
`.env`, and calibration outputs are regenerated with the consumer's own key. FortyGuard and
Temperature API are trademarks of their respective owner; this project is an independent
integration and is not endorsed by or affiliated with FortyGuard.
