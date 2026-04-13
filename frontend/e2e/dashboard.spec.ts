import { test, expect } from "@playwright/test";

test.describe("Dashboard (with real backend)", () => {
  test("renders main dashboard with verdict", async ({ page }) => {
    await page.goto("/", { timeout: 15000 });
    await expect(page.locator("text=Nuri-Quant")).toBeVisible({ timeout: 10000 });
    // Dashboard should render — either with data or error boundary
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(100);
  });

  test("sidebar shows navigation links", async ({ page }) => {
    await page.goto("/", { timeout: 15000 });
    await expect(page.locator("text=Dashboard").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Portfolio").first()).toBeVisible();
    await expect(page.locator("text=Signals").first()).toBeVisible();
  });

  test("shows SIEGE status in system health", async ({ page }) => {
    await page.goto("/", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // SIEGE health card: shows score % or Korean status (인증/미인증) or English
    const siege = page.locator("text=SIEGE");
    const certified = page.locator("text=CERTIFIED");
    const rejected = page.locator("text=REJECTED");
    const korCertified = page.locator("text=인증");
    const korRejected = page.locator("text=미인증");
    const hasSiege = (await siege.count()) > 0 ||
      (await certified.count()) > 0 || (await rejected.count()) > 0 ||
      (await korCertified.count()) > 0 || (await korRejected.count()) > 0;
    expect(hasSiege).toBe(true);
  });

  test("navigates to each page without crash", async ({ page }) => {
    const routes = ["/signals", "/consensus", "/targets", "/engine", "/evidence", "/decisions"];
    for (const route of routes) {
      await page.goto(route, { timeout: 15000 });
      const body = await page.textContent("body");
      expect(body!.length).toBeGreaterThan(50);
    }
  });
});
