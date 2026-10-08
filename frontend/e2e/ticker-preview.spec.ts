// cspell:words MUTUALFUND
import { test, expect } from "@playwright/test";
import { OVERVIEW, TICKER_PREVIEW as T } from "../src/lib/strings";

test("ticker tab URL survives reload and restores the previous tab with browser Back", async ({ page }) => {
  // CI seed 와 universe.yaml 에 있는 종목만 쓴다 — 로컬 보유 종목은 CI 에 없다
  await page.goto("/ticker-next/AAPL?bucket=portfolio&tab=history");
  const main = page.getByRole("main");

  await expect(main.getByRole("tab", { name: T.HISTORY })).toHaveAttribute("aria-selected", "true");
  await main.getByRole("tab", { name: T.RESEARCH }).click();
  await expect(page).toHaveURL(/bucket=portfolio&tab=research/);
  await page.reload();
  await expect(main.getByRole("tab", { name: T.RESEARCH })).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  // URL 먼저 — 실패하면 "뒤로가 안 됐다" 와 "URL 은 바뀌었는데 탭이 안 따라왔다" 를 구분한다 (#1750)
  await expect(page).toHaveURL(/tab=history/);
  await expect(main.getByRole("tab", { name: T.HISTORY })).toHaveAttribute("aria-selected", "true");
  await expect(main.getByRole("link", { name: T.BACK })).toHaveAttribute("href", "/?bucket=portfolio&ticker=AAPL");
});

