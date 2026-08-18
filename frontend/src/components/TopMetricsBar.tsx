import type { NavigationResult, ThermalGrid } from "../lib/api";

interface Props {
  nav: NavigationResult | null;
  grid: ThermalGrid | null;
  cityName: string;
  hour: number;
  loading: boolean;
}

const RISK_LABEL: Record<string, string> = {
  low: "LOW RISK",
  moderate: "MODERATE RISK",
  high: "HIGH HEAT RISK",
  extreme: "EXTREME HEAT RISK",
};

export default function TopMetricsBar({ nav, grid, cityName, hour, loading }: Props) {
  const ambient = nav?.ambient;
  const risk = ambient?.risk_level ?? "low";
  const color = ambient?.risk_color ?? "#22d3ee";
  const feedOk = nav?.feed.ok ?? false;
  const live = nav?.feed.source === "fortyguard_live";

  return (
    <header className="glass z-20 flex flex-wrap items-stretch gap-px overflow-hidden rounded-xl">
      {/* Brand */}
      <div className="flex min-w-[210px] flex-1 items-center gap-3 px-5 py-3">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg font-bold text-slate-950"
          style={{ background: "linear-gradient(135deg,#22d3ee,#0891b2)" }}
        >
          ❄
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-slate-100">CRYONAV</div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            Thermal Navigation Engine
          </div>
        </div>
      </div>

      <Divider />

      {/* FortyGuard feed status */}
      <div className="flex min-w-[240px] flex-1 flex-col justify-center px-5 py-3">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${feedOk ? "bg-emerald-400" : "bg-slate-600"}`}
            style={feedOk ? { boxShadow: "0 0 8px #34d399" } : undefined}
          />
          <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
            FortyGuard Temperature API
          </span>
        </div>
        <div className="tnum mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
          <span className="font-semibold text-emerald-400">
            {nav ? `${nav.feed.status_code} OK` : loading ? "…" : "—"}
          </span>
          <span>{nav ? `${nav.sensing.resolution_mi2} mi² resolution` : "10 mi² resolution"}</span>
          <span>{nav ? `${nav.sensing.elevation_m} m AGL` : "2 m AGL"}</span>
          {nav && <span>{nav.feed.latency_ms.toFixed(1)} ms</span>}
        </div>
        <div className="mt-0.5 text-[10px] text-slate-600">
          {live ? "live upstream feed" : "deterministic microclimate simulation"}
        </div>
      </div>

      <Divider />

      {/* Current temperature + risk meter */}
      <div className="flex min-w-[300px] flex-[1.4] flex-col justify-center px-5 py-3">
        <div className="flex items-baseline gap-2">
          <span className="tnum text-[26px] font-semibold leading-none text-slate-50">
            {ambient ? `${ambient.air_temp_2m_f.toFixed(0)}°F` : "—"}
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
              {ambient ? `${ambient.surface_temp_f.toFixed(0)}°F` : "—"}
            </b>
          </span>
          <span>
            feels <b className="text-slate-300">{ambient ? `${ambient.heat_index_f.toFixed(0)}°F` : "—"}</b>
          </span>
          <span>WBGT {ambient ? ambient.wbgt_f.toFixed(0) : "—"}</span>
          <span>RH {ambient ? `${ambient.relative_humidity_pct.toFixed(0)}%` : "—"}</span>
        </div>
        <RiskMeter value={ambient?.exposure_index_f ?? 0} />
      </div>

      <Divider />

      {/* Tile context */}
      <div className="flex min-w-[190px] flex-1 flex-col justify-center px-5 py-3">
        <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">Coverage tile</div>
        <div className="mt-1 text-[13px] font-medium text-slate-200">{cityName}</div>
        <div className="tnum mt-0.5 text-[11px] text-slate-500">
          {grid ? `${grid.tile_area_mi2} mi²` : "—"} ·{" "}
          {String(Math.floor(hour)).padStart(2, "0")}:
          {String(Math.round((hour % 1) * 60)).padStart(2, "0")} local
        </div>
        {grid && (
          <div className="tnum mt-0.5 text-[10px] text-rose-400/80">
            {grid.stats.extreme_cell_pct}% of tile in extreme band
          </div>
        )}
      </div>
    </header>
  );
}

function Divider() {
  return <div className="w-px shrink-0 self-stretch bg-slate-700/40" />;
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
        <span className="tnum text-slate-400">thermal load {value ? value.toFixed(1) : "—"}°F</span>
        <span>survival 140°F</span>
      </div>
    </div>
  );
}
