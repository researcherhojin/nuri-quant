import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineStatus } from "@/app/dashboard-next/pipeline-status";

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
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

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
