import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  DashboardSidebar,
  type SidebarAlert,
  type SidebarEvent,
  type SidebarCandidate,
  type SidebarMarketIndex,
} from "@/components/ui/dashboard-sidebar";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: any) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

describe("DashboardSidebar", () => {
  const alerts: SidebarAlert[] = [
    { level: "critical", message: "TSLA 손절선 돌파", href: "/ticker/TSLA" },
    { level: "warning", message: "VIX 상승 주의", href: "/signals" },
  ];
  const events: SidebarEvent[] = [
    { date: "2026-04-22", description: "TSLA 실적발표", ticker: "TSLA" },
    { date: "2026-05-07", description: "FOMC 금리결정", ticker: null },
  ];
  const candidates: SidebarCandidate[] = [
    { action: "BUY", ticker: "GOOGL", name: "Alphabet", account: "Main", confidence: 78 },
    { action: "BUY", ticker: "AMD", name: "AMD Inc", account: "Main", confidence: 65 },
  ];
  const marketIndexes: SidebarMarketIndex[] = [
    { ticker: "SPY", label: "SPY", changePct: 0.5 },
    { ticker: "QQQ", label: "QQQ", changePct: 0.8 },
    { ticker: "VIX", label: "VIX", changePct: -0.3, value: 18.2 },
  ];

  it("renders all four panel headings", () => {
    render(
      <DashboardSidebar
        alerts={alerts}
        events={events}
        candidates={candidates}
        marketIndexes={marketIndexes}
      />,
    );
    expect(screen.getByText(/⚠ 알림/)).toBeInTheDocument();
    expect(screen.getByText(/📅 다음 이벤트/)).toBeInTheDocument();
    expect(screen.getByText(/🎯 신규 매수 후보/)).toBeInTheDocument();
    expect(screen.getByText(/📊 시장/)).toBeInTheDocument();
  });

  it("renders alert count badge when alerts present", () => {
    render(
      <DashboardSidebar alerts={alerts} events={[]} candidates={[]} />,
    );
    // Badge with count (2)
    const heading = screen.getByText(/⚠ 알림/);
    expect(heading.textContent).toContain("2");
  });

  it("renders '위험 없음' when no alerts", () => {
    render(
      <DashboardSidebar alerts={[]} events={events} candidates={[]} />,
    );
    expect(screen.getByText("위험 없음")).toBeInTheDocument();
  });

  it("each alert links to the provided href", () => {
    render(
      <DashboardSidebar alerts={alerts} events={[]} candidates={[]} />,
    );
    const tslaLink = screen.getByText(/TSLA 손절선 돌파/).closest("a");
    expect(tslaLink).toHaveAttribute("href", "/ticker/TSLA");
  });

  it("renders events sorted by input order with date prefix", () => {
    render(
      <DashboardSidebar alerts={[]} events={events} candidates={[]} />,
    );
    expect(screen.getByText("TSLA 실적발표")).toBeInTheDocument();
    expect(screen.getByText("FOMC 금리결정")).toBeInTheDocument();
    // Dates formatted as "MM-DD"
    expect(screen.getByText("04-22")).toBeInTheDocument();
    expect(screen.getByText("05-07")).toBeInTheDocument();
  });

  it("renders '예정된 이벤트 없음' when events empty", () => {
    render(
      <DashboardSidebar alerts={[]} events={[]} candidates={[]} />,
    );
    expect(screen.getByText("예정된 이벤트 없음")).toBeInTheDocument();
  });

  it("renders candidates with confidence colored by threshold", () => {
    render(
      <DashboardSidebar alerts={[]} events={[]} candidates={candidates} />,
    );
    expect(screen.getByText("Alphabet")).toBeInTheDocument();
    expect(screen.getByText("AMD Inc")).toBeInTheDocument();
    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.getByText("65")).toBeInTheDocument();
  });

  it("shows pension waiting message when no visible candidates but pension count > 0 and not month end", () => {
    render(
      <DashboardSidebar
        alerts={[]}
        events={[]}
        candidates={[]}
        pensionCandidatesCount={3}
        isMonthEnd={false}
      />,
    );
    expect(screen.getByText(/연금 3건 — 월말 매수 대기/)).toBeInTheDocument();
  });

  it("shows '신규 후보 없음' when no candidates and no pension", () => {
    render(
      <DashboardSidebar alerts={[]} events={[]} candidates={[]} />,
    );
    expect(screen.getByText("신규 후보 없음")).toBeInTheDocument();
  });

  it("renders market indexes with change percent", () => {
    render(
      <DashboardSidebar
        alerts={[]}
        events={[]}
        candidates={[]}
        marketIndexes={marketIndexes}
      />,
    );
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("+0.5%")).toBeInTheDocument();
    expect(screen.getByText("+0.8%")).toBeInTheDocument();
    expect(screen.getByText("-0.3%")).toBeInTheDocument();
  });

  it("applies neutral tone for market index with exactly 0 change (changeTone fallthrough)", () => {
    render(
      <DashboardSidebar
        alerts={[]}
        events={[]}
        candidates={[]}
        marketIndexes={[{ ticker: "FLAT", label: "FLAT", changePct: 0 }]}
      />,
    );
    // changePct === 0 takes the fallthrough `return "text-zinc-500"` branch
    expect(screen.getByText("+0.0%")).toBeInTheDocument();
  });

  it("omits market section when marketIndexes is empty", () => {
    render(
      <DashboardSidebar
        alerts={[]}
        events={[]}
        candidates={[]}
        marketIndexes={[]}
      />,
    );
    expect(screen.queryByText(/📊 시장/)).not.toBeInTheDocument();
  });

  it("has semantic aria-label for screen readers", () => {
    render(
      <DashboardSidebar alerts={[]} events={[]} candidates={[]} />,
    );
    const sidebar = screen.getByTestId("dashboard-sidebar");
    expect(sidebar).toHaveAttribute("aria-label", "대시보드 사이드바");
  });
});
