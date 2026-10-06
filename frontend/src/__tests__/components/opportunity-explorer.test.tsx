import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { OpportunityExplorer } from "@/components/ui/opportunity-explorer";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const positiveOpp = {
  ticker: "MRVL",
  price: 128.49,
  change_1d: 7.2,
  change_5d: 20.0,
  volume_ratio: 1.7,
  rsi: 83,
  signal: "breakout",
  score: 69,
  observations: ["breakout 시그널 (Score 69)", "RSI 83 과매수"],
  system: { status: "qualified", score: 78.4, threshold: 70, reason: null },
};

const dangerOpp = {
  ticker: "SNOW",
  price: 121.11,
  change_1d: -8.4,
  change_5d: -20.2,
  volume_ratio: 3.7,
  rsi: 17,
  signal: "volume_spike",
  score: 37,
  observations: ["5D -20.2% 급락", "급락 + volume_spike — 원인 확인 필요"],
  system: { status: "blocked", score: null, threshold: null, reason: "VIX 31.0 > 30 (신규 매수 차단)" },
};

const mutedOpp = {
  ticker: "ETN",
  price: 403.0,
  change_1d: 0.6,
  change_5d: 11.6,
  volume_ratio: 0.9,
  rsi: 70,
  signal: "momentum",
  score: 23,
  observations: [],
  system: { status: "not_scored", score: null, threshold: null, reason: "no_factor" },
};

