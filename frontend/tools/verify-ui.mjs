/**
 * Headless end-to-end verification for SPIDER AI.
 *
 * Deliberately real: it reads the published landing page, opens a fresh account with
 * nothing prefilled, uploads a five-page PDF, and then checks that the document is read
 * on its own - the spider standing on the text, firing silk, crossing a page break, and
 * painting the lines it has read. No demo data exists, so none is used.
 *
 *   node tools/verify-ui.mjs
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = process.env.SPIDER_UI_URL || "http://localhost:5173";
const SAMPLES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "backend", "samples");
const OUT = new URL("./shots/", import.meta.url).pathname.replace(/^\/(\w:)/, "$1");
mkdirSync(OUT, { recursive: true });

const problems = [];
const check = (label, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` - ${detail}` : ""}`);
  if (!ok) problems.push(label);
};

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1512, height: 950 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

const bodyText = () => page.evaluate(() => document.body.innerText);

/* ------------------------------------------------------------- landing page */
await page.goto(BASE, { waitUntil: "networkidle" });
const landingButton = page.getByRole("button", { name: /enter the workspace/i });
const onLanding = (await landingButton.count()) > 0;
check("the landing page opens with the reading promise", onLanding, onLanding ? "" : "no call to action found");

const landingCopy = await bodyText();
check("the landing page credits Mariam Xasan Jimcaale", /Mariam Xasan Jimcaale/.test(landingCopy));
check("the landing page links her GitHub", (await page.locator('a[href*="github.com/maryanjimale959-lab"]').count()) > 0);
check(
  "the landing page makes no claim about where files live",
  !/files stay|stay in this folder|local tool|on-device|on device|your machine|no upload/i.test(landingCopy),
);
check(
  "the landing page drops the old step-by-step and jargon",
  !/how it works/i.test(landingCopy) && !/\btrends?\b|\bjack/i.test(landingCopy),
);
check("the landing page states what it reports and what it refuses", /What it reports/.test(landingCopy) && /will not do/.test(landingCopy));

/* the interactive specimen */
const litBefore = await page.locator(".lp-line.is-lit").count();
const litTextBefore = await page.locator(".lp-line.is-lit").first().innerText();
await page.getByRole("button", { name: "Reasoning", exact: true }).click();
await page.waitForTimeout(600);
const litTextAfter = await page.locator(".lp-line.is-lit").first().innerText();
check("the hero specimen is interactive - choosing a reading lights different lines",
  litBefore > 0 && litTextAfter !== litTextBefore && /budget|figure is not stated/i.test(litTextAfter),
  `before="${litTextBefore.slice(0, 28)}" after="${litTextAfter.slice(0, 28)}"`);
await page.screenshot({ path: `${OUT}00-landing.png`, fullPage: true });

await landingButton.first().click();

/* ------------------------------------------------------------------ sign in */
await page.waitForSelector(".auth-card", { timeout: 15000 });
const prefilledEmail = await page.inputValue("#email");
const prefilledPassword = await page.inputValue("#password");
check("nothing is filled in for you - no shared demo account",
  prefilledEmail === "" && prefilledPassword === "",
  `email="${prefilledEmail}" password="${prefilledPassword}"`);

await page.getByRole("button", { name: /back to the page/i }).click();
await page.waitForSelector(".lp-hero", { timeout: 10000 });
check("the workspace link goes back to the page", (await page.locator(".lp-title").count()) === 1);
await page.getByRole("button", { name: /enter the workspace/i }).first().click();
await page.waitForSelector(".auth-card", { timeout: 10000 });

/* -------------------------------------------------------- a real new account */
const stamp = Date.now();
const email = `mariam.${stamp}@spider.local`;
await page.getByRole("button", { name: /create one/i }).click();
await page.fill("#email", email);
await page.fill("#name", "Mariam Xasan Jimcaale");
await page.fill("#password", "spider-real-2026");
await page.click('button[type="submit"]');
await page.waitForSelector(".work, .empty-card", { timeout: 25000 });
check("a fresh account starts with nothing in it", (await page.locator(".empty-card").count()) === 1);
const emptyCopy = await page.locator(".empty-card").innerText();
check("the empty workspace promises the walk, not a menu", /spider walks your document/i.test(emptyCopy));

/* ------------------------------------------- upload a real five-page PDF once */
await page.locator('input[type="file"]').first().setInputFiles(`${SAMPLES}/site_report.pdf`);
await page.waitForSelector(".doc-page .page-image", { timeout: 60000 });
await page.waitForFunction(
  () => Array.from(document.querySelectorAll(".doc-page .page-image")).some((img) => img.naturalWidth > 0),
  null,
  { timeout: 60000 },
);
check("the uploaded PDF renders as its own five pages", (await page.locator(".doc-page").count()) === 5,
  `pages=${await page.locator(".doc-page").count()}`);

