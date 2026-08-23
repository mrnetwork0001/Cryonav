/**
 * Typed client for the Cryonav backend.
 *
 * All calls go through the same-origin `/api` path, which Vite proxies to FastAPI in dev and a
 * reverse proxy handles in production. Nothing here needs to know the backend's host.
 */

const BASE = "/api/v1";

export type RiskLevel = "low" | "moderate" | "high" | "extreme";

export interface CitySummary {
  id: string;
  name: string;
  region: string;
  country_code: string;
  center: [number, number];
  bounds: { south: number; north: number; west: number; east: number };
  season: string;
  air_temp_max_f: number;
  raster_tiles: number;
  calibrated: boolean;
  has_report: boolean;
  report_date: string | null;
  presets: Preset[];
  shelter_count: number;
}

export interface Preset {
  id: string;
  label: string;
  origin: { name: string; coords: [number, number] };
  destination: { name: string; coords: [number, number] };
}

export interface Profile {
  id: string;
  label: string;
  description: string;
  max_detour_ratio: number;
}

export interface RiskBand {
  level: RiskLevel;
  color: string;
  min_exposure_index_f: number;
  advisory: string;
  safe_exposure_minutes: number;
}

export interface Meta {
  profiles: Profile[];
  risk_levels: RiskBand[];
  agents: { name: string; role: string }[];
  thresholds: {
    comfort_baseline_f: number;
    survival_limit_f: number;
    extreme_air_temp_f: number;
  };
}

export type GridSource = "model" | "fortyguard";

export interface ThermalGrid {
  city_id: string;
  hour: number;
  resolution: number | null;
  source?: string;
  units_label?: string;
  date?: string;
  cell_size_m?: number;
  bounds: { south: number; north: number; west: number; east: number };
  cells: [number, number, number, number][];
  exposure_index_f: number[];
  risk_rank: number[];
  tile_area_mi2: number;
  stats: {
    min_exposure_f: number;
    max_exposure_f: number;
    mean_exposure_f: number;
    extreme_cell_pct: number;
  };
}

export interface Shelter {
  id: string;
  name: string;
  type: string;
  center: [number, number];
  air_conditioned: boolean;
  water: boolean;
  hours: string;
  indoor_temp_f: number | null;
  distance_m?: number;
  walk_minutes?: number;
  thermal_relief_f?: number;
}

export interface CityLayers {
  city_id: string;
  heat_islands: { name: string; center: [number, number]; radius_m: number }[];
  heat_corridors: { name: string; path: [number, number][]; width_m: number }[];
  canopy_zones: { name: string; center: [number, number]; radius_m: number }[];
  canopy_corridors: { name: string; path: [number, number][]; width_m: number }[];
  water_bodies: { name: string; center: [number, number]; radius_m: number }[];
  shelters: Shelter[];
}

export interface RouteMetrics {
  distance_m: number;
  distance_km: number;
  duration_min: number;
  mean_exposure_index_f: number;
  peak_exposure_index_f: number;
  mean_air_temp_2m_f: number;
  peak_surface_temp_f: number;
  shade_coverage_pct: number;
  thermal_dose_f_min: number;
  thermal_stress_score: number;
  extreme_exposure_min: number;
  high_plus_exposure_min: number;
  longest_high_risk_leg_min: number;
  hydration_ml: number;
  risk_level: RiskLevel;
  risk_color: string;
  thermal_aversion_used: number;
}

export interface RouteSegment {
  start: [number, number];
  end: [number, number];
  exposure_index_f: number;
  surface_temp_f: number;
  air_temp_2m_f: number;
  canopy_cover_pct: number;
  risk_level: RiskLevel;
  risk_color: string;
  surface_type: string;
}

export interface Route {
  kind: string;
  label: string;
  geometry: [number, number][];
  segments: RouteSegment[];
  waypoints: {
    id: string;
    name: string;
    type: string;
    coords: [number, number];
    indoor_temp_f: number;
    thermal_relief_f: number;
  }[];
  metrics: RouteMetrics;
}

