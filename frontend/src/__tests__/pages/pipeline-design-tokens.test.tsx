/**
 * #1253 — pipeline 캔버스가 다크 토큰 시스템 안에 있는지.
 *
 * ReactFlow 는 SVG 속성이라 Tailwind 클래스가 안 먹는다. 그래서 raw hex 를 박아 뒀는데,
 * 그러면 이 파일만 토큰 시스템 밖에 남아 테마 변경이 여기를 비껴간다. 인라인 스타일이라
 * CSS 변수는 그대로 해석되므로 hex 를 쓸 이유가 없다.
 *
 * 잠금은 두 겹이다:
 *   - **동작** — 실제로 넘어가는 edge/background 값이 `var(--...)` 인가 (ReactFlow 를
 *     가로채 값을 그대로 본다)
 *   - **구조** — 파일에 hex 리터럴이 남지 않았는가 (동작 잠금은 EDGES/Background 만 보므로
 *     새 하드코딩 지점이 생기면 놓친다)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// ReactFlow 를 가로채 실제로 넘어온 edges / Background color 를 노출시킨다.
const captured: { edges: unknown[]; bgColor: unknown } = { edges: [], bgColor: undefined };

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ edges, children }: { edges: unknown[]; children: React.ReactNode }) => {
    captured.edges = edges;
    return <div data-testid="react-flow">{children}</div>;
  },
  Background: ({ color }: { color?: unknown }) => {
    captured.bgColor = color;
    return <div data-testid="flow-background" />;
  },
  Controls: () => <div data-testid="flow-controls" />,
  Handle: () => <div data-testid="handle" />,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

vi.mock("@/lib/api", () => ({ API_BASE: "http://localhost:8001", fetchAPI: vi.fn() }));

const PAGE_PATH = join(process.cwd(), "src/app/pipeline/page.tsx");
/** `#fff` / `#3f3f46` 형태의 색 리터럴. 문자열 안이든 JSX 속성이든 잡는다. */
const HEX_COLOR = /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b/g;

describe("pipeline 캔버스는 다크 토큰을 쓴다 (#1253)", () => {
  beforeEach(() => {
    captured.edges = [];
    captured.bgColor = undefined;
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    ) as unknown as typeof fetch;
  });
  afterEach(() => vi.restoreAllMocks());

  it("edge stroke 와 캔버스 점이 CSS 변수로 넘어간다", async () => {
    const PipelinePage = (await import("@/app/pipeline/page")).default;
    await act(async () => {
      render(<PipelinePage />);
    });

    expect(captured.edges.length).toBeGreaterThan(0);
    for (const e of captured.edges as { id: string; style?: { stroke?: string } }[]) {
      expect(e.style?.stroke, `edge ${e.id} 의 stroke`).toMatch(/^var\(--/);
    }
    expect(captured.bgColor).toMatch(/^var\(--/);
  });

  it("소스에 색 hex 리터럴이 남아 있지 않다", () => {
    const src = readFileSync(PAGE_PATH, "utf8");
    const found = src.match(HEX_COLOR) ?? [];
    expect(found, `raw hex 잔존: ${found.join(", ")}`).toHaveLength(0);
  });

  it("hex 스윕이 실제로 눈이 있다 (canary)", () => {
    // 정규식이 조용히 아무것도 안 잡으면 위 테스트는 영원히 초록이다.
    expect('style: { stroke: "#3f3f46" }'.match(HEX_COLOR)).toEqual(["#3f3f46"]);
    expect('<Background color="#27272a" />'.match(HEX_COLOR)).toEqual(["#27272a"]);
  });

  it("노드는 그림자·상태 글로우 없이 테두리와 점으로만 상태를 말한다", async () => {
    const { PipelineNode } = await import("@/app/pipeline/page");
    const { container } = render(
      <PipelineNode
        data={{
          label: "Collect", sub: "", status: "ok", recordCount: 1,
          lastUpdated: null, stepId: "collect", onRun: vi.fn(), isRunning: false,
        }}
      />
    );
    const root = container.querySelector("div.relative")!;
    // `shadow-` 접두사 전체를 막는다 — shadow-lg 만 지우고 글로우가 남는 절반 회귀를 잡는다.
    expect(root.className).not.toMatch(/\bshadow-/);
    expect(root.className).toContain("border-emerald-500/30"); // 상태는 테두리가 말한다
  });
});
