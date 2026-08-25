/**
 * /evidence — 네이티브 recharts 전환 잠금 (#1225 U5a-2).
 *
 * 이전(evidence-iframe.spec.ts)은 Plotly iframe 로드를 잠갔다. 전환 후의
 * 잠금은 반대다: iframe 0개 + 카드 5종 렌더. 차트 svg 자체는 로컬 DB
 * 데이터에 의존하므로 단언하지 않는다 (빈 상태 1줄 룰이 정상 경로).
 *
 * X-Frame-Options SAMEORIGIN 정책 테스트는 유지 — /evidence iframe 은 사라졌지만
 * 정책 변경(→DENY)은 별도 결정이다 (nuri/api/CLAUDE.md 참조).
 */
import { test, expect } from "@playwright/test";

import { EVIDENCE } from "../src/lib/strings";

test("evidence page renders native chart cards with zero iframes", async ({ page }) => {
  const resp = await page.goto("/evidence", { waitUntil: "domcontentloaded", timeout: 20000 });
  expect(resp?.status()).toBe(200);

  const main = page.locator("main");
  for (const title of [
    EVIDENCE.TITLE_REGIME,
    EVIDENCE.TITLE_HEATMAP,
    EVIDENCE.TITLE_SIGNALS,
    EVIDENCE.TITLE_FEAR_GREED,
    EVIDENCE.TITLE_SELL,
  ]) {
    await expect(main.getByText(title)).toBeVisible({ timeout: 15000 });
  }

  // #1225 핵심: Plotly iframe 완전 제거
  expect(await page.locator("iframe").count()).toBe(0);
});

test("X-Frame-Options header is SAMEORIGIN on both page and api routes", async ({ request }) => {
  // Page
  const pageResp = await request.get("/login");
  expect(pageResp.headers()["x-frame-options"]).toBe("SAMEORIGIN");

  // API via Next.js proxy (same origin to browser)
  const apiResp = await request.get("/api/health");
  expect(apiResp.headers()["x-frame-options"]).toBe("SAMEORIGIN");
});

test("CSP frame-ancestors is 'self' (not 'none')", async ({ request }) => {
  const resp = await request.get("/login");
  const csp = resp.headers()["content-security-policy"] || "";
  expect(csp).toMatch(/frame-ancestors\s+'self'/);
  expect(csp).not.toMatch(/frame-ancestors\s+'none'/);
});
