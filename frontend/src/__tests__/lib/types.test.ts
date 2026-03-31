import { describe, it, expect } from "vitest";
import {
  RegimeSchema,
  MacroSchema,
  CandidateSchema,
  ScorecardSchema,
  RebalanceActionSchema,
  StrategySchema,
} from "@/lib/types";

// ─── RegimeSchema ────────────────────────────────────────────
describe("RegimeSchema", () => {
  const valid = {
    date: "2026-03-31",
    trend: "bull" as const,
    volatility: "low" as const,
    regime: "bull_low_vol",
    confidence: 0.85,
    details: { special_regime: null, base_regime: "bull_low_vol" },
  };

  it("parses valid regime data", () => {
    const result = RegimeSchema.parse(valid);
    expect(result.trend).toBe("bull");
    expect(result.volatility).toBe("low");
    expect(result.confidence).toBe(0.85);
  });

  it("accepts all trend enums", () => {
    for (const trend of ["bull", "bear", "sideways"] as const) {
      expect(RegimeSchema.parse({ ...valid, trend }).trend).toBe(trend);
    }
  });

  it("accepts all volatility enums", () => {
    for (const volatility of ["high", "low"] as const) {
      expect(RegimeSchema.parse({ ...valid, volatility }).volatility).toBe(volatility);
    }
  });

  it("rejects invalid trend value", () => {
    expect(() => RegimeSchema.parse({ ...valid, trend: "flat" })).toThrow();
  });

  it("rejects invalid volatility value", () => {
    expect(() => RegimeSchema.parse({ ...valid, volatility: "medium" })).toThrow();
  });

  it("rejects missing required fields", () => {
    const { date, ...noDate } = valid;
    expect(() => RegimeSchema.parse(noDate)).toThrow();
  });

  it("rejects non-numeric confidence", () => {
    expect(() => RegimeSchema.parse({ ...valid, confidence: "high" })).toThrow();
  });

  it("allows empty details object", () => {
    const result = RegimeSchema.parse({ ...valid, details: {} });
    expect(result.details).toEqual({});
  });

  it("allows details with arbitrary keys", () => {
    const result = RegimeSchema.parse({
      ...valid,
      details: { vix: 15.5, sma50: 550, nested: { a: 1 } },
    });
    expect(result.details).toHaveProperty("vix");
  });
});

// ─── MacroSchema ─────────────────────────────────────────────
describe("MacroSchema", () => {
  const valid = {
    date: "2026-03-31",
    total_score: 65,
    interpretation: "Moderately Bullish",
    yield_curve_score: 70,
    yield_spread_3m10y_score: 60,
    vix_score: 80,
    put_call_ratio_score: 55,
    sentiment_score: 50,
    employment_score: 75,
    inflation_score: 60,
    monetary_score: 65,
    details: {},
  };

  it("parses valid macro data", () => {
    const result = MacroSchema.parse(valid);
    expect(result.total_score).toBe(65);
    expect(result.interpretation).toBe("Moderately Bullish");
  });

  it("rejects missing total_score", () => {
    const { total_score, ...noScore } = valid;
    expect(() => MacroSchema.parse(noScore)).toThrow();
  });

  it("rejects non-string interpretation", () => {
    expect(() => MacroSchema.parse({ ...valid, interpretation: 42 })).toThrow();
  });

  it("rejects non-numeric score fields", () => {
    expect(() => MacroSchema.parse({ ...valid, vix_score: "high" })).toThrow();
    expect(() => MacroSchema.parse({ ...valid, yield_curve_score: null })).toThrow();
  });

  it("accepts zero scores", () => {
    const zeros = {
      ...valid,
      total_score: 0,
      yield_curve_score: 0,
      yield_spread_3m10y_score: 0,
      vix_score: 0,
      put_call_ratio_score: 0,
      sentiment_score: 0,
      employment_score: 0,
      inflation_score: 0,
      monetary_score: 0,
    };
    const result = MacroSchema.parse(zeros);
    expect(result.total_score).toBe(0);
  });

  it("accepts negative scores", () => {
    const result = MacroSchema.parse({ ...valid, total_score: -10 });
    expect(result.total_score).toBe(-10);
  });

  it("requires all 8 sub-scores", () => {
    const scoreKeys = [
      "yield_curve_score",
      "yield_spread_3m10y_score",
      "vix_score",
      "put_call_ratio_score",
      "sentiment_score",
      "employment_score",
      "inflation_score",
      "monetary_score",
    ];
    for (const key of scoreKeys) {
      const copy = { ...valid };
      delete (copy as Record<string, unknown>)[key];
      expect(() => MacroSchema.parse(copy)).toThrow();
    }
  });
});

