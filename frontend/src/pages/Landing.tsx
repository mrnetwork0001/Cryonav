import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDismiss } from "../lib/useDismiss";
import {
  api,
  fetchFacts,
  type CitySummary,
  type ContrastPoint,
  type Facts,
  type NavigationResult,
} from "../lib/api";
import {
  IconArrow,
  IconInstant,
  IconRoute,
  IconSensing,
  IconSentinel,
} from "../components/Icons";

/**
 * Landing page, "operations console" idiom.
 *
 * The previous version floated rounded cards on a blueprint field. This one rules the page
 * with hairlines and puts content INSIDE the cells, which reads as instrumentation rather
 * than as marketing - the register a municipality or a logistics operator buys in.
 *
 * TWO CONSTRAINTS SHAPED IT, and both are product constraints rather than taste:
 *
 * The ground stays near-black. Cryonav's entire output is a thermal gradient, and cyan-to-red
 * needs a dark substrate to read; on a light page the heat layer washes out.
 *
 * The risk palette is SEMANTIC and is never reused as chrome. Cyan means low risk and amber
 * means high risk in the map legend, so promoting amber to brand colour would make the legend
 * ambiguous. Amber appears here only where it labels nothing - horizons and the closing band.
 *
 * Everything numeric is either fetched live from the backend or is a real measured value from
 * this repo's own test runs. Nothing here is invented. When the backend is unreachable the
 * live card falls back to the last measured values and flips its pill to OFFLINE.
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

const NAV_LINKS: [string, string][] = [
  ["#problem", "PROBLEM"],
  ["#agents", "AGENTS"],
  ["#api", "LIVE API"],
  ["#edge", "EDGE"],
  ["/docs", "DOCS"],
];

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  // The dropdown and its toggle live inside this element, so a pointerdown anywhere else
  // is a dismissal. Including the toggle matters: otherwise tapping it would close from
  // the document handler and reopen from onClick, and the menu would never appear.
  const menuRef = useRef<HTMLDivElement | null>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [nav, setNav] = useState<NavigationResult | null>(null);
  const [cals, setCals] = useState<Record<string, CalSummary>>({});
  const [offline, setOffline] = useState(false);
  // Every figure this page states about Cryonav itself. Previously these were literals;
  // see lib/api.ts Facts for why that could not hold.
  const [facts, setFacts] = useState<Facts | null>(null);

  useEffect(() => {
    api
      .cities()
      .then((c) => setCities(c.cities))
      .catch(() => setOffline(true));
    fetchFacts()
      .then(setFacts)
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

  useDismiss(menuRef, menuOpen, closeMenu);
  useScrollReveal([cities.length, !!nav, !!facts]);

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

  const rasterTiles = cities.reduce((a, c) => a + c.raster_tiles, 0) || 4327;
  const cityCount = cities.length || 4;
  const calibrated = cities.filter((c) => c.calibrated).length || cityCount;

  // Gauge position across the comfort (88F) -> survival (140F) span.
  const gaugePct = Math.max(4, Math.min(96, ((pathALoad - 88) / (140 - 88)) * 100));

  return (
    <div className="min-h-full bg-[#05070b] text-slate-200">
      {/* ---- nav ---------------------------------------------------------------------- */}
      <header className="sticky top-0 z-40 border-b border-slate-800/50 bg-[#05070b]/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3.5">
          {/* The supplied wordmark already contains the mark AND the name, so the drawn
              glyph and the text label both go - keeping either would duplicate it. */}
          <a href="/" className="flex items-center" aria-label="Cryonav home">
            <img
              src="/brand/cryonav-wordmark.png"
              alt="Cryonav - Thermal Navigation System"
              className="h-8 w-auto sm:h-9"
              width={506}
              height={128}
            />
          </a>
          {/* Section links sit hard right now that the CTA has gone. The hero and the closing
              band both still carry LAUNCH DASHBOARD, so the route into the app is not lost -
              it is just no longer competing with the wordmark for the corner. */}
          <nav className="hidden items-center gap-1 text-[10px] font-medium tracking-[0.22em] text-slate-500 md:flex">
            {NAV_LINKS.map(([href, label]) => (
              <a key={label} href={href} className="px-3 py-2 transition hover:text-slate-200">
                {label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-2 md:hidden">
            <div className="relative" ref={menuRef}>
              <button
                onClick={() => setMenuOpen((v) => !v)}
                aria-label="Menu"
                aria-expanded={menuOpen}
                className="grid h-9 w-9 place-items-center rounded-md border border-slate-700/60 text-slate-300 transition hover:border-slate-500"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                  {menuOpen ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
                </svg>
              </button>
              {menuOpen && (
                <nav className="absolute right-0 top-11 z-50 w-52 rounded-lg border border-slate-700/60 bg-[#0a0e15]/95 p-1.5 text-[10px] font-medium tracking-[0.18em] text-slate-300 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur">
                  {/* Section links only. DASHBOARD and SOURCE were appended here and are
                      removed: both already have full-width buttons in the hero, which on a
                      phone is a shorter reach than opening a menu. Repeating them made the
                      drawer a list of seven where five are the only ones it uniquely offers. */}
                  {NAV_LINKS.map(
                    ([href, label]) => (
                      <a
                        key={label}
                        href={href}
                        onClick={() => setMenuOpen(false)}
                        className="block rounded px-3 py-3 transition hover:bg-white/5 hover:text-white"
                      >
                        {label}
                      </a>
                    ),
                  )}
                </nav>
              )}
            </div>
          </div>
        </div>
        <div className="ticker h-px w-full opacity-70" aria-hidden />
      </header>

      {/* ================================================================================
          HERO
      ================================================================================= */}
      <section className="relative overflow-hidden border-b border-slate-800/50">
        <div
          className="pointer-events-none absolute -right-40 -top-32 h-[34rem] w-[34rem] rounded-full opacity-[0.10] blur-[120px]"
          style={{ background: "radial-gradient(circle,#fb923c,transparent 70%)" }}
          aria-hidden
        />
        <div className="mx-auto grid max-w-[1400px] gap-14 px-6 pb-20 pt-16 lg:grid-cols-[1.02fr_0.98fr] lg:gap-16 lg:pb-24 lg:pt-24">
          <div className="reveal min-w-0">
            <div className="eyebrow flex items-center gap-2">
              <span className={`ping-soft h-1 w-1 rounded-full ${feedLive ? "bg-emerald-400 text-emerald-400" : "bg-amber-400 text-amber-400"}`} />
              FORTYGUARD TEMPERATURE API&reg; &middot; 2 M AGL
            </div>

            <h1 className="statement mt-7 text-[42px] text-white sm:text-[58px] lg:text-[66px]">
              We turn 124&deg;F streets
              <br />
              into{" "}
              <span className="bg-gradient-to-r from-cyan-300 via-sky-400 to-indigo-400 bg-clip-text text-transparent">
                103&deg;F cool routes.
              </span>
            </h1>

            <p className="mt-8 max-w-xl text-[15px] leading-[1.75] text-slate-400">
              Cryonav is an agentic thermal-navigation engine. It reads the FortyGuard Temperature
              API&reg; at 2&nbsp;m above ground, fuses it with measured urban canopy, and routes
              pedestrians by the heat their body actually absorbs - with an Emergency Sentinel that
              breaks unsafe exposure at real cooling shelters. Deterministic, always.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              <a
                href="/app"
                className="rounded-md bg-white px-6 py-3 text-[12px] font-semibold tracking-[0.1em] text-slate-950 transition hover:bg-slate-200"
              >
                LAUNCH DASHBOARD
              </a>
              <a
                href="https://github.com/mrnetwork0001/Cryonav"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 rounded-md border border-slate-700 px-6 py-3 text-[12px] font-semibold tracking-[0.1em] text-slate-300 transition hover:border-slate-500 hover:text-white"
              >
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current" aria-hidden>
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
                </svg>
                BROWSE SOURCE
              </a>
            </div>
          </div>

          <div className="reveal min-w-0">
            <LiveCard
              feedLive={feedLive}
              distanceKm={nav?.routes.standard.metrics.distance_km ?? 3.4}
              gaugePct={gaugePct}
              pathALoad={pathALoad}
              riskLevel={riskLevel}
              shelterApplied={shelterApplied}
              legBefore={legBefore}
              legAfter={legAfter}
              loadSaved={loadSaved}
              shadeGain={shadeGain}
              addedMin={addedMin}
              shelterName={shelterName}
              solveMs={solveMs}
            />
          </div>
        </div>

        <div className="mx-auto max-w-[1400px] px-6">
          <div className="cell-grid reveal grid grid-cols-2 lg:grid-cols-4">
            <RailStat label="COVERAGE TILES" value={String(cityCount)} note="Phoenix / Dubai / Abu Dhabi / San Jose" />
            <RailStat label="OBSERVED CELLS" value={rasterTiles.toLocaleString()} note="FortyGuard raster, ~100 m" />
            <RailStat label="LIVE CALIBRATIONS" value={`${calibrated}/${cityCount}`} note="refreshed daily from env_params" />
            <RailStat label="SENSING HEIGHT" value="2 m" note="above ground, where a body is" />
          </div>
        </div>
      </section>

      {/* ================================================================================
          PROVENANCE - the honest form of a logo wall
      ================================================================================= */}
      <section className="border-b border-slate-800/50">
        <div className="mx-auto max-w-[1400px] px-6 py-12">
          <p className="eyebrow reveal text-center">
            Every number on this site is measured. These are the instruments.
          </p>
          <div className="reveal mt-7 flex flex-wrap items-start justify-center gap-x-10 gap-y-5 sm:gap-x-14">
            {([
              ["FORTYGUARD", "ambient 2 m"],
              ["NASA ECOSTRESS", "peak-hour surface"],
              ["USGS LANDSAT", "surface 30 m"],
              ["META / WRI", "canopy 1.19 m"],
              ["OPENSTREETMAP", "street network"],
              ["NIOSH / OSHA", "exposure limits"],
            ] as [string, string][]).map(([name, what]) => (
              <div key={name} className="text-center">
                <div className="text-[12px] font-semibold tracking-[0.14em] text-slate-300">{name}</div>
                <div className="mt-1 text-[9.5px] tracking-[0.16em] text-slate-600">{what}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ================================================================================
          THE PROBLEM
      ================================================================================= */}
      <section id="problem" className="relative overflow-hidden">
        <div className="mx-auto max-w-[1400px] px-6 pt-28">
          <div className="reveal mx-auto max-w-3xl text-center">
            <div className="eyebrow">THE PROBLEM</div>
            <h2 className="statement mt-6 text-[32px] text-white sm:text-[44px]">
              Air temperature can&apos;t tell these two streets apart.{" "}
              <span className="text-slate-500">A body can.</span>
            </h2>
            {/* The gaps are read from the live sample rather than asserted. The frozen copy
                claimed a 10 degree air difference; on the day this was wired the real air gap
                measured 0.2 degrees while the radiant gap measured 27 - a stronger statement
                of the same thesis, and one a literal would never have caught up with. */}
            <p className="mt-7 text-[15px] leading-[1.75] text-slate-400">
              Two Phoenix streets, sampled at the same moment from FortyGuard microclimate data
              fused with measured canopy and surface temperature.{" "}
              {facts ? (
                <>
                  A weather API sees{" "}
                  <span className="text-slate-200">
                    {Math.abs(facts.contrast.air_gap_f).toFixed(1)}&deg;F
                  </span>{" "}
                  between them. A pedestrian&apos;s body absorbs{" "}
                  <span className="text-slate-200">
                    {Math.abs(facts.contrast.radiant_gap_f).toFixed(1)}&deg;F
                  </span>{" "}
                  of radiant difference, and that is where heat illness actually comes from.
                </>
              ) : (
                <>
                  The air layer barely separates them. The radiant load does, and that is where
                  heat illness actually comes from.
                </>
              )}
            </p>
          </div>

          {/* Sampled live from /api/v1/facts, not quoted. These two coordinates carry the
              product's central claim, and a frozen temperature stops being true the moment
              the calibration moves - which it does daily. */}
          {facts && (
            <div className="cell-grid reveal mt-14 grid lg:grid-cols-[1.3fr_1fr]">
              <StreetCell tone="hot" point={facts.contrast.hot} />
              <StreetCell tone="cool" point={facts.contrast.cool} />
            </div>
          )}

          <p className="tnum reveal mt-5 text-[10.5px] leading-relaxed text-slate-600">
            Reproduce:{" "}
            <code className="text-slate-500">
              cd backend &amp;&amp; .venv/bin/python -c &quot;from fortyguard_service import
              FortyGuardService as F; print(F().sample(&apos;phoenix&apos;, 33.4520, -112.0825,
              15.0))&quot;
            </code>
          </p>
        </div>
        <div className="horizon mt-16" aria-hidden />
      </section>

      {/* ================================================================================
          MEASURED
      ================================================================================= */}
      <section className="border-y border-slate-800/50">
        <div className="mx-auto max-w-[1400px] gap-16 px-6 py-24 lg:grid lg:grid-cols-[0.8fr_1.2fr]">
          <div className="reveal">
            <div className="eyebrow">MEASURED, NOT ASSERTED</div>
            <h2 className="statement mt-6 text-[28px] text-white sm:text-[36px]">
              Every layer was observed
              <br />
              from orbit or from the street.
            </h2>
            <p className="mt-6 max-w-md text-[14px] leading-[1.75] text-slate-400">
              Canopy used to be a lookup table that called every park 60% shaded. Measurement put
              Phoenix parks at a mean of 16%, and one 4.6-hectare park at 4.2% - a bare lawn the
              router would once have sent people to for shade.
            </p>
          </div>
          <div className="cell-grid reveal mt-12 grid grid-cols-2 lg:mt-0 lg:grid-cols-3">
            <BigStat value={facts ? `${facts.resolution.canopy_m} m` : "-"} label="canopy resolution" />
            <BigStat value={facts ? String(facts.cities) : "-"} label="cities onboarded" />
            <BigStat value={facts ? String(facts.measured_layers) : "-"} label="measured layers" />
            <BigStat value={facts ? String(facts.tests) : "-"} label="tests passing" />
            <BigStat
              value={facts ? `${facts.resolution.surface_peak_m ?? facts.resolution.surface_m} m` : "-"}
              label="surface temperature"
            />
            <BigStat
              value={facts ? String(facts.assumed_constants_remaining) : "-"}
              label="assumed constants left"
            />
          </div>
        </div>
      </section>

      {/* ================================================================================
          THE AGENTS
      ================================================================================= */}
      <section id="agents" className="border-b border-slate-800/50">
        <div className="mx-auto max-w-[1400px] px-6 py-28">
          <div className="reveal max-w-3xl">
            <div className="eyebrow">AGENTIC ARCHITECTURE</div>
            <h2 className="statement mt-6 text-[32px] text-white sm:text-[44px]">
              Three agents. One blackboard.{" "}
              <span className="text-slate-500">The third can overrule the second.</span>
            </h2>
          </div>

          <div className="cell-grid reveal mt-14 grid lg:grid-cols-3">
            <AgentCell
              step="01"
              Glyph={IconSensing}
              color="#facc15"
              name="Thermal Sensing"
              role="Polls the FortyGuard feed for the corridor, classifies microclimate risk low to extreme, and flags asphalt radiation spikes - surface running 60 &deg;F above the air a weather app reports."
              trace="poll_fortyguard / flag_asphalt_trap"
            />
            <AgentCell
              step="02"
              Glyph={IconRoute}
              color="#22d3ee"
              name="Cool-Route Optimizer"
              role="Solves the same origin-destination twice: pure distance (what every navigator returns) and thermal dose - minutes in sun weighted by how punishing that sun is - under a per-profile detour budget. Rejected candidates are kept and shown."
              trace="solve_dual_route / score_tradeoff"
            />
            <AgentCell
              step="03"
              Glyph={IconSentinel}
              color="#fb7185"
              name="Emergency Sentinel"
              role="Checks the longest unbroken high-risk leg against public-health exposure ceilings. When exceeded, it trials real cooling shelters as mandatory waypoints and re-invokes the optimizer - or says honestly that none helps."
              trace="assess_exposure / shelter_reroute"
            />
          </div>

          <div className="cell cell-grid reveal p-7">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[11.5px] text-slate-400">
              <span className="text-amber-300">sensing</span>
              <Arrow />
              <span className="text-cyan-300">optimizer</span>
              <Arrow />
              <span className="text-rose-300">sentinel</span>
              <span className="text-slate-600">- exposure ceiling exceeded? -</span>
              <span className="rounded bg-rose-400/10 px-2 py-0.5 text-rose-300">
                re-solve with shelter waypoint
              </span>
              <Arrow />
              <span className="text-cyan-300">optimizer</span>
              <span className="text-slate-600">(Path A baseline stays pinned)</span>
            </div>
            <p className="mt-4 max-w-3xl text-[13px] leading-relaxed text-slate-500">
              That feedback edge is what makes this a loop rather than a pipeline - and every step
              lands in a structured trace the dashboard renders live, so the reasoning is shown,
              not asserted.
            </p>
          </div>
        </div>
      </section>

      {/* ================================================================================
          LIVE API INTEGRATION
      ================================================================================= */}
      <section id="api" className="border-b border-slate-800/50">
        <div className="mx-auto max-w-[1400px] px-6 py-28">
          <div className="reveal max-w-3xl">
            <div className="eyebrow">FORTYGUARD TEMPERATURE API&reg;</div>
            <h2 className="statement mt-6 text-[32px] text-white sm:text-[44px]">
              Live data, not a mock with a logo.
            </h2>
            <p className="mt-7 max-w-2xl text-[15px] leading-[1.75] text-slate-400">
              Cryonav&apos;s integration was verified against the production API - auth scheme,
              async activity flow, error envelope and all. FortyGuard supplies the ambient truth;
              Cryonav models the urban form on top. Neither is useful alone.
            </p>
          </div>

          <div className="cell-grid reveal mt-14 grid lg:grid-cols-3">
            <EndpointCell
              path="/v1/env_params"
              badge="AMBIENT / GLOBAL"
              badgeColor="#34d399"
              desc="Real 24 h hourly series per point: apparent temperature, wet-bulb, humidity, cloud cover, clear-sky irradiance. Dry-bulb is recovered by inverting wet-bulb + RH - apparent temperature already contains the humidity term."
            />
            <EndpointCell
              path="/v1/heatmap"
              badge="RASTER / US TILES"
              badgeColor="#22d3ee"
              desc="Observed ~100 m tiles over the Phoenix and San Jose areas, rendered as a switchable map layer. Its small spatial spread is the empirical proof of the thesis: air cannot tell streets apart - radiant load can."
            />
            <EndpointCell
              path="/v1/status/{id}"
              badge="ASYNC FLOW"
              badgeColor="#a78bfa"
              desc="Every enterprise endpoint returns an activity_id; results are collected on completion. Failures surface with their real upstream status - a 401 renders as a red DEGRADED pill, never as a green 200."
            />
          </div>

          <div className="cell cell-grid reveal overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-[13px]">
              <thead>
                <tr className="border-b border-slate-800/70 text-[9.5px] uppercase tracking-[0.2em] text-slate-500">
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
                      { id: "san_jose", name: "San Jose", raster_tiles: 1920 },
                    ] as CitySummary[])
                ).map((c) => {
                  const cal = cals[c.id];
                  return (
                    <tr key={c.id} className="border-b border-slate-800/50 last:border-0">
                      <td className="px-5 py-3.5 font-medium text-slate-200">{c.name}</td>
                      <td className="px-5 py-3.5 text-slate-400">
                        {cal?.calibrated
                          ? `${cal.air_temp_min_f?.toFixed(1)} - ${cal.air_temp_max_f?.toFixed(1)} °F`
                          : "synthetic model"}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">
                        {cal?.calibrated ? `${String(cal.peak_hour ?? 15).padStart(2, "0")}:00` : "-"}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{cal?.timezone ?? "-"}</td>
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
          <p className="reveal mt-4 text-[10.5px] text-slate-600">
            Ambient ranges above are today&apos;s, fetched from the live API at page load. Tiles
            without raster coverage run the same physics on modelled spatial structure - and are
            labelled as such everywhere they appear.
          </p>
        </div>
      </section>

      {/* ================================================================================
          EDGE TIER
      ================================================================================= */}
      <section id="edge" className="border-b border-slate-800/50">
        {/* minmax(0,1fr) + min-w-0: grid items default to min-width:auto, which lets the
            JSON <pre>'s min-content width propagate upward and force the whole page wider
            than a phone - its own overflow-x-auto never engages. Measured: 530px page at a
            390px viewport without this. */}
        <div className="mx-auto grid max-w-[1400px] gap-12 px-6 py-28 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="reveal min-w-0">
            <div className="eyebrow">MUNICIPAL EDGE TIER</div>
            <h2 className="statement mt-6 text-[32px] text-white sm:text-[44px]">
              Small enough for a kiosk on a metered uplink.
            </h2>
            <p className="mt-7 max-w-xl text-[15px] leading-[1.75] text-slate-400">
              The same routing core serves a bandwidth-optimised endpoint for NVIDIA Jetson
              pedestrian kiosks and delivery-worker wearables: polylines decimated to the
              panel&apos;s resolution, telemetry stripped, one pre-rendered instruction string so
              firmware never does unit conversion. Once a kiosk has the response it needs no further
              network to guide the walk - nothing in the payload is a reference to fetch later, so
              the endpoint reports <span className="text-slate-300">offline_capable</span> only
              after checking that, rather than asserting it. The Jetson hardware tier is simulated;
              the payload and compute figures are measured server-side.
            </p>
            <div className="cell-grid mt-10 grid grid-cols-3">
              <BigStat value="~1.7 KB" label="payload" />
              <BigStat value="~280 ms" label="solve" />
              <BigStat value="OPTIONAL" label="uplink" />
            </div>
          </div>
          <div className="cell cell-grid reveal min-w-0 p-6 font-mono text-[12px] leading-relaxed text-slate-400">
            <div className="eyebrow">POST /api/v1/edge/jetson-kiosk</div>
            <pre className="mt-4 overflow-x-auto whitespace-pre text-[11px]">{`{
  "now":    { "air_f": 109, "surface_f": 164, "risk": "extreme" },
  "route":  { "distance_m": 3018, "minutes": 47, "shade_pct": 54 },
  "savings":{ "thermal_load_f": 1.2, "heat_stress_pct": 5.0 },
  "shelter":{ "name": "Justa Center Respite", "walk_min": 5.1 },
  "instruction": "COOL ROUTE: 3.02 km, 47 min. ...
                  Carry 555 ml water.",
  "edge": {
    "runtime": "NVIDIA Jetson Orin Nano (simulated)",
    "inference_ms": 271.4, "payload_bytes": 1681,
    "offline_capable": true,
    "no_external_references": true
  }
}`}</pre>
          </div>
        </div>
      </section>

      {/* ================================================================================
          VERIFICATION
      ================================================================================= */}
      <section className="border-b border-slate-800/50">
        <div className="mx-auto max-w-[1400px] px-6 py-28">
          <div className="reveal max-w-3xl">
            <div className="eyebrow">VERIFICATION POSTURE</div>
            <h2 className="statement mt-6 text-[32px] text-white sm:text-[44px]">
              Honest by construction.
            </h2>
            <p className="mt-7 max-w-2xl text-[15px] leading-[1.75] text-slate-400">
              A safety product that flatters its own numbers is worse than none. Cryonav&apos;s
              guarantees are enforced in the test suite, not the marketing copy.
            </p>
          </div>

          <div className="cell-grid reveal mt-14 grid sm:grid-cols-2 lg:grid-cols-4">
            <ProofCell
              stat="142"
              label="tests"
              desc="Physics, routing, agents, API surface, upstream failure modes - including a no-regression sweep across every corridor and profile combination."
            />
            {/* The qualifier is not padding. A live Dubai route returns -0.2 F when the
                Sentinel engages, because a mandated shelter stop trades a slightly higher
                mean for a much shorter UNBROKEN high-risk leg - 49.1 min down to 33.3. That
                is the correct safety trade, and the unqualified claim contradicted it. */}
            <ProofCell
              stat="0"
              label="negative savings, unless the Sentinel intervenes"
              desc="If no admissible route beats the direct path on both dose and peak exposure, Cryonav returns the direct path and reports zero - it never manufactures a detour. The exception is a mandated cooling stop, which can raise mean exposure to cut the longest unbroken high-risk leg, because continuous exposure is what causes heat illness."
            />
            <ProofCell
              stat="401 / 200"
              label="degraded is visible"
              desc="An upstream auth failure renders as a red DEGRADED pill with the real status code. Simulated data is labelled simulated, everywhere it appears."
            />
            <ProofCell
              stat="(city, t)"
              label="deterministic"
              desc="Every reading is a pure function of place, time and the day's FortyGuard calibration - runs reproduce byte-for-byte within a calibration day."
            />
          </div>
        </div>
      </section>

      {/* ================================================================================
          CLOSING BAND
      ================================================================================= */}
      <section className="cta-band relative overflow-hidden border-b border-slate-800/50">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-8 px-6 py-24 lg:flex-row lg:items-end lg:justify-between">
          <div className="reveal max-w-2xl">
            <h2 className="statement text-[32px] text-white sm:text-[44px]">
              Route a walk by the heat
              <br />
              a body actually absorbs.
            </h2>
            <p className="mt-6 max-w-lg text-[15px] leading-[1.75] text-slate-400">
              Four cities live. Press verify in the dashboard and watch it call FortyGuard in front
              of you.
            </p>
          </div>
          <div className="reveal flex flex-wrap gap-3">
            <a
              href="/app"
              className="rounded-md bg-white px-6 py-3 text-[12px] font-semibold tracking-[0.1em] text-slate-950 transition hover:bg-slate-200"
            >
              LAUNCH DASHBOARD
            </a>
            <a
              href="https://github.com/mrnetwork0001/Cryonav"
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-slate-600 px-6 py-3 text-[12px] font-semibold tracking-[0.1em] text-slate-200 transition hover:border-slate-400 hover:text-white"
            >
              BROWSE SOURCE
            </a>
          </div>
        </div>
      </section>

      {/* ---- footer ------------------------------------------------------------------- */}
      <footer>
        <div className="mx-auto grid max-w-[1400px] gap-12 px-6 py-16 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="min-w-0">
            <img
              src="/brand/cryonav-wordmark.png"
              alt="Cryonav - Thermal Navigation System"
              className="h-11 w-auto"
              width={506}
              height={128}
            />
            <p className="mt-6 max-w-sm text-[13.5px] leading-relaxed text-slate-400">
              Agentic thermal navigation on the FortyGuard Temperature API&reg;. Live microclimate
              intelligence at 2&nbsp;m above ground, fused with measured urban canopy - returned as
              a walkable, survivable route on real city streets.
            </p>
            <a
              href="https://github.com/mrnetwork0001/Cryonav"
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub"
              className="mt-6 inline-block text-slate-500 transition hover:text-slate-300"
            >
              <svg viewBox="0 0 16 16" className="h-5 w-5 fill-current" aria-hidden>
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
              </svg>
            </a>
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
              ["https://dashboard.fortyguard.com", "Temperature Dashboard"],
              ["https://docs-api.fortyguard.com/docs", "Temperature API Docs"],
              ["https://www.fortyguard.com/hackathon26", "Hackathon '26"],
            ]}
          />
          <FooterCol
            title="RESOURCES"
            links={[
              ["https://github.com/mrnetwork0001/Cryonav", "GitHub"],
              ["/docs", "Documentation"],
              ["/api/docs", "API Reference"],
              ["/api/v1/health", "Live Status"],
              ["https://www.openstreetmap.org/copyright", "OpenStreetMap"],
            ]}
          />
        </div>

        <div className="border-t border-slate-800/50">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-6 text-[10.5px] tracking-[0.06em] text-slate-600">
            <span>&copy; 2026 Cryonav &middot; MIT License &middot; Built for FortyGuard Hackathon &apos;26</span>
            <span className="tnum">
              Map data &copy; OpenStreetMap contributors &middot; Thermal data: FortyGuard
              Temperature API&reg;
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------
   Cell primitives.

   Every one of these renders INSIDE a ruled grid rather than as a floating card, so they
   carry no background, no radius and no shadow - the hairline does the containing. Padding
   is generous because the rule is the only separator, and cramped cells read as a table.
   ------------------------------------------------------------------------------------------ */

function RailStat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="cell px-5 py-6">
      <div className="eyebrow">{label}</div>
      <div className="tnum mt-3 font-mono text-[30px] font-light text-slate-100">{value}</div>
      <div className="mt-1.5 text-[10.5px] leading-snug text-slate-600">{note}</div>
    </div>
  );
}

function BigStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="cell px-5 py-7">
      <div className="tnum font-mono text-[26px] font-light text-slate-100 sm:text-[30px]">
        {value}
      </div>
      <div className="mt-2 text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
    </div>
  );
}

function AgentCell(props: {
  step: string;
  Glyph: (p: { className?: string; strokeWidth?: number }) => React.ReactElement;
  color: string;
  name: string;
  role: string;
  trace: string;
}) {
  return (
    <div className="cell flex flex-col p-7">
      <div className="flex items-center justify-between">
        <span
          className="grid h-10 w-10 place-items-center rounded-md"
          style={{ background: `${props.color}14`, color: props.color }}
        >
          <props.Glyph className="h-[19px] w-[19px]" />
        </span>
        <span className="tnum font-mono text-[11px] text-slate-700">{props.step}</span>
      </div>
      <div className="mt-5 text-[16px] font-medium text-slate-100">{props.name}</div>
      <p
        className="mt-3 flex-1 text-[13px] leading-relaxed text-slate-400"
        dangerouslySetInnerHTML={{ __html: props.role }}
      />
      <div className="mt-6 font-mono text-[10px] tracking-[0.06em] text-slate-600">
        {props.trace}
      </div>
    </div>
  );
}

function EndpointCell(props: { path: string; badge: string; badgeColor: string; desc: string }) {
  return (
    <div className="cell flex flex-col p-7">
      <div className="flex items-start justify-between gap-3">
        <code className="text-[14px] font-medium text-slate-100">{props.path}</code>
        <span
          className="shrink-0 rounded px-2 py-0.5 text-[9px] font-bold tracking-wider"
          style={{ background: `${props.badgeColor}14`, color: props.badgeColor }}
        >
          {props.badge}
        </span>
      </div>
      <p className="mt-4 flex-1 text-[13px] leading-relaxed text-slate-400">{props.desc}</p>
    </div>
  );
}

function ProofCell(props: { stat: string; label: string; desc: string }) {
  return (
    <div className="cell p-7">
      <div className="tnum font-mono text-[30px] font-light text-cyan-300">{props.stat}</div>
      <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        {props.label}
      </div>
      <p className="mt-4 text-[12.5px] leading-relaxed text-slate-500">{props.desc}</p>
    </div>
  );
}

function StreetCell({ tone, point }: { tone: "hot" | "cool"; point: ContrastPoint }) {
  const hot = tone === "hot";
  const rows: [string, string][] = [
    ["Air @ 2 m", `${point.air_temp_2m_f.toFixed(1)} °F`],
    ["Surface", `${point.surface_temp_f.toFixed(1)} °F`],
    ["Mean radiant temp", `${point.mean_radiant_temp_f.toFixed(1)} °F`],
    ["Measured canopy", `${point.canopy_cover_pct.toFixed(0)} %`],
  ];
  return (
    <div
      className="cell relative flex flex-col overflow-hidden p-7 sm:p-9"
      style={{
        background: hot
          ? "linear-gradient(160deg,rgba(239,68,68,0.07),transparent 62%)"
          : "linear-gradient(160deg,rgba(34,211,238,0.06),transparent 62%)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[18px] font-medium text-slate-100">{point.name}</div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
            {point.kind}
          </div>
        </div>
        <span
          className={`shrink-0 rounded px-2 py-1 text-[9px] font-bold tracking-wider ${
            hot ? "bg-rose-500/15 text-rose-400" : "bg-yellow-400/10 text-yellow-300"
          }`}
        >
          {point.risk_level.toUpperCase()}
        </span>
      </div>
      <div className="tnum mt-8 flex-1 space-y-3 text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between border-b border-slate-800/50 pb-3">
            <span className="text-slate-500">{k}</span>
            <span className="font-medium text-slate-200">{v}</span>
          </div>
        ))}
      </div>
      <div className="mt-6 flex items-baseline justify-between">
        <span className="text-[12px] text-slate-500">Exposure index</span>
        <span
          className={`tnum font-mono text-[34px] font-light sm:text-[40px] ${
            hot ? "text-rose-400" : "text-cyan-300"
          }`}
        >
          {point.exposure_index_f.toFixed(1)} °F
        </span>
      </div>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <nav aria-label={title}>
      <div className="eyebrow">{title}</div>
      <ul className="mt-5 space-y-0.5 text-[13px]">
        {links.map(([href, label]) => {
          const external = href.startsWith("http");
          return (
            <li key={label}>
              <a
                href={href}
                {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
                className="-mx-2 block rounded px-2 py-1.5 text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
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

function Arrow() {
  return <IconArrow className="h-3 w-3 text-slate-600" strokeWidth={1.3} />;
}

/* ------------------------------------------------------------------------------------------
   The live product card. Unlike everything above it IS a raised panel, deliberately: it is a
   running instrument rather than page furniture, and lifting it off the ruled ground is what
   marks the difference.
   ------------------------------------------------------------------------------------------ */

function LiveCard(props: {
  feedLive: boolean;
  distanceKm: number;
  gaugePct: number;
  pathALoad: number;
  riskLevel: string;
  shelterApplied: boolean;
  legBefore: number;
  legAfter: number;
  loadSaved: number;
  shadeGain: number;
  addedMin: number;
  shelterName: string;
  solveMs: number;
}) {
  const {
    feedLive, distanceKm, gaugePct, pathALoad, riskLevel, shelterApplied,
    legBefore, legAfter, loadSaved, shadeGain, addedMin, shelterName, solveMs,
  } = props;
  return (
    <div className="live-card relative rounded-xl border border-slate-800 bg-[#0a0e15]/90 p-5">
      <div className="sheen" aria-hidden />
      <div className="flex items-center justify-between px-1">
        <span className="eyebrow">ROUTE REQUEST INGESTED</span>
        <span className="flex items-center gap-1.5 text-[10px] font-semibold tracking-[0.18em]">
          <span
            className={`ping-soft h-1.5 w-1.5 rounded-full ${feedLive ? "bg-emerald-400 text-emerald-400" : "bg-amber-400 text-amber-400"}`}
            style={{ boxShadow: feedLive ? "0 0 8px #34d399" : "0 0 8px #fbbf24" }}
          />
          <span className={feedLive ? "text-emerald-400" : "text-amber-400"}>
            {feedLive ? "LIVE" : "OFFLINE"}
          </span>
        </span>
      </div>

      <div className="mt-4 rounded-lg border border-slate-800 bg-[#0d1219] p-4">
        <div className="flex items-center gap-2">
          <span className="rounded bg-cyan-400/15 px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-cyan-300">
            PHX
          </span>
          <span className="text-[10.5px] text-slate-500">just now</span>
        </div>
        <div className="mt-2 text-[16px] font-medium text-slate-100">
          Capitol Mall &rarr; Roosevelt Row &middot; {distanceKm.toFixed(2)} km
        </div>
        <div className="mt-1 text-[10px] font-medium tracking-[0.16em] text-slate-500">
          OUTDOOR DELIVERY WORKER &middot; 15:00 MST
        </div>
      </div>

      <div className="mt-5 px-1">
        <div className="flex items-baseline justify-between">
          <span className="eyebrow">THERMAL LOAD &middot; DIRECT ROUTE</span>
          <span className="tnum text-[10.5px] text-slate-500">88 - 140 &deg;F</span>
        </div>
        <div className="relative mt-3 h-1.5 rounded-full bg-slate-800">
          <div
            className="gauge-fill absolute inset-y-0 left-0 rounded-full transition-all duration-1000"
            style={{
              width: `${gaugePct}%`,
              background: "linear-gradient(90deg,#818cf8,#22d3ee 30%,#facc15 60%,#fb923c 80%,#ef4444)",
            }}
          />
          <div
            className="ping-soft absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full border-2 border-slate-950 bg-white text-white transition-all duration-1000"
            style={{ left: `calc(${gaugePct}% - 7px)` }}
          />
        </div>
        <div className="tnum mt-2 text-[10.5px] font-semibold tracking-[0.14em] text-slate-400">
          {pathALoad.toFixed(0)}&deg;F &middot; TIER{" "}
          <span className={riskLevel === "extreme" ? "text-rose-400" : "text-orange-400"}>
            {riskLevel.toUpperCase()}
          </span>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-3 px-1">
        <div>
          <div className="eyebrow">{shelterApplied ? "EXPOSURE LEG CUT" : "COOL ROUTE PRICED"}</div>
          <div className="metric-glow tnum mt-1.5 font-mono text-[30px] font-light text-emerald-400 sm:text-[36px]">
            {shelterApplied
              ? `-${(legBefore - legAfter).toFixed(1)} min`
              : `-${loadSaved.toFixed(1)}°F`}
          </div>
        </div>
        <span className="tnum rounded-full border border-emerald-400/40 bg-emerald-400/10 px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] text-emerald-300">
          {shelterApplied
            ? `${legBefore.toFixed(0)} → ${legAfter.toFixed(0)} MIN UNBROKEN`
            : `SHADE ${shadeGain >= 0 ? "+" : "-"}${Math.abs(shadeGain).toFixed(0)}% · ${
                addedMin >= 0 ? "+" : "-"
              }${Math.abs(addedMin).toFixed(1)} MIN`}
        </span>
      </div>
      {shelterApplied && (
        <div className="mt-2 px-1 text-[10.5px] text-slate-500">
          Cooling stop inserted at <span className="text-cyan-300">{shelterName}</span> - shade{" "}
          {shadeGain >= 0 ? "+" : "-"}
          {Math.abs(shadeGain).toFixed(0)}%, {addedMin >= 0 ? "+" : "-"}
          {Math.abs(addedMin).toFixed(1)} min
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-400/25 bg-indigo-500/10 p-3.5 pl-4">
        <div className="flex items-center gap-3">
          <span className="bolt-flicker text-indigo-300">
            <IconInstant className="h-4 w-4" />
          </span>
          <div>
            <div className="text-[11.5px] font-semibold tracking-[0.12em] text-slate-100">
              1-CLICK COOL ROUTE READY
            </div>
            <div className="tnum mt-0.5 text-[9.5px] tracking-[0.08em] text-slate-500">
              FortyGuard 2 m AGL &middot; 3 agents &middot; {solveMs.toFixed(0)} ms solve &middot;
              deterministic
            </div>
          </div>
        </div>
        <a
          href="/app"
          className="rounded-md bg-cyan-400 px-5 py-2.5 text-[11px] font-bold tracking-[0.1em] text-slate-950 transition hover:bg-cyan-300"
        >
          NAVIGATE
        </a>
      </div>
    </div>
  );
}
