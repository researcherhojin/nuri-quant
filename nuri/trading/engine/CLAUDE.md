# nuri/trading/engine/ — SIEGE Gated Execution

## Confidence Scoring Formula

```
base = regime_win_rate * 60% + profit_factor * 40%
     * drift_multiplier (0.3 ~ 1.1)        <- Learning Memory
     * conflict_penalty (0.5x if high)      <- Conflict Detection
     * regime_fit_penalty (0.4x if avoid)    <- Strategy Map
     * position_penalty (0.3x if minimal)    <- Regime position sizing
     * vix_gate (0x if blocked, 0.5x caution)
```

## SIEGE 11-Gate Specification

All recommendations must pass. 1 error-grade failure = REJECTED.

| # | Condition | Grade | Threshold |
|---|-----------|-------|-----------|
| 1 | position_limit | error | Single stock <= 15% |
| 2 | sector_limit | error | Sector <= 35% |
| 3 | stop_loss_growth | error | Growth -7% enforced |
| 4 | stop_loss_value | error | Value -10% enforced |
| 5 | data_fresh | warning | SPY data <= 72h |
| 6 | leverage_ban | error | No TSLL/TQQQ etc. |
| 7 | vix_gate | warning | VIX > 30 = no new buys |
| 8 | external_data | warning | >= 10 external sources |
| 9 | conflict_free | warning | No BUY/SELL conflict |
| 10 | drift_safe | warning | No critical drift |
| 11 | macro_event_alignment | warning | \|event_score\| >= 10 alert |

## Execution Priority

Mechanical ordering: `stop_loss -> take_profit -> trailing_stop_set -> new_buy`
- Within stop_loss: sort by loss% desc (biggest loss first)
- Within take_profit: sort by excess% desc (biggest winner first)
- Rationale: declining momentum loses more per hour delayed; rising momentum is forgiving
