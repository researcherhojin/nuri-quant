/**
 * #1250 — 파이프라인 3개 fetch 의 로딩 · 없음 · 실패 3-state 잠금.
 *
 * 이전 동작: `.catch(() => {})` 가 실패를 삼켜 상태가 초기값(빈 배열)에 머물렀고,
 * 화면은 그걸 "아직 이벤트 없음" / "게이트 조건 로딩 중..." 으로 렌더했다.
 * 운영자 터미널에서 **"백엔드 죽음" 과 "데이터 없음" 이 같은 픽셀**인 건 오판을 부른다
 * (배포 검증 사례와 같은 축: 헬스는 초록인데 실경로가 죽어 있음).
 *
 * 여기서 잠그는 성질은 셋이다:
 *   (a) 실패가 빈 화면으로 접히지 않는다
 *   (b) 빈 화면이 실패로 오해되지 않는다 (대조군)
 *   (c) 재시도가 실제로 복구한다
 */
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ERRORS, PIPELINE as PL } from "@/lib/strings";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, children }: { nodes: unknown[]; children: React.ReactNode }) => (
    <div data-testid="react-flow">
      <div data-testid="flow-nodes">{nodes.length} nodes</div>
      {children}
    </div>
  ),
  Background: () => <div data-testid="flow-background" />,
  Controls: () => <div data-testid="flow-controls" />,
  Handle: () => <div data-testid="handle" />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

vi.mock("@/lib/api", () => ({ API_BASE: "http://localhost:8001", fetchAPI: vi.fn() }));

const okSteps = [
  { step: "collect", label: "Collect", description: "", record_count: 10, last_updated: null, status: "done", started_at: null, error: null },
];

const okGates = {
  collect: {
    phase: "collect", total: 1, passed: 1, score: 1.0, ready: true,
    conditions: [{ id: "c1", phase: "collect", description: "Prices available", passed: true, detail: "OK" }],
  },
};