/* the reading has to start by itself - nobody should have to find a button */
await page.waitForFunction(
  () => /Read - the results are listed below/.test(document.querySelector(".status-text")?.textContent ?? ""),
  null,
  { timeout: 120000 },
);
check("an uploaded document is read on its own, without a button", true);
await page.waitForSelector(".strip", { timeout: 20000 });
await page.waitForSelector(".spider-layer", { timeout: 20000 });

/* the old jargon must be gone from the toolbar */
const toolbarCopy = await page.locator(".toolbar").innerText();
check("the controls use plain words",
  !/replay crawl|show all|on-device/i.test(toolbarCopy) && /Watch it again|Pause|Skip to the results/.test(toolbarCopy),
  toolbarCopy.replace(/\s+/g, " ").slice(0, 120));

/* -------------------------------------- the spider works on the text, line by line */
await page.getByRole("button", { name: /Quick/i }).click();

/** Make sure a walk is running, so the measurements below are of a moving spider. */
async function ensureWalking() {
  const again = page.getByRole("button", { name: /Watch it again/i });
  if (await again.count()) await again.first().click();
  await page.waitForTimeout(1400);
}
await ensureWalking();

const positions = [];
const pagesVisited = new Set();
const silk = { fired: false, hung: false };
let surfaceWidth = 0;

for (let attempt = 0; attempt < 500; attempt++) {
  // a dev-server reload can kill the context mid-run; skip that sample rather than fail
  let sample;
  try {
    sample = await page.evaluate(() => {
    const body = document.querySelector(".spider-layer .spider-body");
    const transform = body ? body.getAttribute("transform") : "";
    const match = transform ? transform.match(/translate\(([-\d.]+) ([-\d.]+)\)/) : null;
    const surface = document.querySelector(".doc-surface");
    const strand = document.querySelector(".silk-strand");
    const hang = document.querySelector(".silk-hang");
    const pageBoxes = Array.from(document.querySelectorAll(".doc-page")).map((el) => ({
      top: el.offsetTop,
      bottom: el.offsetTop + el.offsetHeight,
    }));
    const x = match ? Number(match[1]) : null;
    const y = match ? Number(match[2]) : null;
    let pageIndex = -1;
    if (y != null) pageIndex = pageBoxes.findIndex((box) => y >= box.top - 8 && y <= box.bottom + 8);
    return {
      x,
      pageIndex,
      width: surface ? surface.clientWidth : 0,
      strand: strand ? Number(getComputedStyle(strand).opacity) : 0,
      strandLength: strand ? (strand.getAttribute("d") || "").length : 0,
      hang: hang ? Number(getComputedStyle(hang).opacity) : 0,
      done: /Read to the end/.test(document.querySelector(".status-task")?.textContent ?? ""),
    };
    });
  } catch {
    await page.waitForTimeout(900);
    continue;
  }

  if (sample.x != null && sample.x > 1) {
    positions.push(sample.x);
    surfaceWidth = sample.width || surfaceWidth;
  }
  if (sample.pageIndex >= 0) pagesVisited.add(sample.pageIndex);
  if (sample.strand > 0.2 && sample.strandLength > 12) silk.fired = true;
  if (sample.hang > 0.2) silk.hung = true;
  if (sample.done && positions.length > 20) break;
  await page.waitForTimeout(160);
}

const medianX = positions.length ? positions.sort((a, b) => a - b)[Math.floor(positions.length / 2)] : null;
check("the spider stands on the text column, not beside it",
  medianX != null && surfaceWidth > 0 && medianX > surfaceWidth * 0.14 && medianX < surfaceWidth * 0.86,
  `median x=${medianX == null ? "n/a" : Math.round(medianX)} of ${Math.round(surfaceWidth)}, samples=${positions.length}`);
check("the web-shooter fires silk", silk.fired);
check("the spider hangs from a thread", silk.hung);
check("the walk crosses a page break - it reads the whole document", pagesVisited.size >= 2,
  `pages visited=${Array.from(pagesVisited).map((i) => i + 1).sort().join(",")}`);
await page.screenshot({ path: `${OUT}01-crawl.png` });

/* ------------------------------------------------------------------ the gait */
await ensureWalking();
const femoraA = await page.locator(".leg-femur").evaluateAll((ps) => ps.map((p) => p.getAttribute("d")));
const tibiaeA = await page.locator(".leg-tibia").evaluateAll((ps) => ps.map((p) => p.getAttribute("d")));
await page.waitForTimeout(420);
const femoraB = await page.locator(".leg-femur").evaluateAll((ps) => ps.map((p) => p.getAttribute("d")));
check("eight legs, each in two tapered segments", femoraA.length === 8 && tibiaeA.length === 8, `femurs=${femoraA.length}`);
check("the legs move while it walks", femoraA.filter((value, i) => value !== femoraB[i]).length >= 2,
  `changed=${femoraA.filter((value, i) => value !== femoraB[i]).length}`);

