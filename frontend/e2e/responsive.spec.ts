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

// /pipeline 포함 — ReactFlow 캔버스가 전역 캡의 최대 리스크 페이지 (codex P2).
// 상세 라우트는 데이터 의존이라 첫 decision id 를 API 에서 조회해 동적 추가 (#1216, PLAN §2.3).
const ROUTES = ["/", "/decisions", "/scan", "/portfolio", "/engine", "/pipeline", "decision-detail"] as const;

const CONTENT_CAP_PX = 1600;

// decision-detail 플레이스홀더 → 실제 /decisions/{id}. 데이터가 없으면 해당 케이스 skip
// (assert 약화가 아니라 라우트 자체가 존재하지 않는 경우다).
async function resolveRoute(
  route: (typeof ROUTES)[number],
  request: { get: (url: string) => Promise<{ ok: () => boolean; json: () => Promise<unknown> }> },
): Promise<string | null> {
  if (route !== "decision-detail") return route;
  const res = await request.get("/api/decisions?limit=1");
  if (!res.ok()) return null;
  const body = (await res.json()) as { decisions?: Array<{ id: number }> };
  const id = body.decisions?.[0]?.id;
  return id != null ? `/decisions/${id}` : null;
}

for (const vp of VIEWPORT_MATRIX) {
  test.describe(`viewport ${vp.name} (${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    for (const routeSpec of ROUTES) {
      test(`${routeSpec} — no horizontal scroll, content capped`, async ({ page, request }) => {
        const route = await resolveRoute(routeSpec, request);
        test.skip(route === null, "decision 데이터 없음 — 상세 라우트 생략");
        if (route === null) return;
        await page.goto(route, { timeout: 30000, waitUntil: "networkidle" });

        // 1. 가로 스크롤 금지 — 실제 스크롤 컨테이너는 root 가 아니라 main (overflow-auto,
        // codex P1: root 만 재면 main 내부 오버플로가 false-pass 된다). 둘 다 잰다.
        const widths = await page.evaluate(() => {
          const root = document.documentElement;
          const main = document.querySelector("main");
          return {
            rootScroll: root.scrollWidth, rootClient: root.clientWidth,
            mainScroll: main?.scrollWidth ?? 0, mainClient: main?.clientWidth ?? 0,
          };
        });
        expect(widths.rootScroll, `${route} @ ${vp.name}: root 가로 스크롤`).toBeLessThanOrEqual(widths.rootClient);
        expect(widths.mainScroll, `${route} @ ${vp.name}: main 가로 스크롤 (${widths.mainScroll} > ${widths.mainClient})`).toBeLessThanOrEqual(widths.mainClient);

        // 2. 컨테이너 캡 — 래퍼 폭 + 패널 스팟 체크 (codex P2: 래퍼만 재면 자식 오버플로를
        // 못 본다). 래퍼 내부의 카드/섹션이 래퍼 경계를 1px 초과해 벗어나면 FAIL.
        const cap = await page.evaluate(() => {
          const wrapper = document.querySelector("main > div");
          if (!wrapper) return null;
          const wb = wrapper.getBoundingClientRect();
          let worst = 0;
          for (const el of wrapper.querySelectorAll("section, [data-slot=card], table")) {
            const r = el.getBoundingClientRect();
            if (r.width === 0) continue; // hidden
            worst = Math.max(worst, r.right - wb.right, wb.left - r.left);
          }
          return { wrapperW: wb.width, worstOverhang: worst };
        });
        expect(cap, `${route} @ ${vp.name}: main > div 래퍼 없음`).not.toBeNull();
        expect(cap!.wrapperW, `${route} @ ${vp.name}: 래퍼 폭 ${cap!.wrapperW}px > 캡 ${CONTENT_CAP_PX}px`).toBeLessThanOrEqual(CONTENT_CAP_PX);
        expect(cap!.worstOverhang, `${route} @ ${vp.name}: 패널이 래퍼 경계를 ${cap!.worstOverhang}px 이탈`).toBeLessThanOrEqual(1);

        // 3. 스크린샷 아카이브 (수동 검토물 — assert 아님)
        await page.screenshot({
          path: `test-results/responsive/${vp.name}${routeSpec === "/" ? "/home" : `/${routeSpec.replace(/^\//, "")}`}.png`,
          fullPage: false,
        });
      });
    }
  });
}
