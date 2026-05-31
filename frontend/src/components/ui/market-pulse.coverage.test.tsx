import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketPulse } from "@/components/ui/market-pulse";

// MarketPulse 는 순수 표시 컴포넌트 (recharts/fetch/next-navigation 없음).
// 모든 helper (vixColor/fearGreedColor/fearGreedLabel/macroColor/trendColor/
// confidenceLabel) 의 분기를 props 로 자연스럽게 실행해 100% statements 달성.

const baseRegime = {
  regime: "bull_low_vol",
  trend: "bull",
  volatility: "normal_vol",
  confidence: 85,
  vix: 14,
  fear_greed: 50,
};

const baseMacro = { score: 70, interpretation: "Favorable" };

describe("MarketPulse — base render", () => {
  it("renders the Market Pulse header and regime label", () => {
    render(<MarketPulse regime={baseRegime} macro={baseMacro} />);
    expect(screen.getByText("Market Pulse")).toBeInTheDocument();
    expect(screen.getByText("bull_low_vol")).toBeInTheDocument();
  });

  it("renders all six metric labels", () => {
    render(<MarketPulse regime={baseRegime} macro={baseMacro} />);
    expect(screen.getByText("Trend")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("Fear & Greed")).toBeInTheDocument();
    expect(screen.getByText("Macro")).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Volatility")).toBeInTheDocument();
  });

  it("formats macro score, confidence, and trend uppercase", () => {
    render(<MarketPulse regime={baseRegime} macro={baseMacro} />);
    expect(screen.getByText("70/100")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("BULL")).toBeInTheDocument();
  });
});

// ─── trendColor branches ──────────────────────────────
describe("MarketPulse — trend variants", () => {
  it("bull trend renders green BULL value", () => {
    render(<MarketPulse regime={baseRegime} macro={baseMacro} />);
    expect(screen.getByText("BULL").className).toContain("text-emerald-400");
  });

  it("bear trend renders red BEAR value", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, trend: "bear" }} macro={baseMacro} />,
    );
    const el = screen.getByText("BEAR");
    expect(el.className).toContain("text-red-400");
  });

  it("sideways trend renders default color", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, trend: "sideways" }}
        macro={baseMacro}
      />,
    );
    const el = screen.getByText("SIDEWAYS");
    expect(el.className).toContain("text-zinc-200");
  });

  it("empty trend falls back to UNKNOWN (default color)", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, trend: "" }} macro={baseMacro} />,
    );
    const el = screen.getByText("UNKNOWN");
    expect(el.className).toContain("text-zinc-200");
  });
});

// ─── vixColor + VIX sub-text branches ─────────────────
describe("MarketPulse — VIX variants", () => {
  it("low VIX (<15) shows calm and green", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, vix: 12 }} macro={baseMacro} />,
    );
    const el = screen.getByText("12.0");
    expect(el.className).toContain("text-emerald-400");
    expect(screen.getByText("calm")).toBeInTheDocument();
  });

  it("normal VIX (15-25) shows normal and default", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, vix: 20 }} macro={baseMacro} />,
    );
    const el = screen.getByText("20.0");
    expect(el.className).toContain("text-zinc-200");
    // VIX 15-25 sub is "normal"; base volatility metric (normal_vol) also reads
    // "normal" → scope to this VIX metric's own wrapper to avoid a text collision.
    const sub = el.parentElement?.querySelector("p:last-child");
    expect(sub?.textContent).toBe("normal");
  });

  it("high VIX (>25) shows elevated and red", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, vix: 32 }} macro={baseMacro} />,
    );
    const el = screen.getByText("32.0");
    expect(el.className).toContain("text-red-400");
    expect(screen.getByText("elevated")).toBeInTheDocument();
  });

  it("null vix shows em-dash and 'no data'", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, vix: null }} macro={baseMacro} />,
    );
    expect(screen.getByText("no data")).toBeInTheDocument();
  });

  it("undefined vix (omitted) falls back to null path", () => {
    const { vix: _vix, ...noVix } = baseRegime;
    render(<MarketPulse regime={noVix} macro={baseMacro} />);
    expect(screen.getByText("no data")).toBeInTheDocument();
  });
});

