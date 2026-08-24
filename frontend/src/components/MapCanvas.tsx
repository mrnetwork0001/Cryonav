import { useEffect, useRef } from "react";
import L from "leaflet";
import {
  exposureColor,
  type CityLayers,
  type CitySummary,
  type NavigationResult,
  type ThermalGrid,
} from "../lib/api";
import type { SimFrame } from "./TransitSim";

interface Props {
  city: CitySummary;
  grid: ThermalGrid | null;
  layers: CityLayers | null;
  nav: NavigationResult | null;
  showHeat: boolean;
  showStandard: boolean;
  showCool: boolean;
  showShelters: boolean;
  showCorridors: boolean;
  onPickPoint: (which: "origin" | "destination", coords: [number, number]) => void;
  pickMode: "origin" | "destination" | null;
  sim: SimFrame | null;
}

/**
 * Leaflet is driven imperatively here rather than through react-leaflet: the wrapper's peer-dep
 * churn across React majors buys nothing for a map with this few interactions.
 *
 * The thermal grid is painted into an offscreen canvas at one pixel per FortyGuard cell and
 * handed to Leaflet as an image overlay. Letting the browser scale that tiny bitmap gives free
 * bilinear interpolation -- a smooth heat field instead of visible tiles -- and means the layer
 * needs no reprojection on pan or zoom, which is where hand-rolled canvas overlays usually break.
 */
