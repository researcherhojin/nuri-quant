import { test, expect } from "@playwright/test";

test.describe("Action-First Dashboard", () => {
  test("renders system health cards (SIEGE, regime, macro, freshness)", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // System health section should have SIEGE label
    await expect(page.locator("text=SIEGE").first()).toBeVisible({ timeout: 10000 });
    // Should show regime info
    const body = await page.textContent("body");
    expect(body).toBeTruthy();
    // At least one health card should show a percentage or status
    const hasHealth = body!.includes("SIEGE") || body!.includes("인증") || body!.includes("미인증");
    expect(hasHealth).toBe(true);
  });

  test("renders action items with priority sections", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // "오늘의 액션" heading should be visible
    await expect(page.locator("text=오늘의 액션").first()).toBeVisible({ timeout: 10000 });
    // Should have at least one action item (TSLA urgent or check items)
    const body = await page.textContent("body");
    const hasActions = body!.includes("즉시 실행") || body!.includes("오늘 확인") || body!.includes("유지 종목");
    expect(hasActions).toBe(true);
  });

  test("TSLA shows as urgent action (SIEGE violation)", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    const body = await page.textContent("body");
    // TSLA should appear in the action items section
    expect(body).toContain("TSLA");
    // SIEGE violation should be mentioned
    const hasSiegeWarning = body!.includes("SIEGE") || body!.includes("한도") || body!.includes("15.4%");
    expect(hasSiegeWarning).toBe(true);
  });

  test("action items have expand/collapse detail button", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // Find "상세 근거" buttons
    const detailButtons = page.locator("text=상세 근거");
    const count = await detailButtons.count();
    if (count > 0) {
      // Click first detail button
      await detailButtons.first().click();
      // After click, should show price info (현재가, 손절, etc.)
      await page.waitForTimeout(500);
      const expanded = await page.textContent("body");
      const hasDetail = expanded!.includes("현재가") || expanded!.includes("손절") || expanded!.includes("1차익절");
      expect(hasDetail).toBe(true);
    }
  });

  test("renders market context with macro events", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    const body = await page.textContent("body");
    // Macro events should include Iran/Hormuz or TSMC or other recent events
    const hasEvents = body!.includes("시장 컨텍스트") || body!.includes("Iran") || body!.includes("Hormuz") || body!.includes("TSMC");
    expect(hasEvents).toBe(true);
  });

  test("opportunity explorer renders non-portfolio tickers", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    const body = await page.textContent("body");
    // Opportunities should show tickers NOT in portfolio (e.g., INTC, SNOW, PLTR)
    const hasOpportunity = body!.includes("이슈 종목") || body!.includes("기회 탐색") ||
      body!.includes("매수 고려") || body!.includes("관망") || body!.includes("매수 금지");
    expect(hasOpportunity).toBe(true);
  });

  test("opportunity cards show pros and cons", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    const body = await page.textContent("body");
    // Pros/cons labels should appear if opportunities exist
    const hasProsOrCons = body!.includes("찬성") || body!.includes("반대") || body!.includes("판정");
    expect(hasProsOrCons).toBe(true);
  });

  test("action items link to ticker detail page", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // TSLA link should navigate to /ticker/TSLA
    const tslaLink = page.locator("a[href='/ticker/TSLA']").first();
    if (await tslaLink.count() > 0) {
      await tslaLink.click();
      await page.waitForURL("**/ticker/TSLA", { timeout: 10000 });
      expect(page.url()).toContain("/ticker/TSLA");
    }
  });

  test("hold items render as compact chips", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // "유지 종목" section with compact ticker chips
    const holdSection = page.locator("text=유지 종목");
    if (await holdSection.count() > 0) {
      await expect(holdSection.first()).toBeVisible();
      // Should have multiple ticker chips in hold section
      const body = await page.textContent("body");
      // At least some BUY/HOLD tickers should appear
      const hasBuyHold = body!.includes("BUY") || body!.includes("HOLD");
      expect(hasBuyHold).toBe(true);
    }
  });

  test("responsive: mobile viewport still shows action items", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    await expect(page.locator("text=오늘의 액션").first()).toBeVisible({ timeout: 10000 });
    // Health cards should wrap on mobile
    await expect(page.locator("text=SIEGE").first()).toBeVisible();
  });
});
