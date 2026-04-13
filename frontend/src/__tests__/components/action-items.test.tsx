import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ActionItems } from "@/components/ui/action-items";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const urgentItem = {
  ticker: "TSLA",
  action: "SELL",
  confidence: 46,
  agreement: 20,
  pnl_pct: 1.6,
  position_pct: 15.4,
  current_price: 348.95,
  avg_price: 343.39,
  account: "Main",
  stop_loss: 319.35,
  target_1: 412.07,
  target_2: 480.75,
  reasons: ["SIEGE: 종목 비중 한도 — 위반: TSLA(15.4%>15%)"],
  priority: "urgent",
};

const checkItem = {
  ticker: "NBIS",
  action: "BUY",
  confidence: 59,
  agreement: 40,
  pnl_pct: 32.8,
  position_pct: 7.3,
  current_price: 144.97,
  avg_price: 109.2,
  account: "Main",
  stop_loss: 101.56,
  target_1: 131.04,
  target_2: 152.88,
  reasons: ["1차 익절 도달 (+33%) — 50% 매도 고려", "공매도 19.6% — squeeze 주의"],
  priority: "check",
};

const holdItem = {
  ticker: "GOOGL",
  action: "BUY",
  confidence: 60,
  agreement: 30,
  pnl_pct: 17.5,
  position_pct: 1.9,
  current_price: 317.24,
  avg_price: 269.91,
  account: "Main",
  stop_loss: null,
  target_1: null,
  target_2: null,
  reasons: ["BUY (conf 60)"],
  priority: "hold",
};

describe("ActionItems", () => {
  it("renders empty state when no actions", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[]} />);
    expect(screen.getByText("오늘 실행할 액션이 없습니다.")).toBeTruthy();
  });

  it("renders urgent section with red styling", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("즉시 실행 (1)")).toBeTruthy();
    expect(screen.getByText("TSLA")).toBeTruthy();
    expect(screen.getByText("SELL")).toBeTruthy();
  });

  it("renders check section with amber styling", () => {
    render(<ActionItems urgent={[]} check={[checkItem]} hold={[]} />);
    expect(screen.getByText("오늘 확인 (1)")).toBeTruthy();
    expect(screen.getByText("NBIS")).toBeTruthy();
  });

  it("renders hold section as compact chips", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
    expect(screen.getByText("GOOGL")).toBeTruthy();
  });

  it("renders all three sections together", () => {
    render(<ActionItems urgent={[urgentItem]} check={[checkItem]} hold={[holdItem]} />);
    expect(screen.getByText("즉시 실행 (1)")).toBeTruthy();
    expect(screen.getByText("오늘 확인 (1)")).toBeTruthy();
    expect(screen.getByText("유지 종목 (1)")).toBeTruthy();
  });

  it("shows P&L percentage with correct color", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("+1.6%")).toBeTruthy();
  });

  it("shows action reasons", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const body = document.body.textContent;
    expect(body).toContain("SIEGE");
    expect(body).toContain("한도");
  });

  it("shows multiple reasons for check items", () => {
    render(<ActionItems urgent={[]} check={[checkItem]} hold={[]} />);
    expect(screen.getByText(/1차 익절/)).toBeTruthy();
    expect(screen.getByText(/공매도/)).toBeTruthy();
  });

  it("expands detail on button click", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const detailBtn = screen.getByText(/상세 근거/);
    fireEvent.click(detailBtn);
    expect(screen.getByText("현재가")).toBeTruthy();
    expect(screen.getByText("손절")).toBeTruthy();
  });

  it("collapses detail on second click", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const detailBtn = screen.getByText(/상세 근거/);
    fireEvent.click(detailBtn);
    expect(screen.getByText("현재가")).toBeTruthy();
    const collapseBtn = screen.getByText(/접기/);
    fireEvent.click(collapseBtn);
    expect(screen.queryByText("현재가")).toBeNull();
  });

  it("formats KR prices with won symbol", () => {
    const krItem = { ...urgentItem, ticker: "005930.KS", current_price: 200750, stop_loss: 180675, target_1: 230862 };
    render(<ActionItems urgent={[krItem]} check={[]} hold={[]} />);
    const detailBtn = screen.getByText(/상세 근거/);
    fireEvent.click(detailBtn);
    const body = document.body.textContent;
    expect(body).toContain("₩");
  });

  it("links ticker to detail page", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    const link = screen.getByText("TSLA").closest("a");
    expect(link?.getAttribute("href")).toBe("/ticker/TSLA");
  });

  it("shows account label", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("Main")).toBeTruthy();
  });

  it("shows confidence and weight", () => {
    render(<ActionItems urgent={[urgentItem]} check={[]} hold={[]} />);
    expect(screen.getByText("확신도 46")).toBeTruthy();
    expect(screen.getByText("비중 15.4%")).toBeTruthy();
  });

  it("hold chips link to ticker page", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    const link = screen.getByText("GOOGL").closest("a");
    expect(link?.getAttribute("href")).toBe("/ticker/GOOGL");
  });

  it("hold chips show action and confidence", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[holdItem]} />);
    expect(screen.getByText("BUY 60")).toBeTruthy();
  });

  it("handles negative P&L", () => {
    const lossItem = { ...checkItem, pnl_pct: -5.3 };
    render(<ActionItems urgent={[]} check={[lossItem]} hold={[]} />);
    expect(screen.getByText("-5.3%")).toBeTruthy();
  });
});
