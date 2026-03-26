import { z } from "zod";

// === Regime ===
export const RegimeSchema = z.object({
  date: z.string(),
  trend: z.enum(["bull", "bear", "sideways"]),
  volatility: z.enum(["high", "low"]),
  regime: z.string(),
  confidence: z.number(),
  details: z.record(z.string(), z.unknown()),
});
export type Regime = z.infer<typeof RegimeSchema>;

// === Macro ===
export const MacroSchema = z.object({
  date: z.string(),
  total_score: z.number(),
  interpretation: z.string(),
  yield_curve_score: z.number(),
  vix_score: z.number(),
  sentiment_score: z.number(),
  employment_score: z.number(),
  inflation_score: z.number(),
  monetary_score: z.number(),
  details: z.record(z.string(), z.unknown()),
});
export type Macro = z.infer<typeof MacroSchema>;

// === Candidate ===
export const CandidateSchema = z.object({
  ticker: z.string(),
  signal_id: z.string(),
  signal_date: z.string(),
  direction: z.enum(["BUY", "SELL"]),
  confidence: z.number(),
  win_rate: z.number(),
  profit_factor: z.number(),
  regime_fit: z.boolean(),
  price: z.number(),
  notes: z.string(),
});
export type Candidate = z.infer<typeof CandidateSchema>;

// === Scorecard ===
export const ScorecardSchema = z.object({
  signal_id: z.string(),
  total_trades: z.number(),
  win_rate: z.number(),
  avg_return: z.number(),
  profit_factor: z.number(),
  median_return: z.number(),
  max_return: z.number(),
  max_loss: z.number(),
  avg_holding_days: z.number(),
});
export type Scorecard = z.infer<typeof ScorecardSchema>;

// === Rebalance Action ===
export const RebalanceActionSchema = z.object({
  ticker: z.string(),
  sector: z.string(),
  action: z.string(),
  current_weight: z.number(),
  target_weight: z.number(),
  trade_value: z.number(),
  signals: z.array(z.string()),
  regime_note: z.string(),
});
export type RebalanceAction = z.infer<typeof RebalanceActionSchema>;

// === Strategy ===
export const StrategySchema = z.object({
  regime: z.string(),
  macro_interpretation: z.string(),
  position_sizing: z.string(),
  recommended_signals: z.array(z.string()),
  avoid_signals: z.array(z.string()),
  sector_preference: z.array(z.string()),
  signal_regime_stats: z.record(z.string(), z.unknown()),
  notes: z.string(),
});
export type Strategy = z.infer<typeof StrategySchema>;
