import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock next/link — 반드시 전체 props spread (#1218: children/href 만 넘기면 data-testid 소실)
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

// Mock fetchAPI
const mockFetchAPI = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchAPI: (...args: unknown[]) => mockFetchAPI(...args),
  API_BASE: "http://localhost:8001",
}));

// Mock child components that are client components
vi.mock("@/components/ui/client-table", () => ({
  ClientTable: ({ variant, data }: { variant: string; data: unknown[] }) => (
    <div data-testid={`client-table-${variant}`}>{data.length} rows</div>
  ),
}));

const mockGateData: Record<string, unknown> = {
  collect: {
    phase: "collect",
    total: 3,
    passed: 3,
    score: 1.0,
    ready: true,
    conditions: [
      { id: "c1", phase: "collect", description: "Prices fresh", passed: true, detail: "Updated 2h ago" },
      { id: "c2", phase: "collect", description: "VIX available", passed: true, detail: "VIX = 18.5" },
      { id: "c3", phase: "collect", description: "F&G available", passed: true, detail: "F&G = 55" },
    ],
  },
  validate: {
    phase: "validate",
    total: 2,
    passed: 1,
    score: 0.5,
    ready: false,
    conditions: [
      { id: "v1", phase: "validate", description: "Signal backtest run", passed: true, detail: "15 signals" },
      { id: "v2", phase: "validate", description: "Scorecard pass rate > 50%", passed: false, detail: "Only 40% passed" },
    ],
  },
};

const mockConflictData = {
  conflicts: [
    {
      ticker: "TSLA",
      conflict_type: "signal_divergence",
      severity: "high",
      buy_signals: ["macd_golden"],
      sell_signals: ["rsi_overbought"],
      detail: "MACD buy vs RSI sell conflict",
      recommendation: "Wait for confirmation",
    },
  ],
  count: 1,
  high: 1,
};

const mockMemoryData = {
  drifts: [
    {
      signal_id: "rsi_oversold",
      regime: "bull_low_vol",
      all_time_wr: 65.0,
      recent_wr: 45.0,
      drift_pct: -20.0,
      status: "degrading",
      detail: "Win rate dropped 20%",
    },
  ],
  critical: 0,
  degrading: 1,
};

