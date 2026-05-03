---
name: nuri-harness-debug
description: LLM 에이전트 실패 패턴 디버깅 (hallucination, phantom fix, test illusion, scope creep, context bias, stale number drift). Use when user reports "test passes but doesn't cover the code", "fix applied but bug persists", "why does this keep failing the same way", "Claude is hallucinating API", or when a regression test needs a Gotcha-Test Pair citation. Case study narrative: git log of PR #272, #300-#307.
---

# Harness Debug — LLM 실패 패턴 진단 프로토콜

**Context**: `docs/STRATEGY.md §5` 의 canonical 원칙 (7-rule summary) + 6 실패 패턴 요약은 본문에 남고, case studies · Gotcha-Test Pair 전체 protocol · 실제 사례 상세는 이 skill 로 분리. Invoke 시 panel 이 load.

## 7-원칙 요약 (STRATEGY §5.8)

```
1. 모르면 읽는다              — 가정하지 않는다
2. 2번 실패하면 접근을 바꾼다  — 같은 시도 3회 금지. 같은 fix 3회 부분 해결 시 root cause 의심
3. 사용자 워크플로로 검증한다  — mock test ≠ verification. ship 전 `make X --flag` 직접 실행
4. 스코프를 지킨다            — 요청된 것만 한다
5. 숫자를 grep한다            — 한 곳만 고치지 않는다
6. 시스템이 차단한다          — 문서가 아닌 린터/CI/게이트가 강제
7. 외부 API는 측정한다        — 동시성/timeout/rate-limit 추정 금지. yfinance 10-thread OK ≠ KRX 10-thread OK
```

## 6 실패 패턴 진단 흐름

### 5.1 할루시네이션 (Hallucination)
**증상**: 존재하지 않는 함수/파라미터/경로를 자신 있게 말함.

**실제 사례**:
- `get_exchange_rate(db_path)` — 실제 시그니처 `get_exchange_rate()` (파라미터 없음)
- `nuri.api.routes.dashboard.query` 패치 — 실제로는 함수 내부 local import
- `MagicMock` 을 `dataclasses.asdict()` 에 전달 — 실제 dataclass 인스턴스 필요

**방어**:
- 호출 전 시그니처 grep (`grep -n "def function_name"`)
- 패치 대상이 모듈 레벨인지 local import 인지 확인
- "아마 이럴 것이다" 로 코드 쓰지 않는다. 모르면 먼저 읽는다.

### 5.2 확증 편향 (Context Length Bias)
**증상**: 긴 컨텍스트에서 이전 가정을 "맞다" 가정, 실패를 같은 방식으로 반복.

**실제 사례**:
- `daily_report` 테스트 CI 3회 연속 실패 — 매번 `runpy.run_module()` 시도. 근본 원인: `generate_report()` 가 같은 모듈에 정의되어 runpy 가 mock 덮어씀. 3번째에 `main()` 직접 호출로 전환.
- `runpy` + `monkeypatch.setattr()` 로 `__main__` 블록 테스트 반복 실패. 원인: runpy 는 모듈 소스 재실행 → 모든 이름 재정의. 해결: `patch("source.module.function")`.

**방어**:
- 같은 접근 2번 실패 → 접근 자체 의심. 3번째 시도 금지.
- 실패 시 "왜 실패했는가" 먼저 진단.
- 긴 세션 `/compact` 후 이전 가정 재검증 (코드 다시 읽기).

### 5.3 유령 수정 (Phantom Fix)
**증상**: "수정했습니다" 말하지만 실제 다른 곳 고침 / 원 문제 미해결.

