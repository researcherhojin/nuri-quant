import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import DashboardNext from "@/app/(overview)/page";
import Loading from "@/app/(overview)/loading";
import { readPanel, freshnessSchema } from "@/app/(overview)/data";
import { OVERVIEW, TICKER_PREVIEW } from "@/lib/strings";
import { displayChange, displayShortTime, displayTime } from "@/app/(overview)/format";

const fetchAPI = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ fetchAPI }));

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

const dashboard = {
  verdict: "입력 자료를 확인하세요", verdict_level: "stale",
  regime: { regime: "unknown", trend: "unknown", confidence: 0 },
  macro: { score: 50, interpretation: "Unavailable", coverage: 0 },
  actual_allocation: null, target_allocation: { long: 50, short: 0, cash: 50 },
  fx_unavailable: "환율 미수집", alerts: [],
};

const item = {
  ticker: "DEMO", action: "REBALANCE", confidence: 70,
  reasons: ["집중도 규칙 검토"], decision_id: 42, as_of: "2026-01-01",
  position_pct: null, pnl_pct: null, alpha_action: "LONG", portfolio_action: "REBALANCE",
};

const responses: Record<string, unknown> = {};

// console.warn spy 는 단언 실패 시에도 복원한다
afterEach(() => { vi.restoreAllMocks(); });

beforeEach(() => {
  fetchAPI.mockReset();
  vi.stubGlobal("fetch", vi.fn(async (path: string) => ({ ok: true, json: async () => path === "/api/scheduler/health" ? { status: "unknown" } : responses[path] })));
  Object.assign(responses, {
    "/api/dashboard": dashboard,
    "/api/portfolio": { holdings: [], cash: { total_cash_usd: null, accounts: [] } },
    "/api/actions": { urgent: [], check: [], hold: [], portfolio: [item] },
    "/api/opportunities": { opportunities: [] },
    "/api/pipeline/status": { steps: [] },
    "/api/freshness": { pass: 0, warn: 0, fail: 0, details: [] },
  });
  fetchAPI.mockImplementation(async (path: string) => responses[path]);
});

async function renderPage(props: Parameters<typeof DashboardNext>[0]) {
  await act(async () => { render(await DashboardNext(props)); });
}

