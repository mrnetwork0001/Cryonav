/**
 * Cryonav demo-footage recorder.
 *
 *   cd demo && npm install && npx playwright install chromium && npm run record
 *
 * Drives the running app (backend :8008 + frontend :5180 - start with ./scripts/dev.sh)
 * through the submission narrative and writes one .webm per segment into demo/footage/,
 * ready to narrate over using demo/SCRIPT.md. Segments are recorded at 1920x1080@2x.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.CRYONAV_URL ?? "http://localhost:5180";
const OUT = new URL("./footage/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const failed = [];

async function segment(name, viewport, fn) {
  const ctx = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    recordVideo: { dir: OUT, size: viewport },
  });
  const page = await ctx.newPage();
  // Take the video handle BEFORE the page closes. Playwright names the file with random hex,
  // and this used to be resolved by listing the directory and taking the "newest" - sorted by
  // FILENAME, not by time. Hex names beginning "00" or "01" sort below an already-renamed
  // "01-landing.webm", so the recorder would rename a PREVIOUS segment's video onto the
  // current one, destroying it, and then print a tick. saveAs() asks Playwright which file is
  // actually this page's, so there is nothing left to guess.
  const video = page.video();
  let failure;
  try {
    await fn(page);
  } catch (err) {
    // Keep whatever was captured before the failure rather than losing the segment - but do
    // not let the run claim success. A selector that has drifted must be loud: the last set of
    // footage was recorded before a redesign and nothing said so.
    failure = err;
  } finally {
    await page.close();
    await ctx.close();
    if (video) {
      await video.saveAs(`${OUT}${name}.webm`);
      await video.delete();
    }
    if (failure) {
      console.error(`✗ ${name}.webm - captured, but the script failed: ${failure.message}`);
      failed.push(name);
    } else {
      console.log(`✓ ${name}.webm`);
    }
  }
}

const HD = { width: 1920, height: 1080 };

// ---- 01 · landing ---------------------------------------------------------------------
await segment("01-landing", HD, async (p) => {
  await p.goto(BASE + "/", { waitUntil: "networkidle" });
  await p.waitForTimeout(3500);
  for (const anchor of ["#problem", "#agents", "#api", "#edge"]) {
    await p.evaluate((a) => document.querySelector(a)?.scrollIntoView({ behavior: "smooth" }), anchor);
    await p.waitForTimeout(3200);
  }
  await p.evaluate(() => document.querySelector("footer")?.scrollIntoView({ behavior: "smooth" }));
  await p.waitForTimeout(2500);
});

// ---- 02 · dashboard + FortyGuard raster ------------------------------------------------
await segment("02-dashboard-raster", HD, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(5000);
  await p.getByRole("button", { name: /FortyGuard raster/ }).click();
  await p.waitForTimeout(4500);
  await p.getByRole("button", { name: /Exposure model/ }).click();
  await p.waitForTimeout(3000);
  await p.locator(".leaflet-control-zoom-in").click();
  await p.waitForTimeout(2500);
  await p.locator(".leaflet-control-zoom-out").click();
  await p.waitForTimeout(2000);
});

// ---- 03 · profiles, corridors, shelter reroute -----------------------------------------
await segment("03-routing", HD, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(4500);
  await p.getByRole("button", { name: /Elderly \/ Vulnerable/ }).click();
  await p.waitForTimeout(3500);
  await p.getByRole("button", { name: /Van Buren transit stop/ }).click();
  await p.waitForTimeout(3500);
  await p.getByRole("button", { name: /Capitol Mall/ }).click();
  await p.waitForTimeout(3000);
  const reroute = p.getByRole("button", { name: /cooling station reroute/ });
  if (await reroute.isVisible().catch(() => false)) {
    await reroute.click();
    await p.waitForTimeout(4500);
  }
});

// ---- 04 · Sentinel emergency ------------------------------------------------------------
// CITY AND HOUR ARE SET DELIBERATELY, and this is the one place it matters.
//
// Dispatch needs the walker in the EXTREME band (or air >=110 F), and which conditions qualify
// moves with the daily calibration. On a cooler day Phoenix at the 15:00 default sits in HIGH,
// the Sentinel correctly does not escalate, and the segment records a non-event - the app even
// prints "Sentinel did NOT escalate within the immobility window - safety gap". Honest
// behaviour, useless footage, and narrating a dispatch over it would be a lie.
//
// There is a subtler trap. Phoenix at 14:00 DOES dispatch when the monitor endpoint is probed
// at the corridor's origin - but the replay still only reaches "reroute", because the walker
// collapses part-way along the COOL route, which is by construction the shadier one. The
// feature works; the demo route is the wrong place to look for it.
//
// So the Sentinel segment runs where the whole tile is genuinely extreme. Verified 2026-08-29:
// Abu Dhabi at 13:00 walks the full ladder ok -> advisory -> reroute -> dispatch, with the
// banner up at t=24s. Re-probe on the day you record - drive the replay and watch
// /api/v1/sentinel/monitor for a "dispatch" status - and override with
// CRYONAV_SENTINEL_CITY / CRYONAV_SENTINEL_HOUR rather than editing this file.
const SENTINEL_CITY = process.env.CRYONAV_SENTINEL_CITY ?? "Abu Dhabi";
const SENTINEL_HOUR = Number(process.env.CRYONAV_SENTINEL_HOUR ?? 13);

await segment("04-sentinel-emergency", HD, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(4500);

  if (SENTINEL_CITY) {
    await p.getByRole("button", { name: new RegExp(SENTINEL_CITY) }).click();
    await p.waitForTimeout(5000);
  }

  // Drive the time slider with a native input event so React's onChange fires.
  await p.evaluate((h) => {
    const el = document.querySelector('input[type="range"]');
    if (!el) return;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, "value",
    ).set;
    setter.call(el, String(h));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }, SENTINEL_HOUR);
  await p.waitForTimeout(4000);

  await p.getByRole("button", { name: /Replay transit emergency/ }).click();
  for (let i = 0; i < 45; i++) {
    await p.waitForTimeout(1000);
    if (await p.locator("text=EMERGENCY DISPATCH").first().isVisible().catch(() => false)) break;
  }
  await p.waitForTimeout(6000); // hold on the dispatch state + summary
});

// ---- 05 · mobile ------------------------------------------------------------------------
// This used to open the drawer and sit on it, so the whole segment was a static control panel:
// no map, no route, no scoreboard - under narration about routing on a phone. The drawer is
// the least interesting thing on the screen. Open it, use it, CLOSE it, and let the map and the
// scoreboard carry the segment, which is what the narration actually describes.
await segment("05-mobile", { width: 390, height: 844 }, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(5000);

  const drawer = p.locator('button[aria-label="Open route controls"]');
  await drawer.tap?.().catch(() => drawer.click());
  await p.waitForTimeout(1800);
  await p.getByRole("button", { name: /Dubai/ }).click();
  await p.waitForTimeout(2200);

  // Close it so the map is visible while the route solves - the drawer auto-closes on some
  // actions but not on a city switch, and the point of this segment is the map.
  const close = p.locator('button[aria-label="Close controls"]');
  if (await close.count()) await close.click();
  else await p.mouse.click(195, 760);
  await p.waitForTimeout(4500);

  // Scroll the scoreboard into view: the A/B comparison and the Sentinel verdict are what make
  // this a safety tool rather than a map, and they were never on camera in the mobile cut.
  await p.evaluate(() => window.scrollTo({ top: 620, behavior: "smooth" }));
  await p.waitForTimeout(3500);
  await p.evaluate(() => window.scrollTo({ top: 1250, behavior: "smooth" }));
  await p.waitForTimeout(3000);
});

// ---- 06 · documentation ------------------------------------------------------------------
// The docs are part of the argument, not an appendix: every layer carries its source and
// licence, every threshold its citation, and the assumption counter is on the page. Driven by
// slug so it follows DOCS in frontend/src/lib/docsContent.ts rather than a scroll position.
await segment("06-docs", HD, async (p) => {
  await p.goto(BASE + "/docs#data-sources", { waitUntil: "networkidle" });
  await p.waitForTimeout(4000);
  await p.evaluate(() => window.scrollTo({ top: 900, behavior: "smooth" }));
  await p.waitForTimeout(3000);
  await p.goto(BASE + "/docs#standards", { waitUntil: "networkidle" });
  await p.waitForTimeout(3500);
});

await browser.close();
if (failed.length) {
  console.error(`\n${failed.length} segment(s) failed: ${failed.join(", ")}. The footage they`);
  console.error("produced is partial. Fix the selector before using it.");
  process.exitCode = 1;
} else {
  console.log("\nAll segments in demo/footage/ - narration in demo/SCRIPT.md");
}