describe("OpportunityExplorer", () => {
  it("renders empty state", () => {
    render(<OpportunityExplorer opportunities={[]} />);
    expect(screen.getByText("현재 감지된 기회가 없습니다.")).toBeTruthy();
  });

  it("renders opportunity cards", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp, dangerOpp]} />);
    expect(screen.getByText("MRVL")).toBeTruthy();
    expect(screen.getByText("SNOW")).toBeTruthy();
  });

  it("shows ticker price", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("$128.49")).toBeTruthy();
  });

  it("shows signal badge", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("breakout")).toBeTruthy();
  });

  it("shows 5D change with color", () => {
    render(<OpportunityExplorer opportunities={[dangerOpp]} />);
    const body = document.body.textContent;
    expect(body).toContain("-20.2%");
  });

  it("shows volume ratio when >= 1.5", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("Vol 1.7x")).toBeTruthy();
  });

  it("shows RSI value", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("RSI 83")).toBeTruthy();
  });

  // #1683: 판정 칸은 파이프라인(BUY 후보 emitter) 분류 — 점수·임계는 API 값 그대로
  it("renders the pipeline stance — qualified with score / threshold", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByTestId("system-stance").textContent).toBe("후보 기준 통과 78 / 70");
  });

  it("renders the pipeline stance — below threshold", () => {
    const below = { ...positiveOpp, system: { status: "below_threshold", score: 52, threshold: 65, reason: null } };
    // 69.6 은 내림 — 반올림이면 "기준 미달 70 / 70" 이라는 자기모순 라벨이 된다
    const edge = { ...positiveOpp, ticker: "EDGE", system: { status: "below_threshold", score: 69.6, threshold: 70, reason: null } };
    render(<OpportunityExplorer opportunities={[below, edge]} />);
    expect(screen.getAllByTestId("system-stance").map((b) => b.textContent)).toEqual(["기준 미달 52 / 65", "기준 미달 69 / 70"]);
  });

  it("renders the pipeline stance — excluded with the gate", () => {
    const cool = { ...positiveOpp, system: { status: "excluded", score: null, threshold: 70, reason: "cooldown" } };
    render(<OpportunityExplorer opportunities={[cool]} />);
    expect(screen.getByTestId("system-stance").textContent).toBe("제외 · 쿨다운");
  });

  it("renders the pipeline stance — blocked run, reason in the peek", () => {
    render(<OpportunityExplorer opportunities={[dangerOpp]} />);
    const badge = screen.getByTestId("system-stance");
    expect(badge.textContent).toBe("차단");
    expect(badge.getAttribute("title")).toBe("차단 · VIX 31.0 > 30 (신규 매수 차단)");
  });

  it("renders the pipeline stance — not scored, with why", () => {
    render(<OpportunityExplorer opportunities={[mutedOpp]} />);
    expect(screen.getByTestId("system-stance").textContent).toBe("미평가 · 팩터 데이터 없음");
  });

  // #1652: 행에는 첫 관측만, 펼치면 전체 관측 + 시스템 분류 문장
  it("shows only the first observation in the row and the full list in the quick-peek", () => {
    render(<OpportunityExplorer opportunities={[dangerOpp]} />);
    expect(screen.queryByTestId("opportunity-row-peek")).toBeNull();
    expect(screen.getByText(/^5D -20.2% 급락/)).toBeTruthy();
    expect(screen.queryByText(/원인 확인 필요/)).toBeNull();
    expect(screen.getByText("+1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /SNOW 상세 펼치기/ }));
    const peek = screen.getByTestId("opportunity-row-peek");
    expect(peek.textContent).toContain("스캐너 관측");
    expect(peek.textContent).toContain("급락 + volume_spike — 원인 확인 필요");
    expect(peek.textContent).toContain("차단 · VIX 31.0 > 30 (신규 매수 차단)");
  });

  it("renders column headers so 시스템 판단/스캐너 관측 stay visible without expanding", () => {
    render(<OpportunityExplorer opportunities={[mutedOpp]} />);
    expect(screen.getByText("시스템 판단")).toBeTruthy();
    expect(screen.getByText("스캐너 관측")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1); // 관측 없음
  });

  it("links to ticker detail page", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    const links = screen.getAllByText("MRVL");
    const link = links[0].closest("a");
    expect(link?.getAttribute("href")).toBe("/ticker/MRVL");
  });

  it("shows chart link", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("차트 보기 →")).toBeTruthy();
  });

  it("shows 10-Agent analysis button", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("10-Agent 분석 ▶")).toBeTruthy();
  });

  it("hides analysis button after result", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ action: "BUY", confidence: 72, agreement_rate: 0.4 }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    const btn = screen.getByText("10-Agent 분석 ▶");
    await btn.click();
    // Wait for state update
    await vi.waitFor(() => {
      expect(screen.getByText("BUY")).toBeTruthy();
      expect(screen.getByText("40% 합의")).toBeTruthy();
    });
    expect(screen.queryByText("10-Agent 분석 ▶")).toBeNull();
  });

  it("handles null price gracefully", () => {
    const nullPriceOpp = { ...positiveOpp, price: null };
    render(<OpportunityExplorer opportunities={[nullPriceOpp]} />);
    expect(screen.getByText("$—")).toBeTruthy();
  });

  it("shows SELL analysis result with red styling", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ action: "SELL", confidence: 80, agreement_rate: 0.6 }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("SELL")).toBeTruthy();
      expect(screen.getByText("60% 합의")).toBeTruthy();
    });
  });

  it("shows HOLD analysis result with neutral styling", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ action: "HOLD", confidence: 50, agreement_rate: null }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("HOLD")).toBeTruthy();
      expect(screen.getByText("0% 합의")).toBeTruthy();
    });
  });

  it("keeps button on fetch failure", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network"));
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("10-Agent 분석 ▶")).toBeTruthy();
    });
  });

  it("keeps button when response not ok", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("10-Agent 분석 ▶")).toBeTruthy();
    });
  });

  it("handles missing action/agreement in response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ confidence: 55 }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("HOLD")).toBeTruthy(); // default
    });
  });

  it("shows negative 5D change in red", () => {
    render(<OpportunityExplorer opportunities={[dangerOpp]} />);
    const body = document.body.textContent;
    expect(body).toContain("-20.2%");
  });

  it("hides volume when below 1.5x", () => {
    const lowVol = { ...positiveOpp, volume_ratio: 1.0 };
    render(<OpportunityExplorer opportunities={[lowVol]} />);
    expect(screen.queryByText(/Vol/)).toBeNull();
  });

  it("hides signal badge when null", () => {
    const noSignal = { ...positiveOpp, signal: null };
    render(<OpportunityExplorer opportunities={[noSignal]} />);
    expect(screen.queryByText("breakout")).toBeNull();
  });

  it("shows RSI < 30 in green", () => {
    const oversold = { ...positiveOpp, rsi: 25 };
    render(<OpportunityExplorer opportunities={[oversold]} />);
    expect(screen.getByText("RSI 25")).toBeTruthy();
  });

  it("hides RSI when null", () => {
    const noRsi = { ...positiveOpp, rsi: null };
    const { container } = render(<OpportunityExplorer opportunities={[noRsi]} />);
    // No RSI span should appear — check that no "RSI" text followed by a number exists
    const spans = container.querySelectorAll("span");
    const rsiSpans = Array.from(spans).filter(s => /RSI \d/.test(s.textContent ?? ""));
    expect(rsiSpans.length).toBe(0);
  });

  it("renders multiple opportunity cards", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp, dangerOpp, mutedOpp]} />);
    expect(screen.getByText("MRVL")).toBeTruthy();
    expect(screen.getByText("SNOW")).toBeTruthy();
    expect(screen.getByText("ETN")).toBeTruthy();
  });

  it("treats an unknown status as not scored instead of inventing a stance", () => {
    const unknown = { ...positiveOpp, system: { status: "unknown_status", score: null, threshold: null, reason: null } };
    render(<OpportunityExplorer opportunities={[unknown]} />);
    expect(screen.getByTestId("system-stance").textContent).toBe("미평가");
  });

  it("shows zero change_5d with plus sign", () => {
    const zeroChange = { ...positiveOpp, change_5d: 0 };
    render(<OpportunityExplorer opportunities={[zeroChange]} />);
    const body = document.body.textContent;
    expect(body).toContain("+0.0%");
  });

  it("shows analysis with zero agreement_rate", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ action: "BUY", confidence: 60, agreement_rate: 0 }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("0% 합의")).toBeTruthy();
    });
  });

  // ─── Divergence flag badge (P1 A2, docs/HARNESS.md §2) ──
  it("renders divergence badge when divergence_flag=true in API response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        final_action: "BUY",
        final_confidence: 42,
        agreement_rate: 0.3,
        divergence_flag: true,
        divergence_reason: "기술지표 반대: TechnicalAgent 가 SELL (conf 100)",
      }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      const badge = screen.getByTestId("divergence-badge");
      expect(badge).toBeTruthy();
      expect(badge.getAttribute("title")).toContain("TechnicalAgent");
    });
  });

  it("does not render divergence badge when divergence_flag=false", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        final_action: "HOLD",
        final_confidence: 50,
        agreement_rate: 0.5,
        divergence_flag: false,
        divergence_reason: "",
      }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("HOLD")).toBeTruthy();
    });
    expect(screen.queryByTestId("divergence-badge")).toBeNull();
  });

  it("uses final_action/final_confidence over legacy action/confidence", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        // Legacy keys present but final_* should win
        action: "HOLD",
        confidence: 0,
        final_action: "BUY",
        final_confidence: 75,
        agreement_rate: 0.8,
      }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("BUY")).toBeTruthy();
      expect(screen.getByText("80% 합의")).toBeTruthy();
    });
  });

  it("falls back to legacy action field when final_action is missing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        action: "SELL",
        confidence: 60,
        agreement_rate: 0.55,
      }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      expect(screen.getByText("SELL")).toBeTruthy();
      expect(screen.getByText("55% 합의")).toBeTruthy();
    });
  });

  it("uses default tooltip text when divergence_reason is empty string", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        final_action: "BUY",
        final_confidence: 60,
        agreement_rate: 0.4,
        divergence_flag: true,
        divergence_reason: "",
      }),
    });
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    await screen.getByText("10-Agent 분석 ▶").click();
    await vi.waitFor(() => {
      const badge = screen.getByTestId("divergence-badge");
      expect(badge.getAttribute("title")).toBe("기술지표 반대");
    });
  });
});
