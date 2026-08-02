# nuri/collectors/ — 27 Data Collectors

## BaseCollector Contract

All collectors inherit `BaseCollector` (`base.py`):

1. Implement `collect(**kwargs) -> Any` — fetch data from external source
2. Implement `save(data) -> int` — persist to DB via `nuri/core/db/` package functions
3. External code calls `run()` which does `collect()` → `save()` with logging and timing

## Korean Ticker `.KS` Suffix Convention (canonical)

Korean equities are addressed by KRX 6-digit code suffixed with `.KS` (e.g., `005930.KS` for 삼성전자). yfinance accepts the suffix and returns:

- ✅ Price history (`Ticker.history`), volume, dividend events
- ✅ Fundamentals (`Ticker.info`) for individual stocks: PE, ROE, margins, growth, debt — **but `trailingPE` is NOT provided for KR individuals** (yfinance provider limit). Use `forward_pe` instead (182/209 KR coverage as of 2026-07-08 dev DB — live number, re-probe before citing).
- ❌ Fundamentals for ETFs return empty (expected — ETF wrapper, no underlying P&L).

KIS Open API is NOT needed for KR fundamentals (was previously believed required — corrected during #418 KIS Open API integration audit).

## Ticker Filtering + Source

`_get_tickers(market=, source=)` (#272 Phase 2b):
- `market`: `"us"` (excludes KR) | `"kr"` (KR only) | `None` (전체). KR 판정은 canonical `is_kr_ticker()` — `.KS` **및** `.KQ` (#764). `.KS` 로만 필터하면 KOSDAQ 이 kr 에서 누락되고 동시에 `not .KS` 인 us 로 새어 미국장 시간대(KOSDAQ 휴장)에 수집된다.
  **Test:** `tests/collectors/test_base.py::TestGetTickers::test_kosdaq_routes_to_kr_not_us` — 양방향 잠금(한쪽만 보면 반대 회귀가 통과한다).
- `source`: `"portfolio"` (default, 보유종목 — `SELECT FROM portfolio`) | `"universe"` (`config/universe.yaml` 전체 ~746) | `"all"` (union)

CLI: `--source` flag is the standard way to switch (stock, stock_kr, fundamental, wallstreet, estimates, technical, events, news).

**KR reference tickers bypass `source` entirely.** `stock_kr.collect()` unions `_reference_tickers()` (derived from `rules.yaml brief.benchmark.kr`) into every run. The KR benchmark is not a holding, so `portfolio` misses it, and `universe.yaml` is auto-synced from KRX constituents so a hand-added ETF is wiped by the next `make universe-sync` — it was collected by neither path and sat at **0 rows in production** while four consumers read it (brief benchmark, sector-mover fallback, events, risk_signals). Derived from config, not a second hardcoded list, so changing the benchmark moves collection with it.
**Test:** `tests/collectors/test_stock_kr.py::TestStockKRCollectorScenarios::test_collect_without_kr_holdings_still_gets_reference` — dropping the union returns an empty frame again.

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

## Freshness Sentinel Redundancy (#453/#454, post-#457)

SIEGE freshness gate (`certification.py::_check_freshness_for_class`) reads **`prices` only**. `--source freshness` (#457) feeds SPY/TLT/GC=F into `prices` daily. Two known redundancies:

- **`gold` lives in two tables**: `macro.indicator='gold'` (~5Y backfill, 304 rows as of 2026-07-08 — grows daily) AND `prices."GC=F"` (`period=5d` freshness pass, accumulates daily via upsert). Same yfinance source, separate writers (`macro.py` vs `stock.py --source freshness`, wired daily as `stock_us_freshness` in `scheduler.py` #860). No current historical consumer of `prices."GC=F"` beyond the gate, so single-source-of-truth not enforced — accept as debt.
- **TLT shallow history**: `prices.TLT` comes only from the `period=5d` freshness pass. If a future backtest/analysis needs TLT 5Y, add TLT to `universe.yaml` (don't promote freshness gate to dual-source — drift risk per #454 codex consult 2026-04-28).

**Why not dual-source the gate** (option A in #454, rejected): if gate accepts `macro.gold` 37h-fresh while a downstream consumer reads stale `prices."GC=F"`, gate PASS but downstream gets stale data → silent split-brain. Single-source gate = single truth.
