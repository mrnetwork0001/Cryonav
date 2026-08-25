import { useState } from "react";
import { searchPlaces, type Bounds, type Place } from "../lib/geocode";

/**
 * Address search for setting an origin or destination.
 *
 * Until now a route could only start from a preset corridor or a map click. A preset proves
 * nothing to someone who suspects the demo is rigged - the honest test is a viewer typing
 * their own street and watching the router solve it. That is the whole point of this control.
 *
 * Two deliberate behaviours:
 *
 * - Search runs on submit, never on keystroke. Nominatim's usage policy caps requests at one
 *   per second, and search-as-you-type breaches it immediately.
 * - A hit outside the city tile is SHOWN, and labelled as outside, rather than hidden.
 *   Cryonav only holds measured canopy and surface temperature inside the tile, so routing
 *   from beyond it would silently fall back to a modelled field. Saying so is better than a
 *   confusing empty result, and better than a confident answer built on nothing.
 */

interface Props {
  bounds: Bounds;
  cityName: string;
  onPick: (which: "origin" | "destination", coords: [number, number]) => void;
}

export default function PlaceSearch({ bounds, cityName, onPick }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      const found = await searchPlaces(q, bounds);
      setResults(found);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResults(null);
    } finally {
      setBusy(false);
    }
  };

  const use = (p: Place, which: "origin" | "destination") => {
    onPick(which, [p.lat, p.lon]);
    setResults(null);
    setQ(p.label.split(",")[0]);
  };

  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        Find a place
      </div>
      <form onSubmit={run} className="mt-2 flex gap-1.5">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={`Address or landmark in ${cityName}`}
          aria-label="Search for an address or landmark"
          className="min-w-0 flex-1 rounded-lg border border-slate-700/50 bg-slate-950/60 px-2.5 py-2 text-[12px] text-slate-200 placeholder:text-slate-600 focus:border-sky-500/60 focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy || q.trim().length < 3}
          className="shrink-0 rounded-lg border border-slate-700/50 bg-slate-800/60 px-3 py-2 text-[12px] font-semibold text-slate-300 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "…" : "Search"}
        </button>
      </form>

      {error && <p className="mt-1.5 text-[11px] text-rose-400">{error}</p>}

      {results && results.length === 0 && (
        <p className="mt-1.5 text-[11px] text-slate-500">No match. Try a street plus the city.</p>
      )}

      {results && results.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {results.map((p, i) => (
            <li
              key={`${p.lat}-${p.lon}-${i}`}
              className="rounded-lg border border-slate-700/40 bg-slate-950/40 p-2"
            >
              <div className="truncate text-[11.5px] text-slate-300">{p.label}</div>
              <div className="mt-0.5 flex items-center gap-2">
                {p.inTile ? (
                  <span className="text-[9.5px] uppercase tracking-wider text-emerald-400">
                    in measured tile
                  </span>
                ) : (
                  <span
                    className="text-[9.5px] uppercase tracking-wider text-amber-400"
                    title="Outside the area Cryonav has measured canopy and surface temperature for"
                  >
                    outside tile
                  </span>
                )}
                <button
                  onClick={() => use(p, "origin")}
                  className="ml-auto rounded border border-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:text-white"
                >
                  set A
                </button>
                <button
                  onClick={() => use(p, "destination")}
                  className="rounded border border-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:text-white"
                >
                  set B
                </button>
              </div>
            </li>
          ))}
          <li className="pt-0.5 text-[9.5px] text-slate-600">
            Geocoding &copy; OpenStreetMap contributors, via Nominatim
          </li>
        </ul>
      )}
    </div>
  );
}
