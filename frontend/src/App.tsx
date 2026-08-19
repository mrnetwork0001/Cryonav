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
    <div className="flex h-full flex-col gap-3 bg-[#0b0f17] p-3">
      <TopMetricsBar nav={nav} grid={grid} cityName={`${city.name}, ${city.region}`} hour={hour} loading={loading} />

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[300px_minmax(0,1fr)_340px]">
        <div className="scroll-thin min-h-0 overflow-y-auto">
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

        <div className="glass relative min-h-[420px] overflow-hidden rounded-xl">
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
          />
          <MapLegend />
          {error && (
            <div className="absolute bottom-3 left-3 z-[1000] max-w-md rounded-lg border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-[10px] text-rose-300">
              {error}
            </div>
          )}
        </div>

        <div className="scroll-thin flex min-h-0 flex-col gap-3 overflow-y-auto">
          <ExposureCard
            nav={nav}
            onEmergencyReroute={() => solve(!shelterReroute)}
            rerouteBusy={rerouteBusy}
            rerouteActive={shelterReroute}
          />
          <AgentTrace nav={nav} grid={grid} />
        </div>
      </main>
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
    <div className="glass pointer-events-none absolute bottom-3 right-3 z-[1000] rounded-lg px-3 py-2">
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