**실제 사례**:
- Recharts mock 충돌: `coverage-push.test.tsx` 의 `vi.mock("recharts")` 가 `coverage-push-3.test.tsx` 의 `price-chart` import 깨뜨림. vitest mock hoisting 이 같은 워커 모든 dynamic import 에 영향.
- OpenBB `obb.currency.price.historical` 패치 시도 → 모듈 레벨에 `obb` 없음 `AttributeError`. 함수 내부 local import 이므로 `patch.dict(sys.modules, {"openbb": mock_module})` 필요.
- **`df.copy()` 누락 재발** (PR #306 CI Shard 2 fail → #307): PR #294/#295 commit message 에 "의도한 방어" 라 기록 + CLAUDE.md gotcha 추가했지만 실제 `nuri/collectors/stock.py` 에 `df.copy()` 없었음. `mock.return_value = df_fixture` 가 ThreadPoolExecutor 10-worker 에 공유 → race → `InvalidIndexError`. 수 세션 후 재발. Fix + `TestStandardizeThreadSafety` regression test 로 lock-in.

**방어**:
- 수정 후 반드시 테스트. "논리적으로 맞을 것" 신뢰 금지.
- 테스트 통과해도 의도한 라인이 coverage 에 실제 잡히는지 확인.
- `vi.mock()` hoisting 영향 범위 인식 (파일 단위, 워커 단위).

### 5.4 스코프 팽창 (Scope Creep)
**증상**: 요청받은 것 이상을 "개선" 하려는 경향.

**실제 사례**:
- #16 에이전트 3 개 추가 요청 → config 외부화 + confidence 정규화 + 구조 수정 5건 + 프론트엔드까지 한 PR 에 포함 (29 파일, +2000 줄).
- 커버리지 작업 중 발견한 "작은 버그" 를 같은 PR 에 수정 → 리뷰 범위 확대.

**방어**:
- 이슈 1개 = PR 1개. 선행 작업은 별도 이슈 분리.
- 커밋 ≤ 3. 넘으면 스코프 줄인다.
- "이것도 같이 하면 좋겠다" 금지. 별도 이슈 생성.

### 5.5 테스트 환각 (Test Illusion)
**증상**: 테스트 통과하지만 실제 타겟 코드 미실행.

**실제 사례**:
- `runpy.run_module()` + `patch("module.generate_llm_report_sync")`: runpy 재정의로 mock 무효. 테스트는 실제 Ollama 연결 시도 → 300초 timeout 후 실패.
- `if editBtns.length > 0` 가드로 감싼 테스트: 버튼 미렌더링 시 테스트 로직 자체 실행 안 됨, 테스트는 통과.

**방어**:
- Coverage 리포트에서 의도한 라인 번호 실제 커버 확인.
- 조건부 로직 (`if element exists`) 안에 핵심 assertion 금지.
- `runpy` 테스트 mock 유효성: 패치 대상이 SOURCE 레벨인지 확인 (`BaseCollector.run` vs `EstimatesCollector.run`).

### 5.6 숫자 전파 오류 (Stale Number Propagation)
**증상**: 한 곳의 숫자 변경 후 다른 참조 미업데이트.

**실제 사례**:
- 에이전트 7개 → 10개 추가 후, README/CLAUDE.md/STRATEGY.md 에 "7 agents" 잔존.
- 테스트 수 2700 → 2884 업데이트 시 README 고치고 STRATEGY.md 누락.

**방어**:
- 숫자 변경 시 `grep -ri "이전값"` 전수.
- CLAUDE.md, README.md, STRATEGY.md, 코드 주석 모두 확인.
- 커밋 메시지에 변경 숫자 명시 (`update test counts 2808 → 2884`).
- `make verify-doc-counts` / `make sync-doc-counts` 로 drift 자동 감지/수정.

## Gotcha-Test Pair 프로토콜 (STRATEGY §5.3.1, PR #307)

`df.copy()` 재발 교훈. Gotcha 가 **folklore** 로만 기록되면 다음 리뷰어가 defensive 코드를 "불필요" 로 제거해도 테스트가 안 막는다. **모든 fix-pattern gotcha 는 fix 가 사라졌을 때 fail 하는 test 를 명명해서 cite 해야 한다**.

### 프로토콜

1. Gotcha 문장 끝에 `**Test:** \`path/to/test.py::TestClass::test_name\`` 추가.
2. Cited test 는 **fix 없을 때 실제 fail** 해야 함 — 테스트 자체가 phantom 이면 안 됨. PR 에서 fix 를 임시로 revert 해 test 가 fail 하는지 local 검증 권장.
3. 단순 facts/quirks (e.g. "yfinance .KS fundamentals work") 이고 fix 절차가 아닌 경우 Test: 불필요.
4. 새 gotcha 추가 시 Test: 없이 ship 하려면 PR body 에 "no fix, just facts" 명시.

### Enforcement

- **1차 (현재)**: 리뷰 checklist + STRATEGY §5.3.1 참조. 사람 규율.
- **2차 (Tier 3 후보)**: `scripts/audit_phantom_fixes.py` — CLAUDE.md Gotchas 파싱 → 각 `**Test:**` 참조가 실존 테스트인지 verify → CI lint. 인간 규율 drift 방지.

관련: §5.5 (Test Illusion), §5.8 #1 (모르면 읽는다) — gotcha 는 "고쳤다" 는 이야기, 실제 고침은 코드에서 확인.

## Case Studies

구체 case study narrative 는 `git log` 의 PR / commit 본문에 보존:

- **#272 세션 교훈** (2026-04-14, 12 PRs): Mock-only 테스트, API 동시성 비대칭, ThreadPool timeout, 사용자 관점 검증, multi-role flow → `git log --grep '#272\|mock-only' --since 2026-04-13 --until 2026-04-16`
- **JKHY 에피소드** (PR #300-#303, #306, #307): dissent overwhelmed, mechanical divergence penalty, 초기 진단 오독 정정 → `gh pr view 300/301/302/303/306/307`

## 변경 이력 (원칙 7개)

2026-04-14: #3 강화 ("실행한다" → "사용자 워크플로로 검증한다"), #7 추가 (외부 API 측정). Mock-only ship 함정 3회 반복 후 (`#272` 세션, git log).
