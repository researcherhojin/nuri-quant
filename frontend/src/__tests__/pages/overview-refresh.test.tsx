import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { RefreshDialog } from "@/app/(overview)/refresh-dialog";
import { summarizePortfolio } from "@/app/(overview)/portfolio-summary";
import { PortfolioPanel } from "@/app/(overview)/portfolio-panel";
import { PipelineStatus } from "@/app/(overview)/pipeline-status";
import { Inbox } from "@/app/(overview)/inbox";
import { DetailDialog } from "@/app/(overview)/detail-dialog";
import { OVERVIEW } from "@/lib/strings";

const OPEN = OVERVIEW.PIPELINE_PANEL.REFRESH;

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

  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event("close")); };

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
  expect(screen.getByText("01-02")).toBeInTheDocument(); // #1675 다른 스테이지와 같은 MM-DD 축
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

describe("refresh dialog requests", () => {
  const openDialog = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: OPEN })); }); };

  it.each([[403, "실행 권한이 필요합니다"], [409, "이미 갱신 작업이 실행 중입니다"], [500, "갱신 요청을 처리하지 못했습니다"]])("maps a %i start response to its own message", async (status, message) => {
    render(<RefreshDialog delayedKeys={["signals"]} />);
    await openDialog();
    request.mockResolvedValueOnce({ ok: false, status });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 데이터 갱신" })); });
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("checkbox")).toBeEnabled();
  });
  it("reports an unreadable start response instead of claiming the job started", async () => {
    render(<RefreshDialog delayedKeys={["signals"]} />);
    await openDialog();
    request.mockResolvedValueOnce({ ok: true, json: async () => ({ unexpected: true }) });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 데이터 갱신" })); });
    expect(screen.getByRole("alert")).toHaveTextContent("서버 응답을 확인하지 못했습니다");
    expect(screen.queryByText(/최근 요청/)).not.toBeInTheDocument();
  });
  it("shows a poll error on a non-OK catalog response and clears it on the next successful poll", async () => {
    // 본문은 유효한 카탈로그여도 HTTP 상태가 실패면 신뢰하지 않는다
    request.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ jobs: [job], run: null }) });
    render(<RefreshDialog />);
    await openDialog();
    expect(screen.getByRole("alert")).toHaveTextContent("갱신 상태를 확인하지 못했습니다");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
  it("lets the user toggle jobs, and disables start when nothing is selected", async () => {
    render(<RefreshDialog delayedKeys={["signals"]} />);
    await openDialog();
    const start = screen.getByRole("button", { name: "선택한 데이터 갱신" });

    expect(start).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(start).toBeEnabled();
  });
  it("warns only when a delayed source has no job that refreshes it", async () => {
    render(<RefreshDialog delayedKeys={["signals"]} />);
    await openDialog();
    expect(screen.queryByText(/직접 갱신하지 않습니다/)).not.toBeInTheDocument();
    cleanup();
    render(<RefreshDialog delayedKeys={["signals", "filings"]} />);
    await openDialog();
    expect(screen.getByText(/직접 갱신하지 않습니다/)).toBeInTheDocument();
  });
  it("shows a run status it has no label for verbatim", async () => {
    state = { ...run, status: "cancelled", jobs: [] };
    render(<RefreshDialog />);
    await openDialog();
    expect(screen.getByText("최근 요청 · cancelled")).toBeInTheDocument();
  });
});

