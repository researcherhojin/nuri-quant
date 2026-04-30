---
description: nuri-quant 전용 pre-commit 검증 (`make verify-quick` + manual checklist). 커밋 직전 사용. gstack `/qa` 와 다름 — 우리 프로젝트 lint/test/numbers-grep/conventional-commit 형식 준수 확인용. Usage `/nuri-verify`.
---

`nuri-verify` 스킬을 invoke 하라. `.claude/skills/nuri-verify/SKILL.md` 의 절차를 따라:

1. `make verify-quick` 실행 (≈10s, no network)
2. Manual checklist 적용 (lint / tests / numbers grep / config-driven / kst_now / DB 접근 / 스키마 / commit message format / PR scope)
3. 위반 항목이 있으면 사용자에게 명시적 보고 후 commit 차단 권고

`make verify-all` (with network) 은 push 직전 사용자가 별도 호출.