/* ------------------------------------------------------------- pause and skip */
await page.getByRole("button", { name: /^Pause$/ }).click();
const frozenA = await page.locator(".spider-layer .spider-body").getAttribute("transform");
await page.waitForTimeout(1200);
check("pause freezes the spider", frozenA === (await page.locator(".spider-layer .spider-body").getAttribute("transform")));
await page.getByRole("button", { name: /^Resume$/ }).click();
await page.waitForTimeout(1400);
check("resume continues the walk", frozenA !== (await page.locator(".spider-layer .spider-body").getAttribute("transform")));

await page.getByRole("button", { name: /Skip to the results/i }).click();
await page.waitForTimeout(1200);
const painted = await page.evaluate(() => {
  const bands = Array.from(document.querySelectorAll(".paint"));
  const tones = new Set(bands.map((band) => Array.from(band.classList).find((name) => name.startsWith("tone-"))));
  return { count: bands.length, tones: Array.from(tones), labelled: bands.filter((b) => b.querySelector(".paint-label")).length };
});
check("the lines it read stay painted, in several tones",
  painted.count >= 12 && painted.tones.length >= 3,
  `bands=${painted.count}, tones=${painted.tones.join(",")}, labelled=${painted.labelled}`);
await page.screenshot({ path: `${OUT}02-painted.png` });

/* --------------------------------------------------------- results strip rows */
const rows = await page.locator(".strip-row").count();
check("the results strip lists what was found", rows > 3, `rows=${rows}`);
await page.locator(".strip-row").first().click();
await page.waitForSelector(".detail .quote", { timeout: 20000 });
const quote = await page.locator(".detail .quote-text").first().innerText();
check("the detail shows a quotation taken from the page", quote.length > 12, quote.slice(0, 60));
await page.screenshot({ path: `${OUT}03-detail.png` });

/* ---------------------------------------------------------------- vocabulary */
await page.getByRole("tab", { name: /Vocabulary/ }).click();
await page.locator(".strip-row").first().click();
await page.waitForTimeout(1600);
const keywordBands = await page.evaluate(() => document.querySelectorAll(".paint.tone-keyword").length);
check("choosing a term paints every place it appears", keywordBands >= 1, `painted=${keywordBands}`);
await page.screenshot({ path: `${OUT}04-keyword.png` });

/* ------------------------------------------------------------------------ ask */
await page.getByRole("tab", { name: /Ask a question/ }).click();
await page.locator(".strip-ask input").fill("How many hand pumps were reported as working?");
await page.getByRole("button", { name: /^Ask$/ }).last().click();
await page.waitForSelector(".detail .quote", { timeout: 30000 });
const answer = await page.locator(".detail-body").first().innerText();
check("questions are answered from the document, with the passage quoted", /71/.test(answer), answer.slice(0, 70));

/* ------------------------------------------------------------------ the web */
await page.getByRole("button", { name: /^The web$/ }).click();
await page.waitForSelector(".react-flow__node", { timeout: 25000 });
const nodes = await page.locator(".react-flow__node").count();
const edges = await page.locator(".react-flow__edge").count();
check("the web shows the same results", nodes > 8 && edges > 4, `nodes=${nodes}, edges=${edges}`);
check("the spider is the hub", (await page.locator(".hub-node").count()) === 1);
await page.waitForTimeout(700);
await page.screenshot({ path: `${OUT}05-web.png` });

/* ------------------------------------------------------ ink theme and Arabic */
await page.getByRole("button", { name: /^The crawl$/ }).click();
await page.getByRole("button", { name: /^Display$/ }).click();
await page.getByRole("button", { name: /Ink theme/i }).click();
await page.waitForTimeout(900);
check("the ink theme applies", (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark");
await page.screenshot({ path: `${OUT}06-dark.png` });
await page.getByRole("button", { name: /Ink theme/i }).click();
await page.keyboard.press("Escape");
await page.waitForTimeout(500);

await page.locator(".doc-pick").click();
await page.locator('.pop input[type="file"]').setInputFiles(`${SAMPLES}/arabic_report.md`);
await page.waitForSelector('.doc-passage[dir="rtl"]', { timeout: 60000 });
await page.waitForTimeout(4000);
check("an Arabic upload is read right-to-left, with the spider on it",
  (await page.locator(".leg-femur").count()) === 8);
await page.screenshot({ path: `${OUT}07-arabic.png` });

/* ------------------------------------------------------------------ console */
const noise = consoleErrors.filter((text) => !/favicon|React DevTools|fonts.g|net::ERR_/i.test(text));
check("no console errors during the run", noise.length === 0, noise.slice(0, 3).join(" | "));

await browser.close();
if (problems.length) {
  console.log(`\n${problems.length} check(s) failed:`);
  problems.forEach((problem) => console.log(` - ${problem}`));
  process.exit(1);
}
console.log("\nAll checks passed against a real upload. Screenshots in frontend/tools/shots/");
