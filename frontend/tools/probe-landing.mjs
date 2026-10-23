/** Quick probe: render the landing page and report what is on it. */
import { chromium } from "playwright-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const page = await (await browser.newContext({ viewport: { width: 1512, height: 950 } })).newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
await page.goto(process.env.SPIDER_UI_URL || "http://localhost:5173", { waitUntil: "networkidle" });
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(1200);
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(700);
const text = await page.evaluate(() => document.body.innerText);
console.log("---- body text ----");
console.log(text.slice(0, 1200));
console.log("---- counts ----", {
  hero: await page.locator(".lp-title").count(),
  lines: await page.locator(".lp-line").count(),
  lit: await page.locator(".lp-line.is-lit").count(),
  reports: await page.locator(".lp-report").count(),
  principles: await page.locator(".lp-principle").count(),
  spiderParts: await page.locator(".sp-leg-line").count(),
});
await page.screenshot({ path: new URL("./shots/probe-landing.png", import.meta.url).pathname.replace(/^\/(\w:)/, "$1"), fullPage: true });
console.log("---- errors ----", errors.filter((e) => !/favicon|fonts.g|net::ERR_/i.test(e)).slice(0, 5));
await browser.close();
