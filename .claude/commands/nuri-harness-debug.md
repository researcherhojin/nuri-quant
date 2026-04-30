---
description: LLM agent 실패 패턴 진단 (hallucination / phantom fix / test illusion / scope creep / context bias / stale number drift). 사용자 보고 "테스트는 통과하는데 실제 코드 안 도는 거 같다", "fix 했는데 버그 재발", "Claude 가 존재하지 않는 API 호출" 시 발화. STRATEGY §5.8 7원칙 + Gotcha-Test Pair 프로토콜 적용. Usage `/nuri-harness-debug`.
---

`nuri-harness-debug` 스킬을 invoke 하라. `.claude/skills/nuri-harness-debug/SKILL.md` 의 6 실패 패턴 진단 흐름 (5.1 ~ 5.6) 을 사용자 증상에 매칭하여 진단:

1. 증상 청취 → 어느 패턴인지 분류 (Hallucination / Context Bias / Phantom Fix / Scope Creep / Test Illusion / Stale Number)
2. 해당 섹션의 "실제 사례" + "방어" 절차 적용
3. 발견된 fix 가 새 gotcha 라면 Gotcha-Test Pair (§5.3.1) 작성 권고 — `**Test:** path::TestClass::test_name` cite 필수

세션 진단이 끝나면 변경 이력 (`docs/HARNESS.md` 추가 후보) 검토.
