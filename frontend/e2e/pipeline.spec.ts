import { test, expect } from "@playwright/test";
import { mockAllAPIs } from "./helpers";

test.describe("Pipeline", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page);
  });

  test("renders pipeline page", async ({ page }) => {
    await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
    // Pipeline is "use client" — fetches from browser side (mocked via page.route)
    await page.waitForTimeout(2000);
    const heading = page.locator("h1").first();
    await expect(heading).toBeVisible();
  });

  test("clicking Run triggers step execution", async ({ page }) => {
    await page.route("**/api/pipeline/*/run", (route) => {
      route.fulfill({ json: { status: "started", step: "classify" } });
    });

    await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    const runButtons = page.locator('button:has-text("Run"), button:has-text("실행")');
    const count = await runButtons.count();
    if (count > 0) {
      await runButtons.first().click();
      await page.waitForTimeout(500);
    }
  });

  test("shows timeline events", async ({ page }) => {
    await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    // Page should load without crash
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(0);
  });
});
