/**
 * Cryonav demo-footage recorder.
 *
 *   cd demo && npm install && npx playwright install chromium && npm run record
 *
 * Drives the running app (backend :8008 + frontend :5180 — start with ./scripts/dev.sh)
 * through the submission narrative and writes one .webm per segment into demo/footage/,
 * ready to narrate over using demo/SCRIPT.md. Segments are recorded at 1920x1080@2x.
 */
import { chromium } from "playwright";
import { mkdirSync, renameSync, readdirSync } from "node:fs";

const BASE = process.env.CRYONAV_URL ?? "http://localhost:5180";
const OUT = new URL("./footage/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();

async function segment(name, viewport, fn) {
  const ctx = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    recordVideo: { dir: OUT, size: viewport },
  });
  const page = await ctx.newPage();
  try {
    await fn(page);
  } finally {
    await page.close();
    await ctx.close();
    // playwright names videos randomly; rename the newest to the segment name
    const files = readdirSync(OUT).filter((f) => f.endsWith(".webm") && !f.startsWith(name));
    const newest = files
      .map((f) => ({ f, t: f }))
      .sort((a, b) => (a.f < b.f ? 1 : -1))[0];
    if (newest) renameSync(OUT + newest.f, `${OUT}${name}.webm`);
    console.log(`✓ ${name}.webm`);
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
await segment("04-sentinel-emergency", HD, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(4500);
  await p.getByRole("button", { name: /Simulate transit emergency/ }).click();
  for (let i = 0; i < 45; i++) {
    await p.waitForTimeout(1000);
    if (await p.locator("text=EMERGENCY DISPATCH").first().isVisible().catch(() => false)) break;
  }
  await p.waitForTimeout(6000); // hold on the dispatch state + summary
});

// ---- 05 · mobile ------------------------------------------------------------------------
await segment("05-mobile", { width: 390, height: 844 }, async (p) => {
  await p.goto(BASE + "/app", { waitUntil: "networkidle" });
  await p.waitForTimeout(4000);
  await p.locator('button[aria-label="Open route controls"]').tap?.().catch(() => p.locator('button[aria-label="Open route controls"]').click());
  await p.waitForTimeout(2000);
  await p.getByRole("button", { name: /Dubai/ }).click();
  await p.waitForTimeout(4000);
  await p.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }));
  await p.waitForTimeout(3000);
});

await browser.close();
console.log("\nAll segments in demo/footage/ — narration in demo/SCRIPT.md");
