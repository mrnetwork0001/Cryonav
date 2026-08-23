import { useCallback, useEffect, useRef, useState } from "react";
import type { NavigationResult, RiskLevel, Shelter } from "../lib/api";

/**
 * Emergency Sentinel live-transit playback.
 *
 * Walks a simulated pedestrian along the actual cool route at ~50x wall speed, streaming
 * position/dwell/displacement telemetry to the REAL `/api/v1/sentinel/monitor` endpoint —
 * the same one a Jetson wearable would call. Every verdict shown comes back from the
 * backend; the only scripted element is the mid-route immobility event (the walker stops,
 * as a heat casualty would), and the Sentinel's escalation to dispatch is its own decision.
 */

export interface SimFrame {
  pos: [number, number];
  status: "ok" | "advisory" | "reroute" | "dispatch";
  trail: [number, number][];
  shelter: Shelter | null;
  phase: "walking" | "immobile" | "done";
}

interface MonitorResponse {
  status: SimFrame["status"];
  action: string;
  dwell_minutes: number;
  immobility_suspected: boolean;
  continuous_exposure_ceiling_min: number;
  reading: { risk_level: RiskLevel; air_temp_2m_f: number; exposure_index_f: number };
  nearest_shelters: Shelter[];
  hydration_ml_per_hour: number;
  escalation_contact: string | null;
}

interface Props {
  nav: NavigationResult | null;
  cityId: string;
  hour: number;
  profileId: string;
  onFrame: (frame: SimFrame | null) => void;
}

const TICK_MS = 200;
const WALK_WALL_S = 32; // whole route in ~32s of wall time
const IMMOBILE_AT = 0.62; // freeze the walker at 62% of the route
const IMMOBILE_SIM_MIN = 11; // simulated minutes of immobility before the phase ends
const STATUS_COLOR: Record<SimFrame["status"], string> = {
  ok: "#34d399",
  advisory: "#facc15",
  reroute: "#fb923c",
  dispatch: "#ef4444",
};

interface LogEntry {
  t: number;
  status: SimFrame["status"];
  text: string;
}

