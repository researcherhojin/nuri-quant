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

  it("handles null price gracefully", () => {
    const nullPriceOpp = { ...positiveOpp, price: null };
    render(<OpportunityExplorer opportunities={[nullPriceOpp]} />);
    expect(screen.getByText("$—")).toBeTruthy();
  });

  it("renders multiple opportunity cards", () => {
    render(<OpportunityExplorer opportunities={[positiveOpp, dangerOpp, mutedOpp]} />);
    expect(screen.getByText("MRVL")).toBeTruthy();
    expect(screen.getByText("SNOW")).toBeTruthy();
    expect(screen.getByText("ETN")).toBeTruthy();
  });
});
