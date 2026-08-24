# nuri/core/ — Foundation Layer

## db/ — Sole sqlite3 Importer

The `nuri/core/db/` package is the **ONLY** `sqlite3` importer (the import lives in `db/connection.py`; PR #566 stage 2 packaging). Enforced by a PreToolUse hook (exit 2 block) **and** by `tests/core/test_sqlite3_sole_importer.py` — the hook only fires when a file is edited through it, so the test is what catches an importer that arrived any other way. All other modules use these functions (all accept optional `db_path` for test isolation):

- `get_db(db_path=)` — context manager, auto-commit/rollback
- `query(sql, params, db_path=)` → `list[dict]` (rows converted via `dict(row)`)
- `query_df(sql, params, db_path=)` → `pandas.DataFrame`
- `upsert_*(data, db_path=)` — per-table upsert functions
- `replace_portfolio_account(account, records, db_path=)` — DELETE+INSERT in one tx
- `OperationalError` / `DatabaseError` — sqlite3 exception types re-exported so callers can catch DB failures narrowly without importing `sqlite3` (widening to `except Exception` swallows real bugs)

⚠️ **`db_path` 를 받는 함수는 자기가 부르는 리더에도 넘겨야 한다.** 파라미터만
선언하고 안 쓰면 그 한 줄만 기본 DB 로 새는데, 서명·타입 체크·테스트가 전부
통과해서 눈으로는 반복해서 놓친다 (#1050/#1051 에서 8곳, 그 뒤 #1052 에서 13곳).
`_resolve_db_path` 가 커넥션마다 `nuri.core.db.DB_PATH` 를 다시 읽는 구조라
테스트의 monkeypatch 가 전역으로 먹지만, **그건 배선 누락을 가려줄 뿐 고치지
않는다** — 격리 DB 대신 다른 DB 를 보게 되는 건 그대로다.
**Test:** `tests/core/test_db_path_forwarding.py::TestDbPathIsForwarded::test_every_db_path_aware_call_receives_it`
— `db_path=db_path` 를 하나 지우면 FAIL.

Schema changes: add to `_MIGRATIONS` list only. Never edit existing migrations.

⚠️ **`init_db()` applies migrations only when something calls it. Opening a connection does not.** `query()` / `query_df()` / `get_db()` read whatever schema the file already has. Long-running daemons call `init_db()` at startup, so a machine whose scheduler restarts regularly stays current for free — but a machine that only pulls code and runs pipeline CLI modules never migrates, and the first write against a new column dies with `sqlite3.OperationalError: no such column: <name>`. Measured 2026-08-20: dev DB sat at `schema_version` 49 while the code was at 54, and `python -m nuri.trading.agents.consensus` crashed on `recommendations.source` (#1078). Production was unaffected (54, 1,606 rows, zero gaps) purely because its daemons cycle. If a pipeline command fails on an unknown column, run `init_db()` before debugging anything else.

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

`FRESHNESS_POLICIES` per data source. `check_freshness(key)` returns PASS/WARN/FAIL. 임계(`warn_hours`/`fail_hours`)는 `config/freshness.yaml` 이 정본이고 `_load_config()` 가 기동 시 주입한다 — 키 목록은 양방향 대조라 config 누락/잉여 둘 다 ValueError (#1180). 쿼리·라벨은 구현이라 코드에 남는다. `VERDICT_GATE_KEYS`/`stale_verdict_inputs()` 는 dashboard verdict 의 stale gate 입력 (FAIL 만 센다 — WARN 은 주말/공휴일 정상 나이).

정책을 추가/삭제하면 `tests/core/test_freshness.py::test_expected_policy_keys` 가 **일부러**
깨진다 — 양방향 allowlist 라 등재할 때 "왜 이 정책이 생겼는지" 한 줄을 그 테스트에 같이
적는다 (#1071 `factors` / #1101 `signals` / #1145 `ark` 가 전례).

⚠️ **정책 쿼리는 소스를 재야지, 우리와 소스의 교집합을 재면 안 된다** (#1147). 보유 종목으로
필터된 테이블(`ark` 가 그랬다)의 `MAX(date)` 는 "소스가 마지막으로 발행한 날"이 아니라
"우리가 마지막으로 겹친 날"이다 — 포트폴리오 구성이 바뀌면 멀쩡한 소스가 낡음으로 오판된다.
수집기가 필터 **이전** 사실을 따로 기록하게 하고(`ark_source_dates`) 정책은 그걸 읽는다.
축이 여러 개인 소스(펀드·시장)는 합산 `MAX` 금지 — 멀쩡한 축이 죽은 축을 가린다
(`signals` 의 KR/US 분리, `ark` 의 `COUNT(*)=5` + 펀드별 MIN 이 같은 원칙).

## pipeline.py — Orchestration

`STEP_DEPENDENCIES` defines the 5-stage DAG (`collect → analyze → consensus → certify → track`). `run_step()` enforces dependency completion.

## rules.py / signal_config.py / agent_config.py

Load YAML from `config/`. Rules, signal definitions, and agent thresholds are never hardcoded — always in `config/*.yaml`.
