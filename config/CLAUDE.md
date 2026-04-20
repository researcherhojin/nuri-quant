# config/ — YAML Configuration

**Canonical source of truth** for investment rules, agent thresholds, signal metadata, and account strategy profiles. Python code **never hardcodes** these values — always read from the corresponding loader in `nuri/core/`. (§2.2 mechanical execution.)

## File inventory

| File | Lines | Purpose | Loader |
|------|-------|---------|--------|
| `rules.yaml` | 273 | Investment rules (stop-loss, take-profit, position limits, VIX gate, `account_strategies`, `siege_gates` incl. `regime_overrides`) | `nuri/core/rules.py` |
| `agents.yaml` | 235 | Per-agent thresholds + confidence scale normalization + 10-agent consensus params | `nuri/core/agent_config.py` |
| `signals.yaml` | 186 | 20 signal definitions (type, hold_days, params). Detector code in `nuri/quant/validation/signal_backtest.py` | `nuri/core/signal_config.py` |
| `alerts.yaml` | 24 | Alert thresholds + channel toggles (discord/telegram) + notification types | Direct YAML load |
| `stock_types.yaml` | 49 | Manual growth/value ticker override (bypasses auto-classification from PE + sector) | Direct YAML load |
| `universe.yaml` | 755 | 746 tickers: `us_core` (85) + `us_sp500_extended` (458) + `kr_kospi200` (203). Auto-maintained by `make universe-sync`; manual entries preserved | `nuri/collectors/universe_sync.py` |
| `portfolio.example.yaml` | 39 | Example template showing account + holdings shape | `scripts/import_portfolio.py` (via `cp` to `portfolio.yaml`) |
| `portfolio.yaml` | user | Real portfolio — **gitignored** (account labels, holdings, avg price). Shape matches `portfolio.example.yaml` | `scripts/import_portfolio.py` |
| `kis/` | — | KIS Open API credentials directory — **gitignored** (`kis_devlp.yaml`, token cache). `.gitkeep` only is tracked. Legacy `~/KIS/` also supported for backward compat | `nuri/collectors/kis_*.py` |

## Change procedure

1. Edit the YAML file.
2. If it's a trading rule (`rules.yaml` / `signals.yaml`): run the relevant backtest to verify intended effect.
3. `make test` — confirm no loader breakage or test fixture drift.
4. Commit the YAML change **separately** from code changes when possible — makes diffs easier to review and bisect.
5. If you're also changing a Python-exposed constant (e.g. `STOCK_STOP_LOSS`), update the loader in `nuri/core/` AND the callers. Don't silently leave YAML and code out of sync.

## Account strategy profiles (authoritative in `rules.yaml`)

| Strategy | stop_loss | max_single_position | max_sector_exposure | Extra |
|----------|-----------|---------------------|---------------------|-------|
| `core` | -7% | 15% | 35% | Default |
| `active` | -10% | 25% | 45% | `trailing_stop_arm: 15` (auto-arm trailing stop at +15%) |
| `swing` | -15% | 30% | 50% | — |
| `long_term` | -20% | 25% | 50% | — |
| `pension` | -30% | 40% | 60% | — |

Each `portfolio.yaml` account chooses via `strategy:` field. Default = `core`. Cross-referenced in `docs/STRATEGY.md §3.5`.

## Schema landmarks

### `agents.yaml` — per-agent confidence shape

Every agent (except `korean_market` which uses absolute scores) has a `confidence:` sub-block with a repeating shape:

```yaml
<agent_name>:
  # agent-specific scoring thresholds (pe_undervalued, rsi_oversold, etc.)
  score_buy: N
  score_sell: -N
  confidence:
    cap: NN                  # upper bound for both BUY and SELL (some agents split: buy_cap / sell_cap)
    buy_base: NN             # BUY confidence baseline
    buy_multiplier: NN       # × score → BUY confidence
    sell_base: NN            # SELL confidence baseline
    sell_multiplier: NN
    hold_base: NN
    hold_multiplier: NN
    no_data: NN              # fallback when data absent
```

The duplication across 10 agents is **intentional** — each agent's confidence curve is tuned independently, so the shape is shared but the values diverge. Do not DRY this into a shared default without a PR that also updates `agent_config.py` loader and all agent classes.

### `rules.yaml` — global vs. account-scoped stop_loss

`stop_loss.per_stock: -7` (global, loaded as `STOCK_STOP_LOSS`) currently duplicates `account_strategies.core.stop_loss: -7`. If you change one, change both. A future chore PR may collapse these into a single source (derive `STOCK_STOP_LOSS` from `account_strategies.core.stop_loss`).

### `signals.yaml` — detector ↔ metadata split

The YAML only carries **metadata** (type, hold_days, params). The actual signal detector lives in `nuri/quant/validation/signal_backtest.py` as a function. Disabling a signal:

```yaml
rsi_oversold:
  enabled: false   # detector still exists but config_loader filters it out
```

### `rules.yaml` — `siege_gates.asset_class_rules` ordering

Matching is first-match-wins from top to bottom. `default: true` is the fallback and must stay last. When adding a new asset class, insert before `default` and make sure the per-class policy exists under `asset_classes:`.

## Gitignored files

- `portfolio.yaml` — real holdings (privacy, §4.4.1 scanner catches broker name leaks in commits)
- `kis/*` except `.gitkeep` — KIS credentials

Both directories must keep their tracked sentinel (`portfolio.example.yaml` for shape reference, `kis/.gitkeep` for directory preservation) so fresh clones don't lose the path.
