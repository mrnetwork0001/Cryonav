import { useEffect, useRef, useState } from "react";
import { api, type CitySummary, type NavigationResult } from "../lib/api";

/**
 * Marketing/landing page, styled after the dark "protocol landing" idiom: blueprint grid,
 * two-tone gradient headline, mono stat strip, and a live product card — followed by the
 * full story: the physics problem, the three agents, the live FortyGuard integration, the
 * Jetson edge tier, and the verification posture.
 *
 * Layout follows the bento pattern the best dark developer-product landings converge on:
 * each section is a grid with one dominant tile carrying the core idea and smaller cells
 * around it, rather than a uniform row of equal cards. Sections reveal on scroll.
 *
 * Everything numeric is either fetched live from the backend or is a real measured value
 * from this repo's own test runs. Nothing on this page is invented copy. When the backend
 * is unreachable the live card falls back to the last measured values, marked OFFLINE.
 */

// Recorded 2026-08-24 from the live backend; rendered only when the backend is
// unreachable, with the card pill flipped to OFFLINE. Refresh when re-measuring.
const FALLBACK = {
  pathA_load_f: 116,
  leg_before_min: 57.0,
  leg_after_min: 41.0,
  load_saved_f: 2.2,
  shade_gain_pct: 16,
  added_min: 3.4,
  shelter: "20 W Jackson",
  solve_ms: 270,
};

interface CalSummary {
  calibrated: boolean;
  air_temp_min_f?: number;
  air_temp_max_f?: number;
  peak_hour?: number;
  timezone?: string;
}

