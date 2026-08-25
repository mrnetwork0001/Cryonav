import type { NavigationResult, ThermalGrid } from "../lib/api";
import { IconDownload } from "./Icons";

interface Props {
  nav: NavigationResult | null;
  grid: ThermalGrid | null;
  cityName: string;
  cityId: string;
  reportDate: string | null;
  hour: number;
  loading: boolean;
  /** Opens the mobile control drawer; the button renders below lg only. */
  onMenu: () => void;
}

const RISK_LABEL: Record<string, string> = {
  low: "LOW RISK",
  moderate: "MODERATE RISK",
  high: "HIGH HEAT RISK",
  extreme: "EXTREME HEAT RISK",
};

export default function TopMetricsBar({ nav, grid, cityName, cityId, reportDate, hour, loading, onMenu }: Props) {
  const ambient = nav?.ambient;
  const risk = ambient?.risk_level ?? "low";
  const color = ambient?.risk_color ?? "#22d3ee";
  const feedOk = nav?.feed.ok ?? false;
  const live = nav?.feed.source === "fortyguard_live";
  const calibrated = nav?.feed.source === "fortyguard_calibrated";
  const degraded = nav?.feed.degraded ?? false;

  return (
    <header className="glass z-20 flex flex-wrap items-stretch gap-px overflow-hidden rounded-2xl">
      {/* Brand - links back to the landing page; burger sits top-right (mobile only) */}
      <div className="flex min-w-[210px] flex-1 items-center gap-3 px-4 py-2.5 md:px-5 md:py-3">
        <a href="/" className="flex items-center" title="Cryonav - home">
          <img
            src="/brand/cryonav-wordmark.png"
            alt="Cryonav - Thermal Navigation System"
            className="h-9 w-auto"
            width={506}
            height={128}
          />
        </a>
        <button
          onClick={onMenu}
          aria-label="Open route controls"
          className="ml-auto grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-slate-700/60 text-slate-300 transition hover:border-cyan-400/50 hover:text-cyan-300 lg:hidden"
        >
          <svg viewBox="0 0 20 20" className="h-5 w-5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
            <path d="M3 5.5h14M3 10h14M3 14.5h14" />
          </svg>
        </button>
      </div>

      <Divider />

      {/* FortyGuard feed status */}
      <div className="flex min-w-[240px] flex-1 flex-col justify-center px-4 py-2.5 md:px-5 md:py-3">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              degraded ? "bg-rose-500" : feedOk ? "bg-emerald-400" : "bg-slate-600"
            }`}
            style={
              degraded
                ? { boxShadow: "0 0 8px #f43f5e" }
                : feedOk
                  ? { boxShadow: "0 0 8px #34d399" }
                  : undefined
            }
          />
          <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
            FortyGuard Temperature API
          </span>
          {degraded && (
            <span className="rounded bg-rose-500/20 px-1.5 py-px text-[9px] font-bold tracking-wide text-rose-300">
              DEGRADED
            </span>
          )}
        </div>
        <div className="tnum mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
          {/* Never render an upstream error status as a green "OK" -- a hidden broken
              integration is worse than a visible outage. */}
          {/* "200 OK · 3.3 ms" used to sit here on every render. No network call had
              happened: that was OUR status and OUR local timing, and it read as though
              FortyGuard had answered in 3.3 ms. A status code is only shown when an
              upstream call was actually attempted; otherwise the strip names the real
              source, and the latency is labelled as local. */}
          <span className={`font-semibold ${degraded ? "text-rose-400" : live ? "text-emerald-400" : "text-sky-400"}`}>
            {nav
              ? degraded
                ? `${nav.feed.upstream_status_code ?? "ERR"} UPSTREAM FAIL`
                : live
                  ? `${nav.feed.upstream_status_code ?? 200} LIVE`
                  : "CALIBRATED FIELD"
              : loading
                ? "…"
                : "-"}
          </span>
          <span>{nav ? `${nav.sensing.elevation_m} m AGL` : "2 m AGL"}</span>
          {nav?.sensing.resolution && (
            <span>
              canopy {nav.sensing.resolution.canopy_m} m · surface{" "}
              {nav.sensing.resolution.surface_temp_m} m
            </span>
          )}
          {nav && <span>{nav.feed.latency_ms.toFixed(1)} ms local</span>}
        </div>
        <div className={`mt-0.5 text-[10px] ${degraded ? "text-rose-400/80" : "text-slate-600"}`}>
          {degraded
            ? nav?.feed.detail
            : live
              ? `live upstream feed · ${nav?.feed.live_fields.length ?? 0}/5 metrics`
              : calibrated
                ? nav?.feed.detail
                : "deterministic microclimate simulation"}
        </div>
      </div>

      <Divider />

      {/* Current temperature + risk meter */}
      <div className="flex min-w-[300px] flex-[1.4] flex-col justify-center px-4 py-2.5 md:px-5 md:py-3">
        <div className="flex items-baseline gap-2">
          <span className="tnum text-[26px] font-semibold leading-none text-slate-50">
            {ambient ? `${ambient.air_temp_2m_f.toFixed(0)}°F` : "-"}
          </span>
          <span
            className="rounded px-2 py-0.5 text-[10px] font-bold tracking-wide"
            style={{ background: `${color}22`, color, border: `1px solid ${color}55` }}
          >
            {RISK_LABEL[risk]}
          </span>
        </div>
        <div className="tnum mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-slate-500">
          <span>
            surface{" "}
            <b className="text-orange-400">
              {ambient ? `${ambient.surface_temp_f.toFixed(0)}°F` : "-"}
            </b>
          </span>
          <span>
            feels <b className="text-slate-300">{ambient ? `${ambient.heat_index_f.toFixed(0)}°F` : "-"}</b>
          </span>
          <span>WBGT {ambient ? ambient.wbgt_f.toFixed(0) : "-"}</span>
          <span>RH {ambient ? `${ambient.relative_humidity_pct.toFixed(0)}%` : "-"}</span>
        </div>
        <RiskMeter value={ambient?.exposure_index_f ?? 0} />
      </div>

      <Divider />

      {/* Tile context */}
      <div className="flex min-w-[190px] flex-1 flex-col justify-center px-4 py-2.5 md:px-5 md:py-3">
        <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Coverage tile</div>
        <div className="mt-1 text-[13px] font-medium text-slate-200">{cityName}</div>
        <div className="tnum mt-0.5 text-[11px] text-slate-500">
          {grid ? `${grid.tile_area_mi2} mi²` : "-"} ·{" "}
          {String(Math.floor(hour)).padStart(2, "0")}:
          {String(Math.round((hour % 1) * 60)).padStart(2, "0")} local
        </div>
        {grid && (
          <div className="tnum mt-0.5 text-[10px] text-rose-400/80">
            {grid.stats.extreme_cell_pct}% of tile in extreme band
          </div>
        )}
        {reportDate && (
          <a
            href={`/api/v1/cities/${cityId}/report.pdf`}
            target="_blank"
            rel="noreferrer"
            className="tnum mt-1 inline-flex w-fit items-center gap-1 rounded border border-cyan-400/30 bg-cyan-400/8 px-1.5 py-0.5 text-[9px] font-semibold tracking-wider text-cyan-300 transition hover:bg-cyan-400/15"
            title="FortyGuard heat-intelligence analyst report, generated upstream and cached daily"
          >
            <IconDownload className="h-3.5 w-3.5" />
            FG ANALYST REPORT · {reportDate.slice(5)}
          </a>
        )}
      </div>
    </header>
  );
}

function Divider() {
  // Below md the sections stack full-width, so a 1px vertical divider separates nothing --
  // it just renders as a stray tick in the right gutter.
  return <div className="hidden w-px shrink-0 self-stretch bg-slate-700/40 md:block" />;
}

/** Position of the current exposure index across the comfort → survival-limit span. */
function RiskMeter({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, ((value - 88) / (140 - 88)) * 100));
  return (
    <div className="mt-2">
      <div
        className="relative h-1.5 w-full overflow-hidden rounded-full"
        style={{
          background: "linear-gradient(90deg,#22d3ee 0%,#facc15 42%,#fb923c 62%,#ef4444 100%)",
        }}
      >
        <div className="absolute inset-y-0 right-0 bg-slate-950/70" style={{ width: `${100 - pct}%` }} />
        <div
          className="absolute top-1/2 h-3 w-[2px] -translate-y-1/2 bg-white shadow-[0_0_6px_white]"
          style={{ left: `calc(${pct}% - 1px)` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[9px] uppercase tracking-wider text-slate-600">
        <span>comfort 88°F</span>
        <span className="tnum text-slate-400">thermal load {value ? value.toFixed(1) : "-"}°F</span>
        <span>survival 140°F</span>
      </div>
    </div>
  );
}
