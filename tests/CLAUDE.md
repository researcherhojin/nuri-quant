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

24 LLM/heavy tests marked `@pytest.mark.slow` (collected count — marker sites expand via class-level marks / parametrize). PR CI excludes via `-m "not slow"`.
- `make test-fast` — excludes slow (~98s, M5 Max 2026-07-08)
- `make test-slow` — slow only
- `make test` — full suite (test-fast + slow 24)

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

### Toss FX not covered by global yfinance mock
conftest 전역 mock 은 **yfinance 만** 커버. `MacroCollector.collect()` 는 `_collect_toss_fx()` 로 실 HTTP 를 타므로 `collect()` 를 부르는 테스트는 `_collect_toss_fx` 를 명시 stub 해야 한다. toss 성공 시 usd_krw source='toss' 가 FRED 를 override 하는 건 **의도된 우선순위**라 'FRED 여야 함' assertion 이 네트워크 상태 따라 flaky 했음 (#829).
**Test:** `tests/collectors/test_macro.py::TestMacroCollectorTossFX::test_collect_toss_overrides_fred_usd_krw_in_db` — toss-성공 시나리오를 mock 으로 결정론 고정 (DB 최종 상태까지 lock).

### Time-bomb seed dates (relative `now`-window queries)
코드가 `date('now', '-N days')` 윈도우 + 최소 행 수 임계값으로 필터하면(예: `buy_candidate_emitter._get_price_signals`, 45일 윈도우 + `len(grp) < 6` skip), **고정 절대일로 seed한 fixture 는 wall-clock 이 지나며 윈도우 밖으로 밀려 silent 하게 누락**된다. 합성 가격/날짜 fixture 의 `end` 는 항상 `today_kst()` 로 앵커링 — 리터럴 날짜 금지. (#721: `end="2026-04-30"` → 39일 후 scored=0 회귀)
**Test:** `tests/trading/recommend/test_buy_candidate_emitter.py::test_vix_caution_halves_allocation` (+`test_emit_above_threshold`, `test_allocation_split_by_score`) — 고정일로 되돌리면 즉시 FAIL.

## Privacy in Test Data

Never use real broker names, holdings, prices, or account identifiers. Use placeholders: `Brokerage Alpha`, `Brokerage Beta`, round-million values like `1_000_000`.
