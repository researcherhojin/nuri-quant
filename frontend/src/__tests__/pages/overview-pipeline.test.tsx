import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineStatus } from "@/app/(overview)/pipeline-status";
import styles from "@/app/(overview)/dashboard.module.css";

const initial = { steps: [{ step: "collect", label: "Collect", status: "done", last_updated: "2026-08-01 09:00:00" }] };

const updated = { steps: [{ ...initial.steps[0], status: "running", last_updated: "2026-10-06 09:00:00" }] };

let fail: boolean;

const request = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  fail = false;
  request.mockReset().mockImplementation(async (path: string) => {
    if (fail) throw new Error("offline");

    return { ok: true, json: async () => path === "/api/scheduler/health" ? { status: "unknown" } : updated };
  });
  vi.stubGlobal("fetch", request);
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("pipeline status refresh", () => {
  it("replaces the server snapshot with uncached status and shows the scheduler separately", async () => {
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(screen.getByText("실행 중")).toBeInTheDocument();
    expect(screen.getByText("스케줄러 확인 불가")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/api/pipeline/status", expect.objectContaining({ cache: "no-store" }));
    expect(request.mock.calls.every(([, options]) => !options.method || options.method === "GET")).toBe(true);
  });
  it("polls every minute and refreshes manually without running a job", async () => {
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => { vi.advanceTimersByTime(60000); });
    expect(request).toHaveBeenCalledTimes(4);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "파이프라인 상태 새로고침" })); });
    expect(request).toHaveBeenCalledTimes(6);
  });
  it("retains the last successful rows and marks failure instead of claiming fresh data", async () => {
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    fail = true;
    await act(async () => { vi.advanceTimersByTime(60000); });
    expect(screen.getByRole("status")).toHaveTextContent("갱신 실패 · 이전 기록 표시");
    expect(screen.getByText("실행 중")).toBeInTheDocument();
  });
  it("rejects soft error responses and stops polling after unmount", async () => {
    request.mockResolvedValue({ ok: true, json: async () => ({ error: "unavailable" }) });
    let unmount: () => void;
    await act(async () => { ({ unmount } = render(<PipelineStatus initial={initial} />)); });
    expect(within(screen.getByRole("region", { name: "파이프라인 실행 상태" })).getByText("성공 기록")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("갱신 실패");
    unmount!();
    await act(async () => { vi.advanceTimersByTime(60000); });
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe("pipeline status triggers", () => {
  it("skips polling while the tab is hidden and refreshes once it becomes visible", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");

    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(request).not.toHaveBeenCalled();
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(request).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(request).toHaveBeenCalledTimes(2);
  });
  it("ignores a stale request from a replayed effect that resolves after the newer one (StrictMode)", async () => {
    // StrictMode 는 effect 를 한 번 정리하고 다시 실행한다. abort 를 무시한 첫 요청이
    // 늦게 도착해도 정리된 effect 의 결과로 최신 행을 덮어쓰면 안 된다 (line 59 의 active 가드).
    const stale: Array<() => void> = [];

    request.mockImplementation((path: string) => {
      const body = path === "/api/scheduler/health" ? { status: "ok" } : path === "/api/pipeline/status" && stale.length < 2 ? initial : updated;

      if (stale.length < 2) return new Promise((resolve) => { stale.push(() => resolve({ ok: true, json: async () => body })); });

      return Promise.resolve({ ok: true, json: async () => body });
    });
    await act(async () => { render(<StrictMode><PipelineStatus initial={initial} /></StrictMode>); });
    expect(request).toHaveBeenCalledTimes(4);
    expect(screen.getByText("실행 중")).toBeInTheDocument();
    await act(async () => { stale.forEach((resolve) => resolve()); });
    expect(screen.getByText("실행 중")).toBeInTheDocument();
  });
  it("does not start a second request while one is still pending", async () => {
    let release: () => void = () => {};

    const gate = new Promise<void>((resolve) => { release = resolve; });

    request.mockImplementation(async (path: string) => {
      await gate;

      return { ok: true, json: async () => path === "/api/scheduler/health" ? { status: "ok" } : updated };
    });
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event("nuri-data-refreshed")); });
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => { release(); });
    await act(async () => { window.dispatchEvent(new Event("nuri-data-refreshed")); });
    expect(request).toHaveBeenCalledTimes(4);
  });
  it("aborts a hung request after ten seconds and reports the refresh as failed", async () => {
    const signals: AbortSignal[] = [];

    request.mockImplementation((_path: string, options: { signal: AbortSignal }) => new Promise((_resolve, reject) => {
      signals.push(options.signal);
      options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    }));
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(screen.getByRole("status")).toHaveTextContent("스케줄러 확인 중");
    await act(async () => { vi.advanceTimersByTime(10000); });
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("갱신 실패 · 이전 기록 표시");
  });
  it("treats a non-OK HTTP status as a failed refresh even if the body parses", async () => {
    request.mockImplementation(async (path: string) => ({ ok: path !== "/api/pipeline/status", json: async () => path === "/api/scheduler/health" ? { status: "ok" } : updated }));
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(screen.getByRole("status")).toHaveTextContent("갱신 실패");
    expect(screen.queryByText("실행 중")).not.toBeInTheDocument();
  });
  it("shows a healthy scheduler without the warning style and names unknown scheduler states", async () => {
    request.mockImplementation(async (path: string) => ({ ok: true, json: async () => path === "/api/scheduler/health" ? { status: "ok" } : updated }));
    const { unmount } = render(<PipelineStatus initial={initial} />);

    await act(async () => {});
    expect(styles.pipelineWarning).toBeTruthy();
    expect(screen.getByRole("status")).toHaveTextContent("스케줄러 정상");
    expect(screen.getByRole("status")).not.toHaveClass(styles.pipelineWarning);
    expect(screen.getByText(/^조회 \d{2}:\d{2} KST$/)).toBeInTheDocument();
    unmount();
    request.mockImplementation(async (path: string) => ({ ok: true, json: async () => path === "/api/scheduler/health" ? { status: "degraded" } : updated }));
    await act(async () => { render(<PipelineStatus initial={initial} />); });
    expect(screen.getByRole("status")).toHaveTextContent("스케줄러 degraded");
    expect(screen.getByRole("status")).toHaveClass(styles.pipelineWarning);
  });
});

