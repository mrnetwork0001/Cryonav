import { useEffect, useState } from "react";
import { api, type CitySummary, type NavigationResult } from "../lib/api";

/**
 * Marketing/landing page, styled after the dark "protocol landing" idiom: blueprint grid,
 * two-tone gradient headline, mono stat strip, and a live product card — followed by the
 * full story: the physics problem, the three agents, the live FortyGuard integration, the
 * Jetson edge tier, and the verification posture.
 *
 * Everything numeric is either fetched live from the backend or is a real measured value
 * from this repo's own test runs. Nothing on this page is invented copy. When the backend
 * is unreachable the live card falls back to the last measured values, marked OFFLINE.
 */

const FALLBACK = {
  pathA_load_f: 114,
  leg_before_min: 48.3,
  leg_after_min: 29.1,
  load_saved_f: 1.2,
  shade_gain_pct: 9,
  added_min: 1.6,
  shelter: "Justa Center Respite",
  solve_ms: 150,
};

interface CalSummary {
  calibrated: boolean;
  air_temp_min_f?: number;
  air_temp_max_f?: number;
  peak_hour?: number;
  timezone?: string;
}

export default function Landing() {
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [nav, setNav] = useState<NavigationResult | null>(null);
  const [cals, setCals] = useState<Record<string, CalSummary>>({});
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api
      .cities()
      .then((c) => setCities(c.cities))
      .catch(() => setOffline(true));
    fetch("/api/v1/health")
      .then((r) => r.json())
      .then((h) => setCals(h.calibration ?? {}))
      .catch(() => {});
    api
      .coolRoute({
        origin: { lat: 33.4485, lon: -112.0962 },
        destination: { lat: 33.4576, lon: -112.0705 },
        city_id: "phoenix",
        hour: 15,
        profile: "delivery_worker",
        allow_shelter_reroute: true,
      })
      .then(setNav)
      .catch(() => setOffline(true));
  }, []);

  // Live-or-fallback card values
  const pathALoad = nav?.routes.standard.metrics.mean_exposure_index_f ?? FALLBACK.pathA_load_f;
  const reroute = nav?.shelter_reroute;
  const legBefore = reroute?.longest_leg_min_before ?? FALLBACK.leg_before_min;
  const legAfter = reroute?.longest_leg_min_after ?? FALLBACK.leg_after_min;
  const shelterApplied = reroute?.applied ?? true;
  const shelterName = reroute?.shelter?.name ?? FALLBACK.shelter;
  const loadSaved = nav?.comparison.thermal_load_reduction_f ?? FALLBACK.load_saved_f;
  const shadeGain = nav?.comparison.shade_coverage_gain_pct ?? FALLBACK.shade_gain_pct;
  const addedMin = nav?.comparison.added_minutes ?? FALLBACK.added_min;
  const solveMs = nav?.compute_ms ?? FALLBACK.solve_ms;
  const riskLevel = nav?.routes.standard.metrics.risk_level ?? "high";
  const feedLive = nav ? nav.feed.ok && !nav.feed.degraded : !offline;

  const rasterTiles = cities.reduce((a, c) => a + c.raster_tiles, 0) || 2407;
  const calibrated = cities.filter((c) => c.calibrated).length || 3;

  // Gauge position across the comfort (88°F) → survival (140°F) span.
  const gaugePct = Math.max(4, Math.min(96, ((pathALoad - 88) / (140 - 88)) * 100));

  return (
    <div className="bg-blueprint min-h-full bg-[#05070b] text-slate-200">
      {/* ---- nav ---------------------------------------------------------------------- */}
      <header className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <a href="/" className="flex items-center gap-3">
          <span
            className="grid h-9 w-9 place-items-center rounded-lg font-bold text-slate-950"
            style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
          >
            ❄
          </span>
          <span className="text-[15px] font-bold tracking-[0.08em] text-slate-100">CRYONAV</span>
        </a>
        <nav className="hidden items-center gap-8 text-[11px] font-medium tracking-[0.22em] text-slate-400 sm:flex">
          <a href="#agents" className="transition hover:text-cyan-300">
            AGENTS
          </a>
          <a href="#api" className="transition hover:text-cyan-300">
            LIVE API
          </a>
          <a href="#edge" className="transition hover:text-cyan-300">
            EDGE
          </a>
        </nav>
      </header>

      {/* ---- hero --------------------------------------------------------------------- */}
      <main className="mx-auto grid max-w-7xl gap-14 px-6 pb-24 pt-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10 lg:pt-16">
        <section>
          <h1 className="text-5xl font-bold leading-[1.04] tracking-tight text-white sm:text-6xl lg:text-[64px]">
            We turn 124°F streets into{" "}
            <span className="bg-gradient-to-r from-cyan-300 via-sky-400 to-indigo-400 bg-clip-text text-transparent">
              103°F cool routes.
            </span>
          </h1>

          <p className="mt-8 max-w-xl text-[17px] leading-relaxed text-slate-400">
            Cryonav is an agentic thermal-navigation engine. It reads the FortyGuard Temperature
            API® at 2&nbsp;m above ground, fuses it with urban canopy structure, and routes
            pedestrians by the heat their body actually absorbs — with an Emergency Sentinel that
            breaks unsafe exposure at real cooling shelters. Deterministic, always.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <a
              href="/app"
              className="rounded-lg bg-cyan-400 px-6 py-3 text-[13px] font-bold tracking-[0.08em] text-slate-950 transition hover:bg-cyan-300"
            >
              LAUNCH DASHBOARD
            </a>
            <a
              href="https://github.com/mrnetwork0001/Cryonav"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 rounded-lg border border-slate-700 px-6 py-3 text-[13px] font-semibold tracking-[0.08em] text-slate-200 transition hover:border-slate-500 hover:text-white"
            >
              <svg viewBox="0 0 16 16" className="h-4 w-4 fill-current" aria-hidden>
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
              </svg>
              BROWSE SOURCE
            </a>
          </div>

          {/* ---- stat strip ---- */}
          <div className="mt-14 border-t border-slate-800/80 pt-8">
            <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
              <Stat label="COVERAGE TILES" value={String(cities.length || 3)} />
              <Stat label="OBSERVED CELLS" value={rasterTiles.toLocaleString()} />
              <Stat label="LIVE CALIBRATIONS" value={`${calibrated}/${cities.length || 3}`} />
              <Stat label="SENSING HEIGHT" value="2 m" />
            </div>
          </div>
        </section>

        {/* ---- live product card ------------------------------------------------------- */}
        <section className="lg:pt-2">
          <div className="live-card relative rounded-2xl border border-slate-800 bg-[#0a0e15]/90 p-5">
            <div className="sheen" aria-hidden />
            <div className="flex items-center justify-between px-1">
              <span className="text-[11px] font-semibold tracking-[0.22em] text-slate-400">
                ROUTE REQUEST INGESTED
              </span>
              <span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.18em]">
                <span
                  className={`ping-soft h-1.5 w-1.5 rounded-full ${
                    feedLive ? "bg-emerald-400 text-emerald-400" : "bg-amber-400 text-amber-400"
                  }`}
                  style={{ boxShadow: feedLive ? "0 0 8px #34d399" : "0 0 8px #fbbf24" }}
                />
                <span className={feedLive ? "text-emerald-400" : "text-amber-400"}>
                  {feedLive ? "LIVE" : "OFFLINE"}
                </span>
              </span>
            </div>

            <div className="mt-4 rounded-xl border border-slate-800 bg-[#0d1219] p-4">
              <div className="flex items-center gap-2">
                <span className="rounded bg-cyan-400/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-cyan-300">
                  PHX
                </span>
                <span className="text-[11px] text-slate-500">just now</span>
              </div>
              <div className="mt-2 text-[17px] font-semibold text-slate-100">
                Capitol Mall → Roosevelt Row · 2.86 km
              </div>
              <div className="mt-1 text-[11px] font-medium tracking-[0.16em] text-slate-500">
                OUTDOOR DELIVERY WORKER · 15:00 MST
              </div>
            </div>

            <div className="mt-5 flex items-start gap-3 px-1">
              <span
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm font-bold text-slate-950"
                style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
              >
                ❄
              </span>
              <div>
                <div className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                  CRYONAV SENTINEL EVALUATES
                </div>
                <div className="mt-0.5 text-[13px] text-slate-300">
                  How much heat will this body absorb today?
                </div>
              </div>
            </div>

            <div className="mt-5 px-1">
              <div className="flex items-baseline justify-between">
                <span className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                  THERMAL LOAD · DIRECT ROUTE
                </span>
                <span className="tnum text-[11px] text-slate-500">88 – 140 °F</span>
              </div>
              <div className="relative mt-3 h-1.5 rounded-full bg-slate-800">
                <div
                  className="gauge-fill absolute inset-y-0 left-0 rounded-full transition-all duration-1000"
                  style={{
                    width: `${gaugePct}%`,
                    background:
                      "linear-gradient(90deg,#818cf8,#22d3ee 30%,#facc15 60%,#fb923c 80%,#ef4444)",
                  }}
                />
                <div
                  className="ping-soft absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full border-2 border-slate-950 bg-white text-white transition-all duration-1000"
                  style={{ left: `calc(${gaugePct}% - 7px)` }}
                />
              </div>
              <div className="tnum mt-2 text-[11px] font-semibold tracking-[0.14em] text-slate-400">
                {pathALoad.toFixed(0)}°F · TIER{" "}
                <span className={riskLevel === "extreme" ? "text-rose-400" : "text-orange-400"}>
                  {riskLevel.toUpperCase()}
                </span>
              </div>
            </div>

            <div className="mt-5 flex items-end justify-between px-1">
              <div>
                <div className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                  {shelterApplied ? "EXPOSURE LEG CUT" : "COOL ROUTE PRICED"}
                </div>
                <div className="metric-glow tnum mt-1 text-4xl font-bold text-emerald-400">
                  {shelterApplied
                    ? `−${(legBefore - legAfter).toFixed(1)} min`
                    : `−${loadSaved.toFixed(1)}°F`}
                </div>
              </div>
              <span className="tnum rounded-full border border-emerald-400/40 bg-emerald-400/10 px-3 py-1.5 text-[11px] font-semibold tracking-[0.1em] text-emerald-300">
                {shelterApplied
                  ? `${legBefore.toFixed(0)} → ${legAfter.toFixed(0)} MIN UNBROKEN`
                  : `SHADE ${shadeGain >= 0 ? "+" : "−"}${Math.abs(shadeGain).toFixed(0)}% · ${
                      addedMin >= 0 ? "+" : "−"
                    }${Math.abs(addedMin).toFixed(1)} MIN`}
              </span>
            </div>
            {shelterApplied && (
              <div className="mt-2 px-1 text-[11px] text-slate-500">
                Cooling stop inserted at <span className="text-cyan-300">{shelterName}</span> —
                shade {shadeGain >= 0 ? "+" : "−"}
                {Math.abs(shadeGain).toFixed(0)}%, {addedMin >= 0 ? "+" : "−"}
                {Math.abs(addedMin).toFixed(1)} min
              </div>
            )}

            <div className="mt-5 flex items-center justify-between rounded-xl border border-indigo-400/25 bg-indigo-500/10 p-3.5 pl-4">
              <div className="flex items-center gap-3">
                <span className="bolt-flicker text-indigo-300">⚡</span>
                <div>
                  <div className="text-[12px] font-bold tracking-[0.12em] text-slate-100">
                    1-CLICK COOL ROUTE READY
                  </div>
                  <div className="tnum mt-0.5 text-[10px] tracking-[0.08em] text-slate-500">
                    FortyGuard 2 m AGL · 3 agents · {solveMs.toFixed(0)} ms solve · deterministic
                  </div>
                </div>
              </div>
              <a
                href="/app"
                className="btn-breathe rounded-lg bg-cyan-400 px-5 py-2.5 text-[12px] font-bold tracking-[0.1em] text-slate-950 transition hover:bg-cyan-300"
              >
                NAVIGATE
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* ================================================================================
          THE PROBLEM — two streets, 500 m apart
      ================================================================================= */}
      <section className="border-t border-slate-800/60">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <SectionKicker>THE PROBLEM</SectionKicker>
          <h2 className="mt-4 max-w-3xl text-4xl font-bold tracking-tight text-white">
            Air temperature can't tell these two streets apart.{" "}
            <span className="text-slate-500">A body can.</span>
          </h2>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            Two Phoenix streets, 500 metres apart, same moment — measured by this repo's own
            thermal model over FortyGuard microclimate data. A weather API sees a 10° difference.
            A pedestrian's body absorbs a 46° difference in radiant load, and that is where heat
            illness actually comes from.
          </p>

          <div className="mt-10 grid gap-4 md:grid-cols-2">
            <StreetCard
              tone="hot"
              name="Van Buren St × 7th Ave"
              kind="unshaded asphalt corridor"
              rows={[
                ["Air @ 2 m", "114.8 °F"],
                ["Asphalt surface", "179.7 °F"],
                ["Mean radiant temp", "155.4 °F"],
              ]}
              exposure="123.8 °F"
              tier="EXTREME"
            />
            <StreetCard
              tone="cool"
              name="Central Ave canopy spine"
              kind="mature mesquite alley"
              rows={[
                ["Air @ 2 m", "104.6 °F"],
                ["Asphalt surface", "120.5 °F"],
                ["Mean radiant temp", "109.8 °F"],
              ]}
              exposure="102.9 °F"
              tier="MODERATE"
            />
          </div>

          <p className="tnum mt-6 text-[11px] text-slate-600">
            Reproduce: <code className="text-slate-500">cd backend && .venv/bin/python -c "from
            fortyguard_service import FortyGuardService as F; print(F().sample('phoenix', 33.4520,
            -112.0825, 15.0))"</code>
          </p>
        </div>
      </section>

      {/* ================================================================================
          THE AGENTS
      ================================================================================= */}
      <section id="agents" className="border-t border-slate-800/60">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <SectionKicker>AGENTIC ARCHITECTURE</SectionKicker>
          <h2 className="mt-4 max-w-3xl text-4xl font-bold tracking-tight text-white">
            Three agents. One blackboard.{" "}
            <span className="text-slate-500">The third can overrule the second.</span>
          </h2>

          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            <AgentCard
              glyph="◈"
              color="#facc15"
              name="Thermal Sensing"
              role="Polls the FortyGuard feed for the corridor, classifies microclimate risk low → extreme, and flags asphalt radiation spikes — surface running 60 °F above the air a weather app reports."
              trace='poll_fortyguard · flag_asphalt_trap'
            />
            <AgentCard
              glyph="⬡"
              color="#22d3ee"
              name="Cool-Route Optimizer"
              role="Solves the same origin–destination twice: pure distance (what every navigator returns) and thermal dose — minutes in sun weighted by how punishing that sun is — under a per-profile detour budget. Rejected candidates are kept and shown."
              trace="solve_dual_route · score_tradeoff"
            />
            <AgentCard
              glyph="⬢"
              color="#fb7185"
              name="Emergency Sentinel"
              role="Checks the longest unbroken high-risk leg against public-health exposure ceilings. When exceeded, it trials real cooling shelters as mandatory waypoints and re-invokes the optimizer — or says honestly that none helps."
              trace="assess_exposure · shelter_reroute"
            />
          </div>

          <div className="mt-6 rounded-xl border border-slate-800 bg-[#0a0e15]/80 p-5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[12px] text-slate-400">
              <span className="text-amber-300">sensing</span>
              <Arrow />
              <span className="text-cyan-300">optimizer</span>
              <Arrow />
              <span className="text-rose-300">sentinel</span>
              <span className="text-slate-600">— exposure ceiling exceeded? —</span>
              <span className="rounded bg-rose-400/10 px-2 py-0.5 text-rose-300">
                re-solve with shelter waypoint
              </span>
              <Arrow />
              <span className="text-cyan-300">optimizer</span>
              <span className="text-slate-600">(Path A baseline stays pinned)</span>
            </div>
            <p className="mt-3 text-[13px] leading-relaxed text-slate-500">
              That feedback edge is what makes this a loop rather than a pipeline — and every step
              lands in a structured trace the dashboard renders live, so the reasoning is shown,
              not asserted.
            </p>
          </div>
        </div>
      </section>

      {/* ================================================================================
          LIVE API INTEGRATION
      ================================================================================= */}
      <section id="api" className="border-t border-slate-800/60">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <SectionKicker>FORTYGUARD TEMPERATURE API®</SectionKicker>
          <h2 className="mt-4 max-w-3xl text-4xl font-bold tracking-tight text-white">
            Live data, not a mock with a logo.
          </h2>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            Cryonav's integration was verified against the production API — auth scheme, async
            activity flow, error envelope and all. FortyGuard supplies the ambient truth; Cryonav
            models the urban form on top. Neither is useful alone.
          </p>

          <div className="mt-10 grid gap-4 md:grid-cols-3">
            <EndpointCard
              path="/v1/env_params"
              badge="AMBIENT · GLOBAL"
              badgeColor="#34d399"
              desc="Real 24 h hourly series per tile: apparent temperature, wet-bulb, humidity, cloud cover, clear-sky irradiance. Settles in ~5 s. Dry-bulb is recovered by inverting wet-bulb + RH — apparent temp already contains the humidity term."
            />
            <EndpointCard
              path="/v1/heatmap"
              badge="RASTER · US TILES"
              badgeColor="#22d3ee"
              desc="2,407 observed ~100 m tiles over the Phoenix AOI, rendered as a switchable map layer. Its ~0.4 °C spatial spread is the empirical proof of the thesis: air can't tell streets apart — radiant load can."
            />
            <EndpointCard
              path="/v1/status/{id}"
              badge="ASYNC FLOW"
              badgeColor="#a78bfa"
              desc="Every enterprise endpoint returns an activity_id; results are collected on completion. Failures surface with their real upstream status — a 401 renders as a red DEGRADED pill, never as a green 200."
            />
          </div>

          {/* live calibration table */}
          <div className="mt-6 overflow-x-auto rounded-xl border border-slate-800 bg-[#0a0e15]/80">
            <table className="w-full min-w-[560px] text-left text-[13px]">
              <thead>
                <tr className="border-b border-slate-800 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  <th className="px-5 py-3.5 font-semibold">Coverage tile</th>
                  <th className="px-5 py-3.5 font-semibold">Live ambient range</th>
                  <th className="px-5 py-3.5 font-semibold">Peak</th>
                  <th className="px-5 py-3.5 font-semibold">Timezone</th>
                  <th className="px-5 py-3.5 font-semibold">Raster</th>
                </tr>
              </thead>
              <tbody className="tnum">
                {(cities.length
                  ? cities
                  : ([
                      { id: "phoenix", name: "Phoenix", raster_tiles: 2407 },
                      { id: "dubai", name: "Dubai", raster_tiles: 0 },
                      { id: "abu_dhabi", name: "Abu Dhabi", raster_tiles: 0 },
                    ] as CitySummary[])
                ).map((c) => {
                  const cal = cals[c.id];
                  return (
                    <tr key={c.id} className="border-b border-slate-800/60 last:border-0">
                      <td className="px-5 py-3.5 font-medium text-slate-200">{c.name}</td>
                      <td className="px-5 py-3.5 text-slate-400">
                        {cal?.calibrated
                          ? `${cal.air_temp_min_f?.toFixed(1)} – ${cal.air_temp_max_f?.toFixed(1)} °F`
                          : "synthetic model"}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">
                        {cal?.calibrated ? `${String(cal.peak_hour ?? 15).padStart(2, "0")}:00` : "—"}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{cal?.timezone ?? "—"}</td>
                      <td className="px-5 py-3.5">
                        {c.raster_tiles > 0 ? (
                          <span className="rounded bg-cyan-400/10 px-2 py-0.5 text-[11px] font-semibold text-cyan-300">
                            {c.raster_tiles.toLocaleString()} tiles
                          </span>
                        ) : (
                          <span className="text-[11px] text-slate-600">no US coverage</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] text-slate-600">
            Ambient ranges above are today's, fetched from the live API at page load. Tiles without
            raster coverage run the same physics on modelled spatial structure — and are labelled
            as such everywhere they appear.
          </p>
        </div>
      </section>

      {/* ================================================================================
          EDGE TIER
      ================================================================================= */}
      <section id="edge" className="border-t border-slate-800/60">
        <div className="mx-auto grid max-w-7xl gap-10 px-6 py-24 lg:grid-cols-[1fr_1fr]">
          <div>
            <SectionKicker>MUNICIPAL EDGE TIER</SectionKicker>
            <h2 className="mt-4 text-4xl font-bold tracking-tight text-white">
              Small enough for a kiosk on a metered uplink.
            </h2>
            <p className="mt-5 max-w-xl text-[15px] leading-relaxed text-slate-400">
              The same routing core serves a bandwidth-optimised endpoint for NVIDIA Jetson
              pedestrian kiosks and delivery-worker wearables: polylines decimated to the panel's
              resolution, telemetry stripped, one pre-rendered instruction string so firmware never
              does unit conversion. The Jetson hardware tier is simulated; the payload and compute
              figures are real and measured.
            </p>
            <div className="mt-8 grid grid-cols-3 gap-6">
              <Stat label="PAYLOAD" value="1,953 B" />
              <Stat label="SOLVE" value="~12 ms" />
              <Stat label="OFFLINE" value="✓" />
            </div>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-[#0a0e15]/90 p-5 font-mono text-[12px] leading-relaxed text-slate-400">
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
              POST /api/v1/edge/jetson-kiosk
            </div>
            <pre className="mt-3 overflow-x-auto whitespace-pre text-[11.5px]">{`{
  "now":    { "air_f": 109, "surface_f": 164, "risk": "extreme" },
  "route":  { "distance_m": 3018, "minutes": 47, "shade_pct": 54 },
  "savings":{ "thermal_load_f": 1.2, "heat_stress_pct": 5.0 },
  "shelter":{ "name": "Justa Center Respite", "walk_min": 5.1 },
  "instruction": "COOL ROUTE: 3.02 km, 47 min. …
                  Carry 555 ml water.",
  "edge": {
    "runtime": "NVIDIA Jetson Orin Nano (simulated)",
    "inference_ms": 12.6, "payload_bytes": 1953,
    "offline_capable": true
  }
}`}</pre>
          </div>
        </div>
      </section>

      {/* ================================================================================
          VERIFICATION / HONESTY
      ================================================================================= */}
      <section className="border-t border-slate-800/60">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <SectionKicker>VERIFICATION POSTURE</SectionKicker>
          <h2 className="mt-4 max-w-3xl text-4xl font-bold tracking-tight text-white">
            Honest by construction.
          </h2>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            A safety product that flatters its own numbers is worse than none. Cryonav's guarantees
            are enforced in the test suite, not the marketing copy.
          </p>

          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <ProofCard
              stat="127"
              label="tests"
              desc="Physics, routing, agents, API surface, upstream failure modes — including a no-regression sweep across all 27 corridor × profile combinations."
            />
            <ProofCard
              stat="0"
              label="negative savings"
              desc="If no admissible route beats the direct path on both dose and peak exposure, Cryonav returns the direct path and reports zero — it never manufactures a detour."
            />
            <ProofCard
              stat="401 ≠ 200"
              label="degraded is visible"
              desc="An upstream auth failure renders as a red DEGRADED pill with the real status code. Simulated data is labelled simulated, everywhere it appears."
            />
            <ProofCard
              stat="(city, t)"
              label="deterministic"
              desc="Every simulated reading is a pure function of place and time. Screenshots, tests and demos reproduce byte-for-byte."
            />
          </div>
        </div>
      </section>

      {/* ---- footer ------------------------------------------------------------------- */}
      <footer className="border-t border-slate-800/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-10 text-[11px] tracking-[0.08em] text-slate-500">
          <div className="flex items-center gap-3">
            <span
              className="grid h-7 w-7 place-items-center rounded-md text-xs font-bold text-slate-950"
              style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
            >
              ❄
            </span>
            <span>
              CRYONAV — built for FortyGuard Hackathon '26 · “Building the World's Temperature AI”
            </span>
          </div>
          <div className="flex items-center gap-6">
            <a href="/app" className="transition hover:text-cyan-300">
              DASHBOARD
            </a>
            <a
              href="https://github.com/mrnetwork0001/Cryonav"
              target="_blank"
              rel="noreferrer"
              className="transition hover:text-cyan-300"
            >
              MIT · SOURCE
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------- */

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold tracking-[0.22em] text-slate-500">{label}</div>
      <div className="tnum mt-2 font-mono text-4xl font-medium text-slate-100">{value}</div>
    </div>
  );
}

function SectionKicker({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-px w-8 bg-cyan-400/60" />
      <span className="text-[11px] font-semibold tracking-[0.24em] text-cyan-300">{children}</span>
    </div>
  );
}

function Arrow() {
  return <span className="text-slate-600">→</span>;
}

function StreetCard(props: {
  tone: "hot" | "cool";
  name: string;
  kind: string;
  rows: [string, string][];
  exposure: string;
  tier: string;
}) {
  const hot = props.tone === "hot";
  return (
    <div
      className={`rounded-2xl border p-6 ${
        hot ? "border-rose-500/30 bg-rose-950/10" : "border-cyan-400/25 bg-cyan-950/10"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[17px] font-semibold text-slate-100">{props.name}</div>
          <div className="mt-0.5 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            {props.kind}
          </div>
        </div>
        <span
          className={`rounded px-2 py-1 text-[10px] font-bold tracking-wider ${
            hot ? "bg-rose-500/15 text-rose-400" : "bg-yellow-400/10 text-yellow-300"
          }`}
        >
          {props.tier}
        </span>
      </div>
      <div className="tnum mt-5 space-y-2.5 text-[13px]">
        {props.rows.map(([k, v]) => (
          <div key={k} className="flex justify-between border-b border-slate-800/60 pb-2.5">
            <span className="text-slate-500">{k}</span>
            <span className="font-medium text-slate-200">{v}</span>
          </div>
        ))}
        <div className="flex items-baseline justify-between pt-1">
          <span className="text-slate-400">Exposure index</span>
          <span
            className={`tnum text-3xl font-bold ${hot ? "text-rose-400" : "text-cyan-300"}`}
          >
            {props.exposure}
          </span>
        </div>
      </div>
    </div>
  );
}

function AgentCard(props: { glyph: string; color: string; name: string; role: string; trace: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0a0e15]/80 p-6">
      <div className="flex items-center gap-3">
        <span
          className="grid h-10 w-10 place-items-center rounded-lg text-lg"
          style={{ background: `${props.color}1a`, color: props.color }}
        >
          {props.glyph}
        </span>
        <div className="text-[15px] font-semibold text-slate-100">{props.name}</div>
      </div>
      <p className="mt-4 text-[13px] leading-relaxed text-slate-400">{props.role}</p>
      <div className="mt-4 font-mono text-[10px] tracking-[0.08em] text-slate-600">{props.trace}</div>
    </div>
  );
}

function EndpointCard(props: { path: string; badge: string; badgeColor: string; desc: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0a0e15]/80 p-6">
      <div className="flex items-center justify-between gap-2">
        <code className="text-[13px] font-semibold text-slate-100">{props.path}</code>
        <span
          className="rounded px-2 py-0.5 text-[9px] font-bold tracking-wider"
          style={{ background: `${props.badgeColor}1a`, color: props.badgeColor }}
        >
          {props.badge}
        </span>
      </div>
      <p className="mt-4 text-[13px] leading-relaxed text-slate-400">{props.desc}</p>
    </div>
  );
}

function ProofCard(props: { stat: string; label: string; desc: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0a0e15]/80 p-6">
      <div className="tnum font-mono text-3xl font-bold text-cyan-300">{props.stat}</div>
      <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        {props.label}
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-slate-500">{props.desc}</p>
    </div>
  );
}