for (const width of [390, 1440]) {
  test(`ticker landing searches and opens the briefing at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/ticker-next");
    const main = page.getByRole("main");

    await expect(main.getByRole("heading", { level: 1 })).toHaveText(T.LANDING_TITLE);
    const input = main.getByRole("textbox", { name: T.SEARCH_LABEL });

    await input.fill("AAPL");
    await expect(main.locator("ul").getByRole("link", { name: /AAPL/ }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("ticker-landing.png"), fullPage: true });
    await input.press("Enter");
    await expect(page).toHaveURL(/\/ticker-next\/AAPL$/);
    await expect(main.getByTestId("ticker-preview")).toBeVisible();
  });
}

test("Overview selects a ticker, opens its preview and restores the selection on return", async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 760 });
  await page.goto("/");
  const response = await request.get("/api/actions");

  expect(response.ok()).toBe(true);
  const actions = await response.json();
  const bucket = (["urgent", "check", "portfolio", "hold"] as const).find(key => actions[key].length > 0);

  expect(bucket).toBeDefined();

  if (!bucket) return;
  const item = actions[bucket].at(-1);
  const main = page.getByRole("main");

  await main.getByRole("group", { name: OVERVIEW.INBOX_PANEL.FILTER_ARIA }).getByRole("button", { name: new RegExp(OVERVIEW.INBOX_PANEL.BUCKETS[bucket]) }).click();
  const queue = main.getByRole("group", { name: OVERVIEW.INBOX_PANEL.QUEUE_ARIA(OVERVIEW.INBOX_PANEL.BUCKETS[bucket]) });

  await expect(queue.getByText(T.SELECT, { exact: true })).toBeVisible();
  await queue.getByRole("button").last().click();
  await expect(queue.getByRole("button").last()).toHaveAttribute("aria-pressed", "true");
  const evidence = main.getByRole("article", { name: OVERVIEW.INBOX_PANEL.EVIDENCE_ARIA });

  await expect(evidence.getByRole("heading")).toHaveText(item.name || item.ticker);
  const link = evidence.getByRole("link", { name: T.BRIEF });

  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", `/ticker-next/${encodeURIComponent(item.ticker)}?bucket=${bucket}`);
  await page.screenshot({ path: testInfo.outputPath("overview-entry.png"), fullPage: true });
  await link.click();
  await expect(main.getByTestId("ticker-preview")).toBeVisible();
  const detailResearch = await (await request.get(`/api/ticker/${encodeURIComponent(item.ticker)}/research`)).json();

  await expect(main.getByRole("heading", { level: 1 })).toHaveText(detailResearch.dossier?.profile.display_name || detailResearch.dossier?.profile.name || item.name || item.ticker);
  await main.getByRole("link", { name: T.BACK }).click();
  await expect(main.getByTestId("overview-dashboard")).toBeVisible();
  await expect(main.getByRole("article", { name: OVERVIEW.INBOX_PANEL.EVIDENCE_ARIA }).getByRole("heading")).toHaveText(item.name || item.ticker);
});

for (const [width, height] of [[390, 844], [1280, 800], [1920, 1080]]) {
  test(`ticker preview reads live data and keeps tabs reachable at ${width}x${height}`, async ({ page, request }, testInfo) => {
    // 개인 보유값을 기대값에 고정하지 않고 실행 환경의 보유 종목을 고른다.
    const portfolioResponse = await request.get("/api/portfolio");
    expect(portfolioResponse.ok()).toBe(true);
    const portfolio = await portfolioResponse.json();
    const symbol: string = portfolio.holdings?.[0]?.ticker ?? "AAA";

    await page.setViewportSize({ width, height });
    await page.goto(`/ticker-next/${encodeURIComponent(symbol)}?bucket=portfolio`);
    const main = page.getByRole("main");
    const preview = main.getByTestId("ticker-preview");

    await expect(preview).toBeVisible();
    await expect(main.getByRole("link", { name: T.ORIGINAL })).toHaveAttribute("href", `/ticker/${encodeURIComponent(symbol)}`);
    const response = await request.get(`/api/ticker/${encodeURIComponent(symbol)}?stored_only=true`);
    expect(response.ok()).toBe(true);
    const ticker = await response.json();

    const research = await (await request.get(`/api/ticker/${encodeURIComponent(symbol)}/research`)).json();

    await expect(main.getByRole("heading", { level: 1 })).toHaveText(research.dossier?.profile.display_name || research.dossier?.profile.name || ticker.name || ticker.ticker);

    await main.getByRole("tab", { name: T.EVIDENCE }).click();
    await expect(main.getByRole("tabpanel").getByRole("heading", { name: T.DISSENT, exact: true })).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("evidence.png"), fullPage: true });

    if (ticker.consensus?.as_of) await expect(preview).toContainText(ticker.consensus.as_of);
    await main.getByRole("tab", { name: T.RESEARCH }).click();
    await expect(main.getByRole("tabpanel")).toContainText(T.PRICE_HISTORY);
    const prices = await request.get(`/api/ticker/${encodeURIComponent(symbol)}/prices?days=365`);
    expect(prices.ok()).toBe(true);

    if ((await prices.json()).prices.length) await expect(main.locator(".recharts-surface").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("research.png"), fullPage: true });
    await main.getByRole("tab", { name: T.HISTORY }).click();
    await expect(main.getByRole("tabpanel")).toContainText(T.HISTORY_NOTE);
    const history = await (await request.get(`/api/decisions?ticker=${encodeURIComponent(symbol)}&limit=12`)).json();

    await expect(main.getByRole("tabpanel").getByRole("article")).toHaveCount(history.decisions.length);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("history.png"), fullPage: true });
    await main.getByRole("tab", { name: T.HISTORY }).press("Home");
    await expect(main.getByRole("tab", { name: T.BRIEF })).toBeFocused();

    await expect(main.getByRole("tabpanel").getByRole("heading", { name: T.DOCUMENT_SECTIONS.business, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("preview.png"), fullPage: true });
    await expect(main.getByRole("link", { name: T.BACK })).toHaveAttribute("href", `/?bucket=portfolio&ticker=${encodeURIComponent(symbol)}`);
  });
}

for (const width of [390, 1440]) {
  test(`company briefing matches collected public data at ${width}px`, async ({ page, request }, testInfo) => {
    const response = await request.get("/api/ticker/AAPL/research");
    expect(response.ok()).toBe(true);
    const research = await response.json();
    test.skip(!research.dossier, "Public company research must be collected before this live-data check");
    expect(research.dossier?.profile.symbol).toBe("AAPL");
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/ticker-next/AAPL");
    const panel = page.getByRole("tabpanel");
    await expect(panel).toContainText(research.dossier.profile.name);
    await panel.getByText(T.BUSINESS_ORIGINAL, { exact: true }).click();
    await expect(panel.locator("details").getByText(research.dossier.profile.description, { exact: true })).toBeVisible();
    await panel.getByText(T.BUSINESS_ORIGINAL, { exact: true }).click();
    await expect(panel.getByRole("link", { name: T.SOURCE + " · " + T.YAHOO }).first()).toHaveAttribute("href", "https://finance.yahoo.com/quote/AAPL/profile/");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("company-briefing.png"), fullPage: true });
    await page.getByRole("tab", { name: T.RESEARCH }).click();
    await expect(panel).toContainText(research.dossier.profile.financial_currency);

    for (const income of research.dossier.statements.income) await expect(panel.getByRole("rowheader", { name: income.period })).toBeVisible();

  });
}

for (const width of [390, 1440]) {
  test(`fund briefing explains official fund data and keeps source dates at ${width}px`, async ({ page, request }, testInfo) => {
    const response = await request.get("/api/ticker/NASA/research");
    expect(response.ok()).toBe(true);
    const research = await response.json();
    test.skip(!research.dossier?.fund, "Official fund research must be collected before this live-data check");
    expect(research.collected_today).toBe(true);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/ticker-next/NASA");
    const main = page.getByRole("main");
    const panel = main.getByRole("tabpanel");
    const fund = research.dossier.fund;
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(research.dossier.profile.name);
    await expect(main).toContainText(research.dossier.unavailable?.length ? T.DAILY_PARTIAL : T.DAILY_CURRENT);
    expect(research.dossier.news_check).toBeTruthy();
    await expect(main).toContainText(T.NEWS_CHECKED);

    for (const item of research.dossier.news) {
      expect(item.date >= research.dossier.news_check.window_start).toBe(true);
      expect(item.date <= research.dossier.news_check.window_end).toBe(true);
    }

    await expect(panel).toContainText(fund.strategy_text);
    const font = await panel.locator("p").filter({ hasText: fund.strategy_text }).evaluate(element => parseFloat(getComputedStyle(element).fontSize));
    expect(font).toBe(width < 520 ? 15 : 13);
    const titleFont = await panel.getByRole("heading", { name: T.FUND_INTRO }).evaluate(element => parseFloat(getComputedStyle(element).fontSize));
    expect(titleFont).toBe(14);
    const total = fund.holdings.slice(0, 3).reduce((sum: number, item: { weight_pct: number }) => sum + item.weight_pct, 0);
    await expect(panel.getByText(T.FUND_CONCENTRATION(Math.min(3, fund.holdings.length), total.toFixed(2)), { exact: true })).toBeVisible();
    await panel.getByText(T.JUDGMENT_GUIDE, { exact: true }).click();
    await expect(panel.getByText(T.CONFIDENCE_NOTE, { exact: true })).toBeVisible();
    await panel.getByText(T.JUDGMENT_GUIDE, { exact: true }).click();

    await expect(panel).toContainText(T.FUND_DETAILS_DATE + " · " + fund.details_as_of);
    await expect(panel.getByRole("heading", { name: T.HOLDINGS })).toHaveCount(0);
    await expect(panel.getByRole("heading", { name: T.HOLDING })).toHaveCount(0);
    await expect(panel.getByRole("heading", { name: T.CURRENT_JUDGMENT })).toBeVisible();

    const report = main.getByTestId("ticker-briefing");
    await expect(report).toBeVisible();
    const headings = Object.values(T.DOCUMENT_SECTIONS);
    let previousY = Number.NEGATIVE_INFINITY;

    for (const name of headings) {
      const heading = report.getByRole("heading", { name, exact: true });
      const box = await heading.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThan(previousY);
      previousY = box!.y;
      const border = await heading.locator("xpath=ancestor::section[1]").evaluate(element => getComputedStyle(element).borderTopWidth);
      expect(border).toBe("1px");
    }

    if (width >= 1100) {
      await main.getByRole("navigation", { name: T.DOCUMENT_INDEX }).getByRole("link", { name: new RegExp(T.DOCUMENT_SECTIONS.outlook) }).click();
      await expect(report.getByRole("heading", { name: T.DOCUMENT_SECTIONS.outlook, exact: true })).toBeInViewport();
      await main.getByRole("navigation", { name: T.DOCUMENT_INDEX }).getByRole("link", { name: new RegExp(T.DOCUMENT_SECTIONS.business) }).click();
    }

    await page.screenshot({ path: testInfo.outputPath("fund-briefing.png"), fullPage: true });
    await main.getByRole("tab", { name: T.RESEARCH }).click();
    await expect(panel).toContainText(T.HOLDINGS_DATE + " · " + fund.holdings_as_of);
    const table = panel.getByRole("table").first();

    for (const item of fund.holdings) {
      const row = table.getByRole("row").filter({ hasText: item.name });
      await expect(row).toContainText(item.weight_pct.toFixed(2) + "%");
    }

    await main.getByRole("tab", { name: T.BRIEF }).click();
    await expect(panel.getByRole("link", { name: T.PROSPECTUS })).toHaveAttribute("href", fund.prospectus_url);
    await expect(panel.getByRole("heading", { name: T.FINANCIAL_TREND })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath("fund-briefing.png"), fullPage: true });
    await main.getByRole("tab", { name: T.EVIDENCE }).click();
    await expect(main.getByRole("tabpanel")).toContainText(T.JUDGMENT_SOURCE);
    await expect(main.getByRole("tabpanel").getByRole("heading", { name: T.HOLDING })).toBeVisible();
    await main.getByRole("tab", { name: T.HISTORY }).click();
    await expect(main.getByRole("tabpanel")).toContainText(T.HISTORY_EXPLAIN);
  });
}
