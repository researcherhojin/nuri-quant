---
description: nuri-quant 전용 lightweight code review checklist (architecture rules / harness rules / trading-specific / quality). gstack `/review` 의 heavy specialist+codex pipeline 과 분리. 우리 프로젝트 내부 PR 빠른 self-review 용. Usage `/nuri-review`.
---

`nuri-review` 스킬을 invoke 하라. `.claude/skills/nuri-review/SKILL.md` 의 절차를 그대로 따라:

1. Architecture rules 체크리스트 (sqlite3 import / kst_now / config-driven / migrations)
2. Harness rules 체크리스트 (STRATEGY §5.8 7원칙 위반 여부)
3. Trading-specific (BUY/SELL recommendation 인 경우만)
4. Quality (lint / test coverage / dead code / Korean comments + English names)

발견된 이슈는 severity (P0/P1/P2) 와 함께 사용자에게 보고. 자동 수정은 하지 말고 권고만.

주의: gstack `/review` 와 다름 — 이 슬래시는 우리 도메인 룰만 적용, codex/specialist subagent dispatch 없음.
