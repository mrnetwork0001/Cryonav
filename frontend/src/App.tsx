import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type CityLayers,
  type CitySummary,
  type GridSource,
  type Meta,
  type NavigationResult,
  type Preset,
  type ThermalGrid,
} from "./lib/api";
import MapCanvas from "./components/MapCanvas";
import TopMetricsBar from "./components/TopMetricsBar";
import ExposureCard from "./components/ExposureCard";
import ControlPanel from "./components/ControlPanel";
import AgentTrace from "./components/AgentTrace";
import TransitSim, { type SimFrame } from "./components/TransitSim";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [cities, setCities] = useState<CitySummary[]>([]);
  const [cityId, setCityId] = useState("phoenix");
  const [profileId, setProfileId] = useState("delivery_worker");
  const [hour, setHour] = useState(15);

  const [grid, setGrid] = useState<ThermalGrid | null>(null);
  const [gridSource, setGridSource] = useState<GridSource>("model");
  const [layers, setLayers] = useState<CityLayers | null>(null);
  const [nav, setNav] = useState<NavigationResult | null>(null);

  const [origin, setOrigin] = useState<[number, number] | null>(null);
  const [destination, setDestination] = useState<[number, number] | null>(null);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [pickMode, setPickMode] = useState<"origin" | "destination" | null>(null);

  const [shelterReroute, setShelterReroute] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [simFrame, setSimFrame] = useState<SimFrame | null>(null);
  const [loading, setLoading] = useState(false);
  const [rerouteBusy, setRerouteBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [toggles, setToggles] = useState({
    showHeat: true,
    showStandard: true,
    showCool: true,
    showShelters: true,
    showCorridors: true,
  });

  const city = useMemo(() => cities.find((c) => c.id === cityId) ?? null, [cities, cityId]);

  // -- bootstrap -------------------------------------------------------------------------
  useEffect(() => {
    Promise.all([api.meta(), api.cities()])
      .then(([m, c]) => {
        setMeta(m);
        setCities(c.cities);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // -- when the city changes, load its tile and jump to the first demo corridor ------------
  useEffect(() => {
    if (!city) return;
    setLayers(null);
    api.layers(city.id).then(setLayers).catch((e) => setError(String(e)));

    const preset = city.presets[0];
    if (preset) {
      setOrigin(preset.origin.coords);
      setDestination(preset.destination.coords);
      setActivePreset(preset.id);
    }
  }, [city?.id]);

  // Cities without a cached FortyGuard raster can only show the model layer.
  useEffect(() => {
    if (city && city.raster_tiles === 0 && gridSource === "fortyguard") {
      setGridSource("model");
    }
  }, [city?.id]);

  // -- thermal grid follows city + hour + source --------------------------------------------
  useEffect(() => {
    if (!city) return;
    let cancelled = false;
    api
      .grid(city.id, hour, 40, gridSource)
      .then((g) => !cancelled && setGrid(g))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [city?.id, hour, gridSource]);

  // -- solve ------------------------------------------------------------------------------
  const solve = useCallback(
    async (withShelter: boolean) => {
      if (!city || !origin || !destination) return;
      setError(null);
      withShelter === shelterReroute ? setLoading(true) : setRerouteBusy(true);
      try {
        const result = await api.coolRoute({
          origin: { lat: origin[0], lon: origin[1] },
          destination: { lat: destination[0], lon: destination[1] },
          city_id: city.id,
          hour,
          profile: profileId,
          allow_shelter_reroute: withShelter,
        });
        setNav(result);
        setShelterReroute(withShelter);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
        setRerouteBusy(false);
      }
    },
    [city, origin, destination, hour, profileId, shelterReroute],
  );

  // Auto-solve whenever the inputs settle. Debounced so dragging the time slider does not
  // fire a request per half-hour step.
  const solveRef = useRef(solve);
  solveRef.current = solve;
  useEffect(() => {
    if (!city || !origin || !destination) return;
    const t = setTimeout(() => solveRef.current(shelterReroute), 220);
    return () => clearTimeout(t);
  }, [city?.id, origin, destination, hour, profileId]);

  const applyPreset = (p: Preset) => {
    setOrigin(p.origin.coords);
    setDestination(p.destination.coords);
    setActivePreset(p.id);
    setPickMode(null);
  };

  const pickPoint = (which: "origin" | "destination", coords: [number, number]) => {
    if (which === "origin") setOrigin(coords);
    else setDestination(coords);
    setActivePreset(null);
    setPickMode(null);
  };

  if (!city) {
    return (
      <div className="grid h-full place-items-center bg-[#0b0f17] text-slate-500">
        <div className="text-center">
          <div className="text-sm">{error ? "Backend unreachable" : "Loading Cryonav…"}</div>
          {error && (
            <pre className="mt-3 max-w-xl overflow-auto rounded-lg bg-slate-900/70 p-3 text-left text-[10px] text-rose-400">
              {error}
            </pre>
          )}
        </div>
      </div>
    );
  }

  return (
    // Mobile (<lg): a normal flowing page — the document scrolls, the map gets an explicit
    // viewport-relative height, and the map comes FIRST so a phone user isn't forced through
    // ~800px of controls to reach it. Desktop (lg+): the original locked three-column shell
    // with per-column scrolling. Without this split the columns collapse to 8px slivers on a
    // phone and nothing is operable (measured, not hypothetical).
    <div className="flex min-h-full flex-col gap-3 bg-[#0b0f17] p-3 lg:h-full">
      <TopMetricsBar
        nav={nav}
        grid={grid}
        cityName={`${city.name}, ${city.region}`}
        cityId={city.id}
        reportDate={city.has_report ? city.report_date : null}
        hour={hour}
        loading={loading}
        onMenu={() => setDrawerOpen(true)}
      />

      <main className="flex flex-1 flex-col gap-3 lg:grid lg:min-h-0 lg:grid-cols-[300px_minmax(0,1fr)_340px]">
        <div className="scroll-thin hidden lg:block lg:min-h-0 lg:overflow-y-auto">
          <ControlPanel
            cities={cities}
            meta={meta}
            cityId={cityId}
            profileId={profileId}
            hour={hour}
            presets={city.presets}
            activePreset={activePreset}
            pickMode={pickMode}
            toggles={toggles}
            gridSource={gridSource}
            rasterAvailable={city.raster_tiles > 0}
            loading={loading}
            onCity={setCityId}
            onProfile={setProfileId}
            onHour={setHour}
            onPreset={applyPreset}
            onPickMode={setPickMode}
            onToggle={(k) => setToggles((t) => ({ ...t, [k]: !t[k] }))}
            onGridSource={setGridSource}
            onSolve={() => solve(shelterReroute)}
          />
        </div>

        <div className="glass relative h-[58vh] min-h-[380px] overflow-hidden rounded-xl lg:h-auto lg:min-h-[420px]">
          <MapCanvas
            city={city}
            grid={grid}
            layers={layers}
            nav={nav}
            showHeat={toggles.showHeat}
            showStandard={toggles.showStandard}
            showCool={toggles.showCool}
            showShelters={toggles.showShelters}
            showCorridors={toggles.showCorridors}
            onPickPoint={pickPoint}
            pickMode={pickMode}
            sim={simFrame}
          />
          <MapLegend />
          {error && (
            <div className="absolute bottom-3 left-3 z-[1000] max-w-md rounded-lg border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-[10px] text-rose-300">
              {error}
            </div>
          )}
        </div>

        <div className="scroll-thin flex flex-col gap-3 lg:min-h-0 lg:overflow-y-auto">
          <ExposureCard
            nav={nav}
            onEmergencyReroute={() => solve(!shelterReroute)}
            rerouteBusy={rerouteBusy}
            rerouteActive={shelterReroute}
          />
          <TransitSim
            nav={nav}
            cityId={cityId}
            hour={hour}
            profileId={profileId}
            onFrame={setSimFrame}
          />
          <AgentTrace nav={nav} grid={grid} />
        </div>
      </main>

      {/* ---- mobile control drawer -------------------------------------------------------
          The control panel lives here below lg (the inline column is desktop-only). Kept
          mounted so the slide transition runs; actions that hand focus back to the map —
          picking a preset, arming a map pick, solving — close it automatically. */}
      <div
        onClick={() => setDrawerOpen(false)}
        className={`fixed inset-0 z-[1190] bg-black/60 backdrop-blur-sm transition-opacity duration-300 lg:hidden ${
          drawerOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        aria-hidden
      />
      <aside
        className={`scroll-thin fixed inset-y-0 left-0 z-[1200] w-[85vw] max-w-[340px] overflow-y-auto bg-[#0b0f17] p-3 shadow-[8px_0_40px_-12px_rgba(0,0,0,0.9)] transition-transform duration-300 lg:hidden ${
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Route controls"
      >
        <div className="mb-3 flex items-center justify-between px-1">
          <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Route controls
          </span>
          <button
            onClick={() => setDrawerOpen(false)}
            aria-label="Close controls"
            className="grid h-9 w-9 place-items-center rounded-lg border border-slate-700/60 text-slate-400 transition hover:text-slate-200"
          >
            ✕
          </button>
        </div>
        <ControlPanel
          cities={cities}
          meta={meta}
          cityId={cityId}
          profileId={profileId}
          hour={hour}
          presets={city.presets}
          activePreset={activePreset}
          pickMode={pickMode}
          toggles={toggles}
          gridSource={gridSource}
          rasterAvailable={city.raster_tiles > 0}
          loading={loading}
          onCity={setCityId}
          onProfile={setProfileId}
          onHour={setHour}
          onPreset={(pr) => {
            applyPreset(pr);
            setDrawerOpen(false);
          }}
          onPickMode={(m) => {
            setPickMode(m);
            if (m) setDrawerOpen(false);
          }}
          onToggle={(k) => setToggles((t) => ({ ...t, [k]: !t[k] }))}
          onGridSource={setGridSource}
          onSolve={() => {
            solve(shelterReroute);
            setDrawerOpen(false);
          }}
        />
      </aside>
    </div>
  );
}

function MapLegend() {
  const items = [
    { color: "#fb7185", label: "Path A · standard", dash: true },
    { color: "#22d3ee", label: "Path B · cool route", dash: true },
    { color: "#ef4444", label: "asphalt trap", dash: false },
    { color: "#38bdf8", label: "cooling shelter", dash: false },
  ];
  return (
    <div className="glass pointer-events-none absolute bottom-3 right-3 z-[1000] hidden rounded-lg px-3 py-2 sm:block">
      <div className="space-y-1">
        {items.map((i) => (
          <div key={i.label} className="flex items-center gap-2 text-[9px] text-slate-400">
            <span
              className="h-0.5 w-4 rounded-full"
              style={{
                background: i.dash
                  ? `repeating-linear-gradient(90deg,${i.color} 0 4px,transparent 4px 7px)`
                  : i.color,
              }}
            />
            {i.label}
          </div>
        ))}
      </div>
    </div>
  );
}
