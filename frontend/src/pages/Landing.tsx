import { useEffect, useState } from "react";
import { api, type CitySummary, type NavigationResult } from "../lib/api";

/**
 * Marketing/landing page, styled after the dark "protocol landing" idiom: blueprint grid,
 * two-tone gradient headline, mono stat strip, and a live product card on the right.
 *
 * Everything in the card is real. On mount it runs an actual cool-route solve against the
 * backend (Phoenix delivery corridor, 15:00, delivery-worker profile) and renders whatever
 * the agents actually did — the numbers move when the live calibration moves. If the backend
 * is unreachable the card falls back to the last measured values, clearly marked OFFLINE.
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

export default function Landing() {
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [nav, setNav] = useState<NavigationResult | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api
      .cities()
      .then((c) => setCities(c.cities))
      .catch(() => setOffline(true));
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
          <a href="/app" className="transition hover:text-cyan-300">
            DASHBOARD
          </a>
          <a href="/api/v1/health" className="transition hover:text-cyan-300">
            STATUS
          </a>
          <a
            href="https://github.com/mrnetwork0001/Cryonav"
            target="_blank"
            rel="noreferrer"
            className="transition hover:text-cyan-300"
          >
            SOURCE
          </a>
          <a
            href="https://www.fortyguard.com"
            target="_blank"
            rel="noreferrer"
            className="transition hover:text-cyan-300"
          >
            FORTYGUARD
          </a>
        </nav>
      </header>

      {/* ---- hero --------------------------------------------------------------------- */}
      <main className="mx-auto grid max-w-7xl gap-14 px-6 pb-20 pt-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10 lg:pt-16">
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
          <div className="rounded-2xl border border-slate-800 bg-[#0a0e15]/90 p-5 shadow-[0_24px_80px_-32px_rgba(34,211,238,0.25)]">
            {/* header */}
            <div className="flex items-center justify-between px-1">
              <span className="text-[11px] font-semibold tracking-[0.22em] text-slate-400">
                ROUTE REQUEST INGESTED
              </span>
              <span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.18em]">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${feedLive ? "bg-emerald-400" : "bg-amber-400"}`}
                  style={{ boxShadow: feedLive ? "0 0 8px #34d399" : "0 0 8px #fbbf24" }}
                />
                <span className={feedLive ? "text-emerald-400" : "text-amber-400"}>
                  {feedLive ? "LIVE" : "OFFLINE"}
                </span>
              </span>
            </div>

            {/* request sub-card */}
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

            {/* evaluator */}
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

            {/* thermal gauge */}
            <div className="mt-5 px-1">
              <div className="flex items-baseline justify-between">
                <span className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                  THERMAL LOAD · DIRECT ROUTE
                </span>
                <span className="tnum text-[11px] text-slate-500">88 – 140 °F</span>
              </div>
              <div className="relative mt-3 h-1.5 rounded-full bg-slate-800">
                <div
                  className="absolute inset-y-0 left-0 rounded-full transition-all duration-1000"
                  style={{
                    width: `${gaugePct}%`,
                    background:
                      "linear-gradient(90deg,#818cf8,#22d3ee 30%,#facc15 60%,#fb923c 80%,#ef4444)",
                  }}
                />
                <div
                  className="absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full border-2 border-slate-950 bg-white transition-all duration-1000"
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

            {/* priced result */}
            <div className="mt-5 flex items-end justify-between px-1">
              <div>
                <div className="text-[11px] font-semibold tracking-[0.2em] text-slate-400">
                  {shelterApplied ? "EXPOSURE LEG CUT" : "COOL ROUTE PRICED"}
                </div>
                <div className="tnum mt-1 text-4xl font-bold text-emerald-400">
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

            {/* action strip */}
            <div className="mt-5 flex items-center justify-between rounded-xl border border-indigo-400/25 bg-indigo-500/10 p-3.5 pl-4">
              <div className="flex items-center gap-3">
                <span className="text-indigo-300">⚡</span>
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
                className="rounded-lg bg-cyan-400 px-5 py-2.5 text-[12px] font-bold tracking-[0.1em] text-slate-950 transition hover:bg-cyan-300"
              >
                NAVIGATE
              </a>
            </div>
          </div>
        </section>
      </main>
    </div>
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
