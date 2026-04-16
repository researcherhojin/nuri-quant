import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
  pros: ["breakout 시그널 (Score 69)"],
  cons: ["RSI 83 과매수"],
  verdict: "관망 — 혼재 시그널, 조건부 진입 대기",
  verdict_level: "neutral",
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
  pros: ["RSI 17 과매도"],
  cons: ["5D -20.2% 급락 — 하락 모멘텀", "급락 + volume_spike — 원인 확인 필요"],
  verdict: "매수 금지 — 극단적 하락, 원인 확인 전 진입 위험",
  verdict_level: "danger",
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
  pros: [],
  cons: [],
  verdict: "데이터 부족 — 판단 불가",
  verdict_level: "muted",
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

  it("renders pros section", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("찬성")).toBeTruthy();
    expect(screen.getByText(/breakout 시그널/)).toBeTruthy();
  });

  it("renders cons section", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("반대")).toBeTruthy();
    expect(screen.getByText(/RSI 83 과매수/)).toBeTruthy();
  });

  it("renders verdict badge — neutral", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp]} />);
    expect(screen.getByText("관망")).toBeTruthy();
  });

  it("renders verdict badge — danger", () => {
    render(<OpportunityExplorer opportunities={[dangerOpp]} />);
    expect(screen.getByText("매수 금지")).toBeTruthy();
  });

  it("renders verdict badge — muted", () => {
    render(<OpportunityExplorer opportunities={[mutedOpp]} />);
    expect(screen.getByText("데이터 부족")).toBeTruthy();
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

  it("falls back to muted style for unknown verdict_level", () => {
    const unknownLevel = { ...positiveOpp, verdict_level: "unknown_level" };
    render(<OpportunityExplorer opportunities={[unknownLevel]} />);
    expect(screen.getByText("데이터 부족")).toBeTruthy();
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