describe("decision desk", () => {
  it("keeps portfolio rules separate and lets the user switch buckets without fetching again", async () => {
    await renderPage({});
    expect(screen.queryByText(item.reasons[0])).not.toBeInTheDocument();
    const calls = fetchAPI.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /포트폴리오 규칙/ }));
    expect(screen.getByText(item.reasons[0])).toBeInTheDocument();
    expect(fetchAPI).toHaveBeenCalledTimes(calls);
  });
  it("shows the selected item's evidence, null exposure and independent axes", async () => {
    await renderPage({ searchParams: Promise.resolve({ bucket: "portfolio" }) });
    const evidence = screen.getByRole("article", { name: "선택한 판단 근거" });
    expect(within(evidence).getByText(item.reasons[0])).toBeInTheDocument();
    expect(within(evidence).getByRole("link", { name: /판정 원장에서 전체 근거/ })).toHaveAttribute("href", "/decisions/42");
    expect(within(evidence).getByText("LONG")).toBeInTheDocument();
    expect(within(evidence).getByText("REBALANCE")).toBeInTheDocument();
    expect(within(evidence).getAllByText("—")).toHaveLength(2);
    expect(within(evidence).getByText(/2026-01-01/)).toBeInTheDocument();
    expect(within(evidence).getByRole("link", { name: TICKER_PREVIEW.BRIEF })).toHaveAttribute("href", "/ticker-next/DEMO?bucket=portfolio");
    expect(within(evidence).getByText(TICKER_PREVIEW.CONFIDENCE).parentElement).toHaveTextContent(`${item.confidence}${TICKER_PREVIEW.CONFIDENCE_DENOMINATOR}`);
  });
  it("selects another item and resets selection on a bucket change", async () => {
    responses["/api/actions"] = { urgent: [item, { ...item, ticker: "SAMPLE", reasons: ["두 번째 근거"], decision_id: null }], check: [], hold: [], portfolio: [item] };
    await renderPage({});
    fireEvent.click(screen.getByRole("button", { name: /SAMPLE/ }));
    expect(screen.getByText("두 번째 근거")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /판정 원장에서 전체 근거/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /포트폴리오 규칙/ }));
    expect(screen.getByText(item.reasons[0])).toBeInTheDocument();
    expect(screen.queryByText("두 번째 근거")).not.toBeInTheDocument();
  });
  it("preserves unknown allocation and suppresses the backend fallback macro score", async () => {
    responses["/api/dashboard"] = { ...dashboard, verdict_level: "neutral" };
    await renderPage({});
    expect(screen.getByText(/비중 산출 보류/)).toBeInTheDocument();
    const market = screen.getByLabelText("현재 시장 환경");
    expect(within(market).queryByText("50")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "신선도 확인 불가" })).toBeInTheDocument();
  });
  it("switches portfolio grouping using holdings and cash, without an extra request", async () => {
    responses["/api/portfolio"] = { holdings: [{ ticker: "DEMO", name: "Example", account: "demo", sector: "Technology", currency: "USD", quantity: 2, latest_price: 100, price_date: "2026-01-01" }], cash: { total_cash_usd: 200, accounts: [{ account: "demo", total_usd: 200 }] } };
    await renderPage({});
    const panel = screen.getByRole("region", { name: "포트폴리오 구성" });
    expect(within(panel).getByText("$400")).toBeInTheDocument();
    const calls = fetchAPI.mock.calls.length;
    fireEvent.click(within(panel).getByRole("button", { name: "계좌별" }));
    expect(within(panel).getAllByText("100.0%").length).toBeGreaterThan(0);
    expect(fetchAPI).toHaveBeenCalledTimes(calls);
  });
  it("keeps a healthy panel visible when other endpoints return errors, and says why in the server log", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    fetchAPI.mockImplementation(async (path: string) => {
      if (path === "/api/dashboard") return dashboard;

      if (path === "/api/actions") return { error: "unavailable" };
      throw new Error("API unavailable");
    });
    await renderPage({});
    expect(screen.getByText(/일부 정보를 불러오지 못했습니다/)).toHaveTextContent("5/6");
    expect(screen.getByText(dashboard.verdict)).toBeInTheDocument();
    expect(screen.getAllByText(OVERVIEW.UNAVAILABLE).length).toBeGreaterThan(0);
    // 패널이 왜 사라졌는지는 서버 로그에 남는다 — 스키마 드리프트와 전송 실패를 구분해서 (Codex #1658 P2)
    const messages = warn.mock.calls.map(([message]) => String(message));

    expect(messages).toEqual(expect.arrayContaining([expect.stringContaining("/api/actions unavailable (schema)"), expect.stringContaining("/api/portfolio unavailable (transport)")]));
    warn.mockRestore();
  });
  it("labels price changes by period and never describes them as new decisions", async () => {
    const stance = (status: string, score: number | null, reason: string | null) => ({ status, score, threshold: 70, reason });
    responses["/api/opportunities"] = { opportunities: [
      { ticker: "EXAMPLE", signal: null, score: null, observations: [], system: stance("below_threshold", 52.4, null), change_1d: 1.2, change_5d: null },
      { ticker: "COOLED", signal: null, score: null, observations: [], system: stance("excluded", null, "cooldown"), change_1d: null, change_5d: null },
      { ticker: "STOPPED", signal: null, score: null, observations: [], system: { ...stance("blocked", null, "VIX 31.0 > 30 (신규 매수 차단)"), threshold: null }, change_1d: null, change_5d: null },
    ] };
    await renderPage({});
    // #1683: 판단 칸은 파이프라인 분류 — 점수·임계·사유가 API 값 그대로 나온다
    expect(screen.getByRole("button", { name: "기준 미달 52 / 70" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "제외 · 쿨다운" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "차단" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("STOPPED · 탐색 근거")).getByText("차단 · VIX 31.0 > 30 (신규 매수 차단)")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "1일 변화" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "EXAMPLE" })).toHaveAttribute("href", "/ticker-next/EXAMPLE");
    expect(screen.getAllByText("+1.2%")[0]).toBeInTheDocument();
    expect(screen.getAllByText(/신규 판단이나 판단 변경을 의미하지 않습니다/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/개별 가격 관측 시각은 제공되지 않습니다/)[0]).toBeInTheDocument();
  });
  it("surfaces delayed inputs next to the brief even if pipeline steps completed", async () => {
    responses["/api/dashboard"] = { ...dashboard, verdict_level: "neutral" };
    responses["/api/freshness"] = { pass: 0, warn: 0, fail: 1, details: [{ key: "prices", label: "가격 데이터", status: "FAIL", message: "갱신 지연" }] };
    responses["/api/pipeline/status"] = { steps: [{ step: "collect", label: "Collect", status: "done", last_updated: null }] };
    await renderPage({});
    const brief = screen.getByRole("region", { name: "오늘의 확인 순서" });
    expect(within(brief).getByText("지연된 데이터 1개")).toBeInTheDocument();
    expect(screen.getByTitle(/마지막 실행 결과는 데이터 신선도와 별개/)).toBeInTheDocument();
  });
  it("renders zoned timestamps in KST and preserves zone-less source times", () => {
    expect(displayTime("2026-01-01T00:00:00Z")).toContain("09:00 KST");
    expect(displayTime("2026-01-01T00:00:00")).toBe("2026-01-01 00:00:00");
    expect(displayTime(null)).toBe("기준 시각 미제공");
  });
  it("renders every row time as MM-DD HH:mm in KST (#1675)", () => {
    expect(displayShortTime("2026-10-06T20:45:00Z")).toBe("10-07 05:45");
    expect(displayShortTime("2026-10-07T05:45:00+09:00")).toBe("10-07 05:45");
    expect(displayShortTime("2026-10-06 09:00:00")).toBe("10-06 09:00");
    expect(displayShortTime(null)).toBeNull();
    expect(displayShortTime("2026-13-45T99:00:00Z")).toBeNull();
  });
  it("renders zoned timestamps that fail to parse as unknown instead of NaN", () => {
    expect(displayTime("2026-13-45T99:00:00Z")).toBe("기준 시각 미제공");
  });
  it("signs only positive changes", () => {
    expect(displayChange(2)).toBe("+2%");
    expect(displayChange(-2)).toBe("-2%");
    expect(displayChange(0)).toBe("0%");
    expect(displayChange(Number.NaN)).toBe("—");
  });
});

