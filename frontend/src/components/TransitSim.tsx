import { useCallback, useEffect, useRef, useState } from "react";
import type { NavigationResult, RiskLevel, Shelter } from "../lib/api";
import { displacementM, medianAccuracyM, trimWindow, type Fix } from "../lib/geo";
import { IconPlay, IconRecord, IconRefresh, IconStop } from "./Icons";

/**
 * Emergency Sentinel live-transit playback.
 *
 * Two telemetry sources feed the SAME endpoint, `/api/v1/sentinel/monitor` - the one a
 * Jetson wearable would call. Every verdict on screen is the backend's, never this file's.
 *
 *   LIVE    the device's own GPS via `watchPosition`. Real fixes, real accuracy, real
 *           elapsed time. Requires a secure context, so over LAN it needs a tunnel.
 *
 *   REPLAY  a pedestrian walked along the computed cool route at ~50x wall speed, with a
 *           mid-route collapse. Positions are synthetic and jittered with Gaussian noise at
 *           a stated accuracy, so the displacement estimator is genuinely exercised rather
 *           than handed clean coordinates.
 *
 * Both sources measure displacement with the same `displacementM` estimator, so what the
 * replay demonstrates is what a real phone gets. The scripted part is only *that* the walker
 * stops; whether that becomes an escalation is the Sentinel's own decision.
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
  position_accuracy_m: number | null;
  notification: {
    sent: boolean;
    channel: string;
    reason?: string;
    message_id?: string;
    latency_ms?: number;
    recipient?: string;
  } | null;
}

interface Props {
  nav: NavigationResult | null;
  cityId: string;
  hour: number;
  profileId: string;
  onFrame: (frame: SimFrame | null) => void;
}

const TICK_MS = 200;
/** Synthetic GPS noise on the replay, so the estimator faces what a real phone faces. */
const SIM_GPS_ACCURACY_M = 12;
/** Rolling window the displacement estimator sees, matched to the backend's 8-min test. */
const FIX_WINDOW_MS = 9 * 60 * 1000;
/** How often live mode reports to the Sentinel. */
const LIVE_REPORT_MS = 5000;
const WALK_WALL_S = 32; // whole route in ~32s of wall time
const IMMOBILE_AT = 0.62; // freeze the walker at 62% of the route
const IMMOBILE_SIM_MIN = 11; // simulated minutes of immobility before the phase ends
const STATUS_COLOR: Record<SimFrame["status"], string> = {
  ok: "#34d399",
  advisory: "#facc15",
  reroute: "#fb923c",
  dispatch: "#ef4444",
};