// ─── CandidateSchema ────────────────────────────────────────
describe("CandidateSchema", () => {
  const valid = {
    ticker: "NVDA",
    signal_id: "rsi_oversold",
    signal_date: "2026-03-28",
    direction: "BUY" as const,
    confidence: 72.5,
    win_rate: 0.68,
    profit_factor: 2.1,
    regime_fit: true,
    price: 168.0,
    notes: "RSI below 30, strong support",
  };

  it("parses valid candidate data", () => {
    const result = CandidateSchema.parse(valid);
    expect(result.ticker).toBe("NVDA");
    expect(result.direction).toBe("BUY");
    expect(result.regime_fit).toBe(true);
  });

  it("accepts SELL direction", () => {
    const result = CandidateSchema.parse({ ...valid, direction: "SELL" });
    expect(result.direction).toBe("SELL");
  });

  it("rejects invalid direction", () => {
    expect(() => CandidateSchema.parse({ ...valid, direction: "HOLD" })).toThrow();
  });

  it("rejects non-boolean regime_fit", () => {
    expect(() => CandidateSchema.parse({ ...valid, regime_fit: "yes" })).toThrow();
  });

  it("rejects non-numeric price", () => {
    expect(() => CandidateSchema.parse({ ...valid, price: "168.00" })).toThrow();
  });

  it("rejects missing ticker", () => {
    const { ticker, ...noTicker } = valid;
    expect(() => CandidateSchema.parse(noTicker)).toThrow();
  });

  it("accepts regime_fit false", () => {
    const result = CandidateSchema.parse({ ...valid, regime_fit: false });
    expect(result.regime_fit).toBe(false);
  });

  it("accepts zero confidence", () => {
    const result = CandidateSchema.parse({ ...valid, confidence: 0 });
    expect(result.confidence).toBe(0);
  });

  it("accepts empty notes string", () => {
    const result = CandidateSchema.parse({ ...valid, notes: "" });
    expect(result.notes).toBe("");
  });
});

// ─── ScorecardSchema ────────────────────────────────────────
describe("ScorecardSchema", () => {
  const valid = {
    signal_id: "macd_golden",
    total_trades: 150,
    win_rate: 0.62,
    avg_return: 0.035,
    profit_factor: 1.85,
    median_return: 0.028,
    max_return: 0.42,
    max_loss: -0.15,
    avg_holding_days: 12.5,
  };

  it("parses valid scorecard data", () => {
    const result = ScorecardSchema.parse(valid);
    expect(result.signal_id).toBe("macd_golden");
    expect(result.total_trades).toBe(150);
  });

  it("accepts zero trades", () => {
    const result = ScorecardSchema.parse({ ...valid, total_trades: 0 });
    expect(result.total_trades).toBe(0);
  });

  it("accepts negative returns", () => {
    const result = ScorecardSchema.parse({ ...valid, avg_return: -0.05, max_loss: -0.35 });
    expect(result.avg_return).toBe(-0.05);
    expect(result.max_loss).toBe(-0.35);
  });

  it("rejects missing signal_id", () => {
    const { signal_id, ...noId } = valid;
    expect(() => ScorecardSchema.parse(noId)).toThrow();
  });

  it("rejects non-numeric fields", () => {
    expect(() => ScorecardSchema.parse({ ...valid, win_rate: "62%" })).toThrow();
    expect(() => ScorecardSchema.parse({ ...valid, total_trades: "many" })).toThrow();
  });

  it("requires all numeric fields", () => {
    const numericKeys = [
      "total_trades", "win_rate", "avg_return", "profit_factor",
      "median_return", "max_return", "max_loss", "avg_holding_days",
    ];
    for (const key of numericKeys) {
      const copy = { ...valid };
      delete (copy as Record<string, unknown>)[key];
      expect(() => ScorecardSchema.parse(copy)).toThrow();
    }
  });
});

