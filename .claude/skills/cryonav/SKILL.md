---
name: cryonav
description: Build, extend, run, or debug Cryonav — the hyperlocal thermal navigation / microclimate cool-routing engine powered by the FortyGuard Temperature API (FortyGuard Hackathon '26). Use whenever work touches this repo's backend (FastAPI agents, routing engine, FortyGuard service), frontend (Vite/React thermal dashboard), edge Jetson kiosk endpoint, or the project spec/roadmap.
---

# Cryonav

Hyperlocal thermal navigation & microclimate cool-routing engine. Full brief: [docs/PROJECT_SPEC.md](../../../docs/PROJECT_SPEC.md).

## What it is

Standard navigation optimizes distance/time. Cryonav optimizes **pedestrian thermal exposure at 2 m above ground**, using FortyGuard Temperature API® 10 mi² microclimate intelligence fused with urban canopy GIS, and returns two routes side by side:

- **Path A — Standard Direct Route**: shortest distance, crosses unshaded asphalt heat traps.
- **Path B — Cryonav Cool Route**: canopy-shaded corridor avoiding heat islands, 35–50% lower heat-stress score for a small time penalty.

## Repo layout

```
backend/     FastAPI service — fortyguard_service.py, thermal.py, routing_engine.py, agents.py, models.py, main.py
frontend/    Vite + React + TS + Tailwind dark dashboard (Leaflet map, canvas thermal grid)
data/        cities.json — Phoenix / Abu Dhabi / Dubai microclimate fixtures (heat islands, canopy, shelters, presets)
scripts/     setup.sh, dev.sh, smoke_test.sh
docs/        PROJECT_SPEC.md
```

## Running it

```bash
./scripts/setup.sh        # venv (python3.12) + pip install + npm install
./scripts/dev.sh          # backend :8008 + frontend :5180 together
./scripts/smoke_test.sh   # 9 end-to-end curl checks against a running backend
cd backend && .venv/bin/pytest -q      # 110 unit + integration tests
```

Backend alone: `cd backend && .venv/bin/uvicorn main:app --reload --port 8008`

Ports are **8008 / 5180**, not 8000 / 5173 — both defaults were already occupied on this machine. Override with `CRYONAV_API_PORT` / `CRYONAV_WEB_PORT`.

## Conventions that matter

- **Python 3.9 compatible syntax** — the system python is 3.9.6. Use `typing.Optional[...]` / `typing.List[...]`, never `X | None`. The venv targets `/opt/homebrew/bin/python3.12`.
- **No network required for a demo.** `FORTYGUARD_API_KEY` unset ⇒ `fortyguard_service.py` serves the deterministic physical mock (diurnal curve + UHI gaussians + canopy cooling + WBGT). Set the key and it proxies `POST /v1/heat-intelligence` live, with automatic fallback to mock on failure. Never hardcode a key.
- **Determinism**: the mock is seeded by (city, lat, lon, hour) so screenshots and tests reproduce exactly. Don't introduce unseeded randomness.
- **Agents are explicit classes** in `agents.py` (ThermalSensingAgent, CoolRouteOptimizationAgent, EmergencyThermalSentinelAgent) coordinated by `CryonavOrchestrator` over a shared blackboard. Every agent step appends to `trace[]` — the frontend renders that trace live, so keep trace messages short and demo-legible.
- **Routing**: `routing_engine.py` builds a synthetic street graph per city, then runs Dijkstra twice — once on pure distance (Path A) and once on a thermal-weighted cost (Path B). Profile sensitivity (`pedestrian` / `delivery_worker` / `elderly_vulnerable`) scales the thermal penalty.
- **UI palette**: background `#0B0F17`, cool route `#22D3EE`, standard route `#FB7185`/`#F97316`, glassmorphism panels. Keep the dark aesthetic — it's the demo's first impression.
- **Edge endpoint** `/api/v1/edge/jetson-kiosk` must stay lightweight: decimated polyline, no grid payload, `payload_bytes` + inference latency reported for the Jetson story.

## Invariants worth not breaking

These were each found by a failing test or a wrong-looking screenshot, not by design:

- **Exposure must peak at 15:00, not after sunset.** RH is derived from a conserved daily dewpoint (`thermal.humidity_from_dewpoint`); scaling RH by a solar factor instead makes the heat index spike in the evening.
- **UHI/canopy solar modulations must stay shallow.** They are offsets riding on the diurnal curve; if their dusk-to-peak swing exceeds the curve's amplitude, air temperature climbs after sunset. Current weights: UHI `0.55 + 0.45*(1-solar)`, canopy `0.65 + 0.35*solar`.
- **The thermal penalty must stay convex** (`surplus ** 2.5`). Linear pricing never justifies a detour and the cool route silently degenerates into the standard route.
- **Path A must never be re-solved through the Sentinel's waypoints** — pass `baseline=` to `solve()`, or the scoreboard compares a detour against itself.
- **`solve()` only accepts a candidate that lowers thermal dose** (unless a stop is mandated). `tests/test_routing_engine.py::TestNoRegressions` enforces that no headline metric ever goes negative across all 27 corridor × profile combinations.
- **The Sentinel's assessment always runs**; only its reroute *action* is gated on `allow_shelter_reroute`. Gating the whole agent leaves the UI with no `safety` block.
- **Frontend deltas derive their own sign** (`delta()` in `ExposureCard.tsx`). A mandated shelter stop legitimately increases dose, and a hardcoded `−` prefix renders `−−10.9%`.

## Gotchas

- Leaflet is driven directly via `useEffect` (no react-leaflet) to dodge peer-dep churn. Map tiles come from CARTO dark_matter (no token needed); Mapbox is an optional upgrade behind `VITE_MAPBOX_TOKEN`.
- The thermal grid overlay is a `<canvas>` painted in map-pane pixel space — recompute on `move`/`zoom`, not on React state alone.
- `data/cities.json` is the single source of truth for heat islands, canopy polygons, shelters and demo presets. Add a city there, not in code.
