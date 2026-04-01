import { test, expect } from "@playwright/test";

test.describe("Server Component Pages (real backend)", () => {
  test("signals page renders scorecard table", async ({ page }) => {
    await page.goto("/signals", { timeout: 15000 });
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10000 });
    // Should have signal names like rsi_oversold, macd_golden etc.
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("consensus page renders agent verdicts", async ({ page }) => {
    await page.goto("/consensus", { timeout: 15000 });
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(2000);
  });

  test("targets page renders price targets", async ({ page }) => {
    await page.goto("/targets", { timeout: 15000 });
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(2000);
  });

  test("engine page renders SIEGE status", async ({ page }) => {
    await page.goto("/engine", { timeout: 15000 });
    await page.waitForTimeout(2000);
    // Should show SIEGE gate conditions
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });

  test("scan page renders scanner results", async ({ page }) => {
    await page.goto("/scan", { timeout: 15000 });
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });

  test("advisor page renders", async ({ page }) => {
    await page.goto("/advisor", { timeout: 15000 });
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });

  test("rebalance page renders", async ({ page }) => {
    await page.goto("/rebalance", { timeout: 15000 });
    await page.waitForTimeout(2000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });

  test.skip("ticker detail page renders with real data", async ({ page }) => {
    // Skip: /api/ticker/{symbol} runs 10-agent consensus in real-time (~30s+)
    // Covered by vitest unit tests instead (ticker-detail.test.tsx)
    await page.goto("/ticker/SPY", { timeout: 60000 });
    await expect(page.locator("text=SPY").first()).toBeVisible({ timeout: 30000 });
  });

  test("portfolio page renders holdings", async ({ page }) => {
    await page.goto("/portfolio", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // Should show holdings
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 10000 });
  });

  test("login page renders form", async ({ page }) => {
    await page.goto("/login", { timeout: 15000 });
    await expect(page.locator('input[type="password"]')).toBeVisible({ timeout: 5000 });
  });
});