export interface Comparison {
  thermal_load_reduction_f: number;
  peak_exposure_reduction_f: number;
  surface_temp_avoided_f: number;
  heat_stress_reduction_pct: number;
  thermal_dose_reduction_pct: number;
  shade_coverage_gain_pct: number;
  extreme_minutes_avoided: number;
  high_risk_minutes_avoided: number;
  high_risk_exposure_reduction_pct: number;
  added_distance_m: number;
  added_minutes: number;
  detour_ratio: number;
  hydration_saved_ml: number;
}

export interface TraceStep {
  step: number;
  agent: string;
  action: string;
  detail: string;
  data: Record<string, unknown>;
  elapsed_ms: number;
}

export interface Hotspot {
  at: [number, number];
  exposure_index_f: number;
  surface_temp_f: number;
  air_temp_2m_f: number;
  risk_level: RiskLevel;
  surface_type: string;
  asphalt_radiation_spike_f: number;
}

export interface NavigationResult {
  city_id: string;
  hour: number;
  profile: { id: string; label: string; description: string };
  origin: [number, number];
  destination: [number, number];
  feed: {
    source: string;
    status_code: number;
    ok: boolean;
    latency_ms: number;
    detail: string;
    /** True when a live feed was configured and attempted but the simulation stood in. */
    degraded: boolean;
    upstream_status_code: number | null;
    /** Metric fields that genuinely came from upstream; the rest were modelled locally. */
    live_fields: string[];
  };
  sensing: {
    elevation_m: number;
    resolution_mi2: number;
    tile_area_mi2: number;
    endpoint: string;
  };
  ambient: {
    air_temp_2m_f: number;
    surface_temp_f: number;
    heat_index_f: number;
    wbgt_f: number;
    exposure_index_f: number;
    relative_humidity_pct: number;
    wind_speed_mph: number;
    risk_level: RiskLevel;
    risk_color: string;
    advisory: string;
  };
  risk_vector: {
    peak_risk_level: RiskLevel;
    asphalt_radiation_spike_f: number;
    asphalt_trap_detected: boolean;
    acute_danger_zone: boolean;
  };
  routes: { standard: Route; cool: Route };
  comparison: Comparison;
  hotspots: Hotspot[];
  safety: {
    risk_band: RiskLevel;
    continuous_exposure_ceiling_min: number;
    longest_high_risk_leg_min: number;
    ceiling_exceeded: boolean;
    hydration_ml: number;
    advisory: string;
  };
  shelter_reroute: {
    applied: boolean;
    reason?: string;
    shelter?: Shelter;
    longest_leg_min_before?: number;
    longest_leg_min_after?: number;
    added_minutes?: number;
  };
  nearby_shelters: Shelter[];
  agents: { name: string; role: string }[];
  agent_trace: TraceStep[];
  compute_ms: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/meta"),
  cities: () => get<{ cities: CitySummary[] }>("/cities"),
  grid: (cityId: string, hour: number, resolution = 40, source: GridSource = "model") =>
    get<ThermalGrid>(
      `/cities/${cityId}/grid?hour=${hour}&resolution=${resolution}&source=${source}`,
    ),
  layers: (cityId: string) => get<CityLayers>(`/cities/${cityId}/layers`),
  coolRoute: (body: {
    origin: { lat: number; lon: number };
    destination: { lat: number; lon: number };
    city_id: string;
    hour: number;
    profile: string;
    allow_shelter_reroute: boolean;
  }) => post<NavigationResult>("/navigate/cool-route", body),
};

/** Blue -> yellow -> orange -> red ramp, stretched across the tile's own exposure range.
 *  Absolute banding alone renders a Gulf city as a single flat red rectangle at 15:00, which
 *  hides exactly the spatial structure the map exists to show. The legend prints the real
 *  degrees F either end, so stretching aids legibility without misleading. */
export function exposureColor(t: number): [number, number, number] {
  const stops: [number, [number, number, number]][] = [
    [0.0, [8, 47, 73]],
    [0.28, [34, 211, 238]],
    [0.52, [250, 204, 21]],
    [0.76, [251, 146, 60]],
    [1.0, [239, 68, 68]],
  ];
  const x = Math.max(0, Math.min(1, t));
  for (let i = 0; i < stops.length - 1; i++) {
    const [p0, c0] = stops[i];
    const [p1, c1] = stops[i + 1];
    if (x >= p0 && x <= p1) {
      const f = (x - p0) / (p1 - p0 || 1);
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f),
      ];
    }
  }
  return stops[stops.length - 1][1];
}