describe("pipeline step labels", () => {
  const render0 = async (steps: object[]) => {
    request.mockRejectedValue(new Error("offline"));
    await act(async () => { render(<PipelineStatus initial={{ steps } as never} />); });
  };

  it("falls back to the backend label and raw status for stages and events it does not know", async () => {
    await render0([{ step: "backfill", label: "Backfill", status: "paused", last_updated: null }]);
    const panel = screen.getByRole("region", { name: "파이프라인 실행 상태" });

    expect(within(panel).getByText("Backfill")).toBeInTheDocument();
    expect(within(panel).getByText("paused")).toBeInTheDocument();
    expect(within(panel).getByText("기록 없음")).toBeInTheDocument();
  });
  it("asks for a check when the decide ledger artifact is missing, without inventing a date or count", async () => {
    await render0([{ step: "decide", label: "Decide", status: "paused", last_updated: null }]);
    expect(screen.getByRole("button", { name: "확인 필요" })).toBeInTheDocument();
    expect(screen.getByText("원장 미확인")).toBeInTheDocument();
    const dialog = screen.getByLabelText("판정 기록 상태");

    expect(within(dialog).getByText("최근 원장 기준일: 미확인 · 기록 —건")).toBeInTheDocument();
    expect(within(dialog).getByText(/^실행 이벤트: paused · /)).toBeInTheDocument();
  });
  it("shows every stage, decide included, in the same MM-DD HH:mm KST form (#1675)", async () => {
    await render0([
      { step: "collect", label: "Collect", status: "done", last_updated: "2026-10-07T05:45:00+09:00" },
      { step: "decide", label: "Decide", status: "idle", last_updated: null, artifact: { status: "available", date: "2026-10-06", count: 17, recorded_at: "2026-10-06T07:05:04+09:00" } },
    ]);
    const panel = screen.getByRole("region", { name: "파이프라인 실행 상태" });

    expect(within(panel).getByText("10-07 05:45")).toBeInTheDocument();
    expect(within(panel).getByText("10-06 07:05")).toBeInTheDocument();
    expect(within(panel).queryByText("2026-10-06")).not.toBeInTheDocument();
  });
  it("counts an available decide artifact with no count as zero records", async () => {
    await render0([{ step: "decide", label: "Decide", status: "done", last_updated: null, artifact: { status: "available", date: "2026-01-02", count: null } }]);
    expect(screen.getByRole("button", { name: "0건 기록" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("판정 기록 상태")).getByText(/^실행 이벤트: 성공 기록 · /)).toBeInTheDocument();
  });
});