describe("refresh dialog after unmount", () => {
  const openDialog = async () => { await act(async () => { fireEvent.click(screen.getByRole("button", { name: OPEN })); }); };

  it("does not recheck freshness when a completed run arrives after the dialog unmounted", async () => {
    let resolveCatalog: (value: unknown) => void = () => {};

    request.mockReset().mockImplementation(() => new Promise((resolve) => { resolveCatalog = resolve; }));
    const { unmount } = render(<RefreshDialog />);

    await openDialog();
    unmount();
    await act(async () => { resolveCatalog({ ok: true, json: async () => ({ jobs: [job], run: { ...run, status: "completed" } }) }); });
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(request).toHaveBeenCalledTimes(1);
    expect(refresh).not.toHaveBeenCalled();
  });
  it("does not refresh the page when the freshness recheck finishes after unmount", async () => {
    let resolveFreshness: (value: unknown) => void = () => {};

    const listener = vi.fn();

    window.addEventListener("nuri-data-refreshed", listener);
    onTestFinished(() => window.removeEventListener("nuri-data-refreshed", listener));
    request.mockReset().mockImplementation(async (path: string) => path === "/api/freshness"
      ? new Promise((resolve) => { resolveFreshness = resolve; })
      : { ok: true, json: async () => ({ jobs: [job], run: { ...run, status: "completed" } }) });
    const { unmount } = render(<RefreshDialog />);

    await openDialog();
    expect(request).toHaveBeenCalledWith("/api/freshness", expect.anything());
    unmount();
    await act(async () => { resolveFreshness({ ok: true, json: async () => ({ pass: 1, warn: 0, fail: 0 }) }); });
    expect(refresh).not.toHaveBeenCalled();
    expect(listener).not.toHaveBeenCalled();
  });
  it("stops polling once the dialog closes, and resumes when reopened", async () => {
    request.mockReset().mockImplementation((_path: string, options: { signal: AbortSignal }) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    }));
    render(<RefreshDialog />);
    await openDialog();
    expect(request).toHaveBeenCalledTimes(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "닫기" })); });
    expect(screen.queryByText(OVERVIEW.REFRESH_DIALOG.LOADING)).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(request).toHaveBeenCalledTimes(1);
    await openDialog();
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe("detail dialog", () => {
  const rect = { left: 10, right: 110, top: 10, bottom: 110, width: 100, height: 100, x: 10, y: 10, toJSON: () => ({}) };

  it("opens on demand and closes from the close button", () => {
    render(<DetailDialog label="설명" title="설명 팝업"><p>본문</p></DetailDialog>);
    const dialog = screen.getByLabelText("설명 팝업") as HTMLDialogElement;

    expect(dialog.open).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "설명" }));
    expect(dialog.open).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "닫기" }));
    expect(dialog.open).toBe(false);
  });
  it.each([[5, 50], [200, 50], [50, 5], [50, 200]])("closes on a backdrop click outside the box at (%i, %i)", (clientX, clientY) => {
    render(<DetailDialog label="설명" title="설명 팝업"><p>본문</p></DetailDialog>);
    const dialog = screen.getByLabelText("설명 팝업") as HTMLDialogElement;

    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue(rect);
    fireEvent.click(screen.getByRole("button", { name: "설명" }));
    fireEvent.click(dialog, { clientX, clientY });
    expect(dialog.open).toBe(false);
  });
  it("stays open for clicks on its own padding or on its content", () => {
    render(<DetailDialog label="설명" title="설명 팝업"><p>본문</p></DetailDialog>);
    const dialog = screen.getByLabelText("설명 팝업") as HTMLDialogElement;

    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue(rect);
    fireEvent.click(screen.getByRole("button", { name: "설명" }));
    fireEvent.click(dialog, { clientX: 50, clientY: 50 });
    expect(dialog.open).toBe(true);
    fireEvent.click(within(dialog).getByText("본문"), { clientX: 5, clientY: 5 });
    expect(dialog.open).toBe(true);
  });
  it("renders lazy content only while open", () => {
    render(<DetailDialog label="설명" title="설명 팝업" lazy><p>지연 본문</p></DetailDialog>);
    expect(screen.queryByText("지연 본문")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "설명" }));
    expect(screen.getByText("지연 본문")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByText("지연 본문")).not.toBeInTheDocument();
  });
});

