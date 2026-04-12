# nuri/collectors/ — 24 Data Collectors

## BaseCollector Contract

All collectors inherit `BaseCollector` (`base.py`):

1. Implement `collect(**kwargs) -> Any` — fetch data from external source
2. Implement `save(data) -> int` — persist to DB via `nuri/core/db.py` functions
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

## Ticker Filtering

`_get_tickers(market=)` filters portfolio tickers:
- `"us"` — excludes `.KS` suffix tickers
- `"kr"` — includes only `.KS` suffix tickers

## OpenBB Local Import Pattern

`obb` is imported **inside functions**, not at module level. This means:
- `patch("module.obb")` will FAIL — the name doesn't exist at module level
- Use `patch.dict(sys.modules, {"openbb": mock_module})` for testing

## OpenBB Provider Limitations

| Endpoint | yfinance | Paid alternative |
|----------|----------|-----------------|
| `obb.equity.price.historical` | OK | — |
| `obb.equity.fundamental.metrics` | OK | — |
| `obb.equity.estimates.consensus` | OK | — |
| `obb.equity.fundamental.ratios` | No | `fmp` / `intrinio` |
| `obb.equity.estimates.price_target` | No | `benzinga` / `fmp` |
| `obb.equity.ownership.*` | No | `fmp` |

## Macro Data Quirk

`us_3m_yield` (FRED) is absent in yfinance fallback — `^IRX` (13-week T-Bill) is stored as `us_2y_yield`. `merge_macro_data()` queries `us_2y_yield` when `us_3m_yield` is empty.