// ─── fearGreedColor + fearGreedLabel branches ─────────
describe("MarketPulse — Fear & Greed variants", () => {
  it("extreme fear (<25) shows label and red", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: 10 }}
        macro={baseMacro}
      />,
    );
    expect(screen.getByText("Extreme Fear")).toBeInTheDocument();
    expect(screen.getByText("10").className).toContain("text-red-400");
  });

  it("fear (25-44) shows label and default color", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: 30 }}
        macro={baseMacro}
      />,
    );
    expect(screen.getByText("Fear")).toBeInTheDocument();
    expect(screen.getByText("30").className).toContain("text-zinc-200");
  });

  it("neutral (40-60) shows Neutral and green", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: 50 }}
        macro={baseMacro}
      />,
    );
    expect(screen.getByText("Neutral")).toBeInTheDocument();
    expect(screen.getByText("50").className).toContain("text-emerald-400");
  });

  it("greed (56-75) shows Greed label", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: 70 }}
        macro={baseMacro}
      />,
    );
    expect(screen.getByText("Greed")).toBeInTheDocument();
    // 70 > 60 and <= 75 → default color (not green, not red)
    expect(screen.getByText("70").className).toContain("text-zinc-200");
  });

  it("extreme greed (>75) shows label and red", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: 90 }}
        macro={baseMacro}
      />,
    );
    expect(screen.getByText("Extreme Greed")).toBeInTheDocument();
    expect(screen.getByText("90").className).toContain("text-red-400");
  });

  it("null fear_greed shows em-dash label", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, fear_greed: null }}
        macro={baseMacro}
      />,
    );
    // fearGreedLabel(null) === "—"; VIX value also "—" so use getAllByText
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

// ─── macroColor branches ──────────────────────────────
describe("MarketPulse — Macro score variants", () => {
  it("favorable macro (>=60) is green", () => {
    render(
      <MarketPulse regime={baseRegime} macro={{ score: 80, interpretation: "Strong" }} />,
    );
    expect(screen.getByText("80/100").className).toContain("text-emerald-400");
  });

  it("neutral macro (40-59) is default", () => {
    render(
      <MarketPulse regime={baseRegime} macro={{ score: 50, interpretation: "Neutral" }} />,
    );
    expect(screen.getByText("50/100").className).toContain("text-zinc-200");
  });

  it("weak macro (<40) is red", () => {
    render(
      <MarketPulse regime={baseRegime} macro={{ score: 30, interpretation: "Weak" }} />,
    );
    expect(screen.getByText("30/100").className).toContain("text-red-400");
  });
});

// ─── confidenceLabel branches ─────────────────────────
describe("MarketPulse — confidence variants", () => {
  it("high conviction (>=80)", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, confidence: 90 }} macro={baseMacro} />,
    );
    expect(screen.getByText("high conviction")).toBeInTheDocument();
  });

  it("moderate (60-79)", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, confidence: 65 }} macro={baseMacro} />,
    );
    expect(screen.getByText("moderate")).toBeInTheDocument();
  });

  it("low conviction (<60)", () => {
    render(
      <MarketPulse regime={{ ...baseRegime, confidence: 40 }} macro={baseMacro} />,
    );
    expect(screen.getByText("low conviction")).toBeInTheDocument();
  });
});

// ─── volatility branches (value/sub/color) ────────────
describe("MarketPulse — volatility variants", () => {
  it("high_vol shows HIGH, elevated, red", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, volatility: "high_vol" }}
        macro={baseMacro}
      />,
    );
    const el = screen.getByText("HIGH");
    expect(el.className).toContain("text-red-400");
    expect(screen.getByText("elevated")).toBeInTheDocument();
  });

  it("low_vol shows LOW, calm, green", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, volatility: "low_vol" }}
        macro={baseMacro}
      />,
    );
    const el = screen.getByText("LOW");
    expect(el.className).toContain("text-emerald-400");
    // VIX sub (base vix=14<15) is also "calm" → scope to this metric's wrapper
    const sub = el.parentElement?.querySelector("p:last-child");
    expect(sub?.textContent).toBe("calm");
  });

  it("normal_vol shows NORMAL, normal, default", () => {
    render(
      <MarketPulse
        regime={{ ...baseRegime, volatility: "normal_vol" }}
        macro={baseMacro}
      />,
    );
    const el = screen.getByText("NORMAL");
    expect(el.className).toContain("text-zinc-200");
    // scope to this metric's wrapper (VIX sub may also read "normal")
    const sub = el.parentElement?.querySelector("p:last-child");
    expect(sub?.textContent).toBe("normal");
  });

  it("missing volatility falls back to UNKNOWN with normal sub", () => {
    const { volatility: _vol, ...noVol } = baseRegime;
    render(<MarketPulse regime={noVol} macro={baseMacro} />);
    // vol "unknown" → value "UNKNOWN", sub "normal", color default
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });
});