export default function MapCanvas(props: Props) {
  const { city, grid, layers, nav, showHeat, showStandard, showCool, showShelters, showCorridors } =
    props;

  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const heatRef = useRef<L.ImageOverlay | null>(null);
  const routeLayerRef = useRef<L.LayerGroup | null>(null);
  const shelterLayerRef = useRef<L.LayerGroup | null>(null);
  const corridorLayerRef = useRef<L.LayerGroup | null>(null);
  const simLayerRef = useRef<L.LayerGroup | null>(null);
  const pickRef = useRef(props.pickMode);
  const onPickRef = useRef(props.onPickPoint);

  pickRef.current = props.pickMode;
  onPickRef.current = props.onPickPoint;

  // -- map lifecycle -------------------------------------------------------------------
  useEffect(() => {
    if (!hostRef.current || mapRef.current) return;
    const map = L.map(hostRef.current, {
      center: city.center,
      zoom: 14,
      zoomControl: true,
      attributionControl: true,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OpenStreetMap &copy; CARTO &middot; FortyGuard Temperature API',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(map);

    corridorLayerRef.current = L.layerGroup().addTo(map);
    routeLayerRef.current = L.layerGroup().addTo(map);
    shelterLayerRef.current = L.layerGroup().addTo(map);
    simLayerRef.current = L.layerGroup().addTo(map);

    map.on("click", (e: L.LeafletMouseEvent) => {
      if (!pickRef.current) return;
      onPickRef.current(pickRef.current, [e.latlng.lat, e.latlng.lng]);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // -- keep Leaflet honest about its container size ---------------------------------------
  // The wrapper's height differs per breakpoint (58vh on phones, grid-stretched on desktop)
  // and changes on rotation. Leaflet only measures its container once, so without this the
  // map renders tiles for a stale size and pans reveal grey voids.
  useEffect(() => {
    const map = mapRef.current;
    const host = hostRef.current;
    if (!map || !host) return;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(host);
    return () => ro.disconnect();
  }, []);

  // -- recenter when the city changes ----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.flyTo(city.center, 14, { duration: 0.8 });
  }, [city.id]);

  // -- thermal grid overlay --------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (heatRef.current) {
      heatRef.current.remove();
      heatRef.current = null;
    }
    if (!grid || !showHeat) return;

    const { min_exposure_f: lo, max_exposure_f: hi } = grid.stats;
    const span = Math.max(hi - lo, 0.001);
    const canvas = document.createElement("canvas");
    const ctx0 = canvas.getContext("2d");
    if (!ctx0) return;

    if (grid.resolution != null) {
      // Model grid: a dense n x n array, one pixel per cell.
      const n = grid.resolution;
      canvas.width = n;
      canvas.height = n;
      const img = ctx0.createImageData(n, n);
      for (let row = 0; row < n; row++) {
        for (let col = 0; col < n; col++) {
          const srcIdx = row * n + col;
          // Grid rows run south -> north; canvas rows run top -> bottom.
          const dstIdx = ((n - 1 - row) * n + col) * 4;
          const [r, g, b] = exposureColor((grid.exposure_index_f[srcIdx] - lo) / span);
          img.data[dstIdx] = r;
          img.data[dstIdx + 1] = g;
          img.data[dstIdx + 2] = b;
          img.data[dstIdx + 3] = 255;
        }
      }
      ctx0.putImageData(img, 0, 0);
    } else {
      // FortyGuard raster: scattered ~100 m tile centroids. Bin them into a regular pixel
      // grid over the tile bounds; bins with no observation stay transparent rather than
      // being interpolated -- absence of data must not render as data.
      const b = grid.bounds;
      const latSpan = Math.max(b.north - b.south, 1e-9);
      const lonSpan = Math.max(b.east - b.west, 1e-9);
      // Bins are deliberately ~40% larger than the upstream tiles: the FortyGuard grid is a
      // rotated projected grid, so equal-sized lat/lon bins leave systematic empty columns
      // that render as dark stripes. Oversized bins guarantee every bin inside the AOI catches
      // at least one centroid; multiple hits are averaged rather than last-write-wins.
      const cellDeg = ((grid.cell_size_m ?? 100) * 1.4) / 111_000;
      const W = Math.min(Math.max(Math.round(lonSpan / cellDeg), 16), 128);
      const Hh = Math.min(Math.max(Math.round(latSpan / cellDeg), 16), 128);
      canvas.width = W;
      canvas.height = Hh;
      const sum = new Float64Array(W * Hh);
      const count = new Uint16Array(W * Hh);
      for (const cell of grid.cells) {
        const [lat, lon, value] = cell;
        const col = Math.min(W - 1, Math.max(0, Math.floor(((lon - b.west) / lonSpan) * W)));
        const rowFromS = Math.min(
          Hh - 1,
          Math.max(0, Math.floor(((lat - b.south) / latSpan) * Hh)),
        );
        const bin = (Hh - 1 - rowFromS) * W + col;
        sum[bin] += value;
        count[bin] += 1;
      }
      const img = ctx0.createImageData(W, Hh);
      for (let i = 0; i < W * Hh; i++) {
        if (count[i] === 0) continue; // no observation -> transparent, never interpolated
        const [r, g, bl] = exposureColor((sum[i] / count[i] - lo) / span);
        img.data[i * 4] = r;
        img.data[i * 4 + 1] = g;
        img.data[i * 4 + 2] = bl;
        img.data[i * 4 + 3] = 255;
      }
      ctx0.putImageData(img, 0, 0);
    }

    const b = grid.bounds;
    const overlay = L.imageOverlay(
      canvas.toDataURL(),
      [
        [b.south, b.west],
        [b.north, b.east],
      ],
      { opacity: 0.55, interactive: false, className: "thermal-grid" },
    );
    overlay.addTo(map);
    overlay.bringToBack();
    heatRef.current = overlay;
  }, [grid, showHeat]);

  // -- coverage-tile boundary --------------------------------------------------------------
  // The thermal layer stops at the FortyGuard tile edge. Drawing that edge explicitly reads as
  // a stated coverage limit instead of a rendering gap -- and refusing to paint colour beyond
  // it keeps the map honest about where the data actually ends.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !grid) return;
    const b = grid.bounds;
    const rect = L.rectangle(
      [
        [b.south, b.west],
        [b.north, b.east],
      ],
      {
        color: "#22d3ee",
        weight: 1,
        opacity: 0.3,
        dashArray: "6 6",
        fill: false,
        interactive: false,
      },
    ).addTo(map);

    const label = L.marker([b.north, b.west], {
      interactive: false,
      icon: L.divIcon({
        className: "",
        html: `<div style="white-space:nowrap;transform:translate(6px,6px);font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#22d3ee99">FortyGuard coverage tile · ${grid.tile_area_mi2} mi²</div>`,
        iconSize: [0, 0],
      }),
    }).addTo(map);

    // Keep the viewport tethered to the tile so the user cannot pan into unmeasured space.
    map.setMaxBounds(
      L.latLngBounds([b.south, b.west], [b.north, b.east]).pad(0.35),
    );

    return () => {
      rect.remove();
      label.remove();
    };
  }, [grid?.city_id, grid?.bounds.south, grid?.bounds.west]);

  // -- urban morphology corridors --------------------------------------------------------
  useEffect(() => {
    const group = corridorLayerRef.current;
    if (!group) return;
    group.clearLayers();
    if (!layers || !showCorridors) return;

    layers.heat_corridors.forEach((c) => {
      L.polyline(c.path, {
        color: "#ef4444",
        weight: 2,
        opacity: 0.35,
        dashArray: "1 7",
        interactive: false,
      }).addTo(group);
    });
    layers.canopy_corridors.forEach((c) => {
      L.polyline(c.path, {
        color: "#4ade80",
        weight: 2,
        opacity: 0.4,
        dashArray: "1 7",
        interactive: false,
      }).addTo(group);
    });
    layers.canopy_zones.forEach((z) => {
      L.circle(z.center, {
        radius: z.radius_m * 0.75,
        color: "#4ade80",
        weight: 1,
        opacity: 0.25,
        fillOpacity: 0.05,
        interactive: false,
      }).addTo(group);
    });
  }, [layers, showCorridors]);

  // -- routes, endpoints, hotspots --------------------------------------------------------
  useEffect(() => {
    const group = routeLayerRef.current;
    const map = mapRef.current;
    if (!group || !map) return;
    group.clearLayers();
    if (!nav) return;

    if (showStandard) {
      const geo = nav.routes.standard.geometry;
      L.polyline(geo, { color: "#7f1d1d", weight: 11, opacity: 0.35, interactive: false }).addTo(group);
      L.polyline(geo, {
        color: "#fb7185",
        weight: 3.5,
        opacity: 0.95,
        dashArray: "9 7",
      })
        .bindPopup(
          popup("Standard Direct Route", [
            ["Distance", `${nav.routes.standard.metrics.distance_km} km`],
            ["Duration", `${nav.routes.standard.metrics.duration_min} min`],
            ["Mean exposure", `${nav.routes.standard.metrics.mean_exposure_index_f} °F`],
            ["Peak surface", `${nav.routes.standard.metrics.peak_surface_temp_f} °F`],
            ["Shade coverage", `${nav.routes.standard.metrics.shade_coverage_pct}%`],
          ]),
        )
        .addTo(group);
    }

    if (showCool) {
      const geo = nav.routes.cool.geometry;
      L.polyline(geo, { color: "#22d3ee", weight: 14, opacity: 0.2, interactive: false }).addTo(group);
      L.polyline(geo, { color: "#0891b2", weight: 7, opacity: 0.55, interactive: false }).addTo(group);
      L.polyline(geo, {
        color: "#67e8f9",
        weight: 3.5,
        opacity: 1,
        dashArray: "12 12",
        className: "cool-flow",
      })
        .bindPopup(
          popup("Cryonav Cool Route", [
            ["Distance", `${nav.routes.cool.metrics.distance_km} km`],
            ["Duration", `${nav.routes.cool.metrics.duration_min} min`],
            ["Mean exposure", `${nav.routes.cool.metrics.mean_exposure_index_f} °F`],
            ["Shade coverage", `${nav.routes.cool.metrics.shade_coverage_pct}%`],
            ["Thermal load saved", `${nav.comparison.thermal_load_reduction_f} °F`],
          ]),
        )
        .addTo(group);

      nav.routes.cool.waypoints.forEach((w) => {
        L.marker(w.coords, { icon: shelterIcon("#22d3ee", true) })
          .bindPopup(
            popup(w.name, [
              ["Type", w.type.replace(/_/g, " ")],
              ["Indoor", `${w.indoor_temp_f} °F`],
              ["Thermal relief", `−${w.thermal_relief_f} °F`],
            ]),
          )
          .addTo(group);
      });
    }

    // Pulsing hazard markers on the worst traps of the standard corridor.
    nav.hotspots.forEach((h) => {
      L.marker(h.at, {
        icon: L.divIcon({
          className: "",
          html: `<div class="hazard-marker" style="width:14px;height:14px"><div class="hazard-core"></div></div>`,
          iconSize: [14, 14],
          iconAnchor: [7, 7],
        }),
      })
        .bindPopup(
          popup("Asphalt thermal trap", [
            ["Surface", `${h.surface_temp_f} °F`],
            ["Air @ 2 m", `${h.air_temp_2m_f} °F`],
            ["Radiant spike", `+${h.asphalt_radiation_spike_f} °F`],
            ["Risk", h.risk_level.toUpperCase()],
          ]),
        )
        .addTo(group);
    });

    L.marker(nav.origin, { icon: endpointIcon("#22d3ee", "A") })
      .bindPopup("<b>Origin</b>")
      .addTo(group);
    L.marker(nav.destination, { icon: endpointIcon("#a78bfa", "B") })
      .bindPopup("<b>Destination</b>")
      .addTo(group);

    const bounds = L.latLngBounds([
      ...nav.routes.standard.geometry,
      ...nav.routes.cool.geometry,
    ]);
    map.fitBounds(bounds, { padding: [70, 70], maxZoom: 16 });
  }, [nav, showStandard, showCool]);

  // -- shelters ---------------------------------------------------------------------------
  useEffect(() => {
    const group = shelterLayerRef.current;
    if (!group) return;
    group.clearLayers();
    if (!layers || !showShelters) return;

    layers.shelters.forEach((s) => {
      const color = s.air_conditioned ? "#38bdf8" : "#4ade80";
      L.marker(s.center, { icon: shelterIcon(color, false) })
        .bindPopup(
          popup(s.name, [
            ["Type", s.type.replace(/_/g, " ")],
            ["Hours", s.hours],
            ["Air conditioned", s.air_conditioned ? "yes" : "no"],
            ["Drinking water", s.water ? "yes" : "no"],
            ...(s.indoor_temp_f
              ? [[
                  "Indoor",
                  `${s.indoor_temp_f} °F${s.indoor_temp_assumed ? " (assumed)" : ""}`,
                ] as [string, string]]
              : []),
          ]),
        )
        .addTo(group);
    });
  }, [layers, showShelters]);

  // -- Sentinel transit sim walker ---------------------------------------------------------
  const sim = props.sim;
  useEffect(() => {
    const group = simLayerRef.current;
    if (!group) return;
    group.clearLayers();
    if (!sim) return;

    const color = { ok: "#34d399", advisory: "#facc15", reroute: "#fb923c", dispatch: "#ef4444" }[
      sim.status
    ];

    if (sim.trail.length >= 2) {
      L.polyline(sim.trail, { color: "#e2e8f0", weight: 3, opacity: 0.85, interactive: false }).addTo(
        group,
      );
    }
    if (sim.shelter && (sim.status === "reroute" || sim.status === "dispatch")) {
      L.polyline([sim.pos, sim.shelter.center], {
        color,
        weight: 2.5,
        opacity: 0.9,
        dashArray: "4 8",
        interactive: false,
      }).addTo(group);
      L.marker(sim.shelter.center, { icon: shelterIcon(color, true), interactive: false }).addTo(group);
    }
    const dispatch = sim.status === "dispatch";
    L.marker(sim.pos, {
      interactive: false,
      zIndexOffset: 2000,
      icon: L.divIcon({
        className: "",
        html: `<div class="${dispatch ? "hazard-marker" : "ping-soft"}" style="width:18px;height:18px;color:${color}">
                 <div style="position:absolute;inset:2px;border-radius:9999px;background:${color};border:2.5px solid #0b0f17;box-shadow:0 0 12px ${color}"></div>
               </div>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }),
    }).addTo(group);
  }, [sim]);

  return (
    <div className="relative h-full w-full">
      <div ref={hostRef} className="h-full w-full" />
      {sim?.status === "dispatch" && (
        <div className="pointer-events-none absolute top-3 left-1/2 z-[1001] -translate-x-1/2 rounded-lg border border-rose-500/60 bg-rose-950/95 px-4 py-2 text-center shadow-[0_0_40px_rgba(239,68,68,0.45)]">
          <div className="text-[11px] font-bold tracking-[0.18em] text-rose-300">
            ⚠ EMERGENCY DISPATCH · SIMULATED
          </div>
          <div className="tnum mt-0.5 text-[10px] text-rose-400/90">
            immobility in extreme heat · would relay live position to responders
          </div>
        </div>
      )}
      {props.pickMode && (
        <div className="pointer-events-none absolute top-3 left-1/2 z-[1000] -translate-x-1/2 rounded-full border border-cyan-400/40 bg-slate-950/90 px-4 py-1.5 text-xs font-medium text-cyan-300 shadow-lg">
          Click the map to set the {props.pickMode}
        </div>
      )}
    </div>
  );
}

function popup(title: string, rows: [string, string][]): string {
  const body = rows
    .map(
      ([k, v]) =>
        `<div style="display:flex;justify-content:space-between;gap:16px"><span style="color:#64748b">${k}</span><span style="font-variant-numeric:tabular-nums">${v}</span></div>`,
    )
    .join("");
  return `<div><div style="font-weight:600;margin-bottom:6px;color:#e2e8f0">${title}</div>${body}</div>`;
}

function endpointIcon(color: string, label: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:22px;height:22px;border-radius:9999px;background:${color};display:flex;align-items:center;justify-content:center;color:#0b0f17;font-weight:700;font-size:11px;box-shadow:0 0 0 3px rgba(11,15,23,.9),0 0 14px ${color}">${label}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function shelterIcon(color: string, emphasised: boolean): L.DivIcon {
  const size = emphasised ? 18 : 12;
  return L.divIcon({
    className: "",
    html: `<div style="width:${size}px;height:${size}px;border-radius:4px;background:${color};box-shadow:0 0 0 2px rgba(11,15,23,.9)${
      emphasised ? `,0 0 16px ${color}` : ""
    };transform:rotate(45deg)"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}