/** 한 엔드포인트만 지정한 방식으로 실패시키고 나머지는 정상 응답. */
function makeFetch(opts: {
  statusMode?: "ok" | "reject" | "http500";
  timelineMode?: "ok" | "reject" | "http500" | "empty";
  gateMode?: "ok" | "reject" | "http500" | "empty";
}): Mock {
  const { statusMode = "ok", timelineMode = "ok", gateMode = "ok" } = opts;

  const reply = (mode: string, body: unknown) => {
    if (mode === "reject") return Promise.reject(new Error("network down"));

    // ⚠️ HTTP 실패도 반드시 별도 축으로 잠근다 — `r.ok ? json : …` 는 reject 와 다른
    // 코드 경로다. reject 만 테스트하면 `r.ok` 분기를 되돌려도 초록이다.
    if (mode === "http500") return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });

    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  };

  return vi.fn().mockImplementation((url: string) => {
    if (url.includes("/api/pipeline/status")) return reply(statusMode, { steps: okSteps });

    if (url.includes("/api/pipeline/timeline")) {
      return reply(timelineMode === "empty" ? "ok" : timelineMode, { events: [] });
    }

    if (url.includes("/api/gate")) return reply(gateMode === "empty" ? "ok" : gateMode, gateMode === "empty" ? {} : okGates);

    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

async function renderPage() {
  const PipelinePage = (await import("@/app/pipeline/page-view")).default;
  await act(async () => {
    render(<PipelinePage />);
  });
}

describe("파이프라인 fetch 3-state (#1250)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe("(a) 실패가 빈 화면으로 접히지 않는다", () => {
    it.each(["reject", "http500"] as const)("타임라인 실패(%s)는 '없음' 이 아니라 실패로 렌더한다", async (mode) => {
      global.fetch = makeFetch({ timelineMode: mode }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_TIMELINE_FAILED)).toBeInTheDocument();
      });
      // 핵심 단언 — 이게 이전 동작이었다.
      expect(screen.queryByText(new RegExp(PL.NO_EVENTS))).not.toBeInTheDocument();
    });

    it.each(["reject", "http500"] as const)("게이트 실패(%s)는 '로딩 중' 에 머무르지 않는다", async (mode) => {
      global.fetch = makeFetch({ gateMode: mode }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_GATE_FAILED)).toBeInTheDocument();
      });
      expect(screen.queryByText(PL.GATE_LOADING)).not.toBeInTheDocument();
    });

    it("상태 실패는 DAG 를 지우지 않고 배너로 알린다", async () => {
      global.fetch = makeFetch({ statusMode: "reject" }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_STATUS_FAILED)).toBeInTheDocument();
      });
      // 화면을 비우면 "파이프라인이 비었다" 는 더 나쁜 거짓말이 된다.
      expect(screen.getByTestId("react-flow")).toBeInTheDocument();
    });

    it("실패 패널은 role=alert 로 노출된다", async () => {
      global.fetch = makeFetch({ timelineMode: "reject" }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
      });
    });
  });

  describe("(b) 대조군 — 빈 데이터는 실패가 아니다", () => {
    it("타임라인이 비면 '아직 이벤트 없음'", async () => {
      global.fetch = makeFetch({ timelineMode: "empty" }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(new RegExp(PL.NO_EVENTS))).toBeInTheDocument();
      });
      expect(screen.queryByText(ERRORS.PIPELINE_TIMELINE_FAILED)).not.toBeInTheDocument();
    });

    it("게이트가 비면 '로딩 중' 이 아니라 '조건 없음'", async () => {
      global.fetch = makeFetch({ gateMode: "empty" }) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(PL.GATE_EMPTY)).toBeInTheDocument();
      });
      // 성공했는데 영원히 "로딩 중" 이던 게 원래 증상이다.
      expect(screen.queryByText(PL.GATE_LOADING)).not.toBeInTheDocument();
    });

    it("정상 응답에는 어떤 실패 패널도 없다", async () => {
      global.fetch = makeFetch({}) as unknown as typeof fetch;
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText("Prices available")).toBeInTheDocument();
      });
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("(c) 겹친 폴링 — 늦게 도착한 응답은 화면을 바꾸지 않는다 (codex P2)", () => {
    it("poll N+1 성공 뒤 도착한 poll N 실패가 화면을 에러로 뒤집지 않는다", async () => {
      // 10초 폴링이라 느린 요청이 다음 요청과 겹친다. 응답 순서는 보장되지 않는다.
      let rejectFirst: (e: Error) => void = () => {};

      let timelineCalls = 0;
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/api/pipeline/timeline")) {
          timelineCalls += 1;

          if (timelineCalls === 1) {
            // 1번째: 아직 미결. 2번째가 성공한 **뒤에** 실패시킨다.
            return new Promise((_res, rej) => {
              rejectFirst = rej;
            });
          }

          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [] }) });
        }

        if (url.includes("/api/pipeline/status")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: okSteps }) });
        }

        return Promise.resolve({ ok: true, json: () => Promise.resolve(okGates) });
      }) as unknown as typeof fetch;

      await renderPage();
      // 10초 인터벌 → 2번째 타임라인 폴 발사 + 성공
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await waitFor(() => {
        expect(screen.getByText(new RegExp(PL.NO_EVENTS))).toBeInTheDocument();
      });
      expect(timelineCalls).toBe(2);

      // 이제서야 1번째가 실패한다 — 이미 화면엔 더 새로운 성공 결과가 있다.
      await act(async () => {
        rejectFirst(new Error("slow request died"));
      });

      // Mutation lock: 토큰 검사를 지우면 여기서 에러 패널이 뜬다.
      expect(screen.queryByText(ERRORS.PIPELINE_TIMELINE_FAILED)).not.toBeInTheDocument();
      expect(screen.getByText(new RegExp(PL.NO_EVENTS))).toBeInTheDocument();
    });

    // 나머지 다섯 조합 — 엔드포인트(상태·타임라인·게이트) × 늦게 온 결과(성공·실패). 늦은 응답은
    // 새 응답과 **다른 데이터**를 실어야 한다: 같으면 토큰 검사를 지워도 화면이 그대로라 잠금이 아니다.
    const ok = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

    function held() {
      const handle: { resolve: (body: unknown) => void; reject: (error: Error) => void } = { resolve: () => {}, reject: () => {} };

      const promise = new Promise((resolve, reject) => {
        handle.resolve = (body) => resolve({ ok: true, json: () => Promise.resolve(body) });
        handle.reject = reject;
      });

      return { promise, handle };
    }

    /** 엔드포인트별 응답 순서. 함수는 호출 차수(1부터)를 받는다. */
    function sequence(routes: { status?: (n: number) => unknown; timeline?: (n: number) => unknown; gate?: (n: number) => unknown }) {
      const calls = { status: 0, timeline: 0, gate: 0 };

      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/api/pipeline/status")) return routes.status ? routes.status(++calls.status) : ok({ steps: okSteps });

        if (url.includes("/api/pipeline/timeline")) return routes.timeline ? routes.timeline(++calls.timeline) : ok({ events: [] });

        return routes.gate ? routes.gate(++calls.gate) : ok(okGates);
      }) as unknown as typeof fetch;
    }

    const lateSteps = [
      { ...okSteps[0], step: "late-a", label: "Late A" },
      { ...okSteps[0], step: "late-b", label: "Late B" },
    ];

    it("poll N+1 상태 실패 뒤 도착한 poll N 성공이 배너를 지우거나 노드를 바꾸지 않는다", async () => {
      const first = held();

      sequence({ status: (n) => (n === 1 ? first.promise : Promise.reject(new Error("network down"))) });
      await renderPage();
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_STATUS_FAILED)).toBeInTheDocument();
      });
      const nodes = screen.getByTestId("flow-nodes").textContent;

      await act(async () => {
        first.handle.resolve({ steps: lateSteps });
      });
      expect(screen.getByText(ERRORS.PIPELINE_STATUS_FAILED)).toBeInTheDocument();
      expect(screen.getByTestId("flow-nodes").textContent).toBe(nodes);
      expect(nodes).not.toBe(`${lateSteps.length} nodes`);
    });

    it("poll N+1 상태 성공 뒤 도착한 poll N 실패가 배너를 띄우지 않는다", async () => {
      const first = held();

      sequence({ status: (n) => (n === 1 ? first.promise : ok({ steps: okSteps })) });
      await renderPage();
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await waitFor(() => {
        expect(screen.getByTestId("flow-nodes")).toHaveTextContent(`${okSteps.length} nodes`);
      });
      await act(async () => {
        first.handle.reject(new Error("slow request died"));
      });
      expect(screen.queryByText(ERRORS.PIPELINE_STATUS_FAILED)).not.toBeInTheDocument();
    });

    it("poll N+1 타임라인 실패 뒤 도착한 poll N 성공이 실패 패널을 지우지 않는다", async () => {
      const first = held();

      sequence({ timeline: (n) => (n === 1 ? first.promise : Promise.reject(new Error("network down"))) });
      await renderPage();
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_TIMELINE_FAILED)).toBeInTheDocument();
      });
      await act(async () => {
        first.handle.resolve({ events: [{ timestamp: "2026-01-01T00:00:00Z", event_type: "success", step: "late-step", payload: null }] });
      });
      expect(screen.getByText(ERRORS.PIPELINE_TIMELINE_FAILED)).toBeInTheDocument();
      expect(screen.queryByText("late-step")).not.toBeInTheDocument();
    });

    // 게이트는 폴링하지 않는다 — 겹친 요청은 재시도 버튼을 두 번 눌렀을 때 생긴다(실패 상태에서 버튼이 남아 있다).
    it("두 번째 재시도 실패 뒤 도착한 첫 재시도 성공이 게이트를 바꾸지 않는다", async () => {
      const retry = held();

      sequence({ gate: (n) => (n === 2 ? retry.promise : Promise.reject(new Error("network down"))) });
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_GATE_FAILED)).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: ERRORS.RETRY }));
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: ERRORS.RETRY }));
      });
      await act(async () => {
        retry.handle.resolve(okGates);
      });
      expect(screen.getByText(ERRORS.PIPELINE_GATE_FAILED)).toBeInTheDocument();
      expect(screen.queryByText("Prices available")).not.toBeInTheDocument();
    });

    it("두 번째 재시도 성공 뒤 도착한 첫 재시도 실패가 게이트를 실패로 뒤집지 않는다", async () => {
      const retry = held();

      sequence({ gate: (n) => (n === 1 ? Promise.reject(new Error("network down")) : n === 2 ? retry.promise : ok(okGates)) });
      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_GATE_FAILED)).toBeInTheDocument();
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: ERRORS.RETRY }));
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: ERRORS.RETRY }));
      });
      await waitFor(() => {
        expect(screen.getByText("Prices available")).toBeInTheDocument();
      });
      await act(async () => {
        retry.handle.reject(new Error("slow retry died"));
      });
      expect(screen.queryByText(ERRORS.PIPELINE_GATE_FAILED)).not.toBeInTheDocument();
      expect(screen.getByText("Prices available")).toBeInTheDocument();
    });
  });

  describe("(d) 재시도가 복구한다", () => {
    it("재시도 버튼이 다시 fetch 해 게이트 조건을 표시한다", async () => {
      let gateCalls = 0;
      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes("/api/gate")) {
          gateCalls += 1;

          return gateCalls === 1
            ? Promise.reject(new Error("network down"))
            : Promise.resolve({ ok: true, json: () => Promise.resolve(okGates) });
        }

        if (url.includes("/api/pipeline/status")) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ steps: okSteps }) });
        }

        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [] }) });
      }) as unknown as typeof fetch;

      await renderPage();
      await waitFor(() => {
        expect(screen.getByText(ERRORS.PIPELINE_GATE_FAILED)).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: ERRORS.RETRY }));
      });

      await waitFor(() => {
        expect(screen.getByText("Prices available")).toBeInTheDocument();
      });
      expect(screen.queryByText(ERRORS.PIPELINE_GATE_FAILED)).not.toBeInTheDocument();
      expect(gateCalls).toBe(2);
    });
  });
});
