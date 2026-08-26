import { useCallback, useEffect, useRef, useState } from "react";
import { fetchFacts, type Facts } from "../lib/api";
import { useDismiss } from "../lib/useDismiss";
import { DOCS, type Block, type Section } from "../lib/docsContent";

/**
 * Documentation site at /docs.
 *
 * Same console idiom as the landing page - hairline rules, near-black ground, light-weight
 * statement type - so a reader moving between them does not feel handed off to a different
 * product. Grouped sidebar on the left, one section at a time on the right.
 *
 * Deliberately NOT a router. The app has three pages and no routing dependency; adding one
 * for a documentation site would be the largest new dependency in the project, in service of
 * a single list of anchors. Section selection is state, and the URL hash mirrors it so a
 * section can still be linked, bookmarked and reloaded.
 *
 * /docs previously served FastAPI's Swagger UI, which moved to /api/docs. An API reference
 * and a product manual are different documents for different readers, and the reader who
 * types /docs is almost never after OpenAPI.
 */

const GROUPS = Array.from(new Set(DOCS.map((s) => s.group)));

export default function Docs() {
  const [active, setActive] = useState<string>(() => {
    const hash = window.location.hash.replace("#", "");
    return DOCS.some((s) => s.slug === hash) ? hash : DOCS[0].slug;
  });
  const [menuOpen, setMenuOpen] = useState(false);
  // The docs sidebar REPLACES the content on a phone rather than overlaying it, so there
  // is no outside to tap. Escape still applies - a keyboard user otherwise has no way out
  // except finding the toggle again.
  const shellRef = useRef<HTMLDivElement | null>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  // The hash is the source of truth for deep links, so back/forward work without a router.
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace("#", "");
      if (DOCS.some((s) => s.slug === h)) setActive(h);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useDismiss(shellRef, menuOpen, closeMenu);

  const go = (slug: string) => {
    setActive(slug);
    setMenuOpen(false);
    history.replaceState(null, "", `#${slug}`);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  };

  const section = DOCS.find((s) => s.slug === active) ?? DOCS[0];
  const index = DOCS.findIndex((s) => s.slug === section.slug);
  const prev = index > 0 ? DOCS[index - 1] : null;
  const next = index < DOCS.length - 1 ? DOCS[index + 1] : null;

  return (
    <div className="min-h-full bg-[#05070b] text-slate-200">
      <header className="sticky top-0 z-40 border-b border-slate-800/50 bg-[#05070b]/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3.5">
          <a href="/" className="flex items-center" aria-label="Cryonav home">
            <img
              src="/brand/cryonav-wordmark.png"
              alt="Cryonav - Thermal Navigation System"
              className="h-8 w-auto sm:h-9"
              width={506}
              height={128}
            />
          </a>
          <nav className="hidden items-center gap-1 text-[10px] font-medium tracking-[0.22em] text-slate-500 md:flex">
            <a href="/app" className="px-3 py-2 transition hover:text-slate-200">
              DASHBOARD
            </a>
            <a href="/docs" className="px-3 py-2 text-slate-200">
              DOCS
            </a>
            <a href="/api/docs" className="px-3 py-2 transition hover:text-slate-200">
              API
            </a>
            <a
              href="https://github.com/mrnetwork0001/Cryonav"
              target="_blank"
              rel="noreferrer"
              className="px-3 py-2 transition hover:text-slate-200"
            >
              GITHUB
            </a>
          </nav>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Documentation sections"
            aria-expanded={menuOpen}
            className="grid h-9 w-9 place-items-center rounded-md border border-slate-700/60 text-slate-300 transition hover:border-slate-500 md:hidden"
          >
            <svg
              viewBox="0 0 20 20"
              className="h-4 w-4 fill-none stroke-current"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden
            >
              {menuOpen ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 5.5h14M3 10h14M3 14.5h14" />}
            </svg>
          </button>
        </div>
        <div className="ticker h-px w-full opacity-70" aria-hidden />
      </header>

      <div className="mx-auto flex max-w-[1400px] gap-0 px-6" ref={shellRef}>
        {/* ---- sidebar ---------------------------------------------------------------- */}
        <aside
          className={`${
            menuOpen ? "block" : "hidden"
          } w-full shrink-0 border-slate-800/50 py-8 md:block md:w-[248px] md:border-r md:pr-8`}
        >
          <nav className="md:sticky md:top-24">
            {GROUPS.map((group) => (
              <div key={group} className="mb-7">
                <div className="eyebrow px-3">{group}</div>
                <ul className="mt-2.5 space-y-0.5">
                  {DOCS.filter((s) => s.group === group).map((s) => {
                    const on = s.slug === section.slug;
                    return (
                      <li key={s.slug}>
                        <button
                          onClick={() => go(s.slug)}
                          className={`w-full border-l-2 px-3 py-2 text-left text-[13px] transition ${
                            on
                              ? "border-cyan-400 bg-cyan-400/[0.07] text-cyan-300"
                              : "border-transparent text-slate-400 hover:border-slate-700 hover:text-slate-200"
                          }`}
                        >
                          {s.title}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        {/* ---- content ----------------------------------------------------------------- */}
        <main className={`${menuOpen ? "hidden" : "block"} min-w-0 flex-1 py-10 md:block md:py-14 md:pl-12`}>
          <article className="max-w-3xl">
            <div className="eyebrow">{section.group}</div>
            <h1 className="statement mt-4 text-[34px] text-white sm:text-[42px]">{section.title}</h1>
            <p className="mt-6 text-[15.5px] leading-[1.75] text-slate-400">{section.intro}</p>
            <div className="mt-10 space-y-6">
              {section.blocks.map((b, i) => (
                <BlockView key={i} block={b} />
              ))}
            </div>

            <div className="mt-16 flex flex-wrap items-stretch justify-between gap-3 border-t border-slate-800/50 pt-8">
              {prev ? (
                <button
                  onClick={() => go(prev.slug)}
                  className="cell max-w-[48%] flex-1 border-b border-r px-4 py-3 text-left transition hover:bg-white/[0.02]"
                >
                  <div className="eyebrow">Previous</div>
                  <div className="mt-1.5 text-[13.5px] text-slate-200">{prev.title}</div>
                </button>
              ) : (
                <span />
              )}
              {next && (
                <button
                  onClick={() => go(next.slug)}
                  className="cell max-w-[48%] flex-1 border-b border-r px-4 py-3 text-right transition hover:bg-white/[0.02]"
                >
                  <div className="eyebrow">Next</div>
                  <div className="mt-1.5 text-[13.5px] text-slate-200">{next.title}</div>
                </button>
              )}
            </div>
          </article>
        </main>
      </div>

      <footer className="border-t border-slate-800/50">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-6 py-6 text-[10.5px] tracking-[0.06em] text-slate-600">
          <span>&copy; 2026 Cryonav &middot; MIT License &middot; Built for FortyGuard Hackathon &apos;26</span>
          <span className="tnum">
            Map data &copy; OpenStreetMap contributors &middot; Thermal data: FortyGuard
            Temperature API&reg;
          </span>
        </div>
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------
   Block renderer.

   Content arrives as structured blocks rather than markdown, so no parser ships to the
   browser and every block type is styled deliberately. `**bold**` inside list items and
   paragraphs is the one inline convention supported, because label-then-explanation is the
   shape most of these lists take.
   ------------------------------------------------------------------------------------------ */

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-slate-100">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

/**
 * The coverage table, rendered from the running API instead of from the content file.
 *
 * These figures move whenever a city is onboarded or a tile is recalibrated. Frozen in prose
 * they went stale silently, which is the failure mode documentation is worst at surfacing:
 * the page still looks authoritative while being wrong. Fetching them means the table cannot
 * disagree with the system it documents.
 *
 * When the API is unreachable it says so rather than rendering an empty table or falling back
 * to remembered numbers - a documentation page asserting stale figures with no indication
 * they are stale would be worse than showing nothing.
 */
function LiveCities({ note }: { note?: string }) {
  const [rows, setRows] = useState<string[][] | null>(null);
  const [failed, setFailed] = useState(false);
  const [at, setAt] = useState("");

  useEffect(() => {
    Promise.all([
      fetch("/api/v1/cities").then((r) => r.json()),
      fetch("/api/v1/meta").then((r) => r.json()),
    ])
      .then(([cities, meta]) => {
        const observed = meta.observed_data ?? {};
        setRows(
          (cities.cities ?? []).map((c: Record<string, unknown>) => {
            const id = String(c.id);
            const canopy = observed[id]?.canopy?.city_canopy_fraction;
            const surf = observed[id]?.surface_temperature_peak ? "ECOSTRESS 70 m" : "Landsat 30 m";
            const tiles = Number(c.raster_tiles ?? 0);
            return [
              `${c.name}, ${c.region}`,
              canopy != null ? `${(Number(canopy) * 100).toFixed(2)}%` : "not measured",
              surf,
              String(c.shelter_count ?? "-"),
              tiles > 0 ? `${tiles.toLocaleString()} tiles at ~100 m` : "no US coverage",
              c.calibrated ? "live" : "modelled",
            ];
          }),
        );
        setAt(new Date().toLocaleString());
      })
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <div className="border-l-2 border-amber-500/50 bg-amber-500/[0.05] px-5 py-4 text-[14px] leading-[1.75] text-amber-200/90">
        The coverage table is read from the live API and the API is unreachable from here, so it
        is not shown. It is deliberately not backed by remembered figures: a documentation page
        asserting stale numbers without saying they are stale is worse than one showing none.
      </div>
    );
  }
  if (!rows) {
    return <div className="text-[13px] text-slate-600">Reading coverage from the API...</div>;
  }

  return (
    <div>
      <div className="cell cell-grid overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-[13.5px]">
          <thead>
            <tr className="border-b border-slate-800/70 text-[9.5px] uppercase tracking-[0.2em] text-slate-500">
              {["City", "Canopy", "Peak surface", "Shelters", "FortyGuard raster", "Ambient"].map(
                (h) => (
                  <th key={h} className="px-5 py-3.5 font-semibold">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="tnum">
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-800/50 last:border-0">
                {r.map((cell, j) => (
                  <td
                    key={j}
                    className={`px-5 py-3.5 align-top ${
                      j === 0 ? "font-medium text-slate-200" : "text-slate-400"
                    }`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2.5 text-[10.5px] text-slate-600">
        {note} Read {at}, so this table cannot disagree with the running system.
      </p>
    </div>
  );
}

/**
 * The two-street comparison, sampled rather than quoted.
 *
 * This table carries the product's central claim, and it moves with every daily calibration.
 * Frozen, it was already wrong: it asserted a 10 degree air gap where the live sample measured
 * 0.2 degrees, which is a stronger statement of the same thesis. A claim this load-bearing is
 * the last thing that should be a literal.
 */
function LiveContrast({ note }: { note?: string }) {
  const [f, setF] = useState<Facts | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchFacts().then(setF).catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <div className="border-l-2 border-amber-500/50 bg-amber-500/[0.05] px-5 py-4 text-[14px] leading-[1.75] text-amber-200/90">
        This comparison is sampled from the live API, which is unreachable from here. It is
        deliberately not backed by remembered figures - the readings move with every daily
        calibration, so a stored copy would be wrong without saying so.
      </div>
    );
  }
  if (!f) return <div className="text-[13px] text-slate-600">Sampling both streets...</div>;

  const { hot, cool, air_gap_f, radiant_gap_f, exposure_gap_f } = f.contrast;
  const rows: [string, string, string, string][] = [
    ["Air temperature @ 2 m", `${hot.air_temp_2m_f.toFixed(1)} °F`, `${cool.air_temp_2m_f.toFixed(1)} °F`, `${Math.abs(air_gap_f).toFixed(1)} °F`],
    ["Surface temperature", `${hot.surface_temp_f.toFixed(1)} °F`, `${cool.surface_temp_f.toFixed(1)} °F`, `${Math.abs(hot.surface_temp_f - cool.surface_temp_f).toFixed(1)} °F`],
    ["Mean radiant temperature", `${hot.mean_radiant_temp_f.toFixed(1)} °F`, `${cool.mean_radiant_temp_f.toFixed(1)} °F`, `${Math.abs(radiant_gap_f).toFixed(1)} °F`],
    ["Measured canopy", `${hot.canopy_cover_pct.toFixed(0)} %`, `${cool.canopy_cover_pct.toFixed(0)} %`, ""],
    ["Exposure index", `${hot.exposure_index_f.toFixed(1)} °F`, `${cool.exposure_index_f.toFixed(1)} °F`, `${Math.abs(exposure_gap_f).toFixed(1)} °F`],
    ["Risk band", hot.risk_level.toUpperCase(), cool.risk_level.toUpperCase(), ""],
  ];

  return (
    <div>
      <div className="cell cell-grid overflow-x-auto">
        <table className="w-full min-w-[600px] text-left text-[13.5px]">
          <thead>
            <tr className="border-b border-slate-800/70 text-[9.5px] uppercase tracking-[0.2em] text-slate-500">
              <th className="px-5 py-3.5 font-semibold">Measure</th>
              <th className="px-5 py-3.5 font-semibold">{hot.name}</th>
              <th className="px-5 py-3.5 font-semibold">{cool.name}</th>
              <th className="px-5 py-3.5 font-semibold">Gap</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-800/50 last:border-0">
                {r.map((cell, j) => (
                  <td
                    key={j}
                    className={`px-5 py-3.5 align-top ${
                      j === 0
                        ? "font-medium text-slate-200"
                        : j === 3
                          ? "text-cyan-300"
                          : "text-slate-400"
                    }`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2.5 text-[10.5px] leading-relaxed text-slate-600">
        {note} {hot.kind} against {cool.kind}, both at {f.contrast.hour.toFixed(0)}:00 local in{" "}
        {f.contrast.city_id}. The air layer separates them by{" "}
        {Math.abs(air_gap_f).toFixed(1)} °F; the radiant load separates them by{" "}
        {Math.abs(radiant_gap_f).toFixed(1)} °F. That is the whole argument, and it is sampled
        rather than stated.
      </p>
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "h2":
      return (
        <h2 className="statement pt-6 text-[24px] text-white sm:text-[28px]">{block.text}</h2>
      );

    case "p":
      return <p className="text-[15px] leading-[1.8] text-slate-400">{inline(block.text ?? "")}</p>;

    case "ul":
      return (
        <ul className="space-y-2.5">
          {(block.items ?? []).map((it, i) => (
            <li key={i} className="flex gap-3 text-[15px] leading-[1.75] text-slate-400">
              <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-slate-600" />
              <span>{inline(it)}</span>
            </li>
          ))}
        </ul>
      );

    case "note":
      return (
        <div className="border-l-2 border-cyan-400/50 bg-cyan-400/[0.04] px-5 py-4 text-[14px] leading-[1.75] text-slate-300">
          {inline(block.text ?? "")}
        </div>
      );

    case "code":
      return (
        <div className="cell cell-grid overflow-x-auto">
          {block.lang && <div className="eyebrow px-5 pt-4">{block.lang}</div>}
          <pre className="overflow-x-auto px-5 py-4 font-mono text-[12.5px] leading-relaxed text-slate-300">
            {block.text}
          </pre>
        </div>
      );

    case "live-cities":
      return <LiveCities note={block.text} />;

    case "live-contrast":
      return <LiveContrast note={block.text} />;

    case "table":
      return (
        <div className="cell cell-grid overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-slate-800/70 text-[9.5px] uppercase tracking-[0.2em] text-slate-500">
                {(block.headers ?? []).map((h) => (
                  <th key={h} className="px-5 py-3.5 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(block.rows ?? []).map((row, i) => (
                <tr key={i} className="border-b border-slate-800/50 last:border-0">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className={`px-5 py-3.5 align-top ${
                        j === 0 ? "font-medium text-slate-200" : "text-slate-400"
                      }`}
                    >
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    default:
      return null;
  }
}

export type { Section };