describe("EnginePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchAPI.mockReset();
  });

  it("renders page title", async () => {
    mockFetchAPI.mockResolvedValue({});
    const Page = await import("@/app/engine/page");
    const element = await Page.default();
    render(element);
    expect(screen.getByText("Certification Engine")).toBeInTheDocument();
  });

  it("renders gate section with conditions", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/gate")) return Promise.resolve(mockGateData);
      if (path.includes("/api/conflicts")) return Promise.resolve({ conflicts: [], count: 0, high: 0 });
      if (path.includes("/api/memory")) return Promise.resolve({ drifts: [], critical: 0, degrading: 0 });
      return Promise.resolve({});
    });

    const mod = await import("@/app/engine/page");
    // GateSection is not exported, test through the page's inner async components
    // We render the full page which uses Suspense — the server components resolve inline
    const element = await mod.default();
    render(element);
    expect(screen.getByText("Certification Engine")).toBeInTheDocument();
  });

  // #1218: BLOCKED 페이즈만 다음 행동 링크(/pipeline) — READY 는 없다
  it("renders the next-action link only for blocked gate phases", async () => {
    mockFetchAPI.mockResolvedValue(mockGateData);
    const mod = await import("@/app/engine/page");
    const element = await mod.GateSection();
    render(element);
    const next = screen.getByTestId("gate-next-action-validate"); // ready:false 픽스처
    expect(next).toHaveAttribute("href", "/pipeline");
    expect(next.textContent).toContain("다음 행동:");
    expect(next.textContent).toContain("validate");
    expect(screen.queryByTestId("gate-next-action-collect")).not.toBeInTheDocument(); // ready:true
  });

  // codex R1 P1/P3: gate 어휘(regime)와 step 어휘(classify)는 다르다 — 실제 /api/gate
  // vocabulary 로 잠근다. regime 게이트가 막힌 화면이 실행 불가한 "regime" 을 광고하면 회귀.
  it("maps the regime gate to the runnable classify step, generic copy for unknown phases", async () => {
    const blocked = (phase: string) => ({
      phase, total: 1, passed: 0, score: 0, ready: false,
      conditions: [{ id: `${phase}-1`, phase, description: "d", passed: false, detail: "x" }],
    });
    mockFetchAPI.mockResolvedValue({ regime: blocked("regime"), mystery: blocked("mystery") });
    const mod = await import("@/app/engine/page");
    render(await mod.GateSection());
    // codex R2: 부분 일치·리터럴 부정은 잠금이 아니다 — 카피 전문을 정확 일치로 잠근다
    // (regime 광고 회귀는 어떤 형태든 여기서 깨진다)
    const regime = screen.getByTestId("gate-next-action-regime");
    expect(regime.textContent).toBe("다음 행동: classify 파이프라인에서 실행 →");
    const unknown = screen.getByTestId("gate-next-action-mystery");
    expect(unknown.textContent).toBe("다음 행동: 파이프라인 확인 →");
  });

  it("renders READY badge for passing gate", async () => {
    mockFetchAPI.mockResolvedValueOnce(mockGateData);
    // Dynamically test the GateSection by importing the module
    // The page exports default (EnginePage) which wraps GateSection in Suspense
    // For direct testing, we reach into the module's inner components
    const mod = await import("@/app/engine/page");
    const element = await mod.default();
    render(element);
    expect(screen.getByText("Certification Engine")).toBeInTheDocument();
  });

  it("renders conflict details when conflicts exist", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/gate")) return Promise.resolve({});
      if (path.includes("/api/conflicts")) return Promise.resolve(mockConflictData);
      if (path.includes("/api/memory")) return Promise.resolve({ drifts: [], critical: 0, degrading: 0 });
      return Promise.resolve({});
    });

    // Test ConflictsSection via rendering — since these are async server components,
    // we test the static output
    const { ConflictsSection } = await getInternalComponents();
    const element = await ConflictsSection();
    render(element);

    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("MACD buy vs RSI sell conflict")).toBeInTheDocument();
  });

  it("shows the Korean one-line empty state when no conflicts (#1218)", async () => {
    mockFetchAPI.mockResolvedValue({ conflicts: [], count: 0, high: 0 });

    const { ConflictsSection } = await getInternalComponents();
    const element = await ConflictsSection();
    render(element);

    expect(screen.getByText("시그널 충돌 없음")).toBeInTheDocument();
  });

  it("renders memory drift table when drifts exist", async () => {
    mockFetchAPI.mockResolvedValue(mockMemoryData);

    const { MemorySection } = await getInternalComponents();
    const element = await MemorySection();
    render(element);

    expect(screen.getByText("Learning Memory — Drift")).toBeInTheDocument();
    expect(screen.getByTestId("client-table-drift")).toBeInTheDocument();
  });

  it("shows empty drift message when no drifts", async () => {
    mockFetchAPI.mockResolvedValue({ drifts: [], critical: 0, degrading: 0 });

    const { MemorySection } = await getInternalComponents();
    const element = await MemorySection();
    render(element);

    expect(screen.getByText(/드리프트 데이터 없음/)).toBeInTheDocument();
  });

  it("displays conflict count metrics", async () => {
    mockFetchAPI.mockResolvedValue(mockConflictData);

    const { ConflictsSection } = await getInternalComponents();
    const element = await ConflictsSection();
    render(element);

    expect(screen.getByText("Signal Conflicts")).toBeInTheDocument();
  });

  it("renders conflict recommendation text", async () => {
    mockFetchAPI.mockResolvedValue(mockConflictData);

    const { ConflictsSection } = await getInternalComponents();
    const element = await ConflictsSection();
    render(element);

    expect(screen.getByText(/Wait for confirmation/)).toBeInTheDocument();
  });

  it("renders memory critical and degrading counts", async () => {
    mockFetchAPI.mockResolvedValue({ drifts: [], critical: 2, degrading: 3 });

    const { MemorySection } = await getInternalComponents();
    const element = await MemorySection();
    render(element);

    expect(screen.getByText("Learning Memory — Drift")).toBeInTheDocument();
  });

  it("conflicts fetch 실패(503 shed 포함) → 섹션만 강등 (#1119)", async () => {
    mockFetchAPI.mockImplementation((path: string) => {
      if (path.includes("/api/conflicts")) return Promise.reject(new Error("API /api/conflicts: 503"));
      return Promise.resolve({});
    });
    const { ConflictsSection } = await import("@/app/engine/page");
    const ui = await ConflictsSection();
    render(ui);
    expect(screen.getByText("데이터를 불러오지 못했습니다 — 잠시 후 새로고침하세요.")).toBeInTheDocument();
  });
});

/**
 * #1218: 이전에는 "not exported" 라며 섹션을 테스트 파일 안에 **복제**해 검증했다 —
 * 페이지가 이미 export 하고 있었고, 사본 검증은 실물 회귀를 못 잡는다 (mock-shape 교훈).
 * 실물 export 를 직접 렌더한다.
 */
async function getInternalComponents() {
  const mod = await import("@/app/engine/page");
  return {
    GateSection: mod.GateSection,
    ConflictsSection: mod.ConflictsSection,
    MemorySection: mod.MemorySection,
  };
}
