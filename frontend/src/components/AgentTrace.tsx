import type { NavigationResult, ThermalGrid } from "../lib/api";

interface Props {
  nav: NavigationResult | null;
  grid: ThermalGrid | null;
}

const AGENT_META: Record<string, { label: string; color: string; glyph: string }> = {
  thermal_sensing: { label: "Thermal Sensing", color: "#facc15", glyph: "◈" },
  cool_route_optimizer: { label: "Cool-Route Optimizer", color: "#22d3ee", glyph: "⬡" },
  emergency_sentinel: { label: "Emergency Sentinel", color: "#fb7185", glyph: "⬢" },
};

/** Renders the agents' actual working trace, so the reasoning is shown rather than claimed. */
export default function AgentTrace({ nav, grid }: Props) {
  return (
    <section className="glass flex min-h-0 flex-col rounded-xl p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Agent orchestration trace
        </h2>
        {nav && (
          <span className="tnum text-[10px] text-slate-500">
            {nav.agent_trace.length} steps · {nav.compute_ms.toFixed(0)} ms
          </span>
        )}
      </div>

      {grid && (
        <div className="tnum mt-2 flex items-center gap-2 rounded-lg border border-slate-700/40 bg-slate-950/40 px-2.5 py-1.5 text-[10px] text-slate-500">
          <span>{grid?.source === "fortyguard_heatmap" ? "FG observed air" : "tile exposure"}</span>
          <span className="text-cyan-300">{grid.stats.min_exposure_f}°F</span>
          <div
            className="h-1.5 flex-1 rounded-full"
            style={{
              background:
                "linear-gradient(90deg,#082f49,#22d3ee 28%,#facc15 52%,#fb923c 76%,#ef4444)",
            }}
          />
          <span className="text-rose-400">{grid.stats.max_exposure_f}°F</span>
        </div>
      )}

      <div className="scroll-thin mt-3 max-h-[60vh] space-y-2 overflow-y-auto pr-1 lg:max-h-none lg:min-h-0 lg:flex-1">
        {!nav && <p className="text-xs text-slate-500">Run a route to watch the agents work.</p>}

        {nav?.agent_trace.map((step) => {
          const meta = AGENT_META[step.agent] ?? {
            label: step.agent,
            color: "#94a3b8",
            glyph: "•",
          };
          return (
            <div
              key={step.step}
              className="rounded-lg border border-slate-700/40 bg-slate-950/40 p-2.5"
              style={{ borderLeft: `2px solid ${meta.color}` }}
            >
              <div className="flex items-center gap-1.5">
                <span style={{ color: meta.color }} className="text-[11px]">
                  {meta.glyph}
                </span>
                <span className="text-[10px] font-semibold" style={{ color: meta.color }}>
                  {meta.label}
                </span>
                <span className="text-[9px] text-slate-600">{step.action}</span>
                {step.elapsed_ms > 0 && (
                  <span className="tnum ml-auto text-[9px] text-slate-600">
                    {step.elapsed_ms.toFixed(1)} ms
                  </span>
                )}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{step.detail}</p>
            </div>
          );
        })}

        {nav && nav.hotspots.length > 0 && (
          <div className="rounded-lg border border-rose-500/25 bg-rose-500/5 p-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-rose-400">
              Asphalt traps on Path A
            </div>
            <div className="tnum mt-1.5 space-y-1">
              {nav.hotspots.map((h, i) => (
                <div key={i} className="flex justify-between text-[10px]">
                  <span className="text-slate-500">{h.surface_type.replace(/_/g, " ")}</span>
                  <span className="text-slate-300">
                    {h.surface_temp_f}°F surface{" "}
                    <span className="text-rose-400">(+{h.asphalt_radiation_spike_f} over air)</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
