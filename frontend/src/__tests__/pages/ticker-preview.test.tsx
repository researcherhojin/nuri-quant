import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { CollectResearch } from "@/app/ticker-next/[symbol]/collect-research";
import { ResearchTabs } from "@/app/ticker-next/[symbol]/research-tabs";
import { NewsItem } from "@/app/ticker-next/[symbol]/news-item";
import { sourceUrl } from "@/app/ticker-next/[symbol]/briefing";
import Page from "@/app/ticker-next/[symbol]/page";
import { Inbox } from "@/app/(overview)/inbox";
import { TICKER_PREVIEW as T, CONSENSUS } from "@/lib/strings";

const fetchAPI = vi.hoisted(() => vi.fn());

const refresh = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ fetchAPI, API_BASE: "http://localhost:8001" }));

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

vi.mock("next/navigation", async () => {
  const React = await import("react");

  function subscribe(listener: () => void) {
    window.addEventListener("popstate", listener);

    return () => window.removeEventListener("popstate", listener);
  }

  return { usePathname: () => "/ticker-next/DEMO", useRouter: () => ({ refresh }), useSearchParams: () => new URLSearchParams(React.useSyncExternalStore(subscribe, () => window.location.search)) };
});

vi.mock("@/components/ui/price-chart-lazy", () => ({ PriceChartLazy: () => <div>chart fixture</div> }));

const item = { ticker: "DEMO", action: "HOLD", confidence: 60, reasons: ["집중도 규칙 확인"], alpha_action: "LONG", portfolio_action: "REBALANCE", position_pct: null, pnl_pct: null, account: "Brokerage Alpha", as_of: "2026-01-02", decision_id: 42 };

const responses: Record<string, unknown> = {};

beforeEach(() => {
  window.history.replaceState(null, "", "/ticker-next/DEMO?bucket=portfolio");
  const pushState = window.history.pushState.bind(window.history);

  vi.spyOn(window.history, "pushState").mockImplementation((...args) => { pushState(...args); window.dispatchEvent(new PopStateEvent("popstate")); });
  fetchAPI.mockReset();
  refresh.mockReset();
  Object.assign(responses, {
    "/api/ticker/DEMO?stored_only=true": { ticker: "DEMO", price: { close: 0, date: "2026-01-05" }, consensus: { final_action: "HOLD", final_confidence: 0, agreement_rate: 0, as_of: "2026-01-03", verdicts: [{ agent_name: "value", action: "BUY", confidence: 80, reasoning: "저장된 분석" }, { agent_name: "macro", action: "HOLD", confidence: 99, degraded: true }], dissent: ["저장된 반대 의견"] }, fundamentals: { roe: 0, pe_ratio: 0, date: "2026-01-01" } },
    "/api/ticker/DEMO/prices?days=365": { prices: [] },
    "/api/decisions?ticker=DEMO&limit=12": { decisions: [{ id: 41, ticker: "DEMO", date: "2026-01-01", action: "BUY", pnl_7d: 0, pnl_30d: null, outcome: "pending" }] },
    "/api/actions": { urgent: [], check: [], portfolio: [item], hold: [], generated_at: "2026-01-06T09:00:00" },
  });
  fetchAPI.mockImplementation(async (path: string) => responses[path]);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ ticker: "DEMO", dossier: null, news: [], events: [], fundamentals_history: [] }) })));
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function show() {
  render(await Page({ params: Promise.resolve({ symbol: "demo" }), searchParams: Promise.resolve({ bucket: "portfolio" }) }));
}

