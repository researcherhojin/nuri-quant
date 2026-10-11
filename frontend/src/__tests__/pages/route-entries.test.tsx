/**
 * 라우트 진입점(`page.tsx`) 계약 — #1731 이 아홉 라우트의 본문을 `page-view.tsx` 로 옮기고
 * `page.tsx` 를 얇은 진입점으로 남겼다.
 *
 * 다른 테스트는 전부 `page-view` 를 직접 import 하므로, 진입점이 깨져도 그쪽은 초록이다. 진입점이
 * 지키는 것은 두 가지뿐이라 그 둘을 잠근다:
 *   - route segment config `dynamic = "force-dynamic"` — Next 가 읽는 값이다. 빠지면 빌드 시점에
 *     프리렌더돼 그때의 API 응답이 페이지에 굳는다 (`node_modules/next/dist/docs` 의 segment config).
 *   - 본문을 그대로 default 로 노출 — 재내보내기가 빠지면 라우트가 빈 모듈이 된다.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchAPI: vi.fn(), API_BASE: "http://localhost:8001" }));

vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect: vi.fn(), usePathname: vi.fn(), useRouter: vi.fn(), useSearchParams: vi.fn() }));

const SERVER_ROUTES = [
  ["/consensus", () => import("@/app/consensus/page"), () => import("@/app/consensus/page-view")],
  ["/engine", () => import("@/app/engine/page"), () => import("@/app/engine/page-view")],
  ["/explore", () => import("@/app/explore/page"), () => import("@/app/explore/page-view")],
  ["/rebalance", () => import("@/app/rebalance/page"), () => import("@/app/rebalance/page-view")],
  ["/strategy", () => import("@/app/strategy/page"), () => import("@/app/strategy/page-view")],
  ["/decisions/[id]", () => import("@/app/decisions/[id]/page"), () => import("@/app/decisions/[id]/page-view")],
  ["/ticker/[symbol]", () => import("@/app/ticker/[symbol]/page"), () => import("@/app/ticker/[symbol]/page-view")],
] as const;

describe("route entry points", () => {
  it.each(SERVER_ROUTES)("%s renders at request time and serves its page view", async (_, entry, view) => {
    const [route, body] = await Promise.all([entry(), view()]);

    expect(route.dynamic).toBe("force-dynamic");
    expect(route.default).toBe(body.default);
  });

  it("/decisions renders at request time and forwards its search params to the async page view", async () => {
    const [route, body] = await Promise.all([import("@/app/decisions/page"), import("@/app/decisions/page-view")]);
    const searchParams = Promise.resolve({ outcome: "pending", action: "BUY" });
    const element = route.default({ searchParams });

    expect(route.dynamic).toBe("force-dynamic");
    expect(element.type).toBe(body.default);
    expect(element.props).toEqual({ searchParams });
  });

  it("/pipeline serves its client page view", async () => {
    const [route, body] = await Promise.all([import("@/app/pipeline/page"), import("@/app/pipeline/page-view")]);

    expect(route.default).toBe(body.default);
  });
});
