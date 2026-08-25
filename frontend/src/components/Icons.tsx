/**
 * Cryonav icon set.
 *
 * Replaces the stock glyphs the app had been leaning on - a snowflake for the brand, a
 * high-voltage emoji for "go", geometric dingbats for the three agents. Those render
 * differently on every platform (Apple draws U+26A1 as a colour emoji, Windows as a
 * monochrome outline, Linux often as a missing box), so an interface built from them has no
 * controlled appearance at all. They also carry meanings nobody chose: a lightning bolt says
 * "electricity", which is not what a routing action is.
 *
 * DESIGN RULES, so additions stay coherent:
 *
 *   16x16 viewBox, 1.4 stroke, round caps and joins. Matches the hairline rules the layout is
 *   built from, so an icon reads as part of the ruling rather than as pasted-on decoration.
 *
 *   stroke="currentColor", fill="none" unless a solid is the point (play, record, stop). The
 *   caller owns the colour, which matters because several of these sit inside the risk
 *   palette where colour is semantic.
 *
 *   Geometry over metaphor. Icons here describe what the thing IS in the product - a route
 *   deflecting around heat, a sensor sweep, a dual solve - rather than borrowing an unrelated
 *   real-world object.
 */

type P = { className?: string; strokeWidth?: number };

const base = (className?: string) => ({
  viewBox: "0 0 16 16",
  className: className ?? "h-4 w-4",
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

/**
 * The brand mark: a path deflecting around a thermal source.
 *
 * Concentric arcs on the right are the heat; the line bending clear of them is the route.
 * That is the entire product in one figure, and unlike a snowflake it says what Cryonav does
 * rather than gesturing at "cold". It reads at 20 px because it is three strokes.
 */
export function CryonavMark({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M10.4 3.6a4.6 4.6 0 0 1 0 8.8" opacity="0.45" />
      <path d="M9.6 5.6a2.6 2.6 0 0 1 0 4.8" opacity="0.75" />
      <path d="M2 13.2c2.6 0 3.1-3.1 4.2-5.2C7 6.3 7.6 4.4 9.4 3.3" />
      <circle cx="2" cy="13.2" r="1.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Instant / one-click. A route collapsing to a single decisive stroke, not a lightning bolt. */
export function IconInstant({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M2.5 11.5 6 8l2.4 2.4L13.5 4.5" />
      <path d="M13.5 4.5H10" />
      <path d="M13.5 4.5V8" />
    </svg>
  );
}

/** Caution. A triangle, but drawn open so it sits in a hairline interface. */
export function IconAlert({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M8 2.6 14.4 13H1.6L8 2.6Z" />
      <path d="M8 6.6v3" />
      <circle cx="8" cy="11.4" r="0.55" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Agent 01, Thermal Sensing: a sweep detecting a source. */
export function IconSensing({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="8" cy="8" r="1.5" />
      <path d="M11.2 4.8a4.5 4.5 0 0 1 0 6.4" opacity="0.7" />
      <path d="M4.8 11.2a4.5 4.5 0 0 1 0-6.4" opacity="0.7" />
      <path d="M13.4 2.6a7.6 7.6 0 0 1 0 10.8" opacity="0.35" />
      <path d="M2.6 13.4a7.6 7.6 0 0 1 0-10.8" opacity="0.35" />
    </svg>
  );
}

/** Agent 02, Cool-Route Optimizer: one origin, two solves, one chosen. */
export function IconRoute({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="3" cy="12.8" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="13" cy="3.2" r="1.15" fill="currentColor" stroke="none" />
      <path d="M3.9 11.9C6.2 9.6 9.8 10 12.1 4.1" strokeDasharray="2 1.8" opacity="0.5" />
      <path d="M3.9 11.9c1.6-.2 2.3-2.4 3.6-4.1 1.2-1.6 2.6-2.6 4.4-3.6" />
    </svg>
  );
}

/** Agent 03, Emergency Sentinel: a watch over a threshold, with a pulse. */
export function IconSentinel({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M8 1.9 13.2 4v4.1c0 3-2.2 5.2-5.2 6.1-3-.9-5.2-3.1-5.2-6.1V4L8 1.9Z" />
      <path d="M5.4 8.2h1.4l.9-2 1.1 3.4.8-1.4h1" />
    </svg>
  );
}

/** Verified / measured upstream. */
export function IconCheck({ className, strokeWidth = 1.6 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M3 8.4 6.3 11.7 13 5" />
    </svg>
  );
}

/** Not measured - modelled locally. Deliberately hollow, to read as absence. */
export function IconHollow({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="8" cy="8" r="4.2" strokeDasharray="1.6 1.8" />
    </svg>
  );
}

/** Re-run. */
export function IconRefresh({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M13.2 7.2A5.3 5.3 0 1 0 12 11.4" />
      <path d="M13.4 3.4v3.9h-3.9" />
    </svg>
  );
}

/** Verify against upstream - a reticle, the instrument-panel form of "check this". */
export function IconTarget({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="8" cy="8" r="5.4" />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
      <path d="M8 1.1v1.8M8 13.1v1.8M1.1 8h1.8M13.1 8h1.8" />
    </svg>
  );
}

export function IconPlay({ className }: P) {
  return (
    <svg {...base(className)} stroke="none" fill="currentColor">
      <path d="M4.6 3.3v9.4a.6.6 0 0 0 .93.5l7-4.7a.6.6 0 0 0 0-1l-7-4.7a.6.6 0 0 0-.93.5Z" />
    </svg>
  );
}

export function IconStop({ className }: P) {
  return (
    <svg {...base(className)} stroke="none" fill="currentColor">
      <rect x="4.2" y="4.2" width="7.6" height="7.6" rx="1.1" />
    </svg>
  );
}

/** Live capture - a filled dot inside a ring, the recording convention. */
export function IconRecord({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="8" cy="8" r="5.6" />
      <circle cx="8" cy="8" r="2.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconDownload({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M8 2.6v7.2" />
      <path d="M5.1 7.1 8 10l2.9-2.9" />
      <path d="M2.8 12.6h10.4" />
    </svg>
  );
}

export function IconClose({ className, strokeWidth = 1.5 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

export function IconArrow({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <path d="M2.8 8h10.4" />
      <path d="M9.6 4.4 13.2 8l-3.6 3.6" />
    </svg>
  );
}

/** Neutral marker for an agent the trace does not have a specific icon for. */
export function IconDot({ className, strokeWidth = 1.4 }: P) {
  return (
    <svg {...base(className)} strokeWidth={strokeWidth}>
      <circle cx="8" cy="8" r="2.4" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r="5.6" opacity="0.4" />
    </svg>
  );
}
