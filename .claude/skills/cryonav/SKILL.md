---
name: cryonav
description: Build, extend, run, or debug Cryonav - the hyperlocal thermal navigation / microclimate cool-routing engine powered by the FortyGuard Temperature API (FortyGuard Hackathon '26). Use whenever work touches this repo's backend (FastAPI agents, routing engine, FortyGuard service), frontend (Vite/React thermal dashboard), edge Jetson kiosk endpoint, or the project spec/roadmap.
---

# Cryonav

Hyperlocal thermal navigation & microclimate cool-routing engine. Full brief: [docs/PROJECT_SPEC.md](../../../docs/PROJECT_SPEC.md).

## What it is

Standard navigation optimizes distance/time. Cryonav optimizes **pedestrian thermal exposure at 2 m above ground**, fusing the FortyGuard Temperature API® observed ambient series with six measured layers (canopy, Landsat and ECOSTRESS surface temperature, OSM urban form and street network, NIOSH/OSHA thresholds), and returns two routes side by side:

- **Path A - Standard Direct Route**: shortest distance, crosses unshaded asphalt heat traps.
- **Path B - Cryonav Cool Route**: canopy-shaded corridor avoiding heat islands. Ranges DRIFT with the daily calibration, so never quote a remembered figure - run `scripts/bench/corridor_sweep.py`, which prints the current table across all 36 corridor x profile combinations. On 2026-08-27 it gave 0.0-3.4 °F thermal load for routing alone and up to 4.7 °F with a Sentinel refuge. Never restate the brief's 35-50% claim as met.

## Repo layout

```
backend/     FastAPI service - fortyguard_service.py, thermal.py, routing_engine.py, agents.py, urban.py, main.py
frontend/    Vite + React + TS + Tailwind dark dashboard (Leaflet map, canvas thermal grid)
data/        streets/ urban/ shelters/ calibration/ reports/ (real fetched data) + cities.json (tiles, presets, fallback fixtures)
scripts/     setup.sh, dev.sh, smoke_test.sh, verify_fortyguard.sh
docs/        PROJECT_SPEC.md
```

## Running it

```bash
./scripts/setup.sh        # venv (python3.12) + pip install + npm install
./scripts/dev.sh          # backend :8008 + frontend :5180 together
./scripts/smoke_test.sh   # end-to-end curl checks against a running backend
cd backend && .venv/bin/pytest -q      # 162 unit + integration tests
```

Backend alone: `cd backend && .venv/bin/uvicorn main:app --reload --port 8008`

Ports are **8008 / 5180**, not 8000 / 5173 - both defaults were already occupied on this machine. Override with `CRYONAV_API_PORT` / `CRYONAV_WEB_PORT`.

## Conventions that matter

- **Python 3.9 compatible syntax** - keep `typing.Optional[...]` / `typing.List[...]`, never `X | None`, so the tree stays importable on an older system python. The venv and the deployed service both run 3.12.
- **Three data paths, not two.** `FORTYGUARD_API_KEY` unset ⇒ the deterministic physical mock (diurnal curve + UHI gaussians + canopy cooling + WBGT). With a key the DEFAULT is the *calibrated* field: `scripts/calibrate.py` pulls `/v1/env_params` once daily into `data/calibration/` so public traffic never burns quota. `prefer_live=true` calls `/v1/env_params` in-request, capped at four points. `/v1/heat_intelligence` is NOT the live path - it takes ~145 s and returns a PDF. Failures degrade with a reason and are flagged `degraded`. Never hardcode a key.
- **Determinism**: the mock is seeded by (city, lat, lon, hour) so screenshots and tests reproduce exactly. Don't introduce unseeded randomness.
- **Agents are explicit classes** in `agents.py` (ThermalSensingAgent, CoolRouteOptimizationAgent, EmergencyThermalSentinelAgent) coordinated by `CryonavOrchestrator` over a shared blackboard. Every agent step appends to `trace[]` - the frontend renders that trace live, so keep trace messages short and demo-legible.
- **Routing**: `routing_engine.py` loads the real OSM pedestrian network from `data/streets/<city>.json` (fetch anew with `scripts/fetch_streets.py`; synthetic lattice only as fallback when the file is missing), then runs A* twice - once on pure distance (Path A) and once on a thermal-weighted cost (Path B). Profile sensitivity (`pedestrian` / `delivery_worker` / `elderly_vulnerable`) scales the thermal penalty.
- **UI palette**: background `#0B0F17`, cool route `#22D3EE`, standard route `#FB7185`/`#F97316`, glassmorphism panels. Keep the dark aesthetic - it's the demo's first impression.
- **Edge endpoint** `/api/v1/edge/jetson-kiosk` must stay lightweight: decimated polyline, no grid payload, `payload_bytes` + inference latency reported for the Jetson story.

## Confirmed FortyGuard API facts

Verified against the live host on day 1 of the hackathon - `./scripts/verify_fortyguard.sh` reproduces all of it:

- **Auth is an `api-key` request header.** `Authorization: Bearer` is silently ignored and returns the same "missing header" 401. Both were wrong in the original code.
- **Path is `/v1/heat_intelligence` - underscore.** The hyphenated guess 404s, and auth is checked *before* routing so the 404 is invisible.
- Other endpoints: `/v1/env_params`, `/v1/heatmap` (useful for the grid overlay), `/v1/satellite`, `/v1/streetview`, `/v1/status/`. Paths came from the docs Angular bundle (`main.*.js`) - the docs site itself is an empty SPA shell that renders nothing without a browser and carries no OpenAPI spec.
- Envelope: `{"error": bool, "status_code": int, "data"|"details": …}`. Failure is in-body, so HTTP 200 + `error: true` must not be read as success.
- `GET /health` needs no key: `1.0.1-beta`, `mode: PROD`.
- **Response schema is confirmed** and parsed by `_parse_env_series` - 24 hourly values across 15 parameters, all Celsius. `feed.live_fields` still reports which requested metrics actually arrived.
- **Coverage is global.** The dashboard's "U.S. states only" onboarding gates dashboard access, NOT API coverage - Phoenix, Dubai, Abu Dhabi and San Jose all calibrate live. The one genuinely US-only surface is the `/v1/heatmap` raster.
- **Enterprise endpoints are ASYNC**: POST returns `activity_id`, then `GET /v1/status/{activity_id}` (path param - a query param 400s) until status is `Completed`.
- **`/v1/heat_intelligence` returns a PDF**, not data, and takes ~145 s. Despite the name it cannot drive routing. Body: `latitude`, `longitude`, `temperature`, `date` (string), `analysis` (list of `geographic`/`environmental`/`urban`/`events`/`anthropogenic`).
- **`/v1/heatmap` raster**: fetched+cached by calibrate.py (US-only - Gulf AOIs return empty; Phoenix ~2,407 tiles), integrated as the observed 2 m air anomaly (its presence DISABLES the synthetic UHI/canopy air offsets), and can be days older than the ambient calibration when its fetch fails - the raster carries its own date; surface it wherever quoted.
- **`/v1/env_params` is the real data source** (~5 s, JSON, 24 hourly values × 15 parameters). Body: `latitude`, `longitude`, `temperature`, `date_time{start_date, filter_type: 1|2|3|4}`. Only `filter_type: 3` works reliably; 1/2/4 500 without an end date.
- It has **no dry-bulb series** - invert wet-bulb + RH via `dry_bulb_from_wet_bulb_f`. Never use `apparent_temperature_celsius` as air temperature; it already contains the humidity term.
- Everything is **Celsius**; `heat_index_celsius` just echoes the `temperature` you sent, so ignore it.
- `python scripts/calibrate.py` caches ambient curves to `data/calibration/<city>.json`, loaded on startup.

## Invariants worth not breaking

These were each found by a failing test or a wrong-looking screenshot, not by design:

- **Exposure must peak at 15:00, not after sunset.** RH is derived from a conserved daily dewpoint (`thermal.humidity_from_dewpoint`); scaling RH by a solar factor instead makes the heat index spike in the evening.
- **UHI/canopy solar modulations must stay shallow.** They are offsets riding on the diurnal curve; if their dusk-to-peak swing exceeds the curve's amplitude, air temperature climbs after sunset. Current weights: UHI `0.55 + 0.45*(1-solar)`, canopy `0.65 + 0.35*solar`.
- **The thermal penalty must stay convex** (`surplus ** 2.5`). Linear pricing never justifies a detour and the cool route silently degenerates into the standard route.
- **Path A must never be re-solved through the Sentinel's waypoints** - pass `baseline=` to `solve()`, or the scoreboard compares a detour against itself.
- **`solve()` only accepts a candidate that lowers thermal dose** (unless a stop is mandated). `tests/test_routing_engine.py::TestNoRegressions` enforces that no headline metric goes negative across the corridor x profile matrix *without* the Sentinel. WITH a mandated refuge, dose and time legitimately go negative - that trade breaks the longest unbroken high-risk leg, and a separate test pins it.
- **The Sentinel's assessment always runs**; only its reroute *action* is gated on `allow_shelter_reroute`. Gating the whole agent leaves the UI with no `safety` block.
- **The live path must fail loudly.** `FeedStatus.degraded` / `upstream_status_code` carry the real upstream status; never report a 401 or a schema mismatch as a green 200. An unrecognised envelope, a record-count mismatch, or a non-JSON body all raise `FortyGuardUpstreamError` so the caller degrades with a reason.
- **Frontend deltas derive their own sign** (`delta()` in `ExposureCard.tsx`). A mandated shelter stop legitimately increases dose, and a hardcoded `−` prefix renders `−−10.9%`.

## Frontend layout

- **`/` is the marketing landing** (`src/pages/Landing.tsx`), **`/app` is the dashboard** - a pathname switch in `main.tsx`, no router dependency. The landing's product card runs a REAL cool-route solve on mount and renders whatever the agents did (falls back to last measured values, marked OFFLINE, when the backend is down). Keep it honest: never hardcode impressive numbers there.
- Landing style: an operations-console idiom - hairline-ruled cells (`.cell`, `.cell-grid`), `.eyebrow`, `.statement`, `.horizon`, `.cta-band`, near-black `#05070b`. The risk palette (cyan -> amber -> red) is SEMANTIC and must never be reused as chrome.

## Real-data pipeline (all fixtures replaced)

- `scripts/fetch_urban.py` → `data/urban/<city>.json`: real OSM parks, street trees (palms down-weighted), covered ways, tree rows, water, surface parking (AUH: exclude only underground/multi-storey - 98% of lots carry no subtag), industrial/retail land, primary/secondary road ribbons with real lane counts. Consumed by `backend/urban.py::UrbanIndex` (spatial hash, O(1) terrain queries); `terrain()` prefers it, hand-authored `cities.json` zones are fallback only.
- `scripts/fetch_shelters.py` → `data/shelters/<city>.json`: Phoenix = official MAG Heat Relief Network ArcGIS (`HRN_Public_view/FeatureServer/0`, filter `Year=2026 AND Active='Yes'`); Gulf = OSM mosques/malls/metro/drinking-water with category defaults flagged `assumed`. `service.shelters()` uses these when present; `shelter_source()` reports provenance.
- Overpass etiquette: ALWAYS send the Cryonav User-Agent (406 without it); overpass-api.de rate-limits after ~3 rapid queries - maps.mail.ru mirror is the reliable fallback; space queries ≥8s.
- `out tags` omits node coordinates - trees need `out body`.
- Startup: stale calibration auto-refreshes in a background thread; graphs pre-warm (first real-terrain build ~5.5s/city, then 0.3s per hour bucket via the per-edge terrain cache).
- The assumptions that remain (canopy % per green class, °F boost per hot class, category AC/hours) live in each data file's `assumptions` block - keep them there, not in code comments.

## Mobile layout

- **Dashboard (<lg)**: natural page scroll (root `min-h-full`, `lg:h-full`); map first at `h-[58vh]`; the ControlPanel renders ONLY in a slide-in drawer opened by the hamburger in TopMetricsBar (`onMenu`); the inline left column is `hidden lg:block`. Drawer actions that hand focus to the map (preset, pick, solve) auto-close it. Never reintroduce base-breakpoint `min-h-0 overflow-y-auto` on the columns - that collapses them to 8px slivers on phones (measured).
- **Landing**: `#edge` grid needs `minmax(0,1fr)` columns + `min-w-0` children or the JSON `<pre>`'s min-content width forces a 530px page on a 390px phone. Phone header uses a hamburger dropdown (AGENTS/LIVE API/EDGE/DASHBOARD/SOURCE).
- Leaflet gets `map.invalidateSize()` via ResizeObserver in MapCanvas - required because the wrapper height is breakpoint-dependent.
- Touch targets: base paddings are `py-2.5`, compacted with `lg:py-1.5`; Leaflet zoom buttons upsized under `@media (pointer: coarse)`.

## Gotchas

- Leaflet is driven directly via `useEffect` (no react-leaflet) to dodge peer-dep churn. **Basemaps are Esri ArcGIS Online, NOT CARTO.** CARTO now stamps "API KEY REQUIRED" across every keyless tile while still returning HTTP 200, so it fails invisibly - the map filled with watermarks and nothing errored. Dark Gray Canvas needs both its Base and Reference layers or street labels vanish.
- The thermal grid overlay is painted to an offscreen `<canvas>` at one pixel per FortyGuard cell, then handed to Leaflet as an `L.imageOverlay` over the tile bounds. The browser scales it, giving free bilinear interpolation and correct reprojection on pan/zoom with no move handlers. Do not rewrite it as a map-pane canvas - that was tried and is what needs manual reprojection.
- `data/cities.json` is the single source of truth for heat islands, canopy polygons, shelters and demo presets. Add a city there, not in code.
