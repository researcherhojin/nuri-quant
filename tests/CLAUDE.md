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

23 LLM/heavy tests marked `@pytest.mark.slow`. PR CI excludes via `-m "not slow"`.
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

## Privacy in Test Data

Never use real broker names, holdings, prices, or account identifiers. Use placeholders: `Brokerage Alpha`, `Brokerage Beta`, round-million values like `1_000_000`.
