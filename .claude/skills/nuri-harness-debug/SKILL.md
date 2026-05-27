---
name: nuri-harness-debug
description: LLM 에이전트 실패 패턴 디버깅 — 코드/툴 레벨 (§5.1-5.6: hallucination, phantom fix, test illusion, scope creep, context bias, stale number drift) + 대화/추론 레벨 (§5.14.1-2: data→recommendation slide, cross-context inconsistency). Use when user reports "test passes but doesn't cover the code", "fix applied but bug persists", "why does this keep failing the same way", "Claude is hallucinating API", "갑자기 추천한 이유가 뭔가요", "왜 KR/US 다르게 적용했나요", or when a regression test needs a Gotcha-Test Pair citation. Case study narrative: git log of PR #272, #300-#307, session 2026-05-27.
---

# Harness Debug — 실패 패턴 + Gotcha-Test Pair

**Source**: `docs/STRATEGY.md §5.1-5.6` (code/tool patterns, canonical) + `§5.14` (conversational/reasoning patterns, 2026-05-27 신설). 이 skill 은 진단 flow + 방어. Case study 본문 = git log + NEXT_SESSION 학습.

## A. 코드/툴 레벨 (§5.1-5.6, mechanical patterns)

| 패턴 | 증상 | 방어 |
|---|---|---|
| **5.1 Hallucination** | 존재하지 않는 함수/파라미터/경로 자신 있게 호출 | 호출 전 `grep -n "def name"` / 패치 대상 모듈-레벨 vs local import 확인 / "아마" 로 코드 X |
| **5.2 Context Length Bias** | 긴 세션에서 가정 반복, 실패를 같은 방식으로 반복 | 같은 접근 2번 실패 → 접근 자체 의심. 3번째 시도 금지. `/compact` 후 코드 다시 읽기 |
| **5.3 Phantom Fix** | "수정함" 말하지만 실제 다른 곳 / 원 문제 미해결 | 수정 후 반드시 테스트. coverage 가 의도 라인 잡는지 확인. `vi.mock()` hoisting 워커 단위 인식 |
| **5.4 Scope Creep** | 요청 이상의 "개선" 시도 | 1 issue = 1 PR ≤ 3 commits. "이것도 같이" 금지 — 별 issue 분리 |
| **5.5 Test Illusion** | 테스트 통과하지만 실제 타겟 미실행 | coverage 라인 번호 검증. 조건부 (`if exists`) 안에 핵심 assertion 금지. `runpy` mock 무효 주의 (source-level patch 사용) |
| **5.6 Stale Number Drift** | 한 곳 숫자 변경 후 다른 ref 미업데이트 | `grep -ri "old_value"`. `make verify-doc-counts` 자동 감지 |

## B. 대화/추론 레벨 (§5.14, behavioral patterns, observational)

| 패턴 | 증상 | 방어 |
|---|---|---|
| **5.14.1 Data→Recommendation Slide** | 데이터 수집/분석 결과 공유 요청에 대해 silent 하게 종목/액션 권고로 변환 (user 명시 요청 없이 자의적 advice) | user 가 명시적 권고 요청 ("X 어떻게 생각해", "deploy 어디에", "추천해") 했는지 확인 후만 권고. data presentation 은 ranking / 사실 / freshness 까지만. 권고 시작 전 1 step pause: "user 가 결정 권고 요청했는가?" *(facts, no fix)* |
| **5.14.2 Cross-context Inconsistency** | 같은 정량 filter / rule 을 시장 / 도메인 별로 다르게 적용 (예: KR universe blow-off 보류 → US universe blow-off 진입 권고) | Filter 기준 (60d return cap, vol threshold, blow-off 제외) 을 **명시 선언** 후 모든 시장에 동일 적용. 권고 전 self-check: "내가 컨텍스트 A 에서 적용한 rule 을 B 에 동일 적용하면 통과?" *(facts, no fix)* |

**Case study 2026-05-27 세션** (구체 수치는 git log + NEXT_SESSION.md, gitignored):
- §5.14.1: user 가 "데이터 수집" 요청 → universe top 보고 자의적으로 종목 진입 권고 슬라이드 → user 가 "갑자기 추천한 이유" + "당황스럽지 않을까요" 정정
- §5.14.2: KR universe blow-off threshold (60d return cap) 적용 후 보류 권고, US universe 동일 threshold 적용 안 하고 "진입 가치" 권고 → user 일관성 위반 지적. Filter 기준은 시장 무관 동일 적용 원칙

**Enforcement layer**: 1차 = user memory (`feedback_data_recommendation_boundary.md`, `feedback_ranking_consistency.md`). 2차 = 본 skill (`§5.14.1` / `§5.14.2` 진단). 3차 (미구현) = hook 으로 mechanical 강제 어려움 (LLM 응답 layer, structured 검출 metric 없음).

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
