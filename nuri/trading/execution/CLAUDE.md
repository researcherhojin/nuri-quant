# nuri/trading/execution/ — Broker Adapter Layer

## Scope

Abstract broker interface + paper-trading implementations. **Recommendation system, not auto-trader** — STRATEGY §7.1 keeps order execution permanently deferred. Real money is moved by the user, manually, in their broker app.

This directory exists for backtesting + paper-trading dry runs only. Live `submit_order()` against any real broker is out of scope unless STRATEGY §7.1 is reverted via PR.

## Files

| File | Purpose |
|---|---|
| `broker.py` | `BrokerAdapter` ABC + `Order` dataclass + `AlpacaAdapter` (paper-only via `ALPACA_BASE_URL=paper-api.alpaca.markets`). `--dry-run` is the only sanctioned execution mode. |

## Invariants

- **Paper-only**. Never point `ALPACA_BASE_URL` at the live endpoint. CI / hooks do not enforce this — it's a discipline rule. If you need live execution for a backtest replay, document the rationale in the calling script.
- **Order persistence**: `Order` is an in-memory dataclass. If you need durable order history, add a migration to `_MIGRATIONS` in `nuri/core/db_migrations.py` (forward-only) — do not write a parallel SQLite from this directory.
- **`kst_now()` only** for `Order.timestamp` (hook-enforced, but worth restating since this module formats timestamps for downstream display).

## When to expand this directory

Adding a new broker (e.g., KIS Open API write-side, IBKR) requires:
1. STRATEGY PR re-approving `auto_trading_deferred=False` for that broker scope.
2. New adapter class inheriting `BrokerAdapter` with the same `submit_order` / `get_position` / `cancel_order` contract.
3. Integration tests under `tests/trading/execution/` that exercise `--dry-run` only by default.

KIS Open API **read-side** (account/position queries) belongs in `nuri/collectors/` — it's data collection, not execution.

## References

- Auto-trading deferred: `docs/STRATEGY.md §7.1`
- Order priority (when execution does happen, e.g., paper backtest): `nuri/trading/engine/CLAUDE.md` "Execution Priority"
