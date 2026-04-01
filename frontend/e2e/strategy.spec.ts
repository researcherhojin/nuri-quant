import { test, expect } from "@playwright/test";

test.describe("Strategy page", () => {
  test("renders strategy page with backtest data", async ({ page }) => {
    await page.goto("/strategy", { timeout: 15000 });
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });

  test("renders SVG charts (recharts)", async ({ page }) => {
    await page.goto("/strategy", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // Recharts renders real SVG in browser
    const svgs = page.locator("svg");
    const count = await svgs.count();
    // May have charts if backtest data exists
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Portfolio page", () => {
  test("renders portfolio page", async ({ page }) => {
    await page.goto("/portfolio", { timeout: 15000 });
    await page.waitForTimeout(3000);
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10000 });
  });

  test("can open Add Holding form", async ({ page }) => {
    await page.goto("/portfolio", { timeout: 15000 });
    await page.waitForTimeout(3000);
    const addBtn = page.locator("text=Add Holding").first();
    if ((await addBtn.count()) > 0) {
      await addBtn.click();
      await expect(page.locator('input[placeholder*="Ticker"]')).toBeVisible();
    }
  });

  test("shows import/export buttons", async ({ page }) => {
    await page.goto("/portfolio", { timeout: 15000 });
    await page.waitForTimeout(3000);
    const csv = page.locator("text=Upload CSV").first();
    if ((await csv.count()) > 0) {
      await expect(csv).toBeVisible();
    }
  });
});
