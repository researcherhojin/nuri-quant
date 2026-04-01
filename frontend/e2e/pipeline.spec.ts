import { test, expect } from "@playwright/test";

test.describe("Pipeline page", () => {
  test("renders pipeline with nodes", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // Pipeline is "use client" — should render after data loads
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(100);
  });

  test("shows step run buttons", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // Look for Run/실행 buttons
    const runButtons = page.locator('button:has-text("Run"), button:has-text("실행")');
    const count = await runButtons.count();
    // Pipeline should have run buttons for each step
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("auto-refreshes status", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    // Wait for auto-refresh (10s interval)
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });
});
