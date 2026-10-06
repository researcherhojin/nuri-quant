import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RefreshDialog } from "@/app/dashboard-next/refresh-dialog";
import { summarizePortfolio } from "@/app/dashboard-next/portfolio-summary";
import { PortfolioPanel } from "@/app/dashboard-next/portfolio-panel";
import { PipelineStatus } from "@/app/dashboard-next/pipeline-status";
import { Inbox } from "@/app/dashboard-next/inbox";
import { DASHBOARD_NEXT } from "@/lib/strings";

const OPEN = DASHBOARD_NEXT.PIPELINE_PANEL.REFRESH;

const refresh = vi.hoisted(() => vi.fn());

const router = { refresh };

vi.mock("next/navigation", () => ({ useRouter: () => router }));

const job = { id: "technical", label: "기술 지표 재계산", keys: ["signals"], description: "저장된 주가 기준" };

const run = { id: "test-run", status: "running", jobs: [{ id: job.id, status: "running" }] };

const request = vi.fn();

let state: typeof run | null;

beforeEach(() => {
  vi.useFakeTimers(); state = null; refresh.mockReset();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };

  request.mockReset().mockImplementation(async (path, options) => {
    if (path === "/api/freshness") return { ok: true, json: async () => ({ pass: 1, warn: 1, fail: 1 }) };

    if (options?.method === "POST") { state = run;

 return { ok: true, json: async () => run }; }

    return { ok: true, json: async () => ({ jobs: [job], run: state }) };
  });
  vi.stubGlobal("fetch", request);
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("loads on demand, posts selected jobs only on action and rechecks freshness", async () => {
  render(<RefreshDialog delayedKeys={["signals"]} />);
  expect(request).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: OPEN })); });
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(request.mock.calls.every(([, options]) => options.method !== "POST")).toBe(true);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 데이터 갱신" })); });
  expect(request).toHaveBeenCalledWith("/api/pipeline/refresh", expect.objectContaining({ method: "POST", body: JSON.stringify({ jobs: ["technical"] }) }));
  expect(screen.getByRole("checkbox")).toBeDisabled();
  state = { ...run, status: "completed", jobs: [{ id: "technical", status: "completed" }] };
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText(/재확인: 정상 1 · 주의 1 · 지연 1/)).toBeInTheDocument();
  expect(refresh).toHaveBeenCalledTimes(1);
});

it("shows authorization failure without pretending a job started", async () => {
  render(<RefreshDialog delayedKeys={["signals"]} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: OPEN })); });
  request.mockResolvedValueOnce({ ok: false, status: 401 });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 데이터 갱신" })); });
  expect(screen.getByRole("alert")).toHaveTextContent("실행 권한이 필요합니다");
  expect(refresh).not.toHaveBeenCalled();
});

it("shows Decide artifacts separately from idle events and retains actual errors", async () => {
  request.mockRejectedValue(new Error("offline"));
  const step = { step: "decide", label: "Decide", status: "idle", last_updated: null, artifact: { status: "available", date: "2026-01-02", count: 3 } };
  const { rerender } = render(<PipelineStatus initial={{ steps: [step] }} />);
  await act(async () => {});
  expect(screen.getByRole("button", { name: "3건 기록" })).toBeInTheDocument();
  expect(screen.getByText("2026-01-02")).toBeInTheDocument();
  rerender(<PipelineStatus key="error" initial={{ steps: [{ ...step, status: "error" }] }} />);
  await act(async () => {});
  expect(screen.getByRole("button", { name: "실행 오류" })).toBeInTheDocument();
});

const portfolio = { holdings: [
  { ticker: "DEMO", account: "demo", sector: "Technology", quantity: 1, currency: "USD", latest_price: 100, price_date: "2026-01-01" },
  { ticker: "DEMO", account: "sample", sector: "Technology", quantity: 1, currency: "KRW", latest_price: 1000, price_date: "2026-01-02" },
], cash: { total_cash_usd: 100, accounts: [{ account: "demo", total_usd: 100 }] } };

it("merges duplicate tickers, converts KRW and includes cash in account weights", () => {
  const result = summarizePortfolio(portfolio, 10, "ticker");
  expect(result.total).toBe(300);
  expect(result.rows[0].value).toBe(200);
  expect(result.rows[0].weight).toBeCloseTo(200 / 3);
  expect(result.oldestPrice).toBe("2026-01-01");
  expect(summarizePortfolio(portfolio, 10, "account").rows[0]).toMatchObject({ label: "demo", value: 200 });
});

