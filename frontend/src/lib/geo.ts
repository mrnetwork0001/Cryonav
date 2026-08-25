/**
 * Displacement estimation from noisy GPS fixes.
 *
 * The Sentinel escalates when someone has not moved 25 m in eight minutes. Consumer GPS
 * reports 5–10 m accuracy in the open and degrades badly between tall buildings - exactly
 * where a heat casualty is most likely to be. So the naive estimate (distance from the
 * first fix to the last) is dangerous in a specific direction: two independent errors, each
 * up to the accuracy radius, land in the estimate at full weight. A motionless person can
 * appear to have walked 40 m, the immobility test fails, and nobody is alerted.
 *
 * Monte Carlo, 20 000 motionless walkers per row, isotropic Gaussian error at the stated
 * accuracy, 8-minute window at 1 fix/s, 25 m threshold. Reproduce with
 * `scripts/bench/displacement_montecarlo.mjs`, which imports this very file:
 *
 *   accuracy   naive first-vs-last     median-of-thirds
 *       5 m    misses  0.2%            misses 0.0%
 *      10 m    misses 22.0%            misses 0.0%
 *      20 m    misses 69.1%            misses 0.0%
 *      40 m    misses 91.2%            misses 0.0%
 *      60 m    misses 95.9%            misses 8.7%
 *
 * A low miss-rate is worthless if bought by never reporting movement, so the control matters:
 * over the same trials with the walker actually moving, false-immobility is 0.0% at a normal
 * walk (1.3 m/s) and 0.0% at a slow shuffle (0.4 m/s), at both 10 m and 40 m accuracy. It only
 * degrades (13.1% at 40 m) for a walker covering 48 m in eight minutes - barely over the
 * threshold, where the case is genuinely ambiguous.
 *
 * The estimate runs ~2/3 of true displacement, because the outer anchors sit at 1/6 and 5/6
 * of the window rather than at its ends. That bias is left uncorrected deliberately: it errs
 * toward declaring immobility, so it costs a redundant alert rather than a missed collapse.
 *
 * The fix is to estimate position from many fixes rather than one. Split the window into
 * three equal-time thirds and take the component-wise median of each; the median is robust
 * to the outliers that multipath produces, and averaging over a third of the window shrinks
 * the residual error by roughly sqrt(n). Displacement is then the largest separation among
 * the three anchors - largest, not first-to-last, so that walking away and back still reads
 * as movement rather than as immobility.
 *
 * The same estimator runs on both telemetry sources, so the scripted playback is measured
 * exactly the way a real phone is measured.
 */

export interface Fix {
  /** epoch milliseconds */
  t: number;
  lat: number;
  lon: number;
  /** reported horizontal accuracy in metres, if the source provides one */
  accuracy?: number;
}

const M_PER_DEG_LAT = 110574;
const M_PER_DEG_LON = 111320;

export function metresBetween(a: [number, number], b: [number, number]): number {
  const k = Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot((b[1] - a[1]) * M_PER_DEG_LON * k, (b[0] - a[0]) * M_PER_DEG_LAT);
}

function median(xs: number[]): number {
  const s = [...xs].sort((p, q) => p - q);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Component-wise median position of a set of fixes. */
function anchor(fixes: Fix[]): [number, number] {
  return [median(fixes.map((f) => f.lat)), median(fixes.map((f) => f.lon))];
}

/**
 * Robust displacement over the supplied window, in metres.
 *
 * Returns null when there is not enough data to make a claim - the caller must then decline
 * to assert immobility rather than assume it. Fewer than six fixes cannot fill three thirds
 * meaningfully, and asserting "has not moved" from two noisy points is how false dispatches
 * (and, worse, false reassurance) happen.
 */
export function displacementM(fixes: Fix[]): number | null {
  if (fixes.length < 6) return null;
  const t0 = fixes[0].t;
  const span = fixes[fixes.length - 1].t - t0;
  if (span <= 0) return null;

  const thirds: Fix[][] = [[], [], []];
  for (const f of fixes) {
    const idx = Math.min(2, Math.floor(((f.t - t0) / span) * 3));
    thirds[idx].push(f);
  }
  // A gap that leaves a third empty means the window is not evenly sampled; fall back to
  // halves rather than inventing an anchor.
  const filled = thirds.filter((g) => g.length > 0);
  if (filled.length < 2) return null;

  const anchors = filled.map(anchor);
  let worst = 0;
  for (let i = 0; i < anchors.length; i++) {
    for (let j = i + 1; j < anchors.length; j++) {
      worst = Math.max(worst, metresBetween(anchors[i], anchors[j]));
    }
  }
  return worst;
}

/** Drop fixes older than `windowMs`, keeping the array bounded for a long-running watch. */
export function trimWindow(fixes: Fix[], nowMs: number, windowMs: number): Fix[] {
  const cutoff = nowMs - windowMs;
  let i = 0;
  while (i < fixes.length - 1 && fixes[i].t < cutoff) i++;
  return i > 0 ? fixes.slice(i) : fixes;
}

/** Median reported accuracy over the window - what gets carried into the alert. */
export function medianAccuracyM(fixes: Fix[]): number | null {
  const acc = fixes.map((f) => f.accuracy).filter((a): a is number => typeof a === "number");
  return acc.length ? median(acc) : null;
}
