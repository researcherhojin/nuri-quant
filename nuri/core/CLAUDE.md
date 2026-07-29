# nuri/core/ — Foundation Layer

## db/ — Sole sqlite3 Importer

The `nuri/core/db/` package is the **ONLY** `sqlite3` importer (the import lives in `db/connection.py`; PR #566 stage 2 packaging). Enforced by a PreToolUse hook (exit 2 block) **and** by `tests/core/test_sqlite3_sole_importer.py` — the hook only fires when a file is edited through it, so the test is what catches an importer that arrived any other way. All other modules use these functions (all accept optional `db_path` for test isolation):

- `get_db(db_path=)` — context manager, auto-commit/rollback
- `query(sql, params, db_path=)` → `list[dict]` (rows converted via `dict(row)`)
- `query_df(sql, params, db_path=)` → `pandas.DataFrame`
- `upsert_*(data, db_path=)` — per-table upsert functions
- `replace_portfolio_account(account, records, db_path=)` — DELETE+INSERT in one tx
- `OperationalError` / `DatabaseError` — sqlite3 exception types re-exported so callers can catch DB failures narrowly without importing `sqlite3` (widening to `except Exception` swallows real bugs)

Schema changes: add to `_MIGRATIONS` list only. Never edit existing migrations. `init_db()` auto-applies.

## timezone.py — All Time is KST

**Never use `datetime.now()` directly** — enforced by PostToolUse hook.

- `kst_now()` — current datetime in KST
- `today_kst()` — today's date string (YYYY-MM-DD) in KST
- `to_kst(dt)` — convert any datetime to KST

DB stores dates as `YYYY-MM-DD` strings.

## events.py — Pipeline Event Journal

Append-only. `emit_event()` records state transitions (step_started/completed/failed/blocked). `causation_id` for chain tracing. Never delete events.

Two guarantees hold here, and both are load-bearing for readers elsewhere:

- **`payload` is always valid JSON.** Twelve queries read that column through `json_extract()`, and SQLite raises `OperationalError: malformed JSON` instead of skipping the row — and those queries *scan* the table rather than filtering to their own rows, so one poisoned row kills every unrelated lookup (holdings dedupe, trim age, eight BUY-candidate predicates). All sit under scheduler wrappers that catch and log, so it surfaces as a quiet no-op. `emit_event` therefore `json.dumps()` **every** payload shape, with `default=str` so a non-serializable value cannot raise inside the writer and abort the caller's real work (#935/#894).
- **`emit_event()` is the only writer.** The guarantee above rests on it. Never `INSERT INTO pipeline_events` directly from `nuri/`.

**Test:** `tests/core/test_pipeline_events.py::TestEmitEventAlwaysWritesValidJson::test_json_extract_scan_survives_every_payload_shape` (the per-row `json_valid` check is not enough — the real failure is a query looking for *something else* dying as it passes a poisoned row) and `::TestPipelineEventsSingleWriter::test_only_events_module_inserts` (AST sweep + a canary, since a sweep that silently matches nothing passes as happily as one that matches everything).

## freshness.py — Data Freshness SLA

`FRESHNESS_POLICIES` per data source (prices 48h/120h, VIX 24h/72h, etc.). `check_freshness(key)` returns PASS/WARN/FAIL.

## pipeline.py — Orchestration

`STEP_DEPENDENCIES` defines the 5-stage DAG (`collect → analyze → consensus → certify → track`). `run_step()` enforces dependency completion.

## rules.py / signal_config.py / agent_config.py

Load YAML from `config/`. Rules, signal definitions, and agent thresholds are never hardcoded — always in `config/*.yaml`.
