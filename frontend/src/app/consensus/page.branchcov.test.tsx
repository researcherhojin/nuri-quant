import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

const fetchAPIMock = vi.fn();
vi.mock("@/lib/api", () => ({ fetchAPI: (...args: unknown[]) => fetchAPIMock(...args) }));

// ConsensusSection 자식(Card/ConsensusTable)은 자체 contract(verdicts/scoring_detail)를 요구하므로
// ConsensusSection 의 `data.regime?.vix ?? null` 분기만 검증할 때는 stub 한다.
vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/ui/consensus-table", () => ({
  ConsensusTable: ({ vix }: { vix: number | null }) => (
    <div data-testid="table-vix">{String(vix)}</div>
  ),
}));

// async Server Component 은 <Page/> 전체 렌더 시 jsdom 이 Suspense 자식을 commit 하지 않으므로
// export 한 컴포넌트를 직접 호출/렌더한다 (jsdom-Suspense gotcha).
import { VixBanner, ConsensusSection, DissentSection } from "@/app/consensus/page";

const row = (over: Partial<{ ticker: string; dissent: string[] }> = {}) => ({
  ticker: over.ticker ?? "AAA",
  final_action: "BUY",
  final_confidence: 0.9,
  agreement_rate: 0.8,
  dissent: over.dissent ?? [],
});

describe("VixBanner — `!vix || vix < 25` guard + isBlocked ternaries (B0/B1/B2/B3)", () => {
  // B0 arm0 `!vix` truthy: vix=null → early return null (no banner).
  it("renders nothing when vix is null", () => {
    const { container } = render(<VixBanner vix={null} />);
    expect(container.firstChild).toBeNull();
  });

  // B0 arm1 `vix < 25` true: vix present(falsy short-circuit avoided) AND < 25 → early return null.
  it("renders nothing when 0 < vix < 25", () => {
    const { container } = render(<VixBanner vix={18} />);
    expect(container.firstChild).toBeNull();
  });

  // isBlocked=false branch (vix in [25,30)): amber className + caution text (ternary false arms).
  it("renders amber caution banner for 25 <= vix < 30", () => {
    const { container, getByText } = render(<VixBanner vix={27.5} />);
    expect(container.querySelector(".text-amber-400")).not.toBeNull();
    expect(getByText(/VIX 27.5 \(25-30\)/)).toBeInTheDocument();
    expect(getByText(/반포지션 적용 중/)).toBeInTheDocument();
  });

  // isBlocked=true branch (vix >= 30): red className + blocked text (ternary true arms).
  it("renders red blocked banner for vix >= 30", () => {
    const { container, getByText } = render(<VixBanner vix={35.2} />);
    expect(container.querySelector(".text-red-400")).not.toBeNull();
    expect(getByText(/VIX 35.2 > 30/)).toBeInTheDocument();
    expect(getByText(/win rate 붕괴 구간/)).toBeInTheDocument();
  });
});

describe("ConsensusSection — `data.regime?.vix ?? null` (B4/B5)", () => {
  beforeEach(() => fetchAPIMock.mockReset());

  // `?? null` fallback arm: regime.vix null → both VixBanner & ConsensusTable get null.
  it("passes null when regime.vix is null", async () => {
    fetchAPIMock.mockResolvedValue({ regime: { vix: null }, results: [row()], count: 1 });
    const { getByTestId } = render(await ConsensusSection());
    expect(getByTestId("table-vix").textContent).toBe("null");
  });

  // optional-chain short-circuit then `?? null`: regime undefined.
  it("passes null when regime is undefined", async () => {
    fetchAPIMock.mockResolvedValue({ regime: undefined, results: [row()], count: 1 });
    const { getByTestId } = render(await ConsensusSection());
    expect(getByTestId("table-vix").textContent).toBe("null");
  });

  // left-hand arm of `??`: regime.vix is a real number → that value reaches the table.
  it("passes the numeric vix when present", async () => {
    fetchAPIMock.mockResolvedValue({ regime: { vix: 22 }, results: [row()], count: 1 });
    const { getByTestId } = render(await ConsensusSection());
    expect(getByTestId("table-vix").textContent).toBe("22");
  });
});

describe("DissentSection — filter + `if (!withDissent.length)` (B7/B8)", () => {
  beforeEach(() => fetchAPIMock.mockReset());

  // B8 filter: row with dissent (kept) + row without (dropped); B7 false arm (renders card).
  it("renders dissent cards when some rows have dissent", async () => {
    fetchAPIMock.mockResolvedValue({
      results: [
        row({ ticker: "AAA", dissent: ["technical: too hot", "risk: concentration"] }),
        row({ ticker: "BBB", dissent: [] }),
      ],
    });
    const { getByText } = render(await DissentSection());
    expect(getByText("Dissent — Agent Disagreements")).toBeInTheDocument();
    expect(getByText("AAA")).toBeInTheDocument();
  });

  // B7 true arm: no row has dissent → returns null.
  it("returns null when no row has dissent", async () => {
    fetchAPIMock.mockResolvedValue({ results: [row({ dissent: [] })] });
    const result = await DissentSection();
    expect(result).toBeNull();
  });
});
