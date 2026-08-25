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

const CARDS = [
  { id: "regime", title: EVIDENCE.TITLE_REGIME, chartTestId: "regime-chart" },
  { id: "portfolio_heatmap", title: EVIDENCE.TITLE_HEATMAP, chartTestId: "portfolio-treemap" },
  { id: "signal_performance", title: EVIDENCE.TITLE_SIGNALS, chartTestId: "signal-performance-chart" },
  { id: "fear_greed", title: EVIDENCE.TITLE_FEAR_GREED, chartTestId: "fear-greed-chart" },
  { id: "sell_evidence", title: EVIDENCE.TITLE_SELL, chartTestId: "sell-evidence-chart" },
] as const;

test("evidence page renders native chart cards with zero iframes", async ({ page, request }) => {
  const resp = await page.goto("/evidence", { waitUntil: "domcontentloaded", timeout: 20000 });
  expect(resp?.status()).toBe(200);

  const main = page.locator("main");
  for (const card of CARDS) {
    // 카드 자체(제목+본문)는 데이터와 무관하게 항상 존재해야 한다
    const cardEl = main.getByTestId(`card-${card.id}`);
    await expect(cardEl).toBeVisible({ timeout: 15000 });
    await expect(cardEl.getByText(card.title)).toBeVisible();

    // 차트 마운트 여부는 API 가 실제로 준 것과 일치해야 한다 (라이브 값 하드코딩 금지)
    const api = await request.get(`/api/evidence/data/${card.id}`);
    expect(api.ok()).toBe(true);
    const body = (await api.json()) as { count: number };
    if (body.count > 0) {
      await expect(cardEl.getByTestId(card.chartTestId)).toBeVisible({ timeout: 15000 });
    } else {
      const emptyText = card.id === "sell_evidence" ? EVIDENCE.NO_VIOLATIONS : EVIDENCE.NO_DATA;
      await expect(cardEl.getByText(emptyText)).toBeVisible();
    }
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
