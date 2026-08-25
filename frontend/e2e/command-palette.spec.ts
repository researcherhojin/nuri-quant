/**
 * Cmd-K 커맨드 팔레트 (#1226 U5b) — 단축키 오픈 + 라우트 점프 잠금.
 *
 * 라우트 목록은 정적(NAV_GROUPS)이라 데이터 의존 없음. 티커 검색 경로는
 * DB 의존이라 여기서 단언하지 않는다 (vitest 가 mock 으로 잠근다).
 */
import { test, expect, type Page } from "@playwright/test";

import { PALETTE } from "../src/lib/strings";

// 트리거 버튼은 SSR 마크업이라 하이드레이션 전에도 보인다 — 단축키 리스너가
// 붙을 때까지 press 를 재시도해야 결정론적이다 (visible ≠ hydrated).
async function openPalette(page: Page) {
  await expect(page.getByTestId("palette-trigger")).toBeVisible({ timeout: 15000 });
  await expect(async () => {
    // 이미 열려 있으면 다시 누르지 않는다 — 단축키는 토글이라 재press 가 닫아버린다
    if (!(await page.getByTestId("command-palette").isVisible())) {
      await page.keyboard.press("ControlOrMeta+k");
    }
    await expect(page.getByTestId("command-palette")).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 15000 });
}

test("Cmd-K opens the palette and Escape closes it", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 20000 });
  await openPalette(page);
  const dialog = page.getByTestId("command-palette");
  await expect(dialog.getByText(PALETTE.SECTION_ROUTES)).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

test("filtering and Enter jumps to the route", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 20000 });
  await openPalette(page);
  await page.getByTestId("command-palette-input").fill("deci");
  await expect(page.getByTestId("palette-route-/decisions")).toBeVisible();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/decisions/, { timeout: 15000 });
  await expect(page.getByTestId("command-palette")).not.toBeVisible();
});
