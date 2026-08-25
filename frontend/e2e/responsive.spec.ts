/**
 * 반응형 게이트 (#1202 U1c, docs/UX_REDESIGN_PLAN.md §2.3).
 *
 * 4-뷰포트 매트릭스 × 주요 route 에서 두 가지를 기계 검증한다:
 *  1. 가로 스크롤 금지 — 페이지 body 는 어떤 뷰포트에서도 옆으로 새지 않는다
 *     (테이블은 자체 overflow-x 컨테이너 안에서만 스크롤).
 *  2. 컨테이너 캡 — 본문 콘텐츠 폭은 1600px 을 넘지 않는다 (울트라와이드에서
 *     카드가 ~700px 로 늘어나던 2026-08-25 실측 결함의 재발 방지).
 *
 * CI 게이트에 배선돼 있지 않으므로(#1118) UI PR 마다 수동 실행이 의무다 — PLAN §2.3.
 */
import { test, expect } from "@playwright/test";

const VIEWPORT_MATRIX = [
  { name: "v2-laptop", width: 1280, height: 800 },
  { name: "v2-mbp", width: 1440, height: 900 },
  { name: "v4-fhd", width: 1920, height: 1080 },
  { name: "v4-qhd", width: 2560, height: 1440 },
] as const;

const ROUTES = ["/", "/decisions", "/scan", "/portfolio", "/engine"] as const;

const CONTENT_CAP_PX = 1600;

for (const vp of VIEWPORT_MATRIX) {
  test.describe(`viewport ${vp.name} (${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    for (const route of ROUTES) {
      test(`${route} — no horizontal scroll, content capped`, async ({ page }) => {
        await page.goto(route, { timeout: 30000, waitUntil: "networkidle" });

        // 1. 가로 스크롤 금지
        const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
        const clientW = await page.evaluate(() => document.documentElement.clientWidth);
        expect(scrollW, `${route} @ ${vp.name}: 가로 스크롤 발생 (${scrollW} > ${clientW})`).toBeLessThanOrEqual(clientW);

        // 2. 컨테이너 캡 — layout.tsx 의 main 내부 래퍼 실측 폭
        const contentW = await page
          .locator("main > div")
          .first()
          .evaluate((el) => el.getBoundingClientRect().width);
        expect(contentW, `${route} @ ${vp.name}: 콘텐츠 폭 ${contentW}px > 캡 ${CONTENT_CAP_PX}px`).toBeLessThanOrEqual(CONTENT_CAP_PX);

        // 3. 스크린샷 아카이브 (수동 검토물 — assert 아님)
        await page.screenshot({
          path: `test-results/responsive/${vp.name}${route === "/" ? "/home" : route}.png`,
          fullPage: false,
        });
      });
    }
  });
}
