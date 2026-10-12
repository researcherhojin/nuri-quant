/**
 * Pipeline page — direct PipelineNode rendering coverage (custom node component,
 * timeline payload rendering, gate conditions).
 *
 * Split from coverage-push-2.test.tsx (lines 296-414).
 *
 * NOTE: kept separate from pipeline-coverage.test.tsx (push-1 origin) — different
 * @xyflow/react mock shape (this file's mock provides memo + Handle returning a
 * div so the inner PipelineNode component is exercised; the other file's mock
 * intercepts at ReactFlow level).
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, act, waitFor, within } from "@testing-library/react";
import { PIPELINE as PL } from "@/lib/strings";
import type { ComponentType, ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("onboarding=true"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

// Override the xyflow mock to actually render PipelineNode
type FlowNode = { id: string; data?: { label?: ReactNode; [key: string]: unknown } };

type NodeTypesMap = Record<string, ComponentType<{ data?: FlowNode["data"] }>>;

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, nodeTypes, children }: {
    nodes?: FlowNode[];
    nodeTypes?: NodeTypesMap | (() => NodeTypesMap);
    children?: ReactNode;
  }) => {
    const types = typeof nodeTypes === "function" ? nodeTypes() : nodeTypes;
    const NodeComponent = types?.pipeline;

    return (
      <div data-testid="react-flow">
        {nodes?.map((n: FlowNode) => (
          NodeComponent
            ? <NodeComponent key={n.id} data={n.data} />
            : <div key={n.id}>{n.data?.label as ReactNode}</div>
        ))}
        {children}
      </div>
    );
  },
  Background: () => null,
  Controls: () => null,
  Handle: ({ type }: { type: string; position?: string }) => <div data-testid={`handle-${type}`} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  memo: <T extends { displayName?: string }>(fn: T): T => { (fn as { displayName?: string }).displayName = "PipelineNode";

 return fn; },
}));

vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

describe("Pipeline — PipelineNode rendering", () => {
  let fetchMock: Mock;

  // `GET /api/pipeline/status` 가 실제로 내보내는 5 스테이지 — 상태·나이 분기를 하나씩 맡는다
  const stepsWithAllStatuses = [
    { step: "collect", label: "Collect", description: "Collector jobs + external sources", record_count: 25000,
      last_updated: new Date(Date.now() - 30 * 60000).toISOString(), status: "done", started_at: null, error: null },
    { step: "analyze", label: "Analyze", description: "Factor composite", record_count: 0,
      last_updated: null, status: "idle", started_at: null, error: null },
    { step: "consensus", label: "Consensus", description: "10 agents weighted vote", record_count: 30,
      last_updated: new Date(Date.now() - 25 * 3600000).toISOString(), status: "error",
      started_at: null, error: "timeout: consensus failed after 60s" },
    { step: "decide", label: "Decide", description: "Decision record (in-memory hand-off)", record_count: 10,
      last_updated: new Date(Date.now() - 3600000).toISOString(), status: "running", started_at: "2026-04-01T10:00:00", error: null },
    { step: "track", label: "Track", description: "7–90d outcomes + alpha", record_count: 0,
      last_updated: "invalid-date", status: "done", started_at: null, error: null },
  ];

  const timelineWithPayloads = [
    { timestamp: "2026-04-01T10:05:00", event_type: "error", step: "consensus", payload: { stderr: "Process timed out" } },
    { timestamp: "2026-04-01T10:00:00", event_type: "start", step: "collect", payload: { command: "make collect" } },
    { timestamp: "2026-04-01T09:55:00", event_type: "success", step: "analyze", payload: { error: "minor" } },
    { timestamp: "2026-04-01T09:50:00", event_type: "success", step: "track", payload: { count: 5 } },
  ];

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/pipeline/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: stepsWithAllStatuses }) });
      }

      if (url.includes("/api/pipeline/timeline")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: timelineWithPayloads }) });
      }

      if (url.includes("/api/gate")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({
          collect: { phase: "collect", total: 2, passed: 2, score: 1, ready: true,
                     conditions: [
                       { id: "c1", phase: "collect", description: "Prices", passed: true, detail: "OK" },
                       { id: "c2", phase: "collect", description: "VIX", passed: false, detail: "stale" },
                     ] },
        }) });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders PipelineNode with all status types", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // 다섯 노드 전부 — 정규식 /Collect/ 하나로는 나머지가 사라져도 통과했다 (#1791)
    await waitFor(() => expect(screen.getByText("Collect")).toBeInTheDocument());

    for (const label of ["Analyze", "Consensus", "Decide", "Track"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    // 상태 → 테두리 색: done=ok(emerald) · idle 0건=warning(amber) · error(red) · running(blue)
    const border = (label: string) => screen.getByText(label).closest("div.relative")?.className ?? "";
    expect(border("Collect")).toContain("border-emerald-500/30");
    expect(border("Analyze")).toContain("border-amber-500/30");
    expect(border("Consensus")).toContain("border-red-500/30");
    expect(border("Decide")).toContain("border-blue-500/30");
    expect(border("Track")).toContain("border-emerald-500/30");

    // formatAge 분기 — 30분 전 · 기록 없음 · 25시간 전 · 1시간 전
    expect(screen.getByText("<1h ago")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
    expect(screen.getByText("1d ago")).toBeInTheDocument();
    expect(screen.getByText("1h ago")).toBeInTheDocument();
  });

  it("renders running node with animation + error node with message", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // 폴링한 running 스텝 1개 → 카운터. /실행 중/ 정규식은 정적 범례에도 걸려 공허하다
    await waitFor(() => expect(screen.getByText(`1${PL.RUNNING_SUFFIX}`)).toBeInTheDocument());

    // running 노드만 ping 애니메이션을 갖는다
    const pinging = Array.from(document.querySelectorAll(".animate-ping")).map(
      (el) => el.closest("div.relative")?.querySelector("p.font-bold")?.textContent,
    );

    expect(pinging).toEqual(["Decide"]);
    // 에러 노드는 API 가 준 사유를 보여준다 — 예전엔 error 를 넘기지 않아 늘 "unknown error" 였다
    expect(screen.getByText("timeout: consensus failed after 60s")).toBeInTheDocument();
    expect(screen.queryByText("unknown error")).toBeNull();
  });

  it("nodes carry no run button and the page never POSTs (#1778)", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // 노드가 실제로 렌더된 뒤에 본다 — 렌더 전이면 "버튼 0개" 가 공허하게 참이다
    await waitFor(() => expect(screen.getByText("timeout: consensus failed after 60s")).toBeInTheDocument());
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    await act(async () => { await vi.advanceTimersByTimeAsync(10_500); });
    const postCalls = fetchMock.mock.calls.filter((c: unknown[]) => (c[1] as RequestInit | undefined)?.method === "POST");
    expect(postCalls).toHaveLength(0);
  });

  it("renders timeline with stderr, command, error, and JSON payloads", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // 헤딩만 보면 이벤트가 하나도 안 그려져도 통과한다 — 요약 줄을 직접 본다 (#1791)
    await waitFor(() => expect(screen.getByText("Process timed out")).toBeInTheDocument());
    expect(screen.getByText("make collect")).toBeInTheDocument();
    expect(screen.getByText("minor")).toBeInTheDocument();
    expect(screen.getByText("count 5")).toBeInTheDocument();
  });

  it("renders gate conditions with pass/fail icons", async () => {
    vi.resetModules();
    const PipelinePage = (await import("@/app/pipeline/page-view")).default;
    await act(async () => { render(<PipelinePage />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });

    // 헤딩이 아니라 조건 행 — 행마다 통과 ✓ / 실패 ✗ 와 상세 (#1791)
    await waitFor(() => expect(screen.getByText("Prices")).toBeInTheDocument());
    const row = (description: string) => screen.getByText(description).closest("div.flex") as HTMLElement;
    expect(within(row("Prices")).getByText("\u2713")).toBeInTheDocument();
    expect(within(row("Prices")).getByText("OK")).toBeInTheDocument();
    expect(within(row("VIX")).getByText("\u2717")).toBeInTheDocument();
    expect(within(row("VIX")).getByText("stale")).toBeInTheDocument();
  });
});
