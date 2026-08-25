// Monte Carlo behind the figures documented in frontend/src/lib/geo.ts.
//
// It imports the SHIPPED estimator rather than a copy, so the published numbers describe the
// code that actually runs on the phone.
//
//   cd frontend
//   ./node_modules/.bin/esbuild src/lib/geo.ts --bundle --format=esm --outfile=/tmp/geo.mjs
//   node ../scripts/bench/displacement_montecarlo.mjs /tmp/geo.mjs
//
// The LCG is seeded, so the numbers reproduce exactly.

const { displacementM } = await import(process.argv[2] || "/tmp/geo.mjs");

const LAT = 33.4485;
const LON = -112.0762;
const M_LAT = 110574;
const M_LON = 111320 * Math.cos((LAT * Math.PI) / 180);
const N = 480; // 8-minute window at 1 fix/s
const RADIUS_M = 25; // the Sentinel's immobility threshold
const TRIALS = 20000;

let seed = 20260825;
function rnd() {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x7fffffff;
}
function gauss() {
  const u = Math.max(rnd(), 1e-12);
  const v = rnd();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** The estimator this replaces: distance from the first fix to the last. */
function naive(fixes) {
  const a = fixes[0];
  const b = fixes[fixes.length - 1];
  return Math.hypot((b.lon - a.lon) * M_LON, (b.lat - a.lat) * M_LAT);
}

/** `speed` m/s along a random heading, with isotropic Gaussian error at `acc` metres. */
function walk(speed, acc) {
  const hdg = rnd() * 2 * Math.PI;
  const fixes = [];
  for (let i = 0; i < N; i++) {
    const d = speed * i;
    fixes.push({
      t: i * 1000,
      lat: LAT + (d * Math.cos(hdg) + gauss() * acc) / M_LAT,
      lon: LON + (d * Math.sin(hdg) + gauss() * acc) / M_LON,
      accuracy: acc,
    });
  }
  return fixes;
}

const pct = (x) => ((100 * x) / TRIALS).toFixed(1).padStart(5) + "%";

console.log(
  `Motionless walker — a MISS is a collapse read as movement, so nobody is alerted.\n` +
    `${TRIALS} trials, 8-min window @1 Hz, ${RADIUS_M} m threshold.\n`,
);
console.log("accuracy   naive first-vs-last        median-of-thirds");
for (const acc of [5, 10, 20, 40, 60]) {
  let missN = 0;
  let missM = 0;
  let sumN = 0;
  let sumM = 0;
  for (let trial = 0; trial < TRIALS; trial++) {
    const fixes = walk(0, acc);
    const dn = naive(fixes);
    const dm = displacementM(fixes);
    sumN += dn;
    sumM += dm;
    if (dn >= RADIUS_M) missN++;
    if (dm >= RADIUS_M) missM++;
  }
  console.log(
    `${String(acc).padStart(5)} m   ${pct(missN)} (mean ${(sumN / TRIALS).toFixed(1).padStart(5)} m)   ` +
      `${pct(missM)} (mean ${(sumM / TRIALS).toFixed(1).padStart(4)} m)`,
  );
}

console.log(
  `\nCONTROL — moving walker. A low miss-rate above is worthless if bought by never\n` +
    `reporting movement, so this must stay near zero.\n`,
);
console.log("speed         accuracy   false-immobility   mean estimate");
for (const [speed, label] of [
  [1.3, "normal walk"],
  [0.4, "slow shuffle"],
  [0.1, "barely moving"],
]) {
  for (const acc of [10, 40]) {
    let bad = 0;
    let sum = 0;
    for (let trial = 0; trial < TRIALS; trial++) {
      const dm = displacementM(walk(speed, acc));
      sum += dm;
      if (dm < RADIUS_M) bad++;
    }
    console.log(
      `${label.padEnd(13)} ${String(acc).padStart(2)} m      ${pct(bad)}          ` +
        `${(sum / TRIALS).toFixed(1)} m (true ${(speed * (N - 1)).toFixed(0)} m)`,
    );
  }
}
