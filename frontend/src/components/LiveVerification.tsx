import { useState } from "react";
import { IconCheck, IconHollow, IconRefresh, IconTarget } from "./Icons";
import { verifyLive, type LiveProof } from "../lib/api";

/**
 * Proof-of-provenance panel.
 *
 * A dashboard full of temperatures is indistinguishable from a mock-up. Anyone can render
 * "112°F · FORTYGUARD · 200 OK" over a static JSON file, and a viewer has no way to tell the
 * difference - which means an honest build gets no more credit than a fabricated one.
 *
 * So this makes the app prove itself instead of asking to be believed. Pressing the button
 * fires a real, uncached call to FortyGuard and reports what came back: which endpoint, the
 * round-trip measured in the browser, the upstream status, and - most importantly - WHICH
 * FIELDS actually came from upstream versus which Cryonav modelled locally.
 *
 * It is deliberately not on the render path. The upstream is an asynchronous job queue: the
 * same request measured 22 s once and over 120 s a few minutes later, so nothing that has to
 * paint a frame can depend on it. Live is something a person asks for, once, on demand.
 *
 * When the call degrades, this says so in the same detail. A verification panel that only
 * ever shows success is not a verification panel.
 */

interface Props {
  lat: number;
  lon: number;
  cityId: string;
  hour: number;
}

const FIELD_LABEL: Record<string, string> = {
  air_temperature_2m: "air temperature @2 m",
  relative_humidity: "relative humidity",
  solar_irradiance: "solar irradiance",
  surface_temperature: "surface temperature",
  wind_speed: "wind speed",
};

/** Every metric the reading needs, so the modelled remainder can be named explicitly. */
const ALL_FIELDS = Object.keys(FIELD_LABEL);

export default function LiveVerification({ lat, lon, cityId, hour }: Props) {
  const [proof, setProof] = useState<LiveProof | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setProof(null);
    try {
      const p = await verifyLive(lat, lon, cityId, hour);
      setProof(p);
      setAt(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const modelled = proof ? ALL_FIELDS.filter((f) => !proof.live_fields.includes(f)) : [];

  return (
    <section className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Provenance · verify upstream
        </h2>
        {proof && (
          <span
            className="text-[10px] font-bold tracking-wider"
            style={{ color: proof.ok ? "#34d399" : "#fb923c" }}
          >
            {proof.ok ? "VERIFIED LIVE" : "DEGRADED"}
          </span>
        )}
      </div>

      {!proof && !busy && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          The figures on this page come from a field calibrated against FortyGuard this morning.
          Press below to call the API <em>now</em>, from this browser, and see exactly what comes
          back - endpoint, round-trip, and which values are upstream measurements rather than
          Cryonav's model.
        </p>
      )}

      {busy && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
          Calling FortyGuard… the upstream is an async job queue, so this can take 10–25 s. It is
          abandoned after 25 s rather than left hanging.
        </p>
      )}

      {error && (
        <div className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-[11px] text-rose-300">
          {error}
        </div>
      )}

      {proof && (
        <div className="mt-3 space-y-2.5">
          <div className="tnum grid grid-cols-3 gap-2 text-center">
            <Cell label="endpoint" value={proof.endpoint.replace("/v1/", "")} />
            <Cell label="round trip" value={`${(proof.round_trip_ms / 1000).toFixed(1)}s`} />
            <Cell
              label="live points"
              value={String(proof.live_points)}
              tone={proof.live_points > 0 ? "#34d399" : "#fb923c"}
            />
          </div>

          <div className="rounded-lg border border-slate-700/40 bg-slate-950/40 p-2.5">
            <div className="text-[9px] uppercase tracking-wider text-slate-600">
              measured upstream ({proof.live_fields.length})
            </div>
            {proof.live_fields.length ? (
              <ul className="mt-1 space-y-0.5">
                {proof.live_fields.map((f) => (
                  <li key={f} className="flex items-center gap-1.5 text-[11px] text-emerald-300">
                    <IconCheck className="h-3 w-3 shrink-0 text-emerald-400" />
                    {FIELD_LABEL[f] ?? f}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[11px] text-amber-300">
                nothing came from upstream on this call
              </p>
            )}

            {/* Naming what was NOT upstream is the part that makes this honest. A panel
                listing only the wins would imply the whole reading was measured. */}
            {modelled.length > 0 && (
              <>
                <div className="mt-2 text-[9px] uppercase tracking-wider text-slate-600">
                  modelled by Cryonav ({modelled.length})
                </div>
                <ul className="mt-1 space-y-0.5">
                  {modelled.map((f) => (
                    <li key={f} className="flex items-center gap-1.5 text-[11px] text-slate-500">
                      <IconHollow className="h-3 w-3 shrink-0 text-slate-600" />
                      {FIELD_LABEL[f] ?? f}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          {proof.reading && (
            <div className="tnum grid grid-cols-3 gap-2 text-center">
              <Cell label="air" value={`${proof.reading.air_temp_2m_f.toFixed(1)}°F`} />
              <Cell label="RH" value={`${proof.reading.relative_humidity_pct.toFixed(0)}%`} />
              <Cell label="surface" value={`${proof.reading.surface_temp_f.toFixed(0)}°F`} />
            </div>
          )}

          <p className="text-[10.5px] leading-relaxed text-slate-500">
            {proof.detail}
          </p>
          {at && (
            <p className="text-[10px] text-slate-600">
              verified at {at} · re-run any time; results are cached per coordinate per day
            </p>
          )}
        </div>
      )}

      <button
        onClick={run}
        disabled={busy}
        className="mt-3 w-full rounded-lg border border-sky-400/50 bg-sky-500/15 px-3 py-2.5 text-[12px] font-semibold text-sky-300 transition hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? (
          "Calling FortyGuard..."
        ) : (
          <span className="inline-flex items-center justify-center gap-2">
            {proof ? <IconRefresh className="h-3.5 w-3.5" /> : <IconTarget className="h-3.5 w-3.5" />}
            {proof ? "Verify again" : "Verify against FortyGuard now"}
          </span>
        )}
      </button>
    </section>
  );
}

function Cell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-950/40 px-1 py-2">
      <div className="truncate text-[13px] font-semibold" style={{ color: tone ?? "#e2e8f0" }}>
        {value}
      </div>
      <div className="mt-0.5 text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
    </div>
  );
}
