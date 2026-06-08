# tests/ — Testing Conventions

## DB Isolation Pattern

Every test gets its own SQLite DB via `tmp_path` fixture:

```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```

Pass `db_path` to ALL DB functions. Never use the real `data/portfolio.db`.

## Global Mocks (conftest.py, autouse)

- `yfinance.download` → empty DataFrame
- `yfinance.Ticker` → stub with None attributes

All tests run **network-free**. Override per-test if needed, but never remove global mocks.

## Slow Marker

11 LLM/heavy tests marked `@pytest.mark.slow`. PR CI excludes via `-m "not slow"`.
- `make test-fast` — excludes slow (~24s)
- `make test-slow` — slow only
- `make test` — full suite (~50s)

## Gotchas

### runpy + mock
`runpy.run_module()` re-executes module source, **invalidating all mocks**. Use `patch("source.module.function")` for source-level patching, not `patch("target.module.function")`.

### OpenBB local import
`obb` is imported inside functions. `patch("module.obb")` fails. Use:
```python
patch.dict(sys.modules, {"openbb": mock_module})
```

### vi.mock() hoisting (frontend tests)
`vi.mock("recharts")` affects ALL dynamic imports in the same vitest worker. Keep recharts-dependent and recharts-free tests in **separate files**.

### Time-bomb seed dates (relative `now`-window queries)
코드가 `date('now', '-N days')` 윈도우 + 최소 행 수 임계값으로 필터하면(예: `buy_candidate_emitter._get_price_signals`, 45일 윈도우 + `len(grp) < 6` skip), **고정 절대일로 seed한 fixture 는 wall-clock 이 지나며 윈도우 밖으로 밀려 silent 하게 누락**된다. 합성 가격/날짜 fixture 의 `end` 는 항상 `today_kst()` 로 앵커링 — 리터럴 날짜 금지. (#721: `end="2026-04-30"` → 39일 후 scored=0 회귀)
**Test:** `tests/trading/recommend/test_buy_candidate_emitter.py::test_vix_caution_halves_allocation` (+`test_emit_above_threshold`, `test_allocation_split_by_score`) — 고정일로 되돌리면 즉시 FAIL.

## Privacy in Test Data

Never use real broker names, holdings, prices, or account identifiers. Use placeholders: `Brokerage Alpha`, `Brokerage Beta`, round-million values like `1_000_000`.
