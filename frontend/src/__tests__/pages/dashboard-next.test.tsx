import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import DashboardNext from "@/app/dashboard-next/page";
import { DASHBOARD_NEXT } from "@/lib/strings";
import { displayTime } from "@/app/dashboard-next/format";

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
});
