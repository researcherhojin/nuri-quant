# nuri/trading/swing/ — Swing Trade Pipeline

## Scope

Short-term (≤ 7 trading days) swing-trade scanner + rule engine. Distinct from `recommend/buy_candidate_emitter.py` (multi-week growth holdings) — swing is faster and exits sooner. Same constraint applies: **recommendations only** (STRATEGY §7.1).

## Files

| File | Purpose |
|---|---|
| `scanner.py` | Universe-wide volume-spike + momentum + breakout scan **read from the `prices` table** — no network call. Universe loaded from `config/universe.yaml` (fallback: hardcoded list). |
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
- **The scanner reads the DB, never the network** (#1119). `_fetch_prices` is a single `prices` query pivoted into the `(ticker, field)` MultiIndex frame `_analyze_ticker` expects — the shape yfinance used to return, so downstream code did not change. It used to be `yf.download(tickers, period=...)`, which put an external network round trip inside `/api/scan`'s request handler (1.7s per request, no cache) and held an AnyIO threadpool slot for the duration. Coverage measured 2026-08-21: **US 85/85, KR 202/203** tickers hold ≥ 60 trading days; a ticker short of that drops out of the frame and `_analyze_ticker` returns None for it. Values are **last collected close**, not live — acceptable for a ≤ 7-day horizon and consistent with the rest of the dashboard. If the scan returns nothing, the collectors have not run (`make collect`), not the network.
- **Scan latency** (measured 2026-08-21, M5 Max, warm DB): us-core 85 → **0.17s**, kr-kospi200 203 → **0.21s**, extended 543 → **0.74s**. No threading needed. (The concurrency-asymmetry rule in `.claude/rules/gotchas.md` still governs the *collectors* that fill `prices`: yfinance 10-thread OK, **KRX/pykrx** sequential + `time.sleep(0.1)`.)
- **Entry requires both gates**: scanner score AND agent consensus BUY. A high score alone never triggers an entry — the consensus pipeline (`nuri/trading/agents/`) is the second filter.
- **Position storage**: swing positions go into the `swing_trades` table (`_MIGRATIONS` in `nuri/core/db_migrations.py`). Do not use the main `portfolio` table — swing has its own lifecycle.
- **Korean ticker `.KS` suffix** (root CLAUDE.md "Gotchas"): `.KS` rows live in `prices` like any other ticker, so the scanner needs no special handling. The quirk still bites the **collectors** that fill it — `trailingPE` is missing for KR individuals, use `forward_pe` if screening by valuation.

## Distinction from `recommend/buy_candidate_emitter.py`

| | swing | buy_candidate_emitter |
|---|---|---|
| Holding horizon | ≤ 7 days | weeks to months |
| Universe | `prices` table (hundreds) | factor-screened (top decile) |
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