describe("ticker preview", () => {
  it("flags legacy calculation reasons without rewriting historical evidence", async () => {
    responses["/api/ticker/DEMO?stored_only=true"] = { ticker: "DEMO", consensus: { final_action: "HOLD", verdicts: [
      { agent_name: "fundamental", action: "HOLD", reasoning: "부채비율 150.0x (과다)" },
    ] } };
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    const panel = screen.getByRole("tabpanel", { name: T.EVIDENCE });

    expect(within(panel).getByText(T.LEGACY_CALCULATION_NOTE)).toBeInTheDocument();
    expect(within(panel).getAllByText("부채비율 150.0x (과다)")).toHaveLength(2);
  });
  it("explains a risk veto without presenting confidence 100 as unanimity", async () => {
    responses["/api/ticker/DEMO?stored_only=true"] = { ticker: "DEMO", consensus: { final_action: "SELL", final_confidence: 100, scoring_detail: { final_action_source: "risk_veto" }, verdicts: [
      { agent_name: "technical", action: "SELL", reasoning: "Technical support" },
      { agent_name: "risk", action: "SELL", reasoning: "Actual risk veto reason" },
    ] } };
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    const panel = within(screen.getByRole("tabpanel", { name: T.EVIDENCE })).getByRole("heading", { name: T.CURRENT_JUDGMENT }).closest("section");

    if (!panel) throw new Error("Missing judgment section");
    expect(within(panel).getByText(T.DECISION_MECHANISMS.risk_veto)).toBeInTheDocument();
    expect(within(panel).getByText(T.VETO_CONFIDENCE_NOTE)).toBeInTheDocument();
    expect(within(panel).queryByText(T.LEGACY_CALCULATION_NOTE)).not.toBeInTheDocument();
    expect(within(panel).getAllByRole("listitem")[0]).toHaveTextContent("Actual risk veto reason");
  });

  it("deep links tabs, preserves Overview context and restores browser history", () => {
    window.history.replaceState(null, "", "/ticker-next/DEMO?bucket=portfolio&tab=history");
    render(<ResearchTabs brief={<p>brief fixture</p>} evidence={<p>evidence fixture</p>} research={<p>research fixture</p>} history={<p>history fixture</p>} />);
    expect(screen.getByRole("tab", { name: T.HISTORY })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: T.RESEARCH }));
    expect(window.location.search).toBe("?bucket=portfolio&tab=research");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("research fixture");
    window.history.replaceState(null, "", "?bucket=portfolio&tab=history");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByRole("tab", { name: T.HISTORY })).toHaveAttribute("aria-selected", "true");
  });

  it("only shows source excerpts and conditional reading questions for a verified publisher body", () => {
    render(<ul><NewsItem item={{ date: "2026-01-01", title: "Verified news", url: "https://example.com/rss", article_url: "https://example.com/article", content_status: "verified", excerpt: "A source excerpt", topics: ["earnings"] }} /><NewsItem item={{ date: "2026-01-02", title: "Unverified news", url: "https://example.com/failure", content_status: "unavailable", excerpt: "Must not display", topics: ["operations"] }} /></ul>);
    expect(screen.getByRole("link", { name: "Verified news" })).toHaveAttribute("href", "https://example.com/article");
    expect(screen.getByText("A source excerpt")).toBeInTheDocument();
    expect(screen.getByText(T.NEWS_TOPICS.earnings)).toBeInTheDocument();
    expect(screen.getByText(T.NEWS_CONTENT_UNAVAILABLE)).toBeInTheDocument();
    expect(screen.queryByText("Must not display")).not.toBeInTheDocument();
    expect(screen.queryByText(T.NEWS_TOPICS.operations)).not.toBeInTheDocument();
  });
  it("keeps dated history reasons with their own outcomes and opens only the latest reason initially", async () => {
    responses["/api/decisions?ticker=DEMO&limit=12"] = { decisions: [
      { id: 42, ticker: "DEMO", date: "2026-01-02", action: "HOLD", reasoning: "Latest saved reason", outcome: "pending", pnl_7d: null, pnl_30d: null },
      { id: 41, ticker: "DEMO", date: "2026-01-01", action: "BUY", reasoning: "Previous saved reason", outcome: "pending", pnl_7d: 0, pnl_30d: null },
    ] };
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.HISTORY }));
    const latest = screen.getByRole("article", { name: `2026-01-02 ${T.HISTORY}` });
    const previous = screen.getByRole("article", { name: `2026-01-01 ${T.HISTORY}` });

    expect(within(latest).getByText("Latest saved reason").closest("details")).toHaveAttribute("open");
    expect(within(previous).getByText("Previous saved reason").closest("details")).not.toHaveAttribute("open");
    expect(within(previous).getByText("0.0%")).toBeInTheDocument();
    expect(within(latest).queryByText("0.0%")).not.toBeInTheDocument();
    expect(within(latest).getByRole("link", { name: T.OPEN })).toHaveAttribute("href", "/decisions/42");
    fireEvent.click(within(previous).getByText(T.PRO_REASONS));
    expect(within(previous).getByText("Previous saved reason").closest("details")).toHaveAttribute("open");
  });
  it("starts with source-backed company facts and keeps missing values, currencies and report periods distinct", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({
      ticker: "DEMO", dossier: { ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00",
        news_check: { checked_at: "2026-01-06T09:00:00+09:00", window_start: "2025-12-07", window_end: "2026-01-06", sources: ["Google News"], failed_sources: [] },
        profile: { name: "Demo Company", symbol: "DEMO", description: "Source business description", financial_currency: "KRW", currency: "USD", market_cap: 123, website: "javascript:alert(1)" },
        statements: { income: [{ period: "2025-12-31", revenue: 0, net_income: -20 }, { period: "2024-12-31", revenue: 100 }], cashflow: [{ period: "2025-06-30", operating_cashflow: -10, free_cashflow: null }], balance: [] } },
      news: [{ date: "2026-01-05", title: "Stored news", source: "Source", url: "https://example.com/news" }, { date: "2026-01-04", title: "Unsafe source", url: "javascript:alert(1)" }], events: [], fundamentals_history: [] }) } as Response);
    await show();
    expect(screen.getByRole("tab", { name: T.BRIEF })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { level: 1, name: "Demo Company" })).toBeInTheDocument();
    expect(screen.getAllByText("Source business description")).toHaveLength(2);
    expect(screen.getByText("123 USD")).toBeInTheDocument();
    expect(screen.getByText(T.LOSS_FACT)).toBeInTheDocument();
    expect(screen.getByText(T.CASHFLOW_FACT)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stored news" })).toHaveAttribute("href", "https://example.com/news");
    expect(screen.queryByRole("link", { name: "Unsafe source" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: T.WEBSITE })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: T.RESEARCH }));
    const table = screen.getByRole("table");
    const incomeRow = within(table).getByRole("row", { name: /^2025-12-31/ });
    const cashRow = within(table).getByRole("row", { name: /^2025-06-30/ });
    expect(within(incomeRow).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["0", "—", "-20", "—", "—", "—", "—"]);
    expect(within(cashRow).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["—", "—", "—", "-10", "—", "—", "—"]);
    expect(screen.getByText(T.FINANCIAL_CURRENCY + " · KRW · " + T.FINANCIAL_NOTE)).toBeInTheDocument();
  });

  it("collects only after a click, reports an unresolved symbol and allows retry with refresh", async () => {
    await show();
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 404 } as Response);
    fireEvent.click(screen.getByRole("button", { name: T.COLLECT }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(T.COLLECT_UNKNOWN));
    expect(refresh).not.toHaveBeenCalled();
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true } as Response);
    fireEvent.click(screen.getByRole("button", { name: T.COLLECT }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenLastCalledWith("/api/ticker/DEMO/research/refresh?force=true", { method: "POST" });
  });

  it("explains ETF holdings and source dates without company earnings panels", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({
      ticker: "DEMO", today: "2026-01-06", collected_today: true,
      dossier: { ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00", profile: { name: "Demo Fund", symbol: "DEMO", quote_type: "ETF" }, statements: { income: [], cashflow: [], balance: [] },
        fund: { source_name: "Example Issuer", source_url: "https://example.com/fund", strategy_text: "공식 자료의 한국어 설명", details_as_of: "2026-01-04", holdings_as_of: "2026-01-05", expense_pct: 0.5, holdings: [{ name: "Aerospace Sample", weight_pct: 20 }, { name: "Satellite Sample", weight_pct: 10 }, { name: "Rocket Sample", weight_pct: 5 }], risks: [{ title: "Space Risk", text: "Source risk text" }] },
        price_history: [{ date: "2026-01-02", open: 10, high: 20, low: 9, close: 10, volume: 100 }, { date: "2026-01-05", open: 10, high: 12, low: 8, close: 11, volume: 200 }] },
      news: [], events: [], fundamentals_history: [] }) } as Response);
    await show();
    expect(screen.getByRole("heading", { name: T.FUND_INTRO })).toBeInTheDocument();
    expect(screen.getByText("공식 자료의 한국어 설명")).toBeInTheDocument();
    expect(screen.getByText(/상위 3개가 35.00%/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: T.HOLDINGS })).not.toBeInTheDocument();
    expect(screen.getByText(T.FUND_DETAILS_DATE + " · 2026-01-04")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: T.FINANCIAL_TREND })).not.toBeInTheDocument();
    expect(screen.getByText(T.RISK_GLOSSARY["Space Risk"].text)).toBeInTheDocument();
    expect(screen.getByText("$11.00")).toBeInTheDocument();
    expect(screen.getByText("-45.0%")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("tab", { name: T.RESEARCH }));
    expect(screen.queryByRole("heading", { name: T.FUNDAMENTALS })).not.toBeInTheDocument();
    expect(screen.getByText(T.HOLDINGS_DATE + " · 2026-01-05")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: T.HOLDINGS })).toBeInTheDocument();
  });

  it("opening a page without today's research sends no collection request", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({ ticker: "DEMO", today: "2026-01-06", collected_today: false, dossier: null, news: [], events: [], fundamentals_history: [] }) } as Response);
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.HISTORY }));
    fireEvent.click(screen.getByRole("tab", { name: T.BRIEF }));
    // 자료 조회 1건뿐 — 마운트·탭 이동이 /research/refresh 를 부르면 외부 수집이 방문만으로 시작된다
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/research/refresh"))).toBe(false);
    render(<CollectResearch symbol="DEMO" />);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects unsafe and malformed source links", () => {
    expect(sourceUrl("https://example.com/report")).toBe("https://example.com/report");

    for (const value of ["javascript:alert(1)", "data:text/html,test", "file:///tmp/test", "not a url", null]) expect(sourceUrl(value)).toBeNull();
  });

  it("separates price, consensus and review dates, keeps axes and links the exact review decision", async () => {
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    expect(screen.getByText(`${T.PRICE_DATE} · 2026-01-05`)).toBeInTheDocument();
    const dates = screen.getByText(T.DATA_DATES).closest("details");

    expect(dates).toHaveTextContent("2026-01-03");
    expect(dates).toHaveTextContent("2026-01-02");
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("REBALANCE")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: T.LEDGER })).toHaveAttribute("href", "/decisions/42");
    expect(screen.getByRole("link", { name: T.BACK })).toHaveAttribute("href", "/?bucket=portfolio&ticker=DEMO");
    expect(screen.getByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText(CONSENSUS.PLACEHOLDER_DEGRADED)).toBeInTheDocument();
    expect(screen.queryByText("99")).not.toBeInTheDocument();
    expect(fetchAPI).toHaveBeenCalledTimes(4);
  });

  it("exposes original reasoning and navigates tabs with keyboard without refetching", async () => {
    await show();
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    fireEvent.click(screen.getByText("value"));
    expect(screen.getByText("저장된 분석").closest("details")).toHaveAttribute("open");
    fireEvent.keyDown(screen.getByRole("tab", { name: T.EVIDENCE }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: T.RESEARCH })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent(T.FUNDAMENTALS);
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: T.RESEARCH }), { key: "End" });
    expect(screen.getByRole("link", { name: T.OPEN })).toHaveAttribute("href", "/decisions/41");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("0.0%");
    expect(fetchAPI).toHaveBeenCalledTimes(4);
  });

  it("keeps remaining panels usable when a source fails and never claims a missing review is an unheld ticker", async () => {
    responses["/api/ticker/DEMO?stored_only=true"] = { error: "failed" };
    responses["/api/actions"] = { urgent: [], check: [], portfolio: [], hold: [] };
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await show();
    expect(screen.getAllByText(T.UNAVAILABLE).length).toBeGreaterThan(0);
    expect(screen.queryByText(T.NO_REVIEW)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: T.HISTORY }));
    expect(screen.getByRole("link", { name: T.OPEN })).toHaveAttribute("href", "/decisions/41");
  });

  it("labels an empty successful review list without asserting ownership", async () => {
    responses["/api/actions"] = { urgent: [], check: [], portfolio: [], hold: [], generated_at: "2026-01-06" };
    await show();
    expect(screen.queryByText(T.NO_REVIEW)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: T.EVIDENCE }));
    expect(screen.getByText(T.NO_REVIEW)).toBeInTheDocument();
  });

  it("does not replace a successful empty recent news search with an old stored article", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({
      ticker: "DEMO", dossier: { ticker: "DEMO", collected_at: "2026-01-06T09:00:00+09:00", profile: { name: "Demo Company", symbol: "DEMO" }, statements: { income: [], cashflow: [], balance: [] }, news: [], news_check: { checked_at: "2026-01-06T09:00:00+09:00", window_start: "2025-12-07", window_end: "2026-01-06", sources: ["Google News"], failed_sources: [] } }, news: [{ date: "2025-01-01", title: "Old stored headline", source: "Publisher", url: "https://example.com/old" }], events: [], fundamentals_history: [] }) } as Response);
    await show();
    expect(screen.getByText(T.NEWS_NONE_RECENT)).toBeInTheDocument();
    expect(screen.queryByText("Old stored headline")).not.toBeInTheDocument();
  });

  it("restores the selected Overview ticker and builds its preview link", () => {
    render(<Inbox initialBucket="portfolio" initialTicker="DEMO" actions={{ urgent: [], check: [], hold: [], portfolio: [{ ...item, ticker: "OTHER" }, item] }} />);
    const selected = screen.getByRole("article");

    expect(within(selected).getByRole("heading")).toHaveTextContent("DEMO");
    expect(screen.getByRole("link", { name: T.BRIEF })).toHaveAttribute("href", "/ticker-next/DEMO?bucket=portfolio");
  });
});
