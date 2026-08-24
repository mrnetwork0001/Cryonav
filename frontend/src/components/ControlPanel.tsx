import type { CitySummary, GridSource, Meta, Preset } from "../lib/api";

interface Props {
  cities: CitySummary[];
  meta: Meta | null;
  cityId: string;
  profileId: string;
  hour: number;
  presets: Preset[];
  activePreset: string | null;
  pickMode: "origin" | "destination" | null;
  toggles: {
    showHeat: boolean;
    showStandard: boolean;
    showCool: boolean;
    showShelters: boolean;
    showCorridors: boolean;
  };
  gridSource: GridSource;
  rasterAvailable: boolean;
  loading: boolean;
  onCity: (id: string) => void;
  onProfile: (id: string) => void;
  onHour: (h: number) => void;
  onPreset: (p: Preset) => void;
  onPickMode: (m: "origin" | "destination" | null) => void;
  onToggle: (key: keyof Props["toggles"]) => void;
  onGridSource: (s: GridSource) => void;
  onSolve: () => void;
}

export default function ControlPanel(p: Props) {
  return (
    <section className="glass space-y-4 rounded-2xl p-4">
      <div>
        <Label>Coverage tile</Label>
        <div className="mt-1.5 grid grid-cols-3 gap-1">
          {p.cities.map((c) => (
            <button
              key={c.id}
              onClick={() => p.onCity(c.id)}
              className={`rounded-lg border px-2 py-2 text-[11px] font-medium transition ${
                c.id === p.cityId
                  ? "border-cyan-400/50 bg-cyan-400/15 text-cyan-300"
                  : "border-slate-700/50 bg-slate-900/40 text-slate-400 hover:border-slate-600 hover:text-slate-200"
              }`}
            >
              {c.name}
              <span className="mt-0.5 block text-[9px] font-normal text-slate-600">
                design {c.air_temp_max_f}°F
              </span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <Label>User profile</Label>
        <div className="mt-1.5 space-y-1">
          {(p.meta?.profiles ?? []).map((prof) => (
            <button
              key={prof.id}
              onClick={() => p.onProfile(prof.id)}
              title={prof.description}
              className={`w-full rounded-lg border px-2.5 py-2.5 text-left text-[11px] transition lg:py-1.5 ${
                prof.id === p.profileId
                  ? "border-cyan-400/50 bg-cyan-400/12 text-cyan-300"
                  : "border-slate-700/50 bg-slate-900/40 text-slate-400 hover:border-slate-600 hover:text-slate-200"
              }`}
            >
              <span className="font-medium">{prof.label}</span>
              <span className="ml-1.5 text-[9px] text-slate-600">
                ≤{Math.round((prof.max_detour_ratio - 1) * 100)}% detour
              </span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between">
          <Label>Time of day</Label>
          <span className="tnum text-[11px] font-semibold text-cyan-300">
            {String(Math.floor(p.hour)).padStart(2, "0")}:
            {String(Math.round((p.hour % 1) * 60)).padStart(2, "0")}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={23.5}
          step={0.5}
          value={p.hour}
          onChange={(e) => p.onHour(Number(e.target.value))}
          className="mt-2 h-6 w-full accent-cyan-400 lg:h-auto"
        />
        <div className="mt-0.5 flex justify-between text-[9px] text-slate-600">
          <span>00:00</span>
          <span>solar peak 15:00</span>
          <span>23:30</span>
        </div>
      </div>

      <div>
        <Label>Demo corridors</Label>
        <div className="mt-1.5 space-y-1">
          {p.presets.map((preset) => (
            <button
              key={preset.id}
              onClick={() => p.onPreset(preset)}
              className={`w-full rounded-lg border px-2.5 py-2.5 text-left text-[11px] transition lg:py-1.5 ${
                preset.id === p.activePreset
                  ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-300"
                  : "border-slate-700/50 bg-slate-900/40 text-slate-400 hover:border-slate-600 hover:text-slate-200"
              }`}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <div className="mt-1.5 grid grid-cols-2 gap-1">
          <PickButton
            active={p.pickMode === "origin"}
            onClick={() => p.onPickMode(p.pickMode === "origin" ? null : "origin")}
          >
            Set origin
          </PickButton>
          <PickButton
            active={p.pickMode === "destination"}
            onClick={() => p.onPickMode(p.pickMode === "destination" ? null : "destination")}
          >
            Set destination
          </PickButton>
        </div>
      </div>

      <div>
        <Label>Heat layer source</Label>
        <div className="mt-1.5 grid grid-cols-2 gap-1">
          <button
            onClick={() => p.onGridSource("model")}
            className={`rounded-lg border px-2 py-2.5 text-[10px] transition lg:py-1.5 ${
              p.gridSource === "model"
                ? "border-cyan-400/50 bg-cyan-400/12 text-cyan-300"
                : "border-slate-700/50 bg-slate-900/40 text-slate-500 hover:text-slate-300"
            }`}
            title="Cryonav's composite exposure index — the field the routes optimise on"
          >
            Exposure model
          </button>
          <button
            onClick={() => p.rasterAvailable && p.onGridSource("fortyguard")}
            disabled={!p.rasterAvailable}
            className={`rounded-lg border px-2 py-2.5 text-[10px] transition lg:py-1.5 ${
              p.gridSource === "fortyguard"
                ? "border-emerald-400/50 bg-emerald-400/12 text-emerald-300"
                : p.rasterAvailable
                  ? "border-slate-700/50 bg-slate-900/40 text-slate-500 hover:text-slate-300"
                  : "cursor-not-allowed border-slate-800 bg-slate-900/20 text-slate-700"
            }`}
            title={
              p.rasterAvailable
                ? "Raw FortyGuard /v1/heatmap raster — observed ~100 m tiles, no Cryonav modelling"
                : "No FortyGuard raster coverage for this tile (raster product is US-only)"
            }
          >
            FortyGuard raster
          </button>
        </div>
      </div>

      <div>
        <Label>Map layers</Label>
        <div className="mt-1.5 grid grid-cols-2 gap-1">
          <Toggle on={p.toggles.showHeat} onClick={() => p.onToggle("showHeat")} dot="#ef4444">
            Heat grid
          </Toggle>
          <Toggle
            on={p.toggles.showCorridors}
            onClick={() => p.onToggle("showCorridors")}
            dot="#4ade80"
          >
            Canopy
          </Toggle>
          <Toggle
            on={p.toggles.showStandard}
            onClick={() => p.onToggle("showStandard")}
            dot="#fb7185"
          >
            Path A
          </Toggle>
          <Toggle on={p.toggles.showCool} onClick={() => p.onToggle("showCool")} dot="#22d3ee">
            Path B
          </Toggle>
          <Toggle
            on={p.toggles.showShelters}
            onClick={() => p.onToggle("showShelters")}
            dot="#38bdf8"
          >
            Shelters
          </Toggle>
        </div>
      </div>

      <button
        onClick={p.onSolve}
        disabled={p.loading}
        className="w-full rounded-lg bg-gradient-to-r from-cyan-500 to-cyan-600 px-3 py-2.5 text-[12px] font-semibold text-slate-950 transition hover:from-cyan-400 hover:to-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {p.loading ? "Running agents…" : "Compute cool route"}
      </button>
    </section>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
      {children}
    </span>
  );
}

function Toggle({
  on,
  onClick,
  dot,
  children,
}: {
  on: boolean;
  onClick: () => void;
  dot: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-lg border px-2 py-2.5 text-[10px] transition lg:py-1.5 ${
        on
          ? "border-slate-600 bg-slate-800/60 text-slate-200"
          : "border-slate-800 bg-slate-900/30 text-slate-600"
      }`}
    >
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: on ? dot : "#334155" }}
      />
      {children}
    </button>
  );
}

function PickButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border px-2 py-2.5 text-[10px] transition lg:py-1.5 ${
        active
          ? "border-cyan-400/60 bg-cyan-400/15 text-cyan-300"
          : "border-slate-700/50 bg-slate-900/40 text-slate-500 hover:text-slate-300"
      }`}
    >
      {children}
    </button>
  );
}
