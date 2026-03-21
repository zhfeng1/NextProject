#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

function readArg(name, defaultValue = "") {
  const idx = process.argv.indexOf(name);
  if (idx === -1) return defaultValue;
  return process.argv[idx + 1] || defaultValue;
}

const baseUrl = readArg("--base-url", "http://localhost:18080").replace(/\/+$/, "");
const siteId = readArg("--site-id", "site-1");
const artifactsDir = readArg("--artifacts-dir", path.resolve(process.cwd(), "tmp-playwright-artifacts"));
fs.mkdirSync(artifactsDir, { recursive: true });

const steps = [];
const screenshots = [];

async function runStep(name, fn, page) {
  try {
    await fn();
    steps.push({ name, ok: true });
  } catch (error) {
    const screenshot = path.join(artifactsDir, `${steps.length + 1}-${name.replace(/\s+/g, "-")}.png`);
    try {
      await page.screenshot({ path: screenshot, fullPage: true });
      screenshots.push(screenshot);
    } catch (_) {}
    steps.push({ name, ok: false, error: String(error) });
    throw error;
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await runStep("open-home", async () => {
      await page.goto(`${baseUrl}/home`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForSelector("text=站点管理", { timeout: 10000 });
    }, page);

    await runStep("open-site-editor", async () => {
      await page.goto(`${baseUrl}/site-editor/${siteId}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForSelector(`text=编辑站点：${siteId}`, { timeout: 10000 });
    }, page);

    await runStep("open-site-preview", async () => {
      await page.goto(`${baseUrl}/sites/${siteId}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForSelector("body", { timeout: 10000 });
    }, page);

    await runStep("adjust-from-editor", async () => {
      await page.goto(`${baseUrl}/site-editor/${siteId}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.getByRole("button", { name: "测试任务" }).click();
      const textarea = page.locator("textarea[placeholder*='普通调整']").first();
      await textarea.fill("playwright smoke 调整");
      const adjustBtn = page.getByRole("button", { name: "普通调整" });
      const respPromise = page.waitForResponse(
        (resp) => resp.url().includes("/api/adjust-site") && resp.request().method() === "POST",
        { timeout: 30000 },
      );
      await adjustBtn.click();
      const resp = await respPromise;
      if (resp.status() >= 400) {
        throw new Error(`adjust api status ${resp.status()}`);
      }
    }, page);

    const result = {
      ok: true,
      steps,
      artifacts: { screenshots },
      summary: "Playwright smoke passed",
    };
    console.log(JSON.stringify(result));
    await browser.close();
    process.exit(0);
  } catch (error) {
    const result = {
      ok: false,
      steps,
      artifacts: { screenshots },
      summary: `Playwright smoke failed: ${error}`,
    };
    console.log(JSON.stringify(result));
    await browser.close();
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