describe("market and source panels", () => {
  it("shows a known regime and macro reading with their localized labels", async () => {
    responses["/api/dashboard"] = { ...dashboard, verdict_level: "neutral", regime: { regime: "bull_low_vol", trend: "up", confidence: 80, vix: 15 }, macro: { score: 62, interpretation: "Favorable", coverage: 1 } };
    await renderPage({});
    const market = screen.getByLabelText("현재 시장 환경");

    expect(within(market).getByText("상승 · 저변동")).toBeInTheDocument();
    expect(within(market).getByText(/80%/)).toBeInTheDocument();
    expect(within(market).getByText("62")).toBeInTheDocument();
    expect(within(market).getByText("양호")).toBeInTheDocument();
    expect(within(market).queryByText(OVERVIEW.METRICS.MACRO_UNAVAILABLE)).not.toBeInTheDocument();
  });
  it("gives every metric card an icon + title heading and a guide dialog that lists stored sources (#1682)", async () => {
    responses["/api/dashboard"] = {
      ...dashboard,
      market_indices: [{ key: "sp500", label: "S&P 500", close: 100, prev_close: 99, change_pct: 1, date: "2026-01-02", source: "yfinance", symbol: "^GSPC" }],
      macro_inputs: [
        { key: "vix", date: "2026-01-02", source: "FRED" },
        { key: "cpi_yoy", date: "2025-11-01", source: "newfeed" },
        { key: "unemployment", date: null, source: null },
        { key: "us_2y_yield", date: "2026-01-02", source: "yfinance" },
      ],
    };
    responses["/api/actions"] = { urgent: [{ ticker: "DEMO", action: "SELL", confidence: 1, reasons: [], as_of: "2026-01-03" }], check: [{ ticker: "DEMO2", action: "HOLD", confidence: 1, reasons: [], as_of: "2025-12-30" }], hold: [], portfolio: [], generated_at: "2026-01-09T09:00:00+09:00" };
    await renderPage({});
    const metrics = screen.getByLabelText(OVERVIEW.METRICS.ARIA);
    const titles = within(metrics).getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

    expect(titles).toEqual([OVERVIEW.METRICS.INDICES, OVERVIEW.METRICS.MACRO, OVERVIEW.METRICS.VIX, OVERVIEW.METRICS.ACTIONS]);
    const guides = within(metrics).getAllByRole("button", { name: OVERVIEW.METRICS.GUIDE });

    expect(guides).toHaveLength(4);
    // ⓘ 아이콘만 — 문구는 접근 가능한 이름으로만 남는다
    guides.forEach((button) => expect(button).toHaveTextContent(/^$/));
    // 우선 점검: 판정 기준일(가장 최근 as_of)이지 목록 생성 시각이 아니다
    expect(within(metrics).getByText(OVERVIEW.METRICS.ACTIONS_JUDGED_SHORT("01-03"))).toBeInTheDocument();
    // 우측 하단 출처 요약 — 저장된 코드를 표시 이름으로
    expect(within(metrics).getByText("FRED · 01-02")).toBeInTheDocument();
    // 경제 여건 점수 모달: 지표별 출처·기준일, 모르는 코드는 그대로, 없으면 미제공
    const macroDialog = screen.getByLabelText(OVERVIEW.METRICS.MACRO_GUIDE_TITLE);
    const rows = within(macroDialog).getAllByRole("row", { hidden: true }).map((row) => row.textContent);

    expect(rows).toContain("VIXFRED2026-01-02");
    expect(rows).toContain("CPI 상승률newfeed2025-11-01");
    expect(rows).toContain(`실업률${OVERVIEW.METRICS.SOURCE_UNKNOWN}—`);
    // 출처가 대용치면 이름도 바뀐다 — yfinance 의 2년물 자리는 13주물(^IRX)
    expect(rows).toContain("미국 13주물 금리 (2년물 대용)Yahoo Finance2026-01-02");
    const marketDialog = screen.getByLabelText(OVERVIEW.METRICS.REGIME_GUIDE_TITLE);

    expect(within(marketDialog).getAllByRole("row", { hidden: true }).map((row) => row.textContent)).toContain("S&P 500Yahoo Finance ^GSPC2026-01-02");
  });
  it("headlines the four official indices with level, signed change and bar date, and leaves missing values blank", async () => {
    const index = (key: string, label: string, close: number | null, change: number | null, date: string | null) => ({ key, label, close, prev_close: null, change_pct: change, date });

    responses["/api/dashboard"] = { ...dashboard, market_indices: [
      index("sp500", "S&P 500", 1234.5, 0.5, "2026-01-02"),
      index("nasdaq", "NASDAQ", 2345.678, -1.25, "2026-01-02"),
      index("kospi", "KOSPI", 3456, null, "2026-01-05"),
      index("kosdaq", "KOSDAQ", null, null, null),
    ] };
    await renderPage({});
    const card = screen.getByRole("article", { name: OVERVIEW.METRICS.INDICES });
    const rows = within(card).getAllByRole("listitem");

    expect(rows.map((row) => within(row).getByText(/^[A-Z&P ]+\d*$/).textContent)).toEqual(["S&P 500", "NASDAQ", "KOSPI", "KOSDAQ"]);
    expect(within(rows[0]).getByText("1,234.50")).toBeInTheDocument();
    expect(within(rows[0]).getByText("+0.50%")).toHaveAttribute("data-direction", "up");
    expect(within(rows[0]).getByText("01-02")).toHaveAttribute("datetime", "2026-01-02"); // 기준일은 이름 줄에 MM-DD, 전체 날짜는 datetime
    expect(within(rows[1]).getByText("2,345.68")).toBeInTheDocument();
    expect(within(rows[1]).getByText("-1.25%")).toHaveAttribute("data-direction", "down");
    // 직전 관측이 없으면 변화율은 비워 두고 0% 로 만들지 않는다
    expect(within(rows[2]).getByText("—")).toHaveAttribute("data-direction", "unknown");
    expect(within(rows[2]).queryByText("0.00%")).not.toBeInTheDocument();
    expect(within(rows[3]).getAllByText("—")).toHaveLength(2);
    expect(within(rows[3]).getByText(OVERVIEW.METRICS.INDEX_DATE_UNKNOWN)).toBeInTheDocument();
  });
  it("says the index block is unavailable when the API sends none", async () => {
    await renderPage({});
    const card = screen.getByRole("article", { name: OVERVIEW.METRICS.INDICES });

    expect(within(card).getByText(OVERVIEW.METRICS.INDICES_UNAVAILABLE)).toBeInTheDocument();
    expect(within(card).queryByRole("listitem")).not.toBeInTheDocument();
  });
  it("labels a special regime and separates the base call from the check agreement it does not describe", async () => {
    responses["/api/dashboard"] = { ...dashboard, regime: { regime: "sector_rotation", trend: "bull", volatility: "low", confidence: 100 } };
    await renderPage({});
    const card = screen.getByRole("article", { name: OVERVIEW.METRICS.INDICES });

    expect(within(card).getByText("섹터 순환")).toBeInTheDocument();
    expect(within(card).queryByText("sector_rotation")).not.toBeInTheDocument();
    expect(within(card).getByText(`${OVERVIEW.METRICS.REGIME_BASE("상승 · 저변동")} · ${OVERVIEW.METRICS.REGIME_AGREEMENT("100%")}`)).toBeInTheDocument();
  });
  it("does not repeat the base call when the regime is itself a base regime", async () => {
    responses["/api/dashboard"] = { ...dashboard, regime: { regime: "bull_low_vol", trend: "bull", volatility: "low", confidence: 75 } };
    await renderPage({});
    const card = screen.getByRole("article", { name: OVERVIEW.METRICS.INDICES });

    expect(within(card).getByText(OVERVIEW.METRICS.REGIME_AGREEMENT("75%"))).toBeInTheDocument();
    expect(within(card).queryByText(new RegExp(OVERVIEW.METRICS.REGIME_BASE("상승 · 저변동")))).not.toBeInTheDocument();
  });
  it("falls back to raw regime and macro labels the string maps do not know", async () => {
    responses["/api/dashboard"] = { ...dashboard, regime: { regime: "crisis_mode", trend: "down", confidence: 40 }, macro: { score: 30, interpretation: "Unmapped", coverage: 0.5 } };
    await renderPage({});
    const market = screen.getByLabelText("현재 시장 환경");

    expect(within(market).getByText("crisis_mode")).toBeInTheDocument();
    expect(within(market).getByText("Unmapped")).toBeInTheDocument();
  });
  it("hides the macro score when coverage is reported but the interpretation is the Unavailable placeholder", async () => {
    responses["/api/dashboard"] = { ...dashboard, macro: { score: 50, interpretation: "Unavailable", coverage: 0.4 } };
    await renderPage({});
    const market = screen.getByLabelText("현재 시장 환경");

    expect(within(market).queryByText("50")).not.toBeInTheDocument();
    expect(within(market).getByText(OVERVIEW.METRICS.MACRO_UNAVAILABLE)).toBeInTheDocument();
  });
  it("says unavailable when the verdict text is empty", async () => {
    responses["/api/dashboard"] = { ...dashboard, verdict: "" };
    await renderPage({});
    const summary = screen.getByRole("region", { name: "오늘의 확인 순서" });

    expect(within(summary).getByText(OVERVIEW.UNAVAILABLE)).toBeInTheDocument();
  });
  it("reports warnings when nothing failed, and readiness only when every source passes", async () => {
    responses["/api/freshness"] = { pass: 1, warn: 1, fail: 0, details: [{ key: "a", label: "소스 A", status: "PASS" }, { key: "b", label: "소스 B", status: "WARN", last_updated: "2026-01-01T00:00:00" }] };
    await renderPage({});
    expect(screen.getByRole("link", { name: "주의할 데이터 1개" })).toHaveAttribute("data-health", "attention");
  });
  it("marks freshness ready when every monitored source passes", async () => {
    responses["/api/freshness"] = { pass: 2, warn: 0, fail: 0, details: [{ key: "a", label: "소스 A", status: "PASS" }, { key: "b", label: "소스 B", status: "PASS" }] };
    await renderPage({});
    expect(screen.getByRole("link", { name: "수집 데이터 정상" })).toHaveAttribute("data-health", "ready");
    const trust = screen.getByText("2개 소스 모니터링").closest("section")!;

    expect(within(trust).getByText("주의·지연 항목 없음")).toBeInTheDocument();
  });
  it("lists failing sources before warnings and falls back to the update time when no message is given", async () => {
    responses["/api/freshness"] = { pass: 0, warn: 1, fail: 1, details: [
      { key: "warned", label: "주의 소스", status: "WARN", last_updated: "2026-01-01T09:30:00" },
      { key: "failed", label: "지연 소스", status: "FAIL", message: "갱신 지연" },
    ] };
    await renderPage({});
    const trust = screen.getByText("2개 소스 모니터링").closest("section")!;
    const body = trust.querySelector(":scope > div:nth-of-type(2)")!;
    const labels = [...body.querySelectorAll("b")].map((node) => node.textContent);

    expect(labels.slice(-2)).toEqual(["지연 소스", "주의 소스"]);
    expect(within(body as HTMLElement).getByText("2026-01-01 09:30:00")).toBeInTheDocument();
    const dots = [...body.querySelectorAll("[data-tone]")].slice(-2).map((node) => node.getAttribute("data-tone"));

    expect(dots).toEqual(["danger", "warning"]);
  });
  it("labels every source in the full-source dialog with its own tone and raw status for unknown ones", async () => {
    responses["/api/freshness"] = { pass: 1, warn: 1, fail: 1, details: [
      { key: "p", label: "정상 소스", status: "PASS", last_updated: "2026-01-02T00:00:00" },
      { key: "w", label: "주의 소스", status: "WARN", message: "확인 필요" },
      { key: "f", label: "지연 소스", status: "FAIL", message: "갱신 지연" },
      { key: "x", label: "기타 소스", status: "SKIP", message: "측정 안 함" },
    ] };
    responses["/api/dashboard"] = { ...dashboard, verdict_stale_inputs: [{ key: "prices", label: "가격", last_updated: null, age_hours: 30 }, { key: "macro", label: "매크로", last_updated: null, age_hours: null }] };
    await renderPage({});
    const sources = screen.getByLabelText("데이터 소스별 신선도");
    const tone = (label: string) => within(sources).getByText(label).closest("div")!.querySelector("[data-tone]")!;

    expect(tone("정상 소스")).toHaveAttribute("data-tone", "neutral");
    expect(tone("정상 소스")).toHaveTextContent("정상");
    expect(tone("주의 소스")).toHaveAttribute("data-tone", "warning");
    expect(tone("지연 소스")).toHaveAttribute("data-tone", "danger");
    expect(tone("기타 소스")).toHaveTextContent("SKIP");
    expect(within(sources).getByText("2026-01-02 00:00:00")).toBeInTheDocument();
    expect(within(sources).getByText("종합 의견 보류 입력: 가격 · 매크로")).toBeInTheDocument();
  });
  it("says the source list is unavailable, not empty, when freshness failed to load", async () => {
    fetchAPI.mockImplementation(async (path: string) => {
      if (path === "/api/freshness") throw new Error("down");

      return responses[path];
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await renderPage({});
    const sources = screen.getByLabelText("데이터 소스별 신선도");

    expect(within(sources).getByText(OVERVIEW.UNAVAILABLE)).toBeInTheDocument();
    expect(within(sources).queryByText(OVERVIEW.EMPTY)).not.toBeInTheDocument();
    warn.mockRestore();
  });
  it("colors falling and flat changes and lists the candidate's scanner observations", async () => {
    responses["/api/opportunities"] = { generated_at: "2026-01-01T00:00:00Z", opportunities: [{ ticker: "EXAMPLE", signal: "momentum", score: 70, observations: ["추세 유지", "변동성 확대"], system: { status: "qualified", score: 78, threshold: 70, reason: null }, change_1d: -1.5, change_5d: 0 }] };
    await renderPage({});
    const row = screen.getByRole("rowheader", { name: "EXAMPLE" }).closest("tr")!;
    const cells = row.querySelectorAll("td[data-direction]");

    expect(cells[0]).toHaveAttribute("data-direction", "down");
    expect(cells[1]).toHaveAttribute("data-direction", "flat");
    const detail = screen.getByLabelText("EXAMPLE · 탐색 근거");

    expect(within(detail).getByText(OVERVIEW.RADAR_PANEL.OBSERVATIONS)).toBeInTheDocument();
    expect(within(detail).getByText("추세 유지")).toBeInTheDocument();
    expect(within(detail).getByText("변동성 확대")).toBeInTheDocument();
    expect(within(detail).queryByText(OVERVIEW.RADAR_PANEL.NO_OBSERVATIONS)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "후보 기준 통과 78 / 70" })).toBeInTheDocument();
  });
  it("says so when a candidate has no observations and was not scored", async () => {
    responses["/api/opportunities"] = { opportunities: [{ ticker: "EXAMPLE", signal: null, score: null, observations: [], system: { status: "not_scored", score: null, threshold: 70, reason: "no_factor" }, change_1d: null, change_5d: null }] };
    await renderPage({});
    const detail = screen.getByLabelText("EXAMPLE · 탐색 근거");

    expect(within(detail).getByText(OVERVIEW.RADAR_PANEL.NO_OBSERVATIONS)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "미평가 · 팩터 데이터 없음" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "EXAMPLE" }).closest("tr")!.querySelector("td[data-direction]")).toHaveAttribute("data-direction", "unknown");
  });
  it("lists system alerts, says none when empty, and unavailable when the dashboard failed", async () => {
    responses["/api/dashboard"] = { ...dashboard, alerts: [{ level: "warning", message: "환율 데이터 지연" }] };
    await renderPage({});
    expect(within(screen.getByLabelText("시스템 알림")).getByText("환율 데이터 지연")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "시스템 알림 1" })).toBeInTheDocument();
    cleanup();

    responses["/api/dashboard"] = dashboard;
    await renderPage({});
    expect(within(screen.getByLabelText("시스템 알림")).getByText(OVERVIEW.EMPTY)).toBeInTheDocument();
    cleanup();

    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    responses["/api/dashboard"] = { error: "unavailable" };
    await renderPage({});
    expect(within(screen.getByLabelText("시스템 알림")).getByText(OVERVIEW.UNAVAILABLE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "시스템 알림 —" })).toBeInTheDocument();
    warn.mockRestore();
  });
});

describe("panel reader and loading state", () => {
  it("logs non-Error rejections as transport failures with their text", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    fetchAPI.mockRejectedValueOnce("offline");
    await expect(readPanel("/api/freshness", freshnessSchema)).resolves.toBeNull();
    expect(warn).toHaveBeenCalledWith("[overview] /api/freshness unavailable (transport): offline");
    warn.mockRestore();
  });
  it("announces loading as a busy status with the loading copy", () => {
    render(<Loading />);
    const status = screen.getByRole("status");

    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent(OVERVIEW.LOADING);
  });
});
