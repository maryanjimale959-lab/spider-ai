/**
 * Hosted-build smoke test: does the single-origin server (API + built interface,
 * the thing a public host runs) actually work end to end?
 *
 *   node tools/verify-hosted.mjs            # against http://localhost:8000
 *
 * It registers a fresh account, uploads a real five-page PDF, waits for the
 * document to be read on its own, and writes two screenshots to the Desktop.
 */
import { chromium } from "playwright-core";
import os from "node:os";
import path from "node:path";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = process.env.SPIDER_HOSTED_URL || "http://localhost:8000";
const SAMPLE = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1")), "..", "..", "backend", "samples", "site_report.pdf");
const DESKTOP = path.join(os.homedir(), "Desktop");

const problems = [];
const check = (label, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` - ${detail}` : ""}`);
  if (!ok) problems.push(label);
};

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const page = await (await browser.newContext({ viewport: { width: 1512, height: 950 } })).newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

await page.goto(BASE, { waitUntil: "networkidle" });
check("the published build serves its own landing page", (await page.locator(".lp-title").count()) === 1);
await page.screenshot({ path: path.join(DESKTOP, "spider-ai-landing.png"), fullPage: true });

const stamp = Date.now();
await page.getByRole("button", { name: /enter the workspace/i }).first().click();
await page.waitForSelector(".auth-card", { timeout: 15000 });
await page.getByRole("button", { name: /create one/i }).click();
await page.fill("#email", `hosted.${stamp}@spider.local`);
await page.fill("#name", "Mariam Xasan Jimcaale");
await page.fill("#password", "spider-hosted-2026");
await page.click('button[type="submit"]');
await page.waitForSelector(".empty-card", { timeout: 30000 });
check("an account created over HTTP reaches the workspace", true);

await page.locator('input[type="file"]').first().setInputFiles(SAMPLE);
await page.waitForSelector(".doc-page .page-image", { timeout: 90000 });
await page.waitForFunction(
  () => /Read - the results are listed below/.test(document.querySelector(".status-text")?.textContent ?? ""),
  null,
  { timeout: 180000 },
);
check("the uploaded document was read without a button, over the hosted origin", true);

let sawSpider = false;
for (let attempt = 0; attempt < 200; attempt++) {
  const ok = await page.evaluate(() => {
    const body = document.querySelector(".spider-layer .spider-body");
    const strand = document.querySelector(".silk-strand");
    return {
      legs: document.querySelectorAll(".leg-femur").length,
      moving: !!body && /translate\((?!0 0)/.test(body.getAttribute("transform") || ""),
      silk: strand ? Number(getComputedStyle(strand).opacity) : 0,
    };
  });
  if (ok.legs === 8 && ok.moving) { sawSpider = true; if (ok.silk > 0.2) break; }
  await page.waitForTimeout(180);
}
check("the spider walks on the document from the hosted build", sawSpider);
await page.screenshot({ path: path.join(DESKTOP, "spider-ai-crawl.png") });

await page.getByRole("button", { name: /Skip to the results/i }).click().catch(() => {});
await page.waitForTimeout(1500);
const painted = await page.evaluate(() => document.querySelectorAll(".paint").length);
check("the painted lines survive on the hosted build", painted >= 12, `bands=${painted}`);
await page.screenshot({ path: path.join(DESKTOP, "spider-ai-results.png") });

const noise = errors.filter((text) => !/favicon|fonts.g|net::ERR_/i.test(text));
check("no console errors on the hosted build", noise.length === 0, noise.slice(0, 2).join(" | "));

/* the ink theme, for the same set of screenshots */
await page.getByRole("button", { name: /^Display$/ }).click();
await page.getByRole("button", { name: /Ink theme/i }).click();
await page.waitForTimeout(1200);
check("the ink theme renders from the hosted build",
  (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark");
await page.screenshot({ path: path.join(DESKTOP, "spider-ai-dark.png") });

await browser.close();
if (problems.length) {
  console.log(`\n${problems.length} check(s) failed:`);
  problems.forEach((p) => console.log(` - ${p}`));
  process.exit(1);
}
console.log(`\nHosted build works. Screenshots written to ${DESKTOP}`);