export default function TransitSim({ nav, cityId, hour, profileId, onFrame }: Props) {
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState<SimFrame["phase"]>("walking");
  const [simMin, setSimMin] = useState(0);
  const [dwell, setDwell] = useState(0);
  const [monitor, setMonitor] = useState<MonitorResponse | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const engine = useRef<{
    timer: ReturnType<typeof setInterval> | null;
    cum: number[];
    total: number;
    durationMin: number;
    t: number; // sim minutes elapsed
    frac: number;
    frozenAt: number | null;
    history: { t: number; pos: [number, number] }[];
    trail: [number, number][];
    dwellHigh: number;
    lastRisk: RiskLevel;
    status: SimFrame["status"];
    shelter: Shelter | null;
    inFlight: boolean;
    lastMonitorAt: number;
    dispatched: boolean;
  } | null>(null);

  const stop = useCallback(
    (final?: SimFrame["phase"]) => {
      const e = engine.current;
      if (e?.timer) clearInterval(e.timer);
      setRunning(false);
      if (final) setPhase(final);
      if (!final) onFrame(null);
    },
    [onFrame],
  );

  useEffect(() => () => stop(), [stop]);
  // Any new route/city invalidates a finished run's frame.
  useEffect(() => {
    stop();
    setLog([]);
    setMonitor(null);
    setPhase("walking");
    onFrame(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav]);

  const start = () => {
    if (!nav) return;
    const geo = nav.routes.cool.geometry;
    if (geo.length < 2) return;
    // cumulative distances (equirectangular is fine at street scale)
    const k = Math.cos((geo[0][0] * Math.PI) / 180);
    const cum = [0];
    for (let i = 1; i < geo.length; i++) {
      const dx = (geo[i][1] - geo[i - 1][1]) * 111320 * k;
      const dy = (geo[i][0] - geo[i - 1][0]) * 110574;
      cum.push(cum[i - 1] + Math.hypot(dx, dy));
    }
    const durationMin = nav.routes.cool.metrics.duration_min;
    engine.current = {
      timer: null,
      cum,
      total: cum[cum.length - 1],
      durationMin,
      t: 0,
      frac: 0,
      frozenAt: null,
      history: [],
      trail: [geo[0]],
      dwellHigh: 0,
      lastRisk: "moderate",
      status: "ok",
      shelter: null,
      inFlight: false,
      lastMonitorAt: -999,
      dispatched: false,
    };
    setLog([{ t: 0, status: "ok", text: "Transit started on the cool route." }]);
    setMonitor(null);
    setPhase("walking");
    setSimMin(0);
    setDwell(0);
    setRunning(true);
    const simRate = durationMin / WALK_WALL_S; // sim minutes per wall second
    engine.current.timer = setInterval(() => tick(simRate), TICK_MS);
  };

  const posAt = (frac: number): [number, number] => {
    const e = engine.current!;
    const geo = nav!.routes.cool.geometry;
    const target = frac * e.total;
    let i = 1;
    while (i < e.cum.length - 1 && e.cum[i] < target) i++;
    const seg = e.cum[i] - e.cum[i - 1] || 1;
    const f = (target - e.cum[i - 1]) / seg;
    return [
      geo[i - 1][0] + (geo[i][0] - geo[i - 1][0]) * f,
      geo[i - 1][1] + (geo[i][1] - geo[i - 1][1]) * f,
    ];
  };

  const tick = (simRate: number) => {
    const e = engine.current;
    if (!e || !nav) return;
    const dt = (TICK_MS / 1000) * simRate; // sim minutes this tick
    e.t += dt;

    let ph: SimFrame["phase"] = "walking";
    if (e.dispatched) {
      ph = "immobile";
    } else if (e.frac >= IMMOBILE_AT && e.frozenAt === null) {
      e.frozenAt = e.t; // the casualty stops here
    }
    if (e.frozenAt !== null && !e.dispatched) {
      ph = "immobile";
      if (e.t - e.frozenAt > IMMOBILE_SIM_MIN + 6) {
        // Sentinel failed to escalate (shouldn't happen) — end the run defensively.
        finish("done");
        return;
      }
    } else if (e.frozenAt === null) {
      e.frac = Math.min(1, e.frac + dt / e.durationMin);
    }

    const pos = posAt(e.frac);
    e.history.push({ t: e.t, pos });
    while (e.history.length > 2 && e.history[0].t < e.t - 9) e.history.shift();
    const last = e.trail[e.trail.length - 1];
    if (Math.abs(last[0] - pos[0]) + Math.abs(last[1] - pos[1]) > 1e-5) e.trail.push(pos);

    // dwell in high+ risk accrues continuously; the backend's own reading updates lastRisk
    if (e.lastRisk === "high" || e.lastRisk === "extreme") e.dwellHigh += dt;

    if (e.frac >= 1 && e.frozenAt === null) {
      finish("done");
      return;
    }

    // telemetry every ~1.5s wall, and immediately once immobile
    const wallNow = e.t / simRate;
    const due = wallNow - e.lastMonitorAt > 1.5 || (ph === "immobile" && wallNow - e.lastMonitorAt > 0.8);
    if (due && !e.inFlight) {
      e.lastMonitorAt = wallNow;
      e.inFlight = true;
      const old = e.history[0];
      const kk = Math.cos((pos[0] * Math.PI) / 180);
      const movedM =
        ph === "immobile"
          ? 4
          : Math.hypot(
              (pos[1] - old.pos[1]) * 111320 * kk,
              (pos[0] - old.pos[0]) * 110574,
            );
      fetch("/api/v1/sentinel/monitor", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          position: { lat: pos[0], lon: pos[1] },
          city_id: cityId,
          hour,
          profile: profileId,
          dwell_minutes: Math.round(e.dwellHigh * 10) / 10,
          moved_m: Math.round(movedM),
        }),
      })
        .then((r) => r.json())
        .then((m: MonitorResponse) => {
          e.inFlight = false;
          e.lastRisk = m.reading.risk_level;
          setMonitor(m);
          if (m.status !== e.status) {
            e.status = m.status;
            setLog((l) =>
              [...l, { t: e.t, status: m.status, text: m.action }].slice(-6),
            );
            if (m.status === "reroute" && m.nearest_shelters[0]) {
              e.shelter = m.nearest_shelters[0];
            }
            if (m.status === "dispatch") {
              e.dispatched = true;
              e.shelter = m.nearest_shelters[0] ?? e.shelter;
              // let the dispatch state breathe on screen, then conclude
              setTimeout(() => finish("done"), 4200);
            }
          }
        })
        .catch(() => {
          e.inFlight = false;
        });
    }

    setSimMin(e.t);
    setDwell(e.dwellHigh);
    setPhase(ph);
    onFrame({ pos, status: e.status, trail: [...e.trail], shelter: e.shelter, phase: ph });
  };

  const finish = (ph: SimFrame["phase"]) => {
    const e = engine.current;
    if (e?.timer) clearInterval(e.timer);
    setRunning(false);
    setPhase(ph);
    if (e && nav) {
      onFrame({
        pos: posAt(e.frac),
        status: e.status,
        trail: [...e.trail],
        shelter: e.shelter,
        phase: ph,
      });
    }
  };

  const reset = () => {
    stop();
    setLog([]);
    setMonitor(null);
    setPhase("walking");
    setSimMin(0);
    setDwell(0);
    onFrame(null);
  };

  const ceiling = monitor?.continuous_exposure_ceiling_min;
  const statusColor = STATUS_COLOR[monitor?.status ?? "ok"];

  return (
    <section className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Sentinel · live transit sim
        </h2>
        {running && (
          <span className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider" style={{ color: statusColor }}>
            <span className="ping-soft h-1.5 w-1.5 rounded-full" style={{ background: statusColor, color: statusColor }} />
            {(monitor?.status ?? "ok").toUpperCase()}
          </span>
        )}
      </div>

      {!running && phase !== "done" && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Replays a delivery walk along the computed cool route at ~50× speed, streaming live
          telemetry to the Sentinel — including a mid-route collapse. Every escalation shown is
          the backend's own verdict.
        </p>
      )}

      {(running || phase === "done") && (
        <div className="tnum mt-3 grid grid-cols-3 gap-2 text-center">
          <Metric label="transit" value={`${simMin.toFixed(0)} min`} />
          <Metric
            label={`dwell ${ceiling ? `/ ${ceiling.toFixed(0)}` : ""}`}
            value={`${dwell.toFixed(1)} min`}
            tone={ceiling != null && dwell > ceiling ? "#ef4444" : undefined}
          />
          <Metric
            label="air here"
            value={monitor ? `${monitor.reading.air_temp_2m_f.toFixed(0)}°F` : "—"}
          />
        </div>
      )}

      {log.length > 0 && (
        <div className="mt-3 space-y-1">
          {log.map((l, i) => (
            <div key={i} className="flex items-start gap-2 text-[10.5px] leading-snug">
              <span
                className="tnum mt-px shrink-0 rounded px-1 font-bold"
                style={{ background: `${STATUS_COLOR[l.status]}22`, color: STATUS_COLOR[l.status] }}
              >
                {l.t.toFixed(0)}m
              </span>
              <span className="text-slate-400">{l.text}</span>
            </div>
          ))}
        </div>
      )}

      {phase === "done" && monitor?.status === "dispatch" && (
        <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-[11px] leading-relaxed text-rose-300">
          Immobility in extreme heat detected — <b>{monitor.escalation_contact}</b> notified with
          the walker's live position{monitor.nearest_shelters[0] ? (
            <> and nearest refuge (<b>{monitor.nearest_shelters[0].name}</b>)</>
          ) : null}
          .
        </div>
      )}

      <button
        onClick={running ? reset : phase === "done" ? reset : start}
        disabled={!nav}
        className={`mt-3 w-full rounded-lg border px-3 py-2.5 text-[12px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
          running
            ? "border-slate-600 bg-slate-800/60 text-slate-300 hover:text-white"
            : "border-rose-400/50 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
        }`}
      >
        {running ? "■ Stop simulation" : phase === "done" ? "↺ Reset" : "▶ Simulate transit emergency"}
      </button>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-950/40 px-1 py-2">
      <div className="text-[15px] font-semibold" style={{ color: tone ?? "#e2e8f0" }}>
        {value}
      </div>
      <div className="mt-0.5 text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
    </div>
  );
}
