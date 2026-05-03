---
description: LLM agent 실패 패턴 진단 (hallucination / phantom fix / test illusion / scope creep / context bias / stale number drift). 사용자 보고 "테스트는 통과하는데 실제 코드 안 도는 거 같다", "fix 했는데 버그 재발", "Claude 가 존재하지 않는 API 호출" 시 발화. STRATEGY §5.8 7원칙 + Gotcha-Test Pair 프로토콜 적용. Usage `/nuri-harness-debug`.
---

`nuri-harness-debug` 스킬을 invoke. 본문 + 6 실패 패턴 진단 흐름 + Gotcha-Test Pair 프로토콜 → `.claude/skills/nuri-harness-debug/SKILL.md` (canonical, drift 차단).
