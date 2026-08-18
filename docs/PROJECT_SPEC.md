# Cryonav — Master Project Specification

> Persisted verbatim from the original build brief so the plan survives context resets.
> Companion skill: `.claude/skills/cryonav/SKILL.md` (build conventions + resume instructions).

---

## TASK: Build "Cryonav" — Hyperlocal Thermal Navigation & Microclimate Cool-Routing Engine powered by FortyGuard Temperature API®

### ABOUT THE PROJECT

"Cryonav" is an open-source, Agentic AI-powered thermal navigation and urban climate safety platform built for the FortyGuard Hackathon '26 ("Building the World's Temperature AI").

During extreme heat events (e.g., Phoenix at 112°F, Abu Dhabi/Dubai at 115°F), standard navigation applications (Google Maps, Apple Maps) only optimize for shortest distance or driving speed — completely ignoring asphalt thermal traps 2 meters above ground. Cryonav leverages FortyGuard's Temperature API® to stream 10 mi² hyperlocal heat intelligence, fused with urban canopy GIS data, to compute "Cool Routes" that reduce pedestrian heat exposure by 35–50% with minimal added transit time.

---

### CORE TECHNICAL STACK

1. **Temperature Intelligence Layer:** FortyGuard Temperature API® (`POST /v1/heat-intelligence`, 2m above ground, 10 mi² microclimate resolution). Includes a mock/simulation service for development and testing.
2. **Backend API & Agentic Engine:** Python (FastAPI) with an Agentic AI orchestration framework (custom multi-agent routing loop).
3. **Frontend Dashboard:** Vite + React (TypeScript) with Tailwind CSS, custom dark-mode styling, and interactive 2D map rendering (Leaflet + canvas thermal grid).
4. **Edge AI / Kiosk Module:** Simulated NVIDIA Jetson AI Developer Kit edge-API endpoint for smart city pedestrian kiosks and delivery worker wearable headsets.

---

### CRYONAV AGENTIC ARCHITECTURE

Three specialized AI agents working in harmony:

1. **Thermal Sensing Agent**
   - Polls FortyGuard Temperature API® live data feeds for target coordinates.
   - Categorizes microclimate risk vectors (`low`, `moderate`, `high`, `extreme`) and tracks asphalt thermal radiation spikes.

2. **Cool-Route Optimization Agent**
   - Takes origin, destination, and user profile (Pedestrian, Outdoor Delivery Worker, Elderly/Vulnerable).
   - Generates dual routes:
     - **Path A (Standard Direct Route):** shortest distance, passes through unshaded high-temperature asphalt corridors.
     - **Path B (Cryonav Cool Route):** shaded, tree-canopy microclimate path avoiding heat islands, reducing thermal stress score by up to 50%.

3. **Emergency Thermal Sentinel Agent**
   - Monitors user transit duration in extreme heat zones (>110°F).
   - Triggers dynamic re-routing to air-conditioned public cooling shelters, hydration stations, or emergency contact dispatch if immobility is detected.

---

### CORE API ENDPOINTS

- `POST /api/v1/fortyguard/heat-intelligence` — FortyGuard API proxy & mock generator.
- `POST /api/v1/navigate/cool-route` — origin/destination → Standard Route vs Cryonav Cool Route + thermal exposure score metrics.
- `GET  /api/v1/shelters/nearby` — nearest municipal air-conditioned cooling centers & water stations.
- `POST /api/v1/edge/jetson-kiosk` — optimized lightweight JSON endpoint for NVIDIA Jetson edge devices.

---

### FRONTEND DASHBOARD & MAP UI REQUIREMENTS

Sleek futuristic dark-mode UI (`#0B0F17` background, cyan/teal cool route paths, pulsing red heat hazard overlays):

1. **Top Metrics Bar** — FortyGuard live feed status (`200 OK`, `10 mi² resolution`, `2m ground elevation`); current temperature & local risk level meter (`112°F - EXTREME HEAT RISK`).
2. **Interactive Map Canvas**
   - Heatmap overlay layer: FortyGuard thermal grid rendered over urban blocks.
   - Route comparison visualizer: standard route (red/orange), Cryonav cool route (cyan/teal) with canopy shade coverage, cooling waypoints, °F savings.
3. **Thermal Safety & Exposure Score Card** — body heat exposure reduction (`-8.4°F thermal load`, `-42% heat stress`).
4. **1-Click Emergency Cooling Station Reroute** — instantly append nearest cooling shelter to the route.

---

### EXECUTION PLAN

| Phase | Scope |
|-------|-------|
| **1** | Monorepo structure (`/backend`, `/frontend`, `/data`, `/scripts`) + `fortyguard_service.py` (live + mock thermal grid for Phoenix / Abu Dhabi / Dubai). |
| **2** | `routing_engine.py` — distance vs thermal weight matrix on road network nodes + 3-agent orchestration. |
| **3** | `main.py` REST endpoints + simulated NVIDIA Jetson hardware optimization layer. |
| **4** | React frontend — dark glassmorphism UI, heatmap toggles, side-by-side route rendering, wired to FastAPI. |
| **5** | End-to-end verification tests + hackathon-ready `README.md` (ASCII logo, problem statement, FortyGuard integration explainer, Jetson edge architecture diagram, quickstart). |