// ─── RebalanceActionSchema ──────────────────────────────────
describe("RebalanceActionSchema", () => {
  const valid = {
    ticker: "AAPL",
    sector: "Technology",
    action: "REDUCE",
    current_weight: 0.18,
    target_weight: 0.12,
    trade_value: -5000,
    signals: ["rsi_overbought", "sector_overweight"],
    regime_note: "Bear market — reduce risk exposure",
  };

  it("parses valid rebalance action", () => {
    const result = RebalanceActionSchema.parse(valid);
    expect(result.ticker).toBe("AAPL");
    expect(result.signals).toHaveLength(2);
  });

  it("accepts empty signals array", () => {
    const result = RebalanceActionSchema.parse({ ...valid, signals: [] });
    expect(result.signals).toEqual([]);
  });

  it("accepts negative trade_value (sell)", () => {
    const result = RebalanceActionSchema.parse({ ...valid, trade_value: -10000 });
    expect(result.trade_value).toBe(-10000);
  });

  it("accepts positive trade_value (buy)", () => {
    const result = RebalanceActionSchema.parse({ ...valid, trade_value: 3000 });
    expect(result.trade_value).toBe(3000);
  });

  it("rejects non-array signals", () => {
    expect(() => RebalanceActionSchema.parse({ ...valid, signals: "rsi_overbought" })).toThrow();
  });

  it("rejects missing required fields", () => {
    const { sector, ...noSector } = valid;
    expect(() => RebalanceActionSchema.parse(noSector)).toThrow();
  });

  it("accepts zero weights", () => {
    const result = RebalanceActionSchema.parse({
      ...valid,
      current_weight: 0,
      target_weight: 0,
    });
    expect(result.current_weight).toBe(0);
    expect(result.target_weight).toBe(0);
  });
});

// ─── StrategySchema ─────────────────────────────────────────
describe("StrategySchema", () => {
  const valid = {
    regime: "bull_low_vol",
    macro_interpretation: "Moderately Bullish",
    position_sizing: "normal",
    recommended_signals: ["macd_golden", "rsi_oversold"],
    avoid_signals: ["gap_down"],
    sector_preference: ["Technology", "Healthcare"],
    signal_regime_stats: { macd_golden: { win_rate: 0.7, pf: 2.1 } },
    notes: "Favor momentum signals in current regime",
  };

  it("parses valid strategy data", () => {
    const result = StrategySchema.parse(valid);
    expect(result.regime).toBe("bull_low_vol");
    expect(result.recommended_signals).toContain("macd_golden");
  });

  it("accepts empty arrays", () => {
    const result = StrategySchema.parse({
      ...valid,
      recommended_signals: [],
      avoid_signals: [],
      sector_preference: [],
    });
    expect(result.recommended_signals).toEqual([]);
    expect(result.avoid_signals).toEqual([]);
    expect(result.sector_preference).toEqual([]);
  });

  it("accepts empty signal_regime_stats", () => {
    const result = StrategySchema.parse({ ...valid, signal_regime_stats: {} });
    expect(result.signal_regime_stats).toEqual({});
  });

  it("rejects missing regime", () => {
    const { regime, ...noRegime } = valid;
    expect(() => StrategySchema.parse(noRegime)).toThrow();
  });

  it("rejects non-string position_sizing", () => {
    expect(() => StrategySchema.parse({ ...valid, position_sizing: 42 })).toThrow();
  });

  it("rejects non-array recommended_signals", () => {
    expect(() => StrategySchema.parse({ ...valid, recommended_signals: "macd_golden" })).toThrow();
  });

  it("accepts nested signal_regime_stats", () => {
    const result = StrategySchema.parse({
      ...valid,
      signal_regime_stats: {
        rsi_oversold: { win_rate: 0.65, pf: 1.9, trades: 50 },
        macd_golden: { win_rate: 0.7, pf: 2.1, trades: 80 },
      },
    });
    expect(Object.keys(result.signal_regime_stats)).toHaveLength(2);
  });

  it("accepts empty notes", () => {
    const result = StrategySchema.parse({ ...valid, notes: "" });
    expect(result.notes).toBe("");
  });
});
