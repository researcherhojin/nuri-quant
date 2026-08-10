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

**2차 발생 (2026-08-10)** — 규칙이 여기 적혀 있었는데도 `tests/trading/recommend/conftest.py` 의
`rich_db` 가 `bdate_range("2024-06-01", periods=500)` 로 리터럴 시작일을 썼다. 윈도우 끝
2026-05-01, 소비 테스트는 `now - 95일` 조회 → **2026-08-05 부터 `test_90d_tracking` 이
결정론적으로 FAIL**. 위 잠금 테스트가 안 잡은 이유는 그게 **emitter 경로만** 덮고 tracker
경로(`track_outcomes`)는 안 덮기 때문 — 규칙 하나에 잠금이 한 경로만 걸려 있으면 나머지
경로는 무방비다. 새 fixture 를 쓰는 소비 경로가 생기면 잠금도 같이 늘릴 것.
- 5일간 아무도 몰랐던 이유는 별개 결함이다: `.github/workflows/main-ci-cd.yml` 의
  `run_backend` 경로 필터가 **문서-only PR 에서 백엔드 shard 를 테스트 0건 실행하고
  pass 로 보고**한다. 초록불이 "통과"가 아니라 "미실행"이었다.
**Test:** `tests/trading/recommend/test_tracker.py::TestTrackerTrackOutcomes::test_90d_tracking`
— `rich_db` 를 리터럴 시작일로 되돌리면 FAIL (2026-08-05~08-10 실제로 FAIL 상태였다).

### 문서 fixer 를 실제 레포에서 돌리는 테스트
`scripts/doc/sync_doc_counts.sh` 는 검사기가 아니라 **in-place fixer** 다. `tests/verify/` 의
테스트가 이걸 `REPO_ROOT` env override 없이 실행하면 **백엔드 테스트를 돌릴 때마다 실제
README / ARCHITECTURE / STRATEGY 가 조용히 재작성**된다. `cwd=` 로는 막을 수 없다 —
`scripts/_common.sh` 가 **스크립트 자신의 레포 루트로 cd** 하므로 override 가 유일한 수단이다.
테스트는 통과하고 pytest 출력에 흔적이 없어 `git status` 를 볼 때까지 모른다 (2026-08-10 하루에
두 번 밟음: 편집 중이던 문서가 되돌려졌다).
`tests/verify/conftest.py` 가 `subprocess.Popen.__init__` 을 감싸 **실행 자체를 막는다.**
쓰기가 일어난 **뒤**가 아니라 **겨눈 순간** 터지므로 문서가 sync 상태여도 발화한다.
설계 3가지가 각각 우회로를 막는다 — 모듈 속성이 아니라 **클래스**를 잡아서 사전 바인딩
별칭(`from subprocess import Popen as X`)까지 덮고, argv 리스트가 아니라 **합친 커맨드
문자열**을 봐서 `shell=True` / `bash -lc "…"` 도 걸리고, fixer 집합을 폴더가 아니라
**동작**(`scripts/**/*.sh` 중 `sed -i` 하는 것 — 실측 27개 중 1개)으로 유도해 이사·신규 추가에
따라간다. 처음엔 소스를 스캔하는 AST 스윕으로 짰다가 argv 변수·`check_call`·헬퍼 래핑·
별칭·shell 문자열에 전부 뚫려 폐기했다 (Codex 리뷰 2라운드, 2026-08-10).
**우회 시도 10종 전부 차단 실측** — 되돌림·argv 변수·`check_call`·`check_output`·헬퍼·
`Popen` 직접·별칭 override·`shell=True`·`bash -lc`·사전 바인딩 별칭.
**Test:** `tests/verify/test_doc_claim_parity.py::TestFixerGuard::test_launching_the_fixer_at_the_real_repo_is_blocked`
— 가드를 걷어내면 FAIL. `_run(SYNC, repo_copy)` 를 직접 실행으로 되돌리면 그 테스트가 여기서 막힌다.
같은 파일의 내용 해시 가드는 **보조** — subprocess 를 안 거치는 직접 쓰기용이고, 문서가 sync 면
발화하지 않으므로 회귀 잠금이 아니다.

### Privacy 가드를 테스트하는 픽스처는 런타임 조립
가드가 차단하는 패턴 자체를 **리터럴로** 적으면 파일을 저장하는 순간 PreToolUse 훅과 CI `privacy-scan` 이 그 테스트 파일을 차단한다 (2026-07-29 실측: `TS`+`LA` 를 리터럴로 쓴 Write 가 막혔다). `ticker = "TS" + "LA"` 처럼 조립해 리터럴이 파일에 남지 않게 할 것 — 스캐너는 정규식이라 이걸로 충분하다.
**Test:** `tests/test_hook_guard_execution.py::TestPrivacyGuard::test_blocks_ticker_pnl_across_newlines` — 리터럴로 되돌리면 커밋 자체가 CI 에서 막힌다.

## Privacy in Test Data

Never use real broker names, holdings, prices, or account identifiers. Use placeholders: `Brokerage Alpha`, `Brokerage Beta`, round-million values like `1_000_000`.
