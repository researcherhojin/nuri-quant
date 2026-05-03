# nuri/trading/engine/ — SIEGE Gated Execution

Implementation pointer for SIEGE v2 (3-D certification: Account × Asset Class × Execution Market). Canonical specs live elsewhere — this file documents only what's specific to this directory's implementation.

## Canonical references

- **Gate spec (full)** — `docs/CERTIFICATION_SPEC.md` — 11~30+ variable conditions, asset-class per-expansion logic, evidence tracking.
- **Canonical condition table** — `docs/STRATEGY.md §6` — base + per-asset-class conditions with grades + thresholds.
- **Confidence scoring formula** — `docs/STRATEGY.md §3.3`. Includes Learning-Memory `drift_multiplier`, conflict penalty, regime-fit, VIX gate composition. Phase 4 (safeslice — Wilson CI + witness cliff) replacement is queued; until then the formula in §3.3 is the live one. **Do not duplicate the formula here.**
- **Action-axis split** (`alpha_action` vs `portfolio_action`, PR A #429) — `nuri/core/axis.py` (helpers) + `docs/STRATEGY.md §3.7`. Engine emits both; concentration / sector / leverage violations route to `portfolio_action=REBALANCE` only — never urgent SELL.

## Engine-specific implementation notes

These are operational details unique to this directory; the canonical sources above own the rules themselves.

- **Gate policy lives in `config/rules.yaml siege_gates`** — code reads YAML, never hardcodes thresholds (§2.2).
- **v2 expansion**: gates `data_fresh` / `volatility_gate` / `external_data` group portfolio holdings by `asset_class` and apply per-class policy from `siege_gates.asset_classes.<class>`. Result: `total_conditions` is **11–30+ variable** depending on portfolio composition. A mixed US + KR + ETF portfolio expands to ~23 conditions; an empty / unconfigured portfolio falls back to legacy SPY/VIX single-check.
- **Severity at a glance** — useful when triaging a `certify()` failure without bouncing to STRATEGY §6: error-grade gates are `position_limit` / `sector_limit` / `stop_loss_growth` / `stop_loss_value` / `leverage_ban` (any single fail → REJECTED). Warning-grade gates (do not reject, surface only) are `data_fresh` / `volatility_gate` / `external_data` / `conflict_free` / `drift_safe` / `macro_event_alignment`. Full table with per-class thresholds: `docs/STRATEGY.md §6`.
- **Account-strategy injection**: `account_strategies.<strategy>` (`stop_loss` / `per_position_max` / `max_sector_exposure`) is read by `_check_position_limits` / `_check_sector_limit` / `_check_stop_loss` per holding row. Strategy is determined by the holding's `account` column joined with `portfolio.yaml accounts.<account>.strategy`.
- **Evidence record per gate** — every condition produces `(source, value, threshold, policy_ref)` for OAE traceability and persistence into the `certifications` table (E4-0a, PR #410).
- **Snapshot invariant**: `CertSnapshot` ContextVar threads `(regime, portfolio_df, portfolio_raw, portfolio_hash, portfolio_error)` through all gate internals — single DB read derives the hash that all downstream consumers see. Any new gate must read from the snapshot, not re-fetch.

## Execution Priority

Mechanical ordering when emitting actions: `stop_loss → take_profit → trailing_stop_set → new_buy`.
- Within `stop_loss`: sort by `loss%` descending (biggest loss first — bleeding stops first).
- Within `take_profit`: sort by `excess%` descending (biggest winner first — lock in gains).
- Rationale: declining momentum loses more per hour delayed; rising momentum is more forgiving. Codified in `nuri/trading/engine/execution_priority.py` (or its caller).
