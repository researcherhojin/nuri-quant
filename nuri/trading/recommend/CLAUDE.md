# nuri/trading/recommend/ — Recommendation Emitters

## Scope

The user-facing output layer: BUY candidates, SELL alerts on holdings, price targets, rebalance actions, and outcome tracking. Per STRATEGY §7.1 this directory **emits recommendations only** — it never submits orders. Output formats: markdown brief, DB row, Discord alert.

## Files

| File | Purpose | Trigger | Issue |
|---|---|---|---|
| `buy_candidate_emitter.py` | Daily 0–5 BUY candidates from factor + momentum + RSI + breakout fusion. Closes the sell-bias gap (7+ sell loops, 0 buy loops). | `make buy-candidates` / scheduler | #507 |
| `holdings_monitor.py` | Post-entry technical-divergence alert (JKHY-class falling-knife defense). REVIEW CTA, never SELL. | scheduler 07:10 KST | PR #303 follow-up |
| `candidates.py` | E-1 signal-based candidate screener (today's signals × historically validated). | `python -m ...candidates` | E-1 |
| `price_targets.py` | entry / stop / TP1 / TP2 / trailing per holding, pulling from `config/rules.yaml` ladders (growth / value / swing). | upstream of every BUY/SELL alert | core |
| `rebalance.py` | E-2 regime-adapted MVO/RP rebalance (defensive vs offensive sector tilt by regime). | `python -m ...rebalance` | E-2 |
| `tracker.py` | E-3 store recommendations + 30/60/90d outcome backfill into `recommendations` table. | scheduler daily + `--save` | E-3 |

## Invariants

- **Recommend, never execute** (§7.1). Output is markdown / DB row / Discord — the user runs the order in their app.
- **Price levels mandatory**: every BUY / SELL recommendation must carry `entry / stop_loss / target_1 / target_2 / trailing` (user-level CLAUDE.md "Price Targets Required"). `price_targets.py` is the canonical source — do not re-derive in callers.
- **rules.yaml is source of truth** for stop / TP / trailing %. Hardcoding any threshold in this directory is a config-discipline violation (CLAUDE.md root §"Always-on Invariants").
- **Outcome tracking writes to `recommendations`, not `agent_decisions`**. The two tables exist by design — see `nuri/trading/CLAUDE.md` "decisions vs agent_decisions" if/when added, or root README for the cross-validation rationale.
- **Dedup window** for re-emission: 7 calendar days per `(ticker, trigger_type)` is the convention (`holdings_monitor.py` baseline). New emitters should match unless they justify otherwise.

## Asset-class scope

| Module | equity_us | equity_kr | crypto | ETF |
|---|---|---|---|---|
| `buy_candidate_emitter` | ✅ | ✅ | — | — |
| `holdings_monitor` | ✅ | ✅ | excluded (different vol profile) | ✅ |
| `candidates` | ✅ | ✅ | — | ✅ |
| `price_targets` | ✅ | ✅ | — | ✅ (with `volatile` ladder) |
| `rebalance` | portfolio-wide | portfolio-wide | — | portfolio-wide |
| `tracker` | universal — any ticker emitted upstream | | | |

## When adding a new emitter

1. Single responsibility: one signal class or one alert type per file.
2. Output format: dataclass list + markdown renderer; the dataclass goes to `recommendations` via `tracker.save()`.
3. Tests under `tests/trading/recommend/` with `tmp_path` DB isolation (see `tests/CLAUDE.md`).
4. Discord alert path: route through `nuri/alerts/` — do not write Discord SDK calls here.
5. Confirm `make buy-candidates` (or equivalent) finishes < 60s on a cold cache; longer means cache the upstream computation.

## References

- STRATEGY §7.1 (auto-trading deferred)
- `config/rules.yaml` — TP/SL/trailing ladders
- `nuri/trading/agents/CLAUDE.md` — consensus pipeline this directory consumes
- `docs/STRATEGY.md §3.7` — alpha vs portfolio action axis (concentration violation routes to REBALANCE, never urgent SELL)
