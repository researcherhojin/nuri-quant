import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import DashboardNext from "@/app/dashboard-next/page";
import Loading from "@/app/dashboard-next/loading";
import { readPanel, freshnessSchema } from "@/app/dashboard-next/data";
import { DASHBOARD_NEXT } from "@/lib/strings";
import { displayChange, displayShortTime, displayTime } from "@/app/dashboard-next/format";

const fetchAPI = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ fetchAPI }));

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard-next" }));

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
    expect(screen.getByRole("link", { name: DASHBOARD_NEXT.COMPARE })).toHaveAttribute("href", "/");
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
    expect(screen.getAllByText(DASHBOARD_NEXT.UNAVAILABLE).length).toBeGreaterThan(0);
    // 패널이 왜 사라졌는지는 서버 로그에 남는다 — 스키마 드리프트와 전송 실패를 구분해서 (Codex #1658 P2)
    const messages = warn.mock.calls.map(([message]) => String(message));

    expect(messages).toEqual(expect.arrayContaining([expect.stringContaining("/api/actions unavailable (schema)"), expect.stringContaining("/api/portfolio unavailable (transport)")]));
    warn.mockRestore();
  });
  it("labels price changes by period and never describes them as new decisions", async () => {
    responses["/api/opportunities"] = { opportunities: [{ ticker: "EXAMPLE", signal: null, score: null, verdict: "관망", verdict_level: "neutral", pros: [], cons: [], change_1d: 1.2, change_5d: null }] };
    await renderPage({});
    expect(screen.getByRole("columnheader", { name: "1일 변화" })).toBeInTheDocument();
    expect(screen.getAllByText("+1.2%")[0]).toBeInTheDocument();
    expect(screen.getByText(/신규 판단이나 판단 변경을 의미하지 않습니다/)).toBeInTheDocument();
    expect(screen.getByText(/개별 가격 관측 시각은 제공되지 않습니다/)).toBeInTheDocument();
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
    expect(within(market).queryByText(DASHBOARD_NEXT.METRICS.MACRO_UNAVAILABLE)).not.toBeInTheDocument();
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
    expect(within(market).getByText(DASHBOARD_NEXT.METRICS.MACRO_UNAVAILABLE)).toBeInTheDocument();
  });
  it("says unavailable when the verdict text is empty", async () => {
    responses["/api/dashboard"] = { ...dashboard, verdict: "" };
    await renderPage({});
    const summary = screen.getByRole("region", { name: "오늘의 확인 순서" });

    expect(within(summary).getByText(DASHBOARD_NEXT.UNAVAILABLE)).toBeInTheDocument();
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

    expect(within(sources).getByText(DASHBOARD_NEXT.UNAVAILABLE)).toBeInTheDocument();
    expect(within(sources).queryByText(DASHBOARD_NEXT.EMPTY)).not.toBeInTheDocument();
    warn.mockRestore();
  });
  it("colors falling and flat changes and lists the candidate's pros and cons", async () => {
    responses["/api/opportunities"] = { generated_at: "2026-01-01T00:00:00Z", opportunities: [{ ticker: "EXAMPLE", signal: "momentum", score: 70, verdict: "관심 — 추세 확인", verdict_level: "positive", pros: ["추세 유지"], cons: ["변동성 확대"], change_1d: -1.5, change_5d: 0 }] };
    await renderPage({});
    const row = screen.getByRole("rowheader", { name: "EXAMPLE" }).closest("tr")!;
    const cells = row.querySelectorAll("td[data-direction]");

    expect(cells[0]).toHaveAttribute("data-direction", "down");
    expect(cells[1]).toHaveAttribute("data-direction", "flat");
    const detail = screen.getByLabelText("EXAMPLE · 탐색 근거");

    expect(within(detail).getByText("추세 유지")).toBeInTheDocument();
    expect(within(detail).getByText("변동성 확대")).toBeInTheDocument();
    expect(within(detail).queryByText(DASHBOARD_NEXT.RADAR_PANEL.NO_PROS)).not.toBeInTheDocument();
    expect(within(detail).queryByText(DASHBOARD_NEXT.RADAR_PANEL.NO_CONS)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "관심" })).toBeInTheDocument();
  });
  it("says so when a candidate has no pros or cons", async () => {
    responses["/api/opportunities"] = { opportunities: [{ ticker: "EXAMPLE", signal: null, score: null, verdict: "관망", verdict_level: "neutral", pros: [], cons: [], change_1d: null, change_5d: null }] };
    await renderPage({});
    const detail = screen.getByLabelText("EXAMPLE · 탐색 근거");

    expect(within(detail).getByText(DASHBOARD_NEXT.RADAR_PANEL.NO_PROS)).toBeInTheDocument();
    expect(within(detail).getByText(DASHBOARD_NEXT.RADAR_PANEL.NO_CONS)).toBeInTheDocument();
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
    expect(within(screen.getByLabelText("시스템 알림")).getByText(DASHBOARD_NEXT.EMPTY)).toBeInTheDocument();
    cleanup();

    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    responses["/api/dashboard"] = { error: "unavailable" };
    await renderPage({});
    expect(within(screen.getByLabelText("시스템 알림")).getByText(DASHBOARD_NEXT.UNAVAILABLE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "시스템 알림 —" })).toBeInTheDocument();
    warn.mockRestore();
  });
});

describe("panel reader and loading state", () => {
  it("logs non-Error rejections as transport failures with their text", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    fetchAPI.mockRejectedValueOnce("offline");
    await expect(readPanel("/api/freshness", freshnessSchema)).resolves.toBeNull();
    expect(warn).toHaveBeenCalledWith("[dashboard-next] /api/freshness unavailable (transport): offline");
    warn.mockRestore();
  });
  it("announces loading as a busy status with the loading copy", () => {
    render(<Loading />);
    const status = screen.getByRole("status");

    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent(DASHBOARD_NEXT.LOADING);
  });
});

