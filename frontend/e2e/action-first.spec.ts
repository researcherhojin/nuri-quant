import { test, expect } from "@playwright/test";
import { ACTION, CONTEXT, OPPORTUNITY } from "../src/lib/strings";

// 라벨 리터럴을 여기 박지 않는다 — strings.ts 가 단일 출처다. 410d385 가
// CONTEXT.SIEGE 값을 "SIEGE" → "Certification" 으로 바꿨을 때 vitest 는 같이
// 갱신됐지만 이 파일은 안 됐고, playwright 가 어떤 게이트에도 없어서 3.5개월간
// 아무도 몰랐다. import 로 묶어두면 다음 rename 은 단언이 따라온다.
//
// 시스템 건강 4-card 중 Certification 카드는 main 안의 /engine 링크다.
// 사이드바에도 /engine 링크("Certification Engine")가 있어 main 스코프가 필요하다 —
// body 전체를 훑으면 카드가 사라져도 사이드바 때문에 초록으로 통과한다.
const healthCard = (page: import("@playwright/test").Page) =>
  page.locator('main a[href="/engine"]');

test.describe("Action-First Dashboard", () => {
  test("renders system health cards (certification, regime, macro, freshness)", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await expect(healthCard(page)).toContainText(CONTEXT.SIEGE, { timeout: 15000 });
    // 카드 본문은 인증/미인증 상태를 함께 낸다
    await expect(healthCard(page)).toContainText(
      new RegExp(`${CONTEXT.CERTIFIED}|${CONTEXT.REJECTED}`),
    );
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

  // 이 테스트는 원래 "TSLA 가 15.4% 비중으로 urgent 에 뜬다" 를 박아뒀다. 셋 다
  // 2026-04-13 당시의 라이브 포트폴리오 값이라 매일 드리프트한다(오늘 TSLA 는
  // 14.3% · check 버킷 · Certification 위반 없음). 티커도 수치도 API 가 실제로
  // 낸 것에서 가져온다.
  test("action items surface the API's urgent/check tickers with their reasons", async ({
    page,
    request,
  }) => {
    test.setTimeout(90_000);

    // 페이지를 **먼저** 연다. `/api/actions` 는 콜드 실측 3.8초인데, 이 fixture 의
    // 요청은 Next rewrite 프록시를 타고 그 프록시는 30초에 소켓을 끊는다
    // (`proxyTimeout || 30000`). 콜드 스위트에서 API 를 먼저 부르면 스위트가
    // 동시에 깨우는 무거운 엔드포인트들 뒤에 줄을 서다 프록시 타임아웃에 걸린다
    // — API 로그는 전부 200 인데 fixture 만 not-ok 를 받는다 (#1119).
    // 대시보드 렌더가 서버사이드에서 같은 엔드포인트를 깨우므로, 그 다음 호출은
    // 5분 TTL 캐시에 맞는다.
    await page.goto("/", { timeout: 30000 });
    const main = page.locator("main");
    await expect(main).toContainText(ACTION.TITLE, { timeout: 15000 });

    const res = await request.get("/api/actions");
    expect(res.ok()).toBe(true);
    const data = await res.json();
    const items: { ticker: string; reasons?: string[] }[] = [
      ...(data.urgent ?? []),
      ...(data.check ?? []),
    ];
    test.skip(items.length === 0, "urgent/check 액션 0건 — 검증 대상 없음");

    for (const item of items) {
      await expect(main.locator(`a[href="/ticker/${item.ticker}"]`).first()).toBeVisible();
    }

    // reason 문자열은 액션 카드에서만 렌더된다(action-items.tsx:69) — 보유
    // 테이블이 대신 통과시켜주지 않는 유일한 스코프다.
    const reason = items.flatMap((i) => i.reasons ?? [])[0];
    expect(reason, "액션 아이템에 reason 이 하나도 없다").toBeTruthy();
    await expect(main).toContainText(reason);
  });

  test("action rows expand quick-peek on click (#1208)", async ({ page }) => {
    await page.goto("/", { timeout: 20000 });
    await page.waitForTimeout(5000);
    // U2b-2: 카드의 "상세 근거" 버튼 → 행 클릭 quick-peek. 이전 스펙은 if(count>0)
    // 가드라 버튼이 사라져도 침묵 통과했다 — 행 존재를 하드 assert 한다.
    const rows = page.getByTestId("action-row");
    expect(await rows.count(), "액션 행이 없다").toBeGreaterThan(0);
    await rows.first().click();
    await expect(page.getByTestId("action-row-peek").first()).toBeVisible();
    const expanded = await page.textContent("body");
    const hasDetail = expanded!.includes("현재가") || expanded!.includes("손절") || expanded!.includes("1차익절");
    expect(hasDetail).toBe(true);
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
    const hasOpportunity = body!.includes(OPPORTUNITY.SUBTITLE) || body!.includes(OPPORTUNITY.TITLE) ||
      body!.includes(OPPORTUNITY.POSITIVE) || body!.includes(OPPORTUNITY.NEUTRAL) ||
      body!.includes(OPPORTUNITY.DANGER);
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
    await expect(healthCard(page)).toContainText(CONTEXT.SIEGE, { timeout: 15000 });
  });
});
