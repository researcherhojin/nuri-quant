# nuri/collectors/ — 24 Data Collectors

## BaseCollector Contract

All collectors inherit `BaseCollector` (`base.py`):

1. Implement `collect(**kwargs) -> Any` — fetch data from external source
2. Implement `save(data) -> int` — persist to DB via `nuri/core/db.py` functions
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

## Ticker Filtering + Source

`_get_tickers(market=, source=)` (#272 Phase 2b):
- `market`: `"us"` (no `.KS`) | `"kr"` (only `.KS`) | `None` (전체)
- `source`: `"portfolio"` (default, 보유종목 — `SELECT FROM portfolio`) | `"universe"` (`config/universe.yaml` 전체 ~746) | `"all"` (union)

CLI: `--source` flag is the standard way to switch (stock, stock_kr, fundamental, wallstreet, estimates, technical, events, news).

## Parallelism Pattern (yfinance vs KRX) ⚠️

**yfinance**: 10 concurrent threads OK. Use `ThreadPoolExecutor(max_workers=10)`.
**KRX (pykrx)**: rate-limits aggressively. Use sequential + 100ms delay.

| Collector | Source | Parallelism | Why |
|-----------|--------|-------------|-----|
| stock, fundamental, wallstreet, estimates | yfinance | **10 threads** | API tolerates concurrency |
| stock_kr | pykrx (KRX) | **sequential + 0.1s sleep** | First ~60 fast then server hangs |
| ark, finviz | yfinance/finviz | small loop | <20 items, no benefit |

Standard parallel pattern (consistent across yfinance collectors):
```python
def _fetch_one(ticker: str) -> tuple[str, ...]:
    """Returns (ticker, result, status)."""
    ...

with ThreadPoolExecutor(max_workers=10) as ex:
    futures = {ex.submit(_fetch_one, t): t for t in tickers}
    for fut in tqdm(as_completed(futures), total=len(tickers), desc=...):
        ticker, result, status = fut.result()
        ...  # aggregate in main thread
```

ThreadPoolExecutor caveat: `.result(timeout=)` cancels FUTURE only — underlying C extension call (e.g. pykrx) keeps running. **Don't rely on timeout for cancellable hangs**. Sequential + delay for hanging APIs (KRX).

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
