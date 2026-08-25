import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ActionItems, type ActionItem } from "@/components/ui/action-items";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => <a href={href} {...props}>{children}</a>,
}));

// 분기 커버리지 전용 테스트 — action-items.tsx 의 모든 branch arm 을
// 이 파일 하나로 100% 커버 (isolation 측정 기준).

const base: ActionItem = {
  ticker: "AAPL",
  name: "Apple Inc",
  action: "BUY",
  confidence: 80,
  pnl_pct: 5.2,
  position_pct: 10,
  current_price: 100,
  avg_price: 90,
  account: "Main",
  stop_loss: 80,
  target_1: 120,
  target_2: 140,
  reasons: ["reason 1"],
  priority: "urgent",
};

describe("ActionItems — full branch coverage", () => {
  afterEach(cleanup);

  it("empty state when all buckets empty (total === 0)", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[]} portfolio={[]} />);
    expect(screen.getByText(/액션이 없습니다|없습니다|action/i)).toBeTruthy();
  });

  it("empty state when portfolio prop omitted and others empty", () => {
    render(<ActionItems urgent={[]} check={[]} hold={[]} />);
    // ACTION.EMPTY 렌더 — 빈 카드만 존재
    expect(document.querySelector("div.rounded-lg")).toBeTruthy();
  });

  it("renders all four buckets; covers urgent/portfolio/check/hold section conditionals", () => {
    const urgent: ActionItem = { ...base, ticker: "TSLA", priority: "urgent", action: "SELL", pnl_pct: -3.1, name: "Tesla" };
    const portfolio: ActionItem = { ...base, ticker: "BAC", priority: "portfolio", action: "HOLD", name: "Bank" };
    const check: ActionItem = { ...base, ticker: "NBIS", priority: "check", action: "BUY", name: "Nebius" };
    const hold: ActionItem = { ...base, ticker: "GOOGL", priority: "hold", action: "BUY", name: "Alphabet" };
    render(<ActionItems urgent={[urgent]} check={[check]} hold={[hold]} portfolio={[portfolio]} />);
    expect(screen.getByText("Tesla")).toBeTruthy();
    expect(screen.getByText("Bank")).toBeTruthy();
    expect(screen.getByText("Nebius")).toBeTruthy();
    expect(screen.getByText("Alphabet")).toBeTruthy();
  });

  it("SELL action badge styling (line 59-60 cond-expr SELL arm)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X1", action: "SELL", name: "SellCo" }]} check={[]} hold={[]} />);
    const badge = screen.getByText("SELL");
    expect(badge.className).toContain("text-red-400");
  });

  it("BUY action badge styling (line 61 cond-expr BUY arm)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X2", action: "BUY", name: "BuyCo" }]} check={[]} hold={[]} />);
    const badge = screen.getByText("BUY");
    expect(badge.className).toContain("text-emerald-400");
  });

  it("neutral action badge styling (line 62 cond-expr else arm)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X3", action: "HOLD", name: "HoldCo" }]} check={[]} hold={[]} />);
    const badge = screen.getByText("HOLD");
    expect(badge.className).toContain("bg-zinc-700");
  });

  it("name present: ticker moves to title attr (#1208 dense row)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X4", name: "Named" }]} check={[]} hold={[]} />);
    const link = screen.getByText("Named");
    expect(link.getAttribute("title")).toContain("X4");
  });

  it("name null: link shows ticker, no subtext (line 56 || right, line 58 && false)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X5", name: null }]} check={[]} hold={[]} />);
    expect(screen.getByText("X5")).toBeTruthy();
    // name 이 null 이면 subtext span 미생성 → "X5" 텍스트 노드는 link 하나뿐
    expect(screen.getAllByText("X5").length).toBe(1);
  });

  it("account present (line 66 && true)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X6", name: "Acc", account: "SubAcct" }]} check={[]} hold={[]} />);
    expect(screen.getByText("SubAcct")).toBeTruthy();
  });

  it("account empty (line 66 && false)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X7", name: "NoAcc", account: "" }]} check={[]} hold={[]} />);
    const body = document.body.textContent ?? "";
    expect(body).not.toContain("Main");
  });

  it("positive pnl color and + sign (line 75/76 arm 1)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X8", name: "Pos", pnl_pct: 4.4 }]} check={[]} hold={[]} />);
    expect(screen.getByText("+4.4%")).toBeTruthy();
  });

  it("negative pnl color and no + sign (line 75/76 arm 0)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X9", name: "Neg", pnl_pct: -4.4 }]} check={[]} hold={[]} />);
    const pnl = screen.getByText("-4.4%");
    expect(pnl.className).toContain("text-red-400");
  });

  it("row accent comes from the bucket, not item.priority (#1208)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X10", name: "Unknown", priority: "nope" }]} check={[]} hold={[]} />);
    const row = screen.getByText("Unknown").closest("tr");
    expect(row?.className).toContain("border-l-red-500/60"); // urgent 버킷 accent
  });

  // #1208: 행 안의 링크 클릭은 peek 토글을 막는다 (stopPropagation 2곳)
  it("ticker/evidence link clicks do not toggle the quick-peek", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X20", name: "LinkCo", decision_id: 7 }]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByText("LinkCo"));
    expect(screen.queryByTestId("action-row-peek")).toBeNull();
    fireEvent.click(screen.getByText(/증거 체인/));
    expect(screen.queryByTestId("action-row-peek")).toBeNull();
  });

  it("quick-peek toggles on row click, formats US prices (#1208)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X11", name: "Exp" }]} check={[]} hold={[]} />);
    const row = screen.getByTestId("action-row");
    fireEvent.click(row);
    expect(screen.getByText("현재가")).toBeTruthy();
    fireEvent.click(row);
    expect(screen.queryByText("현재가")).toBeNull();
  });

  it("KR ticker formats prices with won (line 47 isKr true)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "005930.KS", name: "KR", current_price: 200750 }]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByTestId("action-row"));
    expect((document.body.textContent ?? "").includes("₩")).toBe(true);
  });

  it("null prices render dash (line 46 fmt v == null)", () => {
    render(<ActionItems urgent={[{ ...base, ticker: "X12", name: "Null", current_price: null, stop_loss: null, target_1: null }]} check={[]} hold={[]} />);
    fireEvent.click(screen.getByTestId("action-row"));
    expect((document.body.textContent ?? "").includes("—")).toBe(true);
  });

  it("hold chip BUY action color (line 171 cond BUY arm) and name fallback", () => {
    const hold: ActionItem = { ...base, ticker: "X13", name: "HoldName", priority: "hold", action: "BUY" };
    render(<ActionItems urgent={[]} check={[]} hold={[hold]} />);
    expect(screen.getByText("HoldName")).toBeTruthy(); // line 170 name || ticker (name arm)
    const actionSpan = screen.getByText(/BUY 80/);
    expect(actionSpan.className).toContain("text-emerald-500");
  });

  it("hold chip non-BUY action color (line 171 cond else arm) and name-null ticker fallback", () => {
    const hold: ActionItem = { ...base, ticker: "X14", name: null, priority: "hold", action: "HOLD" };
    render(<ActionItems urgent={[]} check={[]} hold={[hold]} />);
    expect(screen.getByText("X14")).toBeTruthy(); // line 170 name || ticker (ticker arm)
    const actionSpan = screen.getByText(/HOLD 80/);
    expect(actionSpan.className).toContain("text-zinc-500");
  });
});