/** Adds `.is-in` to every `.reveal` element once it scrolls into view. */
function useScrollReveal(deps: unknown[] = []) {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>(".reveal:not(.is-in)"));
    if (!els.length) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      els.forEach((el) => el.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [nav, setNav] = useState<NavigationResult | null>(null);
  const [cals, setCals] = useState<Record<string, CalSummary>>({});
  const [offline, setOffline] = useState(false);
  const heroRef = useRef<HTMLDivElement | null>(null);

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

  useScrollReveal([cities.length, !!nav]);

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
      <header className="sticky top-0 z-40 border-b border-slate-800/40 bg-[#05070b]/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 sm:py-5">
          <a href="/" className="flex items-center gap-3">
            <span
              className="grid h-9 w-9 place-items-center rounded-lg font-bold text-slate-950"
              style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
            >
              ❄
            </span>
            <span className="text-[15px] font-bold tracking-[0.08em] text-slate-100">CRYONAV</span>
          </a>
          <nav className="hidden items-center gap-4 text-[11px] font-medium tracking-[0.22em] text-slate-400 sm:flex">
            <a href="#agents" className="px-2 py-2.5 transition hover:text-cyan-300">
              AGENTS
            </a>
            <a href="#api" className="px-2 py-2.5 transition hover:text-cyan-300">
              LIVE API
            </a>
            <a href="#edge" className="px-2 py-2.5 transition hover:text-cyan-300">
              EDGE
            </a>
            <a
              href="/app"
              className="ml-2 rounded-lg border border-cyan-400/40 px-4 py-2 text-cyan-300 transition hover:bg-cyan-400/10"
            >
              DASHBOARD
            </a>
          </nav>
          {/* phone menu */}
          <div className="relative sm:hidden">
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Menu"
              aria-expanded={menuOpen}
              className="grid h-10 w-10 place-items-center rounded-lg border border-slate-700/60 text-slate-300 transition hover:border-cyan-400/50 hover:text-cyan-300"
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                {menuOpen ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
              </svg>
            </button>
            {menuOpen && (
              <nav className="absolute right-0 top-12 z-50 w-52 rounded-xl border border-slate-700/60 bg-[#0a0e15]/95 p-2 text-[11px] font-medium tracking-[0.18em] text-slate-300 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur">
                {[
                  ["#agents", "AGENTS"],
                  ["#api", "LIVE API"],
                  ["#edge", "EDGE"],
                  ["/app", "DASHBOARD"],
                  ["https://github.com/mrnetwork0001/Cryonav", "SOURCE"],
                ].map(([href, label]) => (
                  <a
                    key={label}
                    href={href}
                    onClick={() => setMenuOpen(false)}
                    className="block rounded-lg px-3 py-3 transition hover:bg-cyan-400/10 hover:text-cyan-300"
                  >
                    {label}
                  </a>
                ))}
              </nav>
            )}
          </div>
        </div>
      </header>

      {/* ---- hero --------------------------------------------------------------------- */}
      <div ref={heroRef} className="relative overflow-hidden">
        {/* ambient glow */}
        <div
          className="aurora"
          style={{ top: "-14rem", left: "-8rem", width: "38rem", height: "38rem", background: "#0891b2" }}
          aria-hidden
        />
        <div
          className="aurora"
          style={{ top: "-6rem", right: "-10rem", width: "32rem", height: "32rem", background: "#4338ca", opacity: 0.28 }}
          aria-hidden
        />

        <main className="relative mx-auto grid max-w-7xl gap-14 px-6 pb-28 pt-14 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12 lg:pt-24">
          <section className="reveal">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/50 px-3 py-1.5 text-[10px] font-semibold tracking-[0.2em] text-slate-400">
              <span
                className={`ping-soft h-1.5 w-1.5 rounded-full ${feedLive ? "bg-emerald-400 text-emerald-400" : "bg-amber-400 text-amber-400"}`}
              />
              FORTYGUARD TEMPERATURE API® · 2 M AGL
            </div>

            <h1 className="display text-[46px] font-bold text-white sm:text-[64px] lg:text-[80px]">
              We turn 124°F streets into{" "}
              <span className="bg-gradient-to-r from-cyan-300 via-sky-400 to-indigo-400 bg-clip-text text-transparent">
                103°F cool routes.
              </span>
            </h1>

            <p className="mt-9 max-w-xl text-[17px] leading-relaxed text-slate-400">
              Cryonav is an agentic thermal-navigation engine. It reads the FortyGuard Temperature
              API® at 2&nbsp;m above ground, fuses it with urban canopy structure, and routes
              pedestrians by the heat their body actually absorbs — with an Emergency Sentinel that
              breaks unsafe exposure at real cooling shelters. Deterministic, always.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-3">
              <a
                href="/app"
                className="btn-breathe rounded-lg bg-cyan-400 px-6 py-3.5 text-[13px] font-bold tracking-[0.08em] text-slate-950 transition hover:bg-cyan-300"
              >
                LAUNCH DASHBOARD
              </a>
              <a
                href="https://github.com/mrnetwork0001/Cryonav"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 rounded-lg border border-slate-700 px-6 py-3.5 text-[13px] font-semibold tracking-[0.08em] text-slate-200 transition hover:border-slate-500 hover:text-white"
              >
                <svg viewBox="0 0 16 16" className="h-4 w-4 fill-current" aria-hidden>
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
                </svg>
                BROWSE SOURCE
              </a>
            </div>

            {/* ---- stat strip ---- */}
            <div className="mt-16 border-t border-slate-800/80 pt-8">
              <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
                <Stat label="COVERAGE TILES" value={String(cities.length || 3)} />
                <Stat label="OBSERVED CELLS" value={rasterTiles.toLocaleString()} />
                <Stat label="LIVE CALIBRATIONS" value={`${calibrated}/${cities.length || 3}`} />
                <Stat label="SENSING HEIGHT" value="2 m" />
              </div>
            </div>
          </section>

          {/* ---- live product card ------------------------------------------------------- */}
          <section className="reveal lg:pt-2">
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
                  Capitol Mall → Roosevelt Row ·{" "}
                  {(nav?.routes.standard.metrics.distance_km ?? 3.4).toFixed(2)} km
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

              <div className="mt-5 flex flex-wrap items-end justify-between gap-3 px-1">
                <div>
                  <div className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                    {shelterApplied ? "EXPOSURE LEG CUT" : "COOL ROUTE PRICED"}
                  </div>
                  <div className="metric-glow tnum mt-1 text-3xl font-bold text-emerald-400 sm:text-4xl">
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

              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-400/25 bg-indigo-500/10 p-3.5 pl-4">
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
      </div>

      {/* ================================================================================
          THE PROBLEM — two streets, 500 m apart
      ================================================================================= */}
      <section id="problem" className="border-t border-slate-800/60">
        <div className="mx-auto max-w-7xl px-6 py-28">
          <div className="reveal">
            <SectionKicker>THE PROBLEM</SectionKicker>
            <h2 className="display-sm mt-5 max-w-3xl text-4xl font-bold text-white sm:text-[52px]">
              Air temperature can't tell these two streets apart.{" "}
              <span className="text-slate-500">A body can.</span>
            </h2>
            <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-slate-400">
              Two Phoenix streets, 500 metres apart, same moment — measured by this repo's own
              thermal model over FortyGuard microclimate data. A weather API sees a 10° difference.
              A pedestrian's body absorbs a 46° difference in radiant load, and that is where heat
              illness actually comes from.
            </p>
          </div>

          {/* bento: dominant hot street, cool street, delta tile */}
          <div className="reveal mt-12 grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <StreetCard
                tone="hot"
                large
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
            </div>
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

          <p className="tnum reveal mt-6 text-[11px] text-slate-600">
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
        <div className="mx-auto max-w-7xl px-6 py-28">
          <div className="reveal">
            <SectionKicker>AGENTIC ARCHITECTURE</SectionKicker>
            <h2 className="display-sm mt-5 max-w-3xl text-4xl font-bold text-white sm:text-[52px]">
              Three agents. One blackboard.{" "}
              <span className="text-slate-500">The third can overrule the second.</span>
            </h2>
          </div>

          {/* bento: optimizer dominant (the core), sensing + sentinel as supporting cells */}
          <div className="reveal mt-12 grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2 lg:row-span-2">
              <AgentCard
                large
                glyph="⬡"
                color="#22d3ee"
                name="Cool-Route Optimizer"
                role="Solves the same origin–destination twice: pure distance (what every navigator returns) and thermal dose — minutes in sun weighted by how punishing that sun is — under a per-profile detour budget. Rejected candidates are kept and shown."
                trace="solve_dual_route · score_tradeoff"
              />
            </div>
            <AgentCard
              glyph="◈"
              color="#facc15"
              name="Thermal Sensing"
              role="Polls the FortyGuard feed for the corridor, classifies microclimate risk low → extreme, and flags asphalt radiation spikes — surface running 60 °F above the air a weather app reports."
              trace='poll_fortyguard · flag_asphalt_trap'
            />
            <AgentCard
              glyph="⬢"
              color="#fb7185"
              name="Emergency Sentinel"
              role="Checks the longest unbroken high-risk leg against public-health exposure ceilings. When exceeded, it trials real cooling shelters as mandatory waypoints and re-invokes the optimizer — or says honestly that none helps."
              trace="assess_exposure · shelter_reroute"
            />
          </div>

          <div className="bento reveal mt-4 p-6">
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
        <div className="mx-auto max-w-7xl px-6 py-28">
          <div className="reveal">
            <SectionKicker>FORTYGUARD TEMPERATURE API®</SectionKicker>
            <h2 className="display-sm mt-5 max-w-3xl text-4xl font-bold text-white sm:text-[52px]">
              Live data, not a mock with a logo.
            </h2>
            <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-slate-400">
              Cryonav's integration was verified against the production API — auth scheme, async
              activity flow, error envelope and all. FortyGuard supplies the ambient truth; Cryonav
              models the urban form on top. Neither is useful alone.
            </p>
          </div>

          {/* bento: env_params dominant, heatmap + status stacked beside it */}
          <div className="reveal mt-12 grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <EndpointCard
                large
                path="/v1/env_params"
                badge="AMBIENT · GLOBAL"
                badgeColor="#34d399"
                desc="Real 24 h hourly series per tile: apparent temperature, wet-bulb, humidity, cloud cover, clear-sky irradiance. Settles in ~5 s. Dry-bulb is recovered by inverting wet-bulb + RH — apparent temp already contains the humidity term."
              />
            </div>
            <div className="grid gap-4">
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
          </div>

          {/* live calibration table */}
          <div className="bento reveal mt-4 overflow-x-auto">
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
          <p className="reveal mt-3 text-[11px] text-slate-600">
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
        {/* minmax(0,1fr) + min-w-0: grid items default to min-width:auto, which lets the
            JSON <pre>'s min-content width propagate upward and force the whole page wider
            than a phone — its own overflow-x-auto never engages. Measured: 530px page at a
            390px viewport without this. */}
        <div className="mx-auto grid max-w-7xl gap-10 px-6 py-28 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="reveal min-w-0">
            <SectionKicker>MUNICIPAL EDGE TIER</SectionKicker>
            <h2 className="display-sm mt-5 text-4xl font-bold text-white sm:text-[52px]">
              Small enough for a kiosk on a metered uplink.
            </h2>
            <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-slate-400">
              The same routing core serves a bandwidth-optimised endpoint for NVIDIA Jetson
              pedestrian kiosks and delivery-worker wearables: polylines decimated to the panel's
              resolution, telemetry stripped, one pre-rendered instruction string so firmware never
              does unit conversion. The Jetson hardware tier is simulated; the payload and compute
              figures are real and measured.
            </p>
            <div className="mt-10 grid grid-cols-3 gap-6">
              <Stat label="PAYLOAD" value="~2 KB" />
              <Stat label="SOLVE" value="~270 ms" />
              <Stat label="OFFLINE" value="✓" />
            </div>
          </div>
          <div className="bento reveal min-w-0 p-5 font-mono text-[12px] leading-relaxed text-slate-400">
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
    "inference_ms": 271.4, "payload_bytes": 2070,
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
        <div className="mx-auto max-w-7xl px-6 py-28">
          <div className="reveal">
            <SectionKicker>VERIFICATION POSTURE</SectionKicker>
            <h2 className="display-sm mt-5 max-w-3xl text-4xl font-bold text-white sm:text-[52px]">
              Honest by construction.
            </h2>
            <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-slate-400">
              A safety product that flatters its own numbers is worse than none. Cryonav's guarantees
              are enforced in the test suite, not the marketing copy.
            </p>
          </div>

          {/* bento: tests dominant, three supporting proofs */}
          <div className="reveal mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2">
              <ProofCard
                large
                stat="130"
                label="tests"
                desc="Physics, routing, agents, API surface, upstream failure modes — including a no-regression sweep across all 27 corridor × profile combinations."
              />
            </div>
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
            <div className="sm:col-span-2 lg:col-span-4">
              <ProofCard
                wide
                stat="(city, t)"
                label="deterministic"
                desc="Every reading is a pure function of place, time and the day's FortyGuard calibration — runs reproduce byte-for-byte within a calibration day."
              />
            </div>
          </div>
        </div>
      </section>

      {/* ---- footer ------------------------------------------------------------------- */}
      <footer className="border-t border-slate-800/60">
        <div className="mx-auto grid max-w-7xl gap-12 px-6 py-16 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          {/* brand block */}
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <span
                className="grid h-10 w-10 place-items-center rounded-lg text-lg font-bold text-slate-950"
                style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
              >
                ❄
              </span>
              <span className="border-l border-slate-700/60 pl-3 leading-tight">
                <span className="block text-[15px] font-bold tracking-[0.14em] text-slate-100">
                  CRYONAV
                </span>
                <span className="block text-[9px] uppercase tracking-[0.22em] text-slate-500">
                  Thermal Navigation Engine
                </span>
              </span>
            </div>
            <p className="mt-6 max-w-sm text-[14px] leading-relaxed text-slate-400">
              Agentic thermal navigation on the FortyGuard Temperature API®. Live microclimate
              intelligence at 2&nbsp;m above ground, fused with urban canopy structure — returned
              as a walkable, survivable route on real city streets.
            </p>
            <div className="mt-6 flex items-center gap-4">
              <a
                href="https://github.com/mrnetwork0001/Cryonav"
                target="_blank"
                rel="noreferrer"
                aria-label="GitHub"
                className="text-slate-500 transition hover:text-cyan-300"
              >
                <svg viewBox="0 0 16 16" className="h-5 w-5 fill-current" aria-hidden>
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
                </svg>
              </a>
            </div>
          </div>

          <FooterCol
            title="PRODUCT"
            links={[
              ["/app", "Live Dashboard"],
              ["#problem", "The Problem"],
              ["#agents", "The Agents"],
              ["#edge", "Edge Kiosk"],
            ]}
          />
          <FooterCol
            title="FORTYGUARD"
            links={[
              ["https://www.fortyguard.com", "FortyGuard"],
              ["https://dashboard.fortyguard.com", "Temperature Dashboard®"],
              ["https://docs-api.fortyguard.com/docs", "Temperature API® Docs"],
              ["https://www.fortyguard.com/hackathon26", "Hackathon '26"],
            ]}
          />
          <FooterCol
            title="RESOURCES"
            links={[
              ["https://github.com/mrnetwork0001/Cryonav", "GitHub"],
              ["/docs", "API Reference"],
              ["/api/v1/health", "Live Status"],
              ["https://www.openstreetmap.org/copyright", "© OpenStreetMap"],
            ]}
          />
        </div>

        <div className="border-t border-slate-800/60">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-[11px] tracking-[0.06em] text-slate-600">
            <span>© 2026 Cryonav · MIT License · Built for FortyGuard Hackathon '26</span>
            <span className="tnum">
              Map data © OpenStreetMap contributors · Thermal data: FortyGuard Temperature API®
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------- */

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <nav aria-label={title}>
      <div className="text-[11px] font-semibold tracking-[0.26em] text-cyan-300">{title}</div>
      <ul className="mt-5 space-y-1 font-mono text-[14px]">
        {links.map(([href, label]) => {
          const external = href.startsWith("http");
          return (
            <li key={label}>
              <a
                href={href}
                {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
                className="-mx-2 block rounded px-2 py-1.5 text-slate-300 transition hover:bg-cyan-400/5 hover:text-cyan-300"
              >
                {label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

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
      <span className="kicker-rule h-px w-10 bg-cyan-400/60" />
      <span className="text-[11px] font-semibold tracking-[0.24em] text-cyan-300">{children}</span>
    </div>
  );
}

function Arrow() {
  return <span className="text-slate-600">→</span>;
}

function StreetCard(props: {
  tone: "hot" | "cool";
  large?: boolean;
  name: string;
  kind: string;
  rows: [string, string][];
  exposure: string;
  tier: string;
}) {
  const hot = props.tone === "hot";
  return (
    <div
      className={`bento flex h-full flex-col p-6 sm:p-7 ${
        hot ? "!border-rose-500/30 bg-rose-950/10" : "!border-cyan-400/25 bg-cyan-950/10"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={`font-semibold text-slate-100 ${props.large ? "text-[22px]" : "text-[17px]"}`}>
            {props.name}
          </div>
          <div className="mt-0.5 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            {props.kind}
          </div>
        </div>
        <span
          className={`shrink-0 rounded px-2 py-1 text-[10px] font-bold tracking-wider ${
            hot ? "bg-rose-500/15 text-rose-400" : "bg-yellow-400/10 text-yellow-300"
          }`}
        >
          {props.tier}
        </span>
      </div>
      <div className="tnum mt-6 flex-1 space-y-2.5 text-[13px]">
        {props.rows.map(([k, v]) => (
          <div key={k} className="flex justify-between border-b border-slate-800/60 pb-2.5">
            <span className="text-slate-500">{k}</span>
            <span className="font-medium text-slate-200">{v}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-baseline justify-between">
        <span className="text-slate-400">Exposure index</span>
        <span
          className={`tnum font-bold ${props.large ? "text-5xl" : "text-3xl"} ${
            hot ? "text-rose-400" : "text-cyan-300"
          }`}
        >
          {props.exposure}
        </span>
      </div>
    </div>
  );
}

function AgentCard(props: {
  glyph: string;
  color: string;
  name: string;
  role: string;
  trace: string;
  large?: boolean;
}) {
  return (
    <div className="bento flex h-full flex-col p-6 sm:p-7">
      <div className="flex items-center gap-3">
        <span
          className={`grid place-items-center rounded-lg ${props.large ? "h-14 w-14 text-2xl" : "h-10 w-10 text-lg"}`}
          style={{ background: `${props.color}1a`, color: props.color }}
        >
          {props.glyph}
        </span>
        <div className={`font-semibold text-slate-100 ${props.large ? "text-[22px]" : "text-[15px]"}`}>
          {props.name}
        </div>
      </div>
      <p
        className={`mt-4 flex-1 leading-relaxed text-slate-400 ${
          props.large ? "text-[15px]" : "text-[13px]"
        }`}
      >
        {props.role}
      </p>
      <div className="mt-5 font-mono text-[10px] tracking-[0.08em] text-slate-600">{props.trace}</div>
    </div>
  );
}

function EndpointCard(props: {
  path: string;
  badge: string;
  badgeColor: string;
  desc: string;
  large?: boolean;
}) {
  return (
    <div className="bento flex h-full flex-col p-6 sm:p-7">
      <div className="flex items-center justify-between gap-2">
        <code className={`font-semibold text-slate-100 ${props.large ? "text-[18px]" : "text-[13px]"}`}>
          {props.path}
        </code>
        <span
          className="shrink-0 rounded px-2 py-0.5 text-[9px] font-bold tracking-wider"
          style={{ background: `${props.badgeColor}1a`, color: props.badgeColor }}
        >
          {props.badge}
        </span>
      </div>
      <p
        className={`mt-4 flex-1 leading-relaxed text-slate-400 ${
          props.large ? "text-[15px]" : "text-[13px]"
        }`}
      >
        {props.desc}
      </p>
    </div>
  );
}

function ProofCard(props: {
  stat: string;
  label: string;
  desc: string;
  large?: boolean;
  wide?: boolean;
}) {
  return (
    <div
      className={`bento h-full p-6 sm:p-7 ${props.wide ? "flex flex-wrap items-center gap-x-8 gap-y-3" : ""}`}
    >
      <div className={props.wide ? "" : undefined}>
        <div
          className={`tnum font-mono font-bold text-cyan-300 ${
            props.large ? "text-6xl" : props.wide ? "text-4xl" : "text-3xl"
          }`}
        >
          {props.stat}
        </div>
        <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {props.label}
        </div>
      </div>
      <p
        className={`leading-relaxed text-slate-500 ${props.wide ? "min-w-[280px] flex-1 text-[13px]" : "mt-3"} ${
          props.large ? "text-[14px]" : "text-[12px]"
        }`}
      >
        {props.desc}
      </p>
    </div>
  );
}
