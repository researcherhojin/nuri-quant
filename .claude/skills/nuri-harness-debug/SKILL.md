---
name: nuri-harness-debug
description: LLM 에이전트 실패 패턴 디버깅 (hallucination, phantom fix, test illusion, scope creep, context bias, stale number drift). Use when user reports "test passes but doesn't cover the code", "fix applied but bug persists", "why does this keep failing the same way", "Claude is hallucinating API", or when a regression test needs a Gotcha-Test Pair citation. Case study narrative: git log of PR #272, #300-#307.
---

# Harness Debug — 6 실패 패턴 + Gotcha-Test Pair

**Source**: `docs/STRATEGY.md §5` canonical (7-rule + 패턴 정의). 이 skill 은 진단 flow + 방어. Case study 본문 = git log.

## 6 실패 패턴 진단

| 패턴 | 증상 | 방어 |
|---|---|---|
| **5.1 Hallucination** | 존재하지 않는 함수/파라미터/경로 자신 있게 호출 | 호출 전 `grep -n "def name"` / 패치 대상 모듈-레벨 vs local import 확인 / "아마" 로 코드 X |
| **5.2 Context Length Bias** | 긴 세션에서 가정 반복, 실패를 같은 방식으로 반복 | 같은 접근 2번 실패 → 접근 자체 의심. 3번째 시도 금지. `/compact` 후 코드 다시 읽기 |
| **5.3 Phantom Fix** | "수정함" 말하지만 실제 다른 곳 / 원 문제 미해결 | 수정 후 반드시 테스트. coverage 가 의도 라인 잡는지 확인. `vi.mock()` hoisting 워커 단위 인식 |
| **5.4 Scope Creep** | 요청 이상의 "개선" 시도 | 1 issue = 1 PR ≤ 3 commits. "이것도 같이" 금지 — 별 issue 분리 |
| **5.5 Test Illusion** | 테스트 통과하지만 실제 타겟 미실행 | coverage 라인 번호 검증. 조건부 (`if exists`) 안에 핵심 assertion 금지. `runpy` mock 무효 주의 (source-level patch 사용) |
| **5.6 Stale Number Drift** | 한 곳 숫자 변경 후 다른 ref 미업데이트 | `grep -ri "old_value"`. `make verify-doc-counts` 자동 감지 |

## Gotcha-Test Pair 프로토콜 (STRATEGY §5.3.1, PR #307)

`df.copy()` 재발 교훈. Folklore 만 남으면 다음 reviewer 가 defensive 코드를 "불필요" 로 제거. **모든 fix-pattern gotcha 는 fix 가 사라졌을 때 fail 하는 test 를 명명해서 cite 해야 한다**.

1. Gotcha 끝에 `**Test:** path/to/test.py::TestClass::test_name` 추가
2. Cited test 는 fix 없을 때 실제 fail 해야 함 (PR 에서 fix revert 후 local 검증)
3. 단순 facts/quirks 는 Test: 불필요, `*(facts, no fix)*` 마킹

Enforcement: 1차 = 사람 규율 + STRATEGY §5.3.1 참조. 2차 (Tier 3) = `scripts/audit_phantom_fixes.py` CI lint.

## Case Studies (git log)

- **#272 세션** (2026-04-14, 12 PRs): Mock-only 테스트, API 동시성 비대칭, ThreadPool timeout, 사용자 워크플로 검증, multi-role flow → `git log --grep '#272' --since 2026-04-13 --until 2026-04-16`
- **JKHY 에피소드** (PR #300-#307): dissent overwhelmed, mechanical divergence penalty, 초기 진단 오독 정정 → `gh pr view 300/301/302/303/306/307`

## 변경 이력 (7-원칙)

2026-04-14 — #3 강화 ("실행" → "사용자 워크플로 검증"), #7 추가 (외부 API 측정). Mock-only ship 함정 3회 반복 후 (`#272` git log).