it("does not invent totals or weights when FX, prices or cash are missing", () => {
  for (const result of [summarizePortfolio(portfolio, null, "ticker"), summarizePortfolio({ ...portfolio, cash: { ...portfolio.cash, total_cash_usd: null } }, 10, "account"), summarizePortfolio({ ...portfolio, holdings: [{ ...portfolio.holdings[0], latest_price: null }] }, 10, "ticker")]) {
    expect(result.total).toBeNull();
    expect(result.rows.every(row => row.weight === null)).toBe(true);
  }
});

it("keeps every holding visible in the scrollable list and uses Korean names without merging identical names", () => {
  const holdings = Array.from({ length: 12 }, (_, i) => ({ ...portfolio.holdings[0], ticker: `TEST${i}.KS`, currency: "KRW", name: i < 2 ? "예시 기업" : `예시 펀드 ${i}` }));
  const data = { ...portfolio, holdings };
  const summary = summarizePortfolio(data, 10, "ticker");
  expect(summary.rows.filter(row => row.label === "예시 기업")).toHaveLength(2);
  expect(new Set(summary.rows.map(row => row.key)).size).toBe(13);
  render(<PortfolioPanel portfolio={data} exchangeRate={10} />);
  const list = screen.getByRole("region", { name: "전체 포트폴리오 비중 목록" });
  expect(list.children).toHaveLength(13);
  expect(list).toHaveTextContent("예시 펀드 11");
  expect(list).not.toHaveTextContent("TEST11.KS");
  expect(screen.getByText("전체 13개 구성 · 목록을 스크롤해 확인")).toBeInTheDocument();
  expect(screen.getByText("TEST11.KS")).toBeInTheDocument();
});

it("falls back to tickers for missing Korean names and preserves US symbols", () => {
  const data = { ...portfolio, holdings: [{ ...portfolio.holdings[0], name: "US Example" }, { ...portfolio.holdings[1], ticker: "TEST.KQ", name: " " }] };
  expect(summarizePortfolio(data, 10, "ticker").rows.map(row => row.label)).toEqual(expect.arrayContaining(["DEMO", "TEST.KQ"]));
});

it("retries the freshness recheck on the next poll when it fails once (Codex #1658 P2)", async () => {
  let freshnessCalls = 0;

  request.mockReset().mockImplementation(async (path, options) => {
    if (path === "/api/freshness") {
      freshnessCalls += 1;

      return freshnessCalls === 1 ? { ok: false, status: 500 } : { ok: true, json: async () => ({ pass: 2, warn: 0, fail: 0 }) };
    }

    if (options?.method === "POST") { state = run;

 return { ok: true, json: async () => run }; }

    return { ok: true, json: async () => ({ jobs: [job], run: state }) };
  });
  state = { ...run, status: "completed", jobs: [{ id: "technical", status: "completed" }] };
  render(<RefreshDialog delayedKeys={["signals"]} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: OPEN })); });
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(refresh).not.toHaveBeenCalled();
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(screen.getByText(/재확인: 정상 2 · 주의 0 · 지연 0/)).toBeInTheDocument();
  expect(refresh).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(refresh).toHaveBeenCalledTimes(1);
});

it("keeps a valid selection when a refreshed bucket shrinks below the selected index (Codex #1658 P2)", () => {
  const item = { ticker: "DEMO", action: "SELL", confidence: 70, reasons: ["첫 근거"], position_pct: null, pnl_pct: null };
  const two = { urgent: [item, { ...item, ticker: "SAMPLE", reasons: ["둘째 근거"] }], check: [], hold: [], portfolio: [] };
  const { rerender } = render(<Inbox actions={two} initialBucket="urgent" />);

  fireEvent.click(screen.getByRole("button", { name: /SAMPLE/ }));
  expect(screen.getByText("둘째 근거")).toBeInTheDocument();
  rerender(<Inbox actions={{ ...two, urgent: [item] }} initialBucket="urgent" />);
  expect(screen.getByText("첫 근거")).toBeInTheDocument();
  expect(screen.queryByText(/목록에 현재 표시할 항목이 없습니다/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /DEMO/ })).toHaveAttribute("aria-pressed", "true");
});