describe("inbox evidence", () => {
  const base = { ticker: "DEMO", action: "TRIM", confidence: 60, reasons: [], position_pct: 10, pnl_pct: null };

  it("tones each bucket's badge and shows the account next to the ticker", () => {
    const actions = { urgent: [{ ...base, action: "SELL" }], check: [{ ...base, action: "REVIEW", account: "demo-account" }], hold: [{ ...base, action: "HOLD" }], portfolio: [{ ...base, action: "REBALANCE" }] };

    render(<Inbox actions={actions} initialBucket="urgent" />);
    const badge = (action: string) => screen.getByText(action, { selector: "[data-tone]" });

    expect(badge("SELL")).toHaveAttribute("data-tone", "danger");
    fireEvent.click(screen.getByRole("button", { name: /^검토/ }));
    expect(badge("REVIEW")).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByText("DEMO · demo-account")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^포트폴리오 규칙/ }));
    expect(badge("REBALANCE")).toHaveAttribute("data-tone", "warning");
    fireEvent.click(screen.getByRole("button", { name: /^유지/ }));
    expect(badge("HOLD")).toHaveAttribute("data-tone", "neutral");
  });
  it("says reasons are missing rather than rendering an empty list", () => {
    render(<Inbox actions={{ urgent: [base], check: [], hold: [], portfolio: [] }} initialBucket="urgent" />);
    expect(screen.getByText("판단 근거 미제공")).toBeInTheDocument();
  });
  it.each([[12, "up"], [-12, "down"], [0, "flat"]])("marks a P&L of %i as %s", (pnl, direction) => {
    render(<Inbox actions={{ urgent: [{ ...base, pnl_pct: pnl }], check: [], hold: [], portfolio: [] }} initialBucket="urgent" />);
    const evidence = screen.getByRole("article", { name: "선택한 판단 근거" });

    expect(within(evidence).getByText("평가 손익률").nextElementSibling).toHaveAttribute("data-direction", direction);
  });
});

describe("portfolio panel edge cases", () => {
  const holding = portfolio.holdings[0];

  it("labels an all-zero portfolio as empty and skips zero-weight segments", () => {
    const { container } = render(<PortfolioPanel portfolio={{ holdings: [{ ...holding, quantity: 0 }], cash: { total_cash_usd: 0, accounts: [] } }} exchangeRate={10} />);

    expect(screen.getByRole("img", { name: "평가 자산 없음" })).toBeInTheDocument();
    expect(container.querySelectorAll("svg circle")).toHaveLength(1);
  });
  it("draws only positive-weight segments when one component is zero", () => {
    const { container } = render(<PortfolioPanel portfolio={{ holdings: [holding], cash: { total_cash_usd: 0, accounts: [] } }} exchangeRate={10} />);

    expect(screen.getByRole("img", { name: "포트폴리오 구성 비중 도넛 차트" })).toBeInTheDocument();
    expect(container.querySelectorAll("svg circle")).toHaveLength(2);
    expect(within(screen.getByRole("region", { name: "전체 포트폴리오 비중 목록" })).getByText("0.0%")).toBeInTheDocument();
  });
  it("shows unknown weights and the price date range when totals cannot be computed", () => {
    render(<PortfolioPanel portfolio={portfolio} exchangeRate={null} />);
    const legend = screen.getByRole("region", { name: "전체 포트폴리오 비중 목록" });

    expect(screen.getByRole("img", { name: "포트폴리오 비중 산출 불가" })).toBeInTheDocument();
    expect(within(legend).getAllByText("—").length).toBeGreaterThan(0);
    const basis = screen.getByLabelText("포트폴리오 구성과 평가 기준");

    expect(within(basis).getAllByText("비중 미상").length).toBeGreaterThan(0);
    expect(within(basis).getByText(/2026-01-01 ~ 2026-01-02/)).toBeInTheDocument();
  });
  it("groups holdings without a sector as unclassified", () => {
    const rows = summarizePortfolio({ ...portfolio, holdings: [{ ...holding, sector: null }, holding] }, 10, "sector").rows;

    expect(rows.map((row) => row.label)).toEqual(expect.arrayContaining(["미분류", "Technology"]));
  });
});

