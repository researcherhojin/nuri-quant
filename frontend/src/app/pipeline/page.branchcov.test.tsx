/**
 * Pipeline page — BRANCH coverage (isolated 100%) for src/app/pipeline/page.tsx.
 *
 * 이 파일 단독 실행으로 page.tsx 의 모든 branch arm 을 커버한다.
 * (full-suite 기준 4개 미커버였으나, 단독 실행 시 기존 page.coverage.test.tsx 가
 *  커버하던 arm 들이 빠지므로 이 파일이 전부 자급해야 한다.)
 *
 * 전략:
 *  - PipelineNode 를 source export 후 직접 렌더 → node 본문의 모든 ternary/&& arm.
 *  - @xyflow/react mock 으로 nodeTypes.pipeline(실 PipelineNode) 렌더.
 *  - client PipelinePage + global fetch mock 으로 fetchStatus/Timeline/Gate +
 *    handleRunStep + getNodeStatus + 타임라인/게이트 렌더 분기.
 *  - formatAge/formatTimestamp 의 catch 는 new Date() 가 throw 하는 값(BigInt)으로 강제.
 *
 * BigInt 리터럴 금지(ES2017) → BigInt() 생성자 사용.
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ERRORS, PIPELINE as PL } from "@/lib/strings";
import type { ComponentType, ReactNode } from "react";

type FlowNode = { id: string; type?: string; data?: Record<string, unknown> };
type NodeTypesMap = Record<string, ComponentType<{ data?: FlowNode["data"] }>>;

// ReactFlow mock 이 실제 PipelineNode (nodeTypes.pipeline) 를 렌더하도록.
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    nodes,
    nodeTypes,
    children,
  }: {
    nodes?: FlowNode[];
    nodeTypes?: NodeTypesMap | (() => NodeTypesMap);
    children?: ReactNode;
  }) => {
    const types = typeof nodeTypes === "function" ? nodeTypes() : nodeTypes;
    const NodeComponent = types?.pipeline;
    return (
      <div data-testid="react-flow">
        {nodes?.map((n) =>
          NodeComponent ? (
            <NodeComponent key={n.id} data={n.data} />
          ) : (
            <div key={n.id}>{n.data?.label as ReactNode}</div>
          ),
        )}
        {children}
      </div>
    );
  },
  Background: () => null,
  Controls: () => null,
  Handle: ({ type }: { type: string; position?: string }) => <div data-testid={`handle-${type}`} />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

// new Date(x) 가 throw 하도록 — 잘못된 날짜 "문자열" 은 Invalid Date 일 뿐 throw 안 함.
// BigInt 는 new Date(bigint) 에서 TypeError 를 던져 catch 분기를 강제한다.
const throwingDate = BigInt(11) as unknown as string;

type NodeData = {
  label: string;
  sub: string;
  status: "ok" | "warning" | "error" | "running";
  recordCount: number;
  lastUpdated: string | null;
  stepId: string;
  onRun: (id: string) => void;
  isRunning: boolean;
  error?: string | null;
};

async function loadNode() {
  vi.resetModules();
  return (await import("@/app/pipeline/page")).PipelineNode;
}

describe("PipelineNode — node-body branch arms", () => {
  afterEach(() => vi.restoreAllMocks());

  const base = (over: Partial<NodeData>): NodeData => ({
    label: "Collect",
    sub: "subtitle",
    status: "ok",
    recordCount: 0,
    lastUpdated: null,
    stepId: "collect",
    onRun: vi.fn(),
    isRunning: false,
    ...over,
  });

  it("status falsy → STATUS_* fallback 'ok' (142 `|| \"ok\"`)", async () => {
    const PipelineNode = await loadNode();
    render(<PipelineNode data={base({ status: "" as unknown as "ok" })} />);
    const root = screen.getByText("Collect").closest("div.relative")!;
    expect(root.className).toContain("border-emerald-500/30");
    expect(root.className).toContain("shadow-emerald-500/10");
  });

  it("status running → animate-ping span renders (170 ternary true) + button running text (196/201 true)", async () => {
    const PipelineNode = await loadNode();
    const { container } = render(<PipelineNode data={base({ status: "running", isRunning: true })} />);
    // 170: status==="running" 이면 animate-ping span 렌더
    expect(container.querySelector(".animate-ping")).not.toBeNull();
    // 201: isRunning true → "실행 중..." 텍스트
    const btn = screen.getByRole("button");
    expect(btn.textContent).toContain("실행 중");
    // 196: isRunning true → cursor-wait 클래스
    expect(btn.className).toContain("cursor-wait");
  });

  it("status NOT running → no animate-ping (170 false) + idle button (196/201 false)", async () => {
    const PipelineNode = await loadNode();
    const { container } = render(<PipelineNode data={base({ status: "ok", isRunning: false })} />);
    expect(container.querySelector(".animate-ping")).toBeNull();
    const btn = screen.getByRole("button");
    expect(btn.textContent).toBe("실행");
    expect(btn.className).toContain("cursor-pointer");
  });

  it("isRunning false → click calls onRun (190 true arm)", async () => {
    const PipelineNode = await loadNode();
    const onRun = vi.fn();
    render(<PipelineNode data={base({ isRunning: false, onRun })} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onRun).toHaveBeenCalledWith("collect");
  });

  it("isRunning true → onClick handler's `if(!isRunning)` false-arm, onRun NOT called (190)", async () => {
    const PipelineNode = await loadNode();
    const onRun = vi.fn();
    render(<PipelineNode data={base({ isRunning: true, onRun })} />);
    const btn = screen.getByRole("button") as HTMLButtonElement;
    expect(btn).toBeDisabled();
    // 버튼이 disabled 라 fireEvent.click 은 핸들러를 안 탄다.
    //  React 가 DOM 노드에 붙여둔 실제 onClick prop 을 꺼내 직접 호출하면
    //  data.isRunning=true 상태로 핸들러 본문이 실행되어
    //  `if (!data.isRunning)` false-arm(implicit-else)을 정직하게 커버한다.
    const propsKey = Object.keys(btn).find((k) => k.startsWith("__reactProps$"));
    expect(propsKey).toBeTruthy();
    const handler = (btn as unknown as Record<string, { onClick?: (e: unknown) => void }>)[
      propsKey as string
    ].onClick;
    expect(handler).toBeTypeOf("function");
    handler!({ stopPropagation: () => {} });
    expect(onRun).not.toHaveBeenCalled();
  });

  it("status error → error <p> renders with error string (205 && true)", async () => {
    const PipelineNode = await loadNode();
    render(<PipelineNode data={base({ status: "error", error: "boom failed" })} />);
    expect(screen.getByText("boom failed")).toBeInTheDocument();
  });

  it("status error with null error → fallback 'unknown error' (206 `|| \"unknown error\"`)", async () => {
    const PipelineNode = await loadNode();
    render(<PipelineNode data={base({ status: "error", error: null })} />);
    expect(screen.getByText("unknown error")).toBeInTheDocument();
  });

  it("formatAge: lastUpdated null → 'N/A' (117 if !dateStr true)", async () => {
    const PipelineNode = await loadNode();
    render(<PipelineNode data={base({ lastUpdated: null })} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("formatAge: <1h ago (122 true)", async () => {
    const PipelineNode = await loadNode();
    const recent = new Date(Date.now() - 5 * 60 * 1000).toISOString(); // 5분 전
    render(<PipelineNode data={base({ lastUpdated: recent })} />);
    expect(screen.getByText("<1h ago")).toBeInTheDocument();
  });

  it("formatAge: Nh ago (123 true, 122 false)", async () => {
    const PipelineNode = await loadNode();
    const hrs = new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(); // 5시간 전
    render(<PipelineNode data={base({ lastUpdated: hrs })} />);
    expect(screen.getByText("5h ago")).toBeInTheDocument();
  });

  it("formatAge: Nd ago (122/123 false)", async () => {
    const PipelineNode = await loadNode();
    const days = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(); // 3일 전
    render(<PipelineNode data={base({ lastUpdated: days })} />);
    expect(screen.getByText("3d ago")).toBeInTheDocument();
  });

  it("formatAge: Date coercion throws → raw fallback (catch)", async () => {
    const PipelineNode = await loadNode();
    render(<PipelineNode data={base({ lastUpdated: throwingDate })} />);
    // catch 가 dateStr 을 그대로 반환 → "11" 텍스트
    expect(screen.getByText("11")).toBeInTheDocument();
  });
});

// ── PipelinePage (client) : fetch-driven 분기 ──
type Step = {
  step: string;
  label: string;
  description: string;
  record_count: number;
  last_updated: string | null;
  status: string;
  started_at: string | null;
  error: string | null;
};

function makeFetch(opts: {
  statusOk?: boolean;
  statusBody?: unknown;
  timelineOk?: boolean;
  timelineBody?: unknown;
  gateOk?: boolean;
  gateBody?: unknown;
  postBody?: unknown;
}): Mock {
  return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(opts.postBody ?? { ok: true }) });
    }
    if (url.includes("/api/pipeline/status")) {
      return Promise.resolve({
        ok: opts.statusOk ?? true,
        json: () => Promise.resolve(opts.statusBody),
      });
    }
    if (url.includes("/api/pipeline/timeline")) {
      return Promise.resolve({
        ok: opts.timelineOk ?? true,
        json: () => Promise.resolve(opts.timelineBody),
      });
    }
    if (url.includes("/api/gate")) {
      return Promise.resolve({
        ok: opts.gateOk ?? true,
        json: () => Promise.resolve(opts.gateBody),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function renderPage() {
  vi.resetModules();
  const PipelinePage = (await import("@/app/pipeline/page")).default;
  await act(async () => {
    render(<PipelinePage />);
  });
  // 초기 3개 fetch 의 마이크로태스크 체인 flush.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
}

describe("PipelinePage — fetch & render branch arms", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("empty payloads → default nodes + empty-state messages (244/262/272 false, 429/473 true, 369 false)", async () => {
    global.fetch = makeFetch({
      statusBody: {}, // data?.steps falsy → 244 false
      timelineBody: {}, // data?.events falsy → 262 false → timeline 비어있음
      gateBody: null, // data falsy → 272 false
    }) as unknown as typeof fetch;
    await renderPage();
    // DEFAULT_NODES 렌더 (steps.length === 0 분기) → "Collect" 라벨 존재
    await waitFor(() => expect(screen.getAllByText("Collect").length).toBeGreaterThan(0));
    // 타임라인 빈 상태 메시지 (timeline.length === 0 → NO_EVENTS / RUN_STEP_HINT)
    expect(screen.getByText(/이벤트 없음/)).toBeInTheDocument();
    // 게이트 빈 상태 — #1250 이후 "로딩 중" 이 아니라 "조건 없음". 성공 응답이 비었을
    // 뿐인데 영원히 로딩으로 보이던 게 원래 증상이다. 리터럴 대신 SSoT 를 쓴다.
    expect(screen.getByText(PL.GATE_EMPTY)).toBeInTheDocument();
    // 369: runningSteps.size === 0 → 실행 중 카운터 badge 없음
    expect(screen.queryByText(/개 실행 중/)).toBeNull();
  });

  it("status not ok → r.json() skipped, null (242 false arm) keeps default nodes", async () => {
    global.fetch = makeFetch({
      statusOk: false,
      statusBody: { steps: [] },
      timelineOk: false,
      gateOk: false,
    }) as unknown as typeof fetch;
    await renderPage();
    // status fetch 가 !ok → null → setSteps 안 됨 → DEFAULT_NODES
    await waitFor(() => expect(screen.getAllByText("Collect").length).toBeGreaterThan(0));
  });

  it("populated steps with running + idle(record>0/=0) (244/249 true, 321/323/325 both arms, 335 fallback)", async () => {
    const steps: Step[] = [
      {
        step: "collect",
        label: "Collect",
        description: "collectors",
        record_count: 100,
        last_updated: null,
        status: "running", // 249 true (running add) + getNodeStatus 321 true
        started_at: null,
        error: null,
      },
      {
        step: "validate",
        label: "Validate",
        description: "backtest",
        record_count: 0,
        last_updated: null,
        status: "error", // getNodeStatus 322 (error)
        started_at: null,
        error: "x",
      },
      {
        step: "classify",
        label: "Classify",
        description: "regime",
        record_count: 0,
        last_updated: null,
        status: "done", // getNodeStatus 323 (done → ok)
        started_at: null,
        error: null,
      },
      {
        step: "idle_zero",
        label: "IdleZero",
        description: "no records",
        record_count: 0,
        last_updated: null,
        status: "idle", // getNodeStatus 325 → record_count>0? false → warning
        started_at: null,
        error: null,
      },
      {
        step: "idle_pos",
        label: "IdlePos",
        description: "has records",
        record_count: 5,
        last_updated: null,
        status: "idle", // getNodeStatus 325 → record_count>0? true → ok
        started_at: null,
        error: null,
      },
      {
        step: "unknown_step",
        label: "Mystery",
        description: "no icon mapped",
        record_count: 7,
        last_updated: null,
        status: "done",
        started_at: null,
        error: null, // 335: STEP_ICONS["unknown_step"] undefined → "" fallback
      },
    ];
    global.fetch = makeFetch({ statusBody: { steps }, timelineBody: { events: [] }, gateBody: {} }) as unknown as typeof fetch;
    await renderPage();
    // 335 fallback: 아이콘 없는 라벨 "Mystery" 렌더
    await waitFor(() => expect(screen.getByText("Mystery")).toBeInTheDocument());
    // 369: runningSteps.size > 0 → 실행 중 카운터 badge 렌더 (running 스텝 존재 → "1개 실행 중")
    await waitFor(() => expect(screen.getByText(/개 실행 중/)).toBeInTheDocument());
    // getNodeStatus 분기 검증 — 각 라벨 존재
    expect(screen.getByText("IdleZero")).toBeInTheDocument();
    expect(screen.getByText("IdlePos")).toBeInTheDocument();
  });

  it("timeline events: all event_type variants + payload variants (442-457, 437 fallback)", async () => {
    const timelineBody = {
      events: [
        { timestamp: "2026-05-31T09:00:00Z", event_type: "success", step: "collect", payload: { stderr: "err output here" } }, // 442 success + 452 stderr true
        { timestamp: "2026-05-31T09:01:00Z", event_type: "error", step: "validate", payload: { command: "make x" } }, // 443 error + 454 command true
        { timestamp: "2026-05-31T09:02:00Z", event_type: "start", step: "classify", payload: { error: "boom" } }, // 444 start (else) + 456 error true
        { timestamp: "2026-05-31T09:03:00Z", event_type: "start", step: "diagnose", payload: { other: 1 } }, // 457 JSON.stringify else
        { timestamp: "2026-05-31T09:04:00Z", event_type: "weird", step: "recommend", payload: {} }, // 437 EVENT_ICONS fallback "•" ; payload {} truthy → JSON.stringify "{}"
        { timestamp: "2026-05-31T09:05:00Z", event_type: "success", step: "track", payload: null }, // 449 payload && false → no <p>
      ],
    };
    global.fetch = makeFetch({ statusBody: { steps: [] }, timelineBody, gateBody: {} }) as unknown as typeof fetch;
    await renderPage();
    // event row 렌더 확인 (stderr 텍스트)
    await waitFor(() => expect(screen.getByText("err output here")).toBeInTheDocument());
    expect(screen.getByText("make x")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    // EVENT_ICONS 폴백 — 미지 타입은 중립 Circle 아이콘 (F-003 #1237)
    expect(screen.getByTestId("event-icon-weird")).toBeInTheDocument();
  });

  it("StepIcon: 라이브 어휘가 사이드바 아이덴티티와 동일 아이콘 — Circle 폴백은 미지 스텝만 (F-003 #1237)", async () => {
    const { StepIcon } = await import("@/app/pipeline/page");
    const { BarChart3, Users, Cog, Search, MapPin } = await import("lucide-react");
    // 패리티 잠금 (codex #1238 P3): 기대 아이콘을 직접 렌더해 lucide-* 클래스를 비교 —
    // 이름 하드코딩 없이 "사이드바와 같은 아이콘" 계약 자체를 검증한다.
    const lucideClass = (el: Element | null) =>
      el?.getAttribute("class")?.split(" ").find((c) => c.startsWith("lucide-") && c !== "lucide");
    const PARITY: Array<[string, React.ComponentType]> = [
      ["collect", Search],
      ["analyze", BarChart3], // 사이드바 Signals
      ["consensus", Users], // 사이드바 Agents
      ["certify", Cog], // 사이드바 Certification Engine
      ["track", MapPin],
    ];
    for (const [step, Expected] of PARITY) {
      const want = render(<Expected />);
      const got = render(<StepIcon stepId={step} />);
      const wantClass = lucideClass(want.container.querySelector("svg"));
      expect(wantClass, `${step} 기대 클래스 추출 실패`).toBeTruthy();
      expect(lucideClass(got.container.querySelector("svg")), `${step} 아이콘 불일치`).toBe(wantClass);
      // 장식 아이콘 — AT 에 노출하지 않는다 (codex #1238 P3)
      expect(got.container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
      want.unmount();
      got.unmount();
    }
    const { container } = render(<StepIcon stepId="unknown-step" />);
    expect(lucideClass(container.querySelector("svg"))).toBe("lucide-circle");

    // EventIcon 도 같은 장식 계약 — 전 타입 aria-hidden (codex #1238 R2)
    const { EventIcon } = await import("@/app/pipeline/page");
    for (const type of ["start", "success", "error", "weird"]) {
      const ev = render(<EventIcon type={type} />);
      expect(ev.container.querySelector("svg")?.getAttribute("aria-hidden"), `${type} aria-hidden 누락`).toBe("true");
      ev.unmount();
    }
  });

  it("timeline timestamp coercion throws → formatTimestamp catch (136)", async () => {
    const timelineBody = {
      events: [{ timestamp: throwingDate, event_type: "success", step: "collect", payload: { command: "c" } }],
    };
    global.fetch = makeFetch({ statusBody: { steps: [] }, timelineBody, gateBody: {} }) as unknown as typeof fetch;
    await renderPage();
    // catch 가 iso(="11") 를 그대로 반환 → "11" 이 타임스탬프 span 에 렌더
    await waitFor(() => expect(screen.getByText("11")).toBeInTheDocument());
  });

  it("gate conditions: passed true & false (481/482/486/491 both arms, 473 false)", async () => {
    const gateBody = {
      collect: {
        phase: "collect",
        total: 2,
        passed: 1,
        score: 0.5,
        ready: false,
        conditions: [
          { id: "c1", phase: "collect", description: "Prices fresh", passed: true, detail: "OK detail" },
          { id: "c2", phase: "validate", description: "Backtest done", passed: false, detail: "FAIL detail" },
        ],
      },
    };
    global.fetch = makeFetch({ statusBody: { steps: [] }, timelineBody: { events: [] }, gateBody }) as unknown as typeof fetch;
    await renderPage();
    // 481/491 passed=true arm + passed=false arm 둘 다
    await waitFor(() => expect(screen.getByText("Prices fresh")).toBeInTheDocument());
    expect(screen.getByText("Backtest done")).toBeInTheDocument();
    expect(screen.getByText("OK detail")).toBeInTheDocument();
    expect(screen.getByText("FAIL detail")).toBeInTheDocument();
    // ✓ 와 ✗ 글리프 둘 다 (481 ternary)
    expect(screen.getByText("✓")).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
  });

  it("handleRunStep: POST returns error → alert + remove from running (298 true arm)", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    const steps: Step[] = [
      {
        step: "collect",
        label: "Collect",
        description: "c",
        record_count: 1,
        last_updated: null,
        status: "idle",
        started_at: null,
        error: null,
      },
    ];
    global.fetch = makeFetch({
      statusBody: { steps },
      timelineBody: { events: [] },
      gateBody: {},
      postBody: { error: "run failed" }, // 298: data.error truthy
    }) as unknown as typeof fetch;
    await renderPage();
    await waitFor(() => expect(screen.getByText("Collect")).toBeInTheDocument());
    // 실행 버튼 클릭 → POST → data.error → alert
    const btn = screen.getByRole("button");
    await act(async () => {
      fireEvent.click(btn);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    // F-002: 한국어 실패 프리픽스 + 원문
    expect(alertSpy).toHaveBeenCalledWith(`${ERRORS.RUN_FAILED_PREFIX}run failed`);
  });

  it("handleRunStep: POST success (298 false arm) schedules refresh", async () => {
    const steps: Step[] = [
      {
        step: "collect",
        label: "Collect",
        description: "c",
        record_count: 1,
        last_updated: null,
        status: "idle",
        started_at: null,
        error: null,
      },
    ];
    const fetchMock = makeFetch({
      statusBody: { steps },
      timelineBody: { events: [] },
      gateBody: {},
      postBody: { ok: true }, // 298: data.error falsy
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    await renderPage();
    await waitFor(() => expect(screen.getByText("Collect")).toBeInTheDocument());
    const btn = screen.getByRole("button");
    await act(async () => {
      fireEvent.click(btn);
    });
    // setTimeout(fetchStatus, 1000) 트리거
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "POST");
    expect(postCall).toBeTruthy();
  });

  it("10s interval re-fetches status+timeline (useEffect setInterval)", async () => {
    const fetchMock = makeFetch({ statusBody: { steps: [] }, timelineBody: { events: [] }, gateBody: {} });
    global.fetch = fetchMock as unknown as typeof fetch;
    await renderPage();
    const before = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });
});
