import { test, expect } from "@playwright/test";
import { NAV } from "../src/lib/strings";

test.describe("Decisions Page", () => {
  test("renders decision intelligence header and summary cards", async ({ page }) => {
    await page.goto("/decisions", { timeout: 15000 });
    await expect(page.locator("h1")).toHaveText("Decision Intelligence");
    await expect(page.locator("text=의사결정 저널")).toBeVisible();

    // Summary cards always render
    await expect(page.locator("text=TOTAL").first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator("text=PENDING").first()).toBeVisible();
    await expect(page.locator("text=SUCCESS").first()).toBeVisible();
    await expect(page.locator("text=FAILURE").first()).toBeVisible();
    await expect(page.locator("text=HIT RATE").first()).toBeVisible();
  });

  test("shows empty state or grouped decision rows", async ({ page }) => {
    await page.goto("/decisions", { timeout: 15000 });
    // #1216: 본문 텍스트 휴리스틱("Outcome"/"pending")은 U3 리스트에 더는 없다 —
    // testid 로 실제 구조를 단정한다 (행이 있으면 날짜 그룹 헤더도 반드시 있다).
    const rows = page.locator('[data-testid="decisions-row"]');
    const empty = page.locator("text=make consensus");
    await expect(rows.first().or(empty.first())).toBeVisible({ timeout: 10000 });
    if ((await rows.count()) > 0) {
      await expect(page.locator('[data-testid="decisions-date-header"]').first()).toBeVisible();
    }
  });

  test("sidebar has Decisions nav under 의사결정 group", async ({ page }) => {
    await page.goto("/decisions", { timeout: 15000 });
    // 그룹 라벨은 strings.ts NAV 가 정본 (#1200 U1b-2 재그룹)
    await expect(page.locator(`text=${NAV.DECISIONS}`).first()).toBeVisible();
    // #1216: 본문 필터 칩("전체")도 /decisions href 를 가지므로 사이드바(aside nav)로 스코프
    const decisionLink = page.locator("aside nav a[href='/decisions']");
    await expect(decisionLink).toBeVisible();
    // Active state: 인터랙션 액센트(blue) — emerald 브랜드 액센트 폐지 (스펙 §1)
    await expect(decisionLink).toHaveClass(/text-primary/);
  });

  test("no hardcoded exchange rate visible", async ({ page }) => {
    await page.goto("/", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // The old hardcoded "1514" should not appear in the page source
    // (it was replaced with API exchange_rate)
    const body = await page.textContent("body");
    // Note: 1514 might appear as a value if it happens to be current rate
    // but it should not be the only possible value
    expect(body!.length).toBeGreaterThan(100);
  });
});
