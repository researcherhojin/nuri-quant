# nuri/trading/strategy/ — Regime-Adaptive Strategy Engines

## Scope

Strategy-level decision modules. Each file is a self-contained strategy that consumes regime classification + price/portfolio data and emits direction / position-sizing decisions. **All output is recommendation-only** (STRATEGY §7.1).

## Files

| File | Strategy | Output |
|---|---|---|
| `longshort.py` | Regime-driven direction switch (bull → long, bear → inverse ETF, sideways → cash). | per-regime allocation `{long_pct, short_pct, cash_pct}` from `REGIME_ALLOCATION` table |
| `ls_backtest.py` | 5-year backtest of `longshort` strategy. Includes `--stress` for crisis-window analysis. | report under `data/reports/` |
| `mean_reversion.py` | BB-band lower break + RSI < 30 entry, BB midline / 5-day exit. | `MeanRevSignal` list |
| `pairs.py` | Correlation-pair Z-score divergence (ρ ≥ 0.7, Z > 2.0 → long underperformer / short outperformer). | pair signals |
| `position.py` | SIEGE certification gate enforcement at position-entry time + P&L tracking. | `PositionCertification` dataclass |
| `monitor.py` | Regime transition detection + position-switch alert + daily P&L surface. | dict / Discord alert payload |
| `strategic_allocation.py` | SAA long-term policy mix per account strategy (STRATEGY §3.10). | target weights from `config/rules.yaml strategic_allocation_targets` |

## Invariants

- **REGIME_ALLOCATION lives in `longshort.py`**, not config. Reason: the table encodes a research result (O'Neil + Minervini + 6-site review on 2026-03-28), not a tunable threshold. Changes require a STRATEGY PR with backtest evidence (STRATEGY §6 promotion gate).
- **Strategies do not write to `recommendations`**. They emit dataclass signals consumed by `nuri/trading/recommend/` modules, which decide what reaches the user.
- **`position.py` SIEGE gate ≠ `nuri/trading/engine/` SIEGE certification**. This file's gate is a thin enforcement helper at the strategy layer (regime-aligned, agent-consensus, factor-rank, drawdown, sector-cap). The full 11–30+ condition certification lives in `engine/`. Do not duplicate logic — call into engine when full certification is needed.
- **Mean-reversion + pairs are research-grade**, not production daily emitters. They run on demand; promotion to scheduler requires win-rate evidence per STRATEGY §6.

## Regime dependency

All strategies in this directory depend on `nuri.quant.regime.classifier.classify_regime()`. Regime keys total 10 = `BASE_REGIMES` 6 (`{bull,bear,sideways}_{low,high}_vol`) + `SPECIAL_REGIMES` 4 (`recovery`, `euphoria`, `stagflation`, `sector_rotation`) — `ALL_REGIMES` in `classifier.py` is the source of truth, and `REGIME_ALLOCATION` carries all 10 keys. Adding a regime requires updating `REGIME_ALLOCATION` in `longshort.py` and re-running `ls_backtest.py --stress`.

## Pyright disabled per file

Several files lead with `# pyright: ...=false` directives. These suppress pandas / numpy strict-typing noise, not real type errors. New files should follow the same pattern only when the suppression is data-frame-related — not as a general license to skip typing.

## When adding a new strategy

1. New file: `nuri/trading/strategy/<name>.py` with dataclass output + `__main__` CLI for ad-hoc runs.
2. Backtest: matching `<name>_backtest.py` showing Sharpe / max drawdown / regime-conditional win rate over ≥ 5 years.
3. Promotion gate: SIEGE-style review per STRATEGY §6 + Codex `/codex review` before scheduler integration.
4. Tests under `tests/trading/strategy/`.

## References

- Regime classifier: `nuri/quant/regime/classifier.py` (`ALL_REGIMES` = 6 base + 4 special, source of all regime keys)
- SIEGE engine (full certification): `nuri/trading/engine/CLAUDE.md`
- O'Neil / Minervini investment rules: user-level CLAUDE.md "Investment Rules"
- Strategy promotion criteria: `docs/STRATEGY.md §6`. safeslice replacement backlog: `docs/CERTIFICATION_SPEC.md` Phase 4 (drift_multiplier → Wilson CI + witness cliff)
