/** Close-up capture of the spider while it walks, for visual quality review. */
import { chromium } from "playwright-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = "http://localhost:5173";

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 3 });
const page = await context.newPage();

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "student@spider.local");
await page.fill("#password", "spider-student-2026");
await page.click('button[type="submit"]');
await page.waitForSelector(".workspace");
await page.getByText("english_report (PDF)", { exact: false }).first().click();
await page.waitForSelector(".spider-layer");
await page.waitForTimeout(2500);

// Ask for a slower crawl so we sample a genuine mid-stride pose.
await page.getByRole("button", { name: /Replay crawl|Pause crawl|Resume crawl/i }).first().click().catch(() => {});

const box = await page.evaluate(() => {
  const body = document.querySelector(".spider-layer .spider-body");
  const layer = document.querySelector(".spider-layer");
  const transform = body.getAttribute("transform") || "";
  const match = transform.match(/translate\(([-\d.]+) ([-\d.]+)\)/);
  const rect = layer.getBoundingClientRect();
  return {
    x: rect.left + (match ? Number(match[1]) : 0),
    y: rect.top + (match ? Number(match[2]) : 0),
    transform,
  };
});

console.log("spider at", JSON.stringify(box));
await page.screenshot({
  path: new URL("./shots/spider-closeup.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"),
  clip: { x: Math.max(0, box.x - 190), y: Math.max(0, box.y - 150), width: 380, height: 300 },
});

// Also a wider context shot showing the spider on the page.
await page.screenshot({
  path: new URL("./shots/spider-on-page.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"),
  clip: { x: Math.max(0, box.x - 320), y: Math.max(0, box.y - 220), width: 900, height: 620 },
});

await browser.close();
console.log("done");
