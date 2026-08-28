# tests/ — Testing Conventions

## DB Isolation Pattern

두 층이다 — **테스트가 명시적으로 넘기는 `db_path`** 와, 그 아래 **전역 격리**.

명시 경로: 대상 함수가 `db_path=` 를 받으면 그걸 쓴다.

```python
@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path
```

전역 격리 (#1049): `tests/conftest.py` 의 autouse 픽스처가 매 테스트마다
`nuri.core.db.DB_PATH` 를 **세션 스키마 템플릿의 복사본**으로 갈아끼운다. 그래서
`db_path` 를 안 받는 함수도 프로덕션 DB 에 닿지 않는다. 왜 복사냐면 매번
`init_db()` 를 부르면 70.8ms × 약 7,000 = 8분이고 파일 복사는 0.5ms 이기 때문
(실측 오버헤드 0.34s / 1,666 테스트).

⚠️ **`db_path` 를 받는 것만으로는 아무것도 보장되지 않는다.** 함수가 인자를
선언해 놓고 내부에서 `analyze_portfolio()` 를 인자 없이 부르면 그 한 줄만
기본 DB 로 샌다. 서명도 맞고 타입 체커도 통과하고 테스트도 초록이다 — 이렇게
샌 지점이 #1050/#1051 에서 8곳, 그 뒤 #1052 에서 13곳 더 나왔다.
**Test:** `tests/core/test_db_path_forwarding.py::TestDbPathIsForwarded::test_every_db_path_aware_call_receives_it`
— `db_path=db_path` 를 하나 지우면 FAIL. 호출 형태 3종(`f()` · `mod.f()` · 별칭
import)을 보고, `**kwargs` unpack 은 forward 로 인정하지 않는다.

## Global Mocks (conftest.py, autouse)

4개 전부 autouse — 순서대로 `_isolate_from_production_db` · `_forbid_production_db` ·
`_force_no_wal` · `mock_yfinance`.

| 픽스처 | 하는 일 |
|---|---|
| `_isolate_from_production_db` | `DB_PATH` → 세션 스키마 템플릿의 per-test 복사본 |
| `_forbid_production_db` | 실 `data/portfolio.db` 를 **여는 순간** 예외 (아래 참조) |
| `_force_no_wal` | `journal_mode=MEMORY` — CI tmpfs 의 WAL/visibility 문제 회피 |
| `mock_yfinance` | `download` → 빈 DataFrame, `Ticker` → None 속성 스텁 |

All tests run **network-free**. Override per-test if needed, but never remove global mocks.

`_forbid_production_db` 의 예외는 **`BaseException` 을 직접 상속한다 — 일부러.**
`AssertionError` 로 던졌더니 `nuri/llm/report.py::gather_context` 의 광범위
`except Exception` 이 삼켜서, **테스트 5개가 프로덕션 DB 를 읽으며 초록**이었다
(2026-08-14 실측). 삼켜지는 백스톱은 백스톱이 아니다.
**Test:** `tests/test_production_db_guard.py::TestProductionDBGuard` — `Exception`
으로 되돌리면 2개 FAIL, 가드를 무력화하면 1개 FAIL.

## Slow Marker

27 LLM/heavy tests marked `@pytest.mark.slow` (collected count — marker sites expand via class-level marks / parametrize). PR CI excludes via `-m "not slow"`.
- `make test-fast` — excludes slow (81.2s, `-n auto --dist worksteal`, M5 Max 2026-08-14)
- `make test-slow` — slow only
- `make test` — full suite (test-fast + slow 27)

## Coverage — 로컬은 `--cov-branch` 없이는 CI 와 다른 것을 잰다

`codecov.yml` 은 `patch: target 100% / threshold 0%` 이고 **부분 분기(partial branch)까지 센다.** 그래서 미커버 **줄**이 0이어도 patch 가 미달할 수 있다. 분기 없이 재면 로컬이 CI 보다 관대해 보인다 — 실측(2026-08-20, 같은 테스트·같은 파일):

```
pytest --cov              nuri/api/routes/evidence.py   60  0        100%
pytest --cov --cov-branch nuri/api/routes/evidence.py   60  0  28  1   99%   ← 부분분기 1
```

codecov 는 이 파일을 `"lines":7,"hits":6,"misses":0,"partials":1` → **85.71%** 로 보고했다. PR #1123·#1124 가 이 착시로 CI 를 한 바퀴 더 돌았다. **ad-hoc 으로 커버리지를 잴 때는 `--cov-branch` 를 붙일 것** (CI 는 `main-ci-cd.yml` 에서 항상 붙인다).

부분 분기는 대개 "루프가 한 바퀴 돌고도 매칭 없이 빠져나가는 arc" 처럼 **테스트가 한 방향만 밟은 조건문**이다. `# pragma: no cover` 는 진짜로 트리거 불가능한 방어 코드에만 쓴다 — 실행 가능한 경로는 테스트로 덮는다.

## Gotchas

### conftest.py 안의 `test_*` 함수는 수집되지 않는다
pytest 의 `python_files` 기본값이 `test_*.py` 라 `conftest.py` 는 **플러그인으로
import 될 뿐 테스트 모듈이 아니다.** 그런데 파일을 인자로 명시하면
(`pytest tests/conftest.py`) 수집돼서 통과한다 — 즉 **"돌려서 확인했다"가
착각일 수 있다.** 프로덕션 DB 가드의 회귀 테스트 3개가 이 상태로 `make test-fast`
와 CI 에서 **한 번도 실행되지 않았다** (2026-08-14, `pytest tests/ --collect-only`
로 0건 실측). conftest 에 사는 픽스처를 검증하려면 테스트는 **수집되는 파일**에
두고, 픽스처 내부 심볼을 import 하는 대신 **성질을 직접 단언**할 것
(`tests/` 는 패키지가 아니라 import 경로가 실행 방식에 따라 달라진다).
**Test:** `tests/test_production_db_guard.py` — 파일 자체가 이 규칙의 산물이다.

### `patch("nuri.core.db.query")` 금지 — mock 이 patch 창을 넘어 산다 (#1149)

patch 가 활성인 동안 **처음 import 되는** 모듈이 `from nuri.core.db import query` 를 하면
mock 을 자기 전역에 **복사**한다. patch 는 원본 속성만 되돌리므로 그 복사본은 mock 인 채
남고, 이후 모든 테스트에서 그 모듈의 DB 조회가 조용히 `[]` 를 낸다.

실측(2026-08-21): `empty_db_ctx` 하나가 3개 모듈을 오염시켰다 — `nuri.core.coverage` ·
`nuri.core.freshness` · `nuri.trading.recommend.tracker`. **`freshness` 가 특히 나쁘다**:
이후 모든 정책이 "데이터 없음" 을 답하므로 *낡음을 감시하는 장치가 죽은 채로 그 장치의
테스트가 돈다.* 피해는 `tracker` 가 보유 조회에 `[]` 를 받아 SELL 을 전부 걸러내는 형태로
`tests/api/test_axis_native_read_path.py` 에서 IndexError 로 터졌다.

**빈 결과가 목적이면 빈 격리 DB 를 준다.** `_resolve_db_path()` 가 호출 시점에 파사드의
`DB_PATH` 를 읽으므로, 어딘가 남은 `query` 복사본도 실전 함수라 그 경로를 그대로 탄다 —
오염 축이 성립조차 안 한다.

```python
empty = tmp_path / "empty.db"
init_db(empty)
monkeypatch.setattr(nuri.core.db, "DB_PATH", empty)   # patch("...query") 대신
```

손으로 나열해 복원하는 방식(`finally: mod.query = _orig`)은 쓰지 않는다 — 그게 원래 방어였고,
새 소비자가 생길 때마다 조용히 샜다.

**금지는 사람 눈이 아니라 기계가 지킨다**: #1150 이 fixture 를 고친 뒤에도 같은 파일의
resilience 테스트에 1곳이 남아 3주 잠복하다 CI 샤드 재구성(#1157) 후 워커 순서에서 발화했다
(PR #1172 red — `market_signals` 가 창 안에서 first-import). **Test:**
`tests/test_no_facade_query_patch.py::TestNoFacadeQueryPatch` — AST 로 실호출만 세고
(독스트링/주석 언급은 오탐이라 텍스트 sweep 기각), allowlist 는 "patch 창의 import 표면이
함수-로컬 lazy import 뿐" 인 파일만 사유와 함께 양방향 등재.

⚠️ **이 계열은 직렬 실행에서만 보인다.** `make test-fast`(`-n auto --dist worksteal`)는
오염원과 피해자를 다른 워커로 보내 초록이다. 격리 의심 시 `pytest tests/ --ignore=tests/quant -x`
로 직렬 확인.

**Test:** `tests/alerts/test_premarket_brief.py::TestFixtureLeavesNoMockBehind` — 4개가
구조와 동작을 나눠 잠근다. fixture 를 query mock 방식으로 되돌리면 **넷 다 FAIL**.
- `test_known_leak_modules_still_hold_the_real_query` — 누출 이력 3종을 **이름으로** 확인.
  스윕만으로는 부족하다: 그 시점 로드된 모듈만 보므로 감시 대상이 아직 로드 전이면 조용히
  통과한다. 여기서는 직접 import 하므로 항상 검사된다.
- `test_no_other_module_holds_a_rebound_query` — 전역 스윕. 타입 이름이 아니라 **동일성**으로
  본다 (새는 값이 `MagicMock` 이 아니라 평범한 callable 이어도 잡아야 한다).
- `test_freshness_still_sees_real_data` · `test_coverage_still_sees_real_data` ·
  `test_tracker_still_sees_a_seeded_portfolio` — 세 모듈 각각의 **동작** 잠금. 구조 스윕만
  두면 tracker 만 초록인 채 낡음 감시가 다시 죽는 회귀가 통과한다.

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

**3차 발생 (2026-08-29) — 리터럴이 아니라 *역함수를 틀린* 변종** (#1270). 위 두 건을 고치며
시드를 `today_kst()` 앵커 + 영업일 계산으로 바꿨는데, 그 짝을
`np.busday_offset(today, -n, roll="backward")` 로 썼다. 프로덕션은 나이를
`np.busday_count(observed, today)` 로 재므로 시드는 그 **역함수**여야 하는데,
`roll="backward"` 는 **오늘이 휴장일이면 롤 자체가 영업일 1일을 소비**해 왕복이 `n+1` 이
된다. 결과: "임계 이내" 로 시드한 경계 행이 임계를 넘어 `None` 이 되고, `make test-fast` 가
**토·일에만** 2건 빨간불 (`test_vix_within_max_age_is_still_used` ·
`test_fresh_row_is_used`). `roll="forward"` 가 7요일 전부 왕복 일치한다.
- **더 낡게 시드하는 테스트(`-(MAX+1)`)는 주말에도 통과**한다 — 결함이 *경계* 테스트에만
  나타나서 요일이 바뀌기 전까지 아무 신호가 없었다.
- 이건 dead gate 가 아니라 **false-red** 다. 코드와 무관한 빨간불은 빨간불을 무시하는
  습관을 만든다는 점에서 같은 값이 나온다.
**Test:** `tests/trading/recommend/test_buy_candidate_emitter.py::TestBusinessDaysAgoIsTheInverseOfBusdayCount`
+ `tests/quant/test_factors_composite.py::TestBusinessDaysAgoIsTheInverseOfBusdayCount`
— 7요일 × n 왕복 잠금. `forward` → `backward` 로 되돌리면 **요일과 무관하게** FAIL.
파일마다 따로 두는 이유는 2차 발생의 교훈 그대로다(한 경로만 잠그면 나머지는 무방비).

⚠️ 이 잠금을 짜면서 **문자열 타깃 monkeypatch 가 조용히 no-op** 인 것도 같이 밟았다.
`monkeypatch.setattr("tests.trading.recommend.test_buy_candidate_emitter.today_kst", …)` 는
`tests/` 가 패키지가 아니라 같은 파일의 *두 번째 사본*을 import 해 거기를 패치한다 —
실행 중인 사본은 그대로다. 증상이 특이하다: 평일 앵커 15개가 전부 FAIL 하고 주말 앵커만
통과했다(진짜 오늘이 토요일이라). **모듈 객체를 직접 잡을 것**:
`monkeypatch.setattr(sys.modules[__name__], "today_kst", …)`.

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