/** Box-Muller. The replay needs plausible GPS noise, not cryptographic randomness. */
function gaussian(): number {
  const u = Math.max(Math.random(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random());
}

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
    fixes: Fix[];
    trail: [number, number][];
    dwellHigh: number;
    lastRisk: RiskLevel;
    status: SimFrame["status"];
    shelter: Shelter | null;
    inFlight: boolean;
    lastMonitorAt: number;
    dispatched: boolean;
  } | null>(null);

  // ---- live telemetry source ----------------------------------------------------------
  const [source, setSource] = useState<"replay" | "live">("replay");
  const [liveOn, setLiveOn] = useState(false);
  const [liveErr, setLiveErr] = useState<string | null>(null);
  const [liveFix, setLiveFix] = useState<{ acc: number | null; n: number; moved: number | null } | null>(null);
  const live = useRef<{
    watchId: number | null;
    reporter: ReturnType<typeof setInterval> | null;
    fixes: Fix[];
    dwellHigh: number;
    lastAccrualMs: number;
    lastRisk: RiskLevel;
    status: SimFrame["status"];
    shelter: Shelter | null;
    trail: [number, number][];
    inFlight: boolean;
  } | null>(null);

  const stopLive = useCallback(() => {
    const l = live.current;
    if (l?.watchId != null) navigator.geolocation.clearWatch(l.watchId);
    if (l?.reporter) clearInterval(l.reporter);
    live.current = null;
    setLiveOn(false);
  }, []);

  const startLive = useCallback(() => {
    setLiveErr(null);
    setLog([]);
    setMonitor(null);
    setLiveFix(null);
    // Geolocation is gated on a secure context. Served over plain HTTP from anything but
    // localhost the API is simply absent, so say why instead of failing silently.
    if (!window.isSecureContext) {
      setLiveErr(
        "Live GPS needs HTTPS (or localhost). Open this page over a secure origin - e.g. a " +
          "`cloudflared tunnel --url` address - and try again.",
      );
      return;
    }
    if (!("geolocation" in navigator)) {
      setLiveErr("This browser exposes no Geolocation API.");
      return;
    }
    live.current = {
      watchId: null,
      reporter: null,
      fixes: [],
      dwellHigh: 0,
      lastAccrualMs: Date.now(),
      lastRisk: "moderate",
      status: "ok",
      shelter: null,
      trail: [],
      inFlight: false,
    };
    setLiveOn(true);
    setLog([{ t: 0, status: "ok", text: "Live GPS watch started - acquiring fixes." }]);

    live.current.watchId = navigator.geolocation.watchPosition(
      (p) => {
        const l = live.current;
        if (!l) return;
        const now = p.timestamp || Date.now();
        l.fixes.push({
          t: now,
          lat: p.coords.latitude,
          lon: p.coords.longitude,
          accuracy: p.coords.accuracy,
        });
        l.fixes = trimWindow(l.fixes, now, FIX_WINDOW_MS);
        const pos: [number, number] = [p.coords.latitude, p.coords.longitude];
        const last = l.trail[l.trail.length - 1];
        if (!last || Math.abs(last[0] - pos[0]) + Math.abs(last[1] - pos[1]) > 1e-5) l.trail.push(pos);
        setLiveFix({
          acc: medianAccuracyM(l.fixes),
          n: l.fixes.length,
          moved: displacementM(l.fixes),
        });
      },
      (err) => {
        const why: Record<number, string> = {
          1: "Location permission denied. Grant it in the browser's site settings to run live.",
          2: "Position unavailable - no GPS or network fix here.",
          3: "Timed out waiting for a fix.",
        };
        setLiveErr(why[err.code] ?? err.message);
        stopLive();
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    );

    live.current.reporter = setInterval(() => {
      const l = live.current;
      if (!l || l.inFlight || l.fixes.length === 0) return;
      const now = Date.now();
      // Dwell accrues in REAL minutes, only while the backend's last reading was high or
      // extreme. Reaching the eight-minute immobility test therefore takes eight real
      // minutes standing in real heat - which is the honest cost of a real alert.
      const elapsedMin = (now - l.lastAccrualMs) / 60000;
      l.lastAccrualMs = now;
      if (l.lastRisk === "high" || l.lastRisk === "extreme") l.dwellHigh += elapsedMin;

      const latest = l.fixes[l.fixes.length - 1];
      const moved = displacementM(l.fixes);
      const acc = medianAccuracyM(l.fixes);
      l.inFlight = true;
      fetch("/api/v1/sentinel/monitor", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          position: { lat: latest.lat, lon: latest.lon },
          city_id: cityId,
          hour,
          profile: profileId,
          dwell_minutes: Math.round(l.dwellHigh * 10) / 10,
          ...(moved === null ? {} : { moved_m: Math.round(moved) }),
          accuracy_m: acc,
          // Live mode is the real thing: an escalation here sends a real push.
          notify: true,
        }),
      })
        .then((r) => r.json())
        .then((m: MonitorResponse) => {
          l.inFlight = false;
          l.lastRisk = m.reading.risk_level;
          setMonitor(m);
          setDwell(l.dwellHigh);
          if (m.status !== l.status) {
            l.status = m.status;
            setLog((g) => [...g, { t: l.dwellHigh, status: m.status, text: m.action }].slice(-6));
            if (m.nearest_shelters[0] && (m.status === "reroute" || m.status === "dispatch")) {
              l.shelter = m.nearest_shelters[0];
            }
          }
          onFrame({
            pos: [latest.lat, latest.lon],
            status: l.status,
            trail: [...l.trail],
            shelter: l.shelter,
            phase: m.immobility_suspected ? "immobile" : "walking",
          });
        })
        .catch(() => {
          l.inFlight = false;
        });
    }, LIVE_REPORT_MS);
  }, [cityId, hour, profileId, onFrame, stopLive]);

  useEffect(() => () => stopLive(), [stopLive]);

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
      fixes: [],
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
        // A Sentinel that fails to escalate is exactly what a reviewer must see - say so
        // loudly rather than ending as if the run completed normally.
        setLog((l) => [
          ...l,
          { t: e.t, status: e.status, text: "Sentinel did NOT escalate within the immobility window - safety gap." },
        ]);
        finish("done");
        return;
      }
    } else if (e.frozenAt === null) {
      e.frac = Math.min(1, e.frac + dt / e.durationMin);
    }

    const pos = posAt(e.frac);
    // What the walker's phone would actually report: the true position plus isotropic error
    // at SIM_GPS_ACCURACY_M. Feeding the estimator clean coordinates would prove nothing.
    const nLat = (gaussian() * SIM_GPS_ACCURACY_M) / 110574;
    const nLon = (gaussian() * SIM_GPS_ACCURACY_M) / (111320 * Math.cos((pos[0] * Math.PI) / 180));
    // Fix timestamps are on the SIMULATED clock, so the 9-minute window means nine simulated
    // minutes - the same span the backend's dwell test uses.
    e.fixes.push({
      t: e.t * 60000,
      lat: pos[0] + nLat,
      lon: pos[1] + nLon,
      accuracy: SIM_GPS_ACCURACY_M,
    });
    e.fixes = trimWindow(e.fixes, e.t * 60000, FIX_WINDOW_MS);
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
      // Measured from the noisy fix history by the same estimator live mode uses. When the
      // window is too short to support a claim it returns null, and `moved_m` is omitted so
      // the backend declines to assert immobility rather than assuming it.
      const movedM = displacementM(e.fixes);
      fetch("/api/v1/sentinel/monitor", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          position: { lat: pos[0], lon: pos[1] },
          city_id: cityId,
          hour,
          profile: profileId,
          dwell_minutes: Math.round(e.dwellHigh * 10) / 10,
          ...(movedM === null ? {} : { moved_m: Math.round(movedM) }),
          accuracy_m: medianAccuracyM(e.fixes),
          // The replay must never fire a real push to a real contact.
          notify: false,
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
          Sentinel · transit monitor
        </h2>
        {(running || liveOn) && (
          <span className="flex items-center gap-1.5 text-[10px] font-bold tracking-wider" style={{ color: statusColor }}>
            <span className="ping-soft h-1.5 w-1.5 rounded-full" style={{ background: statusColor, color: statusColor }} />
            {(monitor?.status ?? "ok").toUpperCase()}
          </span>
        )}
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-1 rounded-lg border border-slate-700/40 bg-slate-950/40 p-0.5">
        {(["replay", "live"] as const).map((sid) => (
          <button
            key={sid}
            onClick={() => {
              if (running) reset();
              if (liveOn) stopLive();
              setSource(sid);
              setLog([]);
              setMonitor(null);
              setLiveErr(null);
              onFrame(null);
            }}
            className={`rounded-md px-2 py-1.5 text-[10.5px] font-semibold transition ${
              source === sid
                ? "bg-slate-700/70 text-white"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {sid === "replay" ? "Route replay" : "My GPS"}
          </button>
        ))}
      </div>

      {source === "replay" && !running && phase !== "done" && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Replays a delivery walk along the computed cool route at ~50× speed, streaming
          telemetry to the Sentinel - including a mid-route collapse. Positions are synthetic and
          carry ±{SIM_GPS_ACCURACY_M} m of GPS noise; displacement is measured from them by the
          same estimator live mode uses. Every escalation shown is the backend's own verdict.
        </p>
      )}

      {source === "live" && !liveOn && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Streams this device's real GPS to the Sentinel. Dwell accrues in real time, so the
          eight-minute immobility test takes eight real minutes - and an escalation sends a
          real push alert. Needs HTTPS and location permission.
        </p>
      )}

      {liveErr && (
        <div className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] leading-relaxed text-amber-300">
          {liveErr}
        </div>
      )}

      {source === "live" && liveOn && (
        <div className="tnum mt-3 grid grid-cols-3 gap-2 text-center">
          <Metric label="fixes" value={liveFix ? String(liveFix.n) : "-"} />
          <Metric
            label="accuracy"
            value={liveFix?.acc != null ? `±${liveFix.acc.toFixed(0)} m` : "-"}
            tone={liveFix?.acc != null && liveFix.acc > 40 ? "#facc15" : undefined}
          />
          <Metric
            label="moved"
            value={liveFix?.moved != null ? `${liveFix.moved.toFixed(0)} m` : "…"}
          />
        </div>
      )}

      {source === "live" && liveOn && (
        <div className="tnum mt-2 grid grid-cols-2 gap-2 text-center">
          <Metric
            label={`dwell ${monitor?.continuous_exposure_ceiling_min ? `/ ${monitor.continuous_exposure_ceiling_min.toFixed(0)}` : ""}`}
            value={`${dwell.toFixed(1)} min`}
          />
          <Metric
            label="air here"
            value={monitor ? `${monitor.reading.air_temp_2m_f.toFixed(0)}°F` : "-"}
          />
        </div>
      )}

      {source === "replay" && (running || phase === "done") && (
        <div className="tnum mt-3 grid grid-cols-3 gap-2 text-center">
          <Metric label="transit" value={`${simMin.toFixed(0)} min`} />
          <Metric
            label={`dwell ${ceiling ? `/ ${ceiling.toFixed(0)}` : ""}`}
            value={`${dwell.toFixed(1)} min`}
            tone={ceiling != null && dwell > ceiling ? "#ef4444" : undefined}
          />
          <Metric
            label="air here"
            value={monitor ? `${monitor.reading.air_temp_2m_f.toFixed(0)}°F` : "-"}
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

      {monitor?.status === "dispatch" && (phase === "done" || source === "live") && (
        <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-[11px] leading-relaxed text-rose-300">
          Immobility in extreme heat detected at{" "}
          {monitor.position_accuracy_m != null ? `±${monitor.position_accuracy_m.toFixed(0)} m` : "unknown"}{" "}
          accuracy
          {monitor.nearest_shelters[0] ? (
            <>, nearest refuge <b>{monitor.nearest_shelters[0].name}</b>
          </>
          ) : null}
          .{" "}
          {monitor.notification?.sent ? (
            <>
              Push alert <b>delivered</b> to the nominated emergency contact over{" "}
              {monitor.notification.channel} in {monitor.notification.latency_ms?.toFixed(0)} ms.
            </>
          ) : (
            <>
              No alert was sent - <b>{monitor.notification?.reason ?? "notification disabled"}</b>.
            </>
          )}{" "}
          Cryonav alerts a contact the user nominates; it does not and cannot file a 911 call.
        </div>
      )}

      <button
        onClick={
          source === "live"
            ? liveOn
              ? stopLive
              : startLive
            : running || phase === "done"
              ? reset
              : start
        }
        disabled={source === "replay" && !nav}
        className={`mt-3 w-full rounded-lg border px-3 py-2.5 text-[12px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
          running || liveOn
            ? "border-slate-600 bg-slate-800/60 text-slate-300 hover:text-white"
            : "border-rose-400/50 bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
        }`}
      >
        {/* Icon and label are chosen from the same condition, so a state can never render a
            play glyph on a stop action. */}
        {(() => {
          const [Icon, label] =
            source === "live"
              ? liveOn
                ? ([IconStop, "Stop live monitoring"] as const)
                : ([IconRecord, "Start live GPS monitoring"] as const)
              : running
                ? ([IconStop, "Stop replay"] as const)
                : phase === "done"
                  ? ([IconRefresh, "Reset"] as const)
                  : ([IconPlay, "Replay transit emergency"] as const);
          return (
            <span className="inline-flex items-center justify-center gap-2">
              <Icon className="h-3.5 w-3.5" />
              {label}
            </span>
          );
        })()}
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
