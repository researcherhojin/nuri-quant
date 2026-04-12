# config/ — YAML Configuration

All rules, thresholds, and metadata live here. **Never hardcode** these values in Python code.

## Change Procedure

1. Edit the YAML file
2. Verify with backtest if it's a trading rule (`config/rules.yaml`)
3. Run `make test` to confirm nothing breaks
4. Commit the YAML change (separate from code changes when possible)

## Files

| File | Purpose | Loaded by |
|------|---------|-----------|
| `rules.yaml` | Investment rules (stop-loss, take-profit, position limits, execution_priority) | `nuri/core/rules.py` |
| `agents.yaml` | Agent weights, thresholds (RSI, PE, confidence caps), normalization scales | `nuri/core/agent_config.py` |
| `signals.yaml` | Signal metadata (thresholds, categories, hold_days, buy/sell type) | `nuri/core/signal_config.py` |
| `alerts.yaml` | Alert thresholds (price swing 3%, F&G bounds 20/80), report timing | Direct YAML load |
| `portfolio.yaml` | Accounts + holdings (gitignored for real data, committed for test/demo) | `scripts/import_portfolio.py` |
| `stock_types.yaml` | Growth/value override per ticker → controls stop-loss/take-profit thresholds | Direct YAML load |

## Account Strategy Profiles (in rules.yaml)

Each `portfolio.yaml` account selects a strategy via `strategy:` field:
- `core` (-7% stop, 15% max position) — default
- `active` (-10% stop, 25% max, trailing_stop_arm at +15%)
- `swing` (-15% stop, 30% max)
- `long_term` (-20% stop, 25% max)
- `pension` (-30% stop, 40% max)
