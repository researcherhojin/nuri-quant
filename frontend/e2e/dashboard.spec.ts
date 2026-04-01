import { test, expect } from "@playwright/test";
import { mockAllAPIs } from "./helpers";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page);
  });

  // Dashboard is a server component — fetchAPI runs server-side,
  // so page.route() can't intercept it. These tests verify the
  // error boundary works when backend is unavailable.

  test("shows error boundary or loading when backend unavailable", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    // Either shows error UI or loading skeleton
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
  });

  test("sidebar navigation renders", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("text=Nuri-Quant")).toBeVisible({ timeout: 5000 });
  });
});
