import type { NavigationResult } from "../lib/api";
import { IconInstant, IconRefresh } from "./Icons";

interface Props {
  nav: NavigationResult | null;
  onEmergencyReroute: () => void;
  rerouteBusy: boolean;
  rerouteActive: boolean;
}

/**
 * Format a "reduction" figure, where a positive number means the cool route improved on the
 * direct one. Prefixing a literal minus sign produces "−−10.9%" the moment a value goes
 * negative, which happens legitimately whenever a mandated shelter detour trades extra dose
 * for a broken exposure leg. A regression that reads as an improvement is worse than no
 * number at all, so the sign is derived and the tone flips with it.
 */
function delta(reduction: number, unit: string, digits = 1): { text: string; worse: boolean } {
  const worse = reduction < 0;
  const magnitude = Math.abs(reduction).toFixed(digits);
  return { text: `${worse ? "+" : "−"}${magnitude}${unit}`, worse };
}

/**
 * The scoreboard: what did routing through shade actually buy, and is the result still safe?
 */
export default function ExposureCard({
  nav,
  onEmergencyReroute,
  rerouteBusy,
  rerouteActive,
}: Props) {
  if (!nav) {
    return (
      <section className="glass rounded-2xl p-4">
        <SectionTitle>Thermal safety & exposure</SectionTitle>
        <p className="mt-3 text-xs text-slate-500">Solve a route to see the exposure scoreboard.</p>
      </section>
    );
  }

  const c = nav.comparison;
  const a = nav.routes.standard.metrics;
  const b = nav.routes.cool.metrics;
  const safety = nav.safety;

  return (
    <section className="glass rounded-2xl p-4">
      <SectionTitle>Thermal safety & exposure</SectionTitle>

      {/* Headline savings */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat
          label="thermal load"
          value={delta(c.thermal_load_reduction_f, "°F").text}
          tone={c.thermal_load_reduction_f < 0 ? "warn" : "cool"}
          hint="mean 2 m exposure index"
        />
        <Stat
          label="heat stress"
          value={delta(c.heat_stress_reduction_pct, "%", 0).text}
          tone={c.heat_stress_reduction_pct < 0 ? "warn" : "cool"}
          hint="physiological strain score"
        />
        <Stat
          label="shade coverage"
          value={`${c.shade_coverage_gain_pct < 0 ? "−" : "+"}${Math.abs(c.shade_coverage_gain_pct).toFixed(0)}%`}
          tone={c.shade_coverage_gain_pct < 0 ? "warn" : "green"}
          hint="canopy along the path"
        />
        <Stat
          label="time cost"
          value={`${c.added_minutes >= 0 ? "+" : ""}${c.added_minutes.toFixed(1)} min`}
          tone={c.added_minutes <= 2 ? "neutral" : "warn"}
          hint={`${c.added_distance_m >= 0 ? "+" : ""}${c.added_distance_m} m detour`}
        />
      </div>

      {/* A vs B comparison */}
      <div className="mt-4 space-y-2">
        <RouteRow
          accent="#fb7185"
          title="Path A · Standard Direct"
          km={a.distance_km}
          min={a.duration_min}
          exposure={a.mean_exposure_index_f}
          surface={a.peak_surface_temp_f}
          shade={a.shade_coverage_pct}
          risk={a.risk_level}
        />
        <RouteRow
          accent="#22d3ee"
          title="Path B · Cryonav Cool Route"
          km={b.distance_km}
          min={b.duration_min}
          exposure={b.mean_exposure_index_f}
          surface={b.peak_surface_temp_f}
          shade={b.shade_coverage_pct}
          risk={b.risk_level}
        />
      </div>

      {/* Secondary metrics */}
      <div className="tnum mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-slate-700/40 pt-3 text-[11px]">
        <Row k="Heat-strain dose" d={delta(c.thermal_dose_reduction_pct, "%")} />
        <Row k="Peak surface" d={delta(c.surface_temp_avoided_f, "°F", 0)} />
        <Row k="Time in high risk" d={delta(c.high_risk_minutes_avoided, " min")} />
        <Row k="Hydration needed" v={`${b.hydration_ml} ml`} />
      </div>

      {/* Sentinel verdict */}
      <div
        className={`mt-3 rounded-lg border p-3 ${
          safety.ceiling_exceeded
            ? "border-rose-500/40 bg-rose-500/8"
            : "border-emerald-500/30 bg-emerald-500/8"
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300">
            Emergency Thermal Sentinel
          </span>
          <span
            className={`tnum text-[10px] font-bold ${
              safety.ceiling_exceeded ? "text-rose-400" : "text-emerald-400"
            }`}
          >
            {safety.longest_high_risk_leg_min.toFixed(1)} / {safety.continuous_exposure_ceiling_min}{" "}
            min
          </span>
        </div>
        <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
          {safety.ceiling_exceeded
            ? `Longest unbroken high-risk leg exceeds the ${safety.continuous_exposure_ceiling_min} min ceiling for ${nav.profile.label}.`
            : `Longest unbroken high-risk leg is within the ${safety.continuous_exposure_ceiling_min} min ceiling.`}{" "}
          {safety.advisory}
        </p>

        {nav.shelter_reroute.applied && nav.shelter_reroute.shelter && (
          <p className="mt-2 rounded bg-cyan-400/10 px-2 py-1.5 text-[11px] text-cyan-300">
            Shelter break added at <b>{nav.shelter_reroute.shelter.name}</b> -{" "}
            <span className="tnum">
              {nav.shelter_reroute.longest_leg_min_before?.toFixed(1)} →{" "}
              {nav.shelter_reroute.longest_leg_min_after?.toFixed(1)} min
            </span>{" "}
            unbroken exposure.
          </p>
        )}
        {rerouteActive && !nav.shelter_reroute.applied && (
          <p className="mt-2 rounded bg-amber-400/10 px-2 py-1.5 text-[11px] text-amber-300">
            {nav.shelter_reroute.reason ?? "No shelter improved the exposure profile."}
          </p>
        )}
      </div>

      <button
        onClick={onEmergencyReroute}
        disabled={rerouteBusy}
        className={`mt-3 w-full rounded-lg px-3 py-2.5 text-[12px] font-semibold transition ${
          rerouteActive
            ? "border border-cyan-400/50 bg-cyan-400/15 text-cyan-300 hover:bg-cyan-400/25"
            : "border border-rose-400/50 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
        } disabled:cursor-not-allowed disabled:opacity-50`}
      >
        {rerouteBusy ? (
          "Re-solving..."
        ) : (
          <span className="inline-flex items-center justify-center gap-2">
            {rerouteActive ? (
              <IconRefresh className="h-3.5 w-3.5" />
            ) : (
              <IconInstant className="h-3.5 w-3.5" />
            )}
            {rerouteActive ? "Remove cooling-shelter stop" : "1-click cooling station reroute"}
          </span>
        )}
      </button>
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
      {children}
    </h2>
  );
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone: "cool" | "green" | "warn" | "neutral";
  hint: string;
}) {
  const tones = {
    cool: "text-cyan-300 border-cyan-400/25 bg-cyan-400/8",
    green: "text-emerald-300 border-emerald-400/25 bg-emerald-400/8",
    warn: "text-amber-300 border-amber-400/25 bg-amber-400/8",
    neutral: "text-slate-300 border-slate-600/40 bg-slate-500/8",
  } as const;
  return (
    <div className={`rounded-lg border p-2.5 ${tones[tone]}`}>
      <div className="text-[9px] uppercase tracking-[0.1em] opacity-70">{label}</div>
      <div className="tnum mt-0.5 text-[19px] font-semibold leading-none">{value}</div>
      <div className="mt-1 text-[9px] text-slate-500">{hint}</div>
    </div>
  );
}

function RouteRow(props: {
  accent: string;
  title: string;
  km: number;
  min: number;
  exposure: number;
  surface: number;
  shade: number;
  risk: string;
}) {
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-950/40 p-2.5">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: props.accent }} />
        <span className="text-[11px] font-medium text-slate-200">{props.title}</span>
        <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-slate-500">
          {props.risk}
        </span>
      </div>
      <div className="tnum mt-1.5 grid grid-cols-4 gap-1 text-center">
        <Mini k="km" v={props.km.toFixed(2)} />
        <Mini k="min" v={props.min.toFixed(0)} />
        <Mini k="°F load" v={props.exposure.toFixed(0)} />
        <Mini k="% shade" v={props.shade.toFixed(0)} />
      </div>
    </div>
  );
}

function Mini({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[13px] font-semibold text-slate-200">{v}</div>
      <div className="text-[9px] text-slate-600">{k}</div>
    </div>
  );
}

function Row({
  k,
  v,
  d,
}: {
  k: string;
  v?: string;
  d?: { text: string; worse: boolean };
}) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-500">{k}</span>
      <span className={`font-medium ${d?.worse ? "text-amber-400" : "text-slate-300"}`}>
        {d ? d.text : v}
      </span>
    </div>
  );
}
