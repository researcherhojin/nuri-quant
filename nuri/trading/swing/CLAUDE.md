# nuri/trading/swing/ — Swing Trade Pipeline

## Scope

Short-term (≤ 7 trading days) swing-trade scanner + rule engine. Distinct from `recommend/buy_candidate_emitter.py` (multi-week growth holdings) — swing is faster and exits sooner. Same constraint applies: **recommendations only** (STRATEGY §7.1).

## Files

| File | Purpose |
|---|---|
| `scanner.py` | Universe-wide volume-spike + momentum + breakout scan via yfinance batch download. Universe loaded from `config/universe.yaml` (fallback: hardcoded list). |
| `rules.py` | Entry / exit decision engine. Uses scanner score + agent consensus to gate entries; `--check` flag scans existing swing positions for exit triggers. |

## Swing rules (constants in `rules.py`, sourced from `config/rules.yaml`)

| Rule | Default | Source |
|---|---|---|
| Min scan score (entry) | `SWING_MIN_SCAN_SCORE` (20) | `config/rules.yaml` |
| Min agent confidence (entry) | `SWING_MIN_AGENT_CONFIDENCE` (50) | `config/rules.yaml` |
| Take profit | `+10%` (`TAKE_PROFIT_SWING.target_2`) | `config/rules.yaml` swing ladder |
| Stop loss | `-5%` (`SWING_STOP_LOSS`) | `config/rules.yaml` swing ladder |
| Max holding | `7` trading days (`SWING_MAX_HOLD_DAYS`) | `config/rules.yaml` |
| Early exit | agent consensus SELL | rules.yaml + agents/consensus output |

The user-level rule for swing is `-5% stop / +5% TP1 (sell 50%) / +10% TP2 (sell all)` (CLAUDE.md root "Investment Rules"). `rules.py` mirrors this — do not introduce a parallel ladder.

## Invariants

- **Universe is YAML-driven**: `scanner.py` reads `config/universe.yaml`. The hardcoded fallback exists for cold-start dev; production runs always load YAML.
- **Scan latency**: us-core (~85 tickers) target < 5s. Extended (~543) < 30s. The scanner needs no threading — it is a single `yf.download(tickers, ...)` batch call (the concurrency-asymmetry rule in `.claude/rules/gotchas.md` allows yfinance 10-thread; it is **KRX/pykrx** that must stay sequential + `time.sleep(0.1)`).
- **Entry requires both gates**: scanner score AND agent consensus BUY. A high score alone never triggers an entry — the consensus pipeline (`nuri/trading/agents/`) is the second filter.
- **Position storage**: swing positions go into the `swing_trades` table (`_MIGRATIONS` in `nuri/core/db_migrations.py`). Do not use the main `portfolio` table — swing has its own lifecycle.
- **Korean ticker `.KS` suffix** (root CLAUDE.md "Gotchas"): scanner handles `.KS` natively via yfinance, but `trailingPE` is missing for KR individuals — use `forward_pe` if scanning by valuation.

## Distinction from `recommend/buy_candidate_emitter.py`

| | swing | buy_candidate_emitter |
|---|---|---|
| Holding horizon | ≤ 7 days | weeks to months |
| Universe | yfinance batch (hundreds) | factor-screened (top decile) |
| Exit | scanner-driven (TP/SL/time) | trailing-stop + thesis change |
| Position table | `swing_trades` | `portfolio` |
| Trigger frequency | continuous (intraday capable) | daily morning |

When a candidate qualifies for both, swing wins for the swing position; the multi-week thesis can still hold separately in `portfolio`.

## When extending

1. New scan filter: add to `scanner.py` as a scoring contributor, document the +N points it adds.
2. New exit rule: add a constant to `config/rules.yaml`, import via `nuri.core.rules`, wire into `rules.py --check`.
3. Backtest new rule changes against ≥ 1 year of swing-position history before merging.

## References

- Universe YAML: `config/universe.yaml` (validation: `scripts/doc/validate_universe.py`)
- Swing ladder rules: `config/rules.yaml` swing section
- Agent consensus (entry gate): `nuri/trading/agents/CLAUDE.md`
- Make targets for daily ops: `make scan` / `scan-extended` / `scan-kr` (scanner), `make swing` / `make swing-check` (rules)
