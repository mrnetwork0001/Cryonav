---
name: cryonav
description: Build, extend, run, or debug Cryonav — the hyperlocal thermal navigation / microclimate cool-routing engine powered by the FortyGuard Temperature API (FortyGuard Hackathon '26). Use whenever work touches this repo's backend (FastAPI agents, routing engine, FortyGuard service), frontend (Vite/React thermal dashboard), edge Jetson kiosk endpoint, or the project spec/roadmap.
---

# Cryonav

Hyperlocal thermal navigation & microclimate cool-routing engine. Full brief: [docs/PROJECT_SPEC.md](../../../docs/PROJECT_SPEC.md).

## What it is

Standard navigation optimizes distance/time. Cryonav optimizes **pedestrian thermal exposure at 2 m above ground**, using FortyGuard Temperature API® 10 mi² microclimate intelligence fused with urban canopy GIS, and returns two routes side by side:

- **Path A — Standard Direct Route**: shortest distance, crosses unshaded asphalt heat traps.
- **Path B — Cryonav Cool Route**: canopy-shaded corridor avoiding heat islands. Measured savings are 0–8.9 °F thermal load / 0–18.7% heat-strain dose / up to −34% time-in-high-risk. The brief's 35–50% claim is NOT met — don't restate it as fact.

## Repo layout

```
backend/     FastAPI service — fortyguard_service.py, thermal.py, routing_engine.py, agents.py, models.py, main.py
frontend/    Vite + React + TS + Tailwind dark dashboard (Leaflet map, canvas thermal grid)
data/        cities.json — Phoenix / Abu Dhabi / Dubai microclimate fixtures (heat islands, canopy, shelters, presets)
scripts/     setup.sh, dev.sh, smoke_test.sh, verify_fortyguard.sh
docs/        PROJECT_SPEC.md
```

## Running it

```bash
./scripts/setup.sh        # venv (python3.12) + pip install + npm install
./scripts/dev.sh          # backend :8008 + frontend :5180 together
./scripts/smoke_test.sh   # 9 end-to-end curl checks against a running backend
cd backend && .venv/bin/pytest -q      # 121 unit + integration tests
```

Backend alone: `cd backend && .venv/bin/uvicorn main:app --reload --port 8008`

Ports are **8008 / 5180**, not 8000 / 5173 — both defaults were already occupied on this machine. Override with `CRYONAV_API_PORT` / `CRYONAV_WEB_PORT`.

## Conventions that matter

- **Python 3.9 compatible syntax** — the system python is 3.9.6. Use `typing.Optional[...]` / `typing.List[...]`, never `X | None`. The venv targets `/opt/homebrew/bin/python3.12`.
- **No network required for a demo.** `FORTYGUARD_API_KEY` unset ⇒ `fortyguard_service.py` serves the deterministic physical mock (diurnal curve + UHI gaussians + canopy cooling + WBGT). Set the key and it proxies `POST /v1/heat_intelligence` live (auth via the `api-key` header), falling back to the mock on failure and flagging it as `degraded`. Never hardcode a key.
- **Determinism**: the mock is seeded by (city, lat, lon, hour) so screenshots and tests reproduce exactly. Don't introduce unseeded randomness.
- **Agents are explicit classes** in `agents.py` (ThermalSensingAgent, CoolRouteOptimizationAgent, EmergencyThermalSentinelAgent) coordinated by `CryonavOrchestrator` over a shared blackboard. Every agent step appends to `trace[]` — the frontend renders that trace live, so keep trace messages short and demo-legible.
- **Routing**: `routing_engine.py` builds a synthetic street graph per city, then runs Dijkstra twice — once on pure distance (Path A) and once on a thermal-weighted cost (Path B). Profile sensitivity (`pedestrian` / `delivery_worker` / `elderly_vulnerable`) scales the thermal penalty.
- **UI palette**: background `#0B0F17`, cool route `#22D3EE`, standard route `#FB7185`/`#F97316`, glassmorphism panels. Keep the dark aesthetic — it's the demo's first impression.
- **Edge endpoint** `/api/v1/edge/jetson-kiosk` must stay lightweight: decimated polyline, no grid payload, `payload_bytes` + inference latency reported for the Jetson story.

## Confirmed FortyGuard API facts

Verified against the live host on day 1 of the hackathon — `./scripts/verify_fortyguard.sh` reproduces all of it:

- **Auth is an `api-key` request header.** `Authorization: Bearer` is silently ignored and returns the same "missing header" 401. Both were wrong in the original code.
- **Path is `/v1/heat_intelligence` — underscore.** The hyphenated guess 404s, and auth is checked *before* routing so the 404 is invisible.
- Other endpoints: `/v1/env_params`, `/v1/heatmap` (useful for the grid overlay), `/v1/satellite`, `/v1/streetview`, `/v1/status/`. Paths came from the docs Angular bundle (`main.*.js`) — the docs site itself is an empty SPA shell that renders nothing without a browser and carries no OpenAPI spec.
- Envelope: `{"error": bool, "status_code": int, "data"|"details": …}`. Failure is in-body, so HTTP 200 + `error: true` must not be read as success.
- `GET /health` needs no key: `1.0.1-beta`, `mode: PROD`.
- **Response field names remain unconfirmed** — auth gates every route. `feed.live_fields` reports which requested metrics actually arrived.
- **Coverage is US-only**, provisioned per state in the dashboard. Dubai and Abu Dhabi tiles are simulation-only.

## Invariants worth not breaking

These were each found by a failing test or a wrong-looking screenshot, not by design:

- **Exposure must peak at 15:00, not after sunset.** RH is derived from a conserved daily dewpoint (`thermal.humidity_from_dewpoint`); scaling RH by a solar factor instead makes the heat index spike in the evening.
- **UHI/canopy solar modulations must stay shallow.** They are offsets riding on the diurnal curve; if their dusk-to-peak swing exceeds the curve's amplitude, air temperature climbs after sunset. Current weights: UHI `0.55 + 0.45*(1-solar)`, canopy `0.65 + 0.35*solar`.
- **The thermal penalty must stay convex** (`surplus ** 2.5`). Linear pricing never justifies a detour and the cool route silently degenerates into the standard route.
- **Path A must never be re-solved through the Sentinel's waypoints** — pass `baseline=` to `solve()`, or the scoreboard compares a detour against itself.
- **`solve()` only accepts a candidate that lowers thermal dose** (unless a stop is mandated). `tests/test_routing_engine.py::TestNoRegressions` enforces that no headline metric ever goes negative across all 27 corridor × profile combinations.
- **The Sentinel's assessment always runs**; only its reroute *action* is gated on `allow_shelter_reroute`. Gating the whole agent leaves the UI with no `safety` block.
- **The live path must fail loudly.** `FeedStatus.degraded` / `upstream_status_code` carry the real upstream status; never report a 401 or a schema mismatch as a green 200. An unrecognised envelope, a record-count mismatch, or a non-JSON body all raise `FortyGuardUpstreamError` so the caller degrades with a reason.
- **Frontend deltas derive their own sign** (`delta()` in `ExposureCard.tsx`). A mandated shelter stop legitimately increases dose, and a hardcoded `−` prefix renders `−−10.9%`.

## Gotchas

- Leaflet is driven directly via `useEffect` (no react-leaflet) to dodge peer-dep churn. Map tiles come from CARTO dark_matter (no token needed); Mapbox is an optional upgrade behind `VITE_MAPBOX_TOKEN`.
- The thermal grid overlay is painted to an offscreen `<canvas>` at one pixel per FortyGuard cell, then handed to Leaflet as an `L.imageOverlay` over the tile bounds. The browser scales it, giving free bilinear interpolation and correct reprojection on pan/zoom with no move handlers. Do not rewrite it as a map-pane canvas — that was tried and is what needs manual reprojection.
- `data/cities.json` is the single source of truth for heat islands, canopy polygons, shelters and demo presets. Add a city there, not in code.
