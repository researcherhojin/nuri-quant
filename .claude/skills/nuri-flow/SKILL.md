---
name: nuri-flow
description: STRATEGY §2.7 7-phase Flow (Think→Plan→Build→Review→Test→Ship→Reflect) orchestrator. **Recommend-only** — 자동 chain 없이 사용자 현재 phase 추정 후 다음 액션/스킬 권고. 사용자가 "다음 단계 뭐?", "지금 phase 가 뭐야?", "Reflect 해야 하나?", "Build 끝났는데 뭘 해야 해?" 같이 진행 단계 질문 시 발화. nuri-quant 프로젝트의 1 issue = 1 PR ≤ 3 commits 룰 준수 보조.
---

# nuri-flow — 7-phase Flow Orchestrator (Recommend-only)

**Source**: `docs/STRATEGY.md §2.7` canonical. `.claude/rules/flow.md` 에 phase matrix 상시 load. 본 skill 은 phase 추정 + 권고.

## 운영 원칙

- **자동 chain 절대 금지** — 사용자 명시 지시 없이 다음 phase 자동 진행 X. STRATEGY §7.1 Auto trading deferred 정신.
- **추천만, 실행 X** — 다음 phase 적합 skill / Make target 권고만. invoke 는 사용자 또는 다른 skill 이.
- **Trivial chore = inline 압축 OK** (typo, README 배지, gitignored 파일) — Build 이상은 모든 단계 준수.

## 도구 매핑 (STRATEGY §2.7 phase 별)

| Phase | 우리 도구 |
|---|---|
| Think | 사용자 질의 / `nuri-codex-review` agent (대형 결정) |
| Plan | `docs/plans/<issue>_*.md` 작성 (gitignored) |
| Build | code edit + `/nuri-verify` |
| Review | `/nuri-codex-review` agent / `gstack /codex review` |
| Test | `make test-fast` + 사용자 워크플로 1회 실행 |
| Ship | `gh pr merge --squash --delete-branch` (수동) + `/nuri-deploy` |
| Reflect | NEXT_SESSION.md 편집 + 신규 gotcha → `/nuri-harness-debug` cite |

## 사용 흐름

### "지금 phase 가 뭐야?" / "다음 단계?"

1. `git log origin/main..HEAD --oneline` (commit 수)
2. `git status` (작업 상태)
3. `gh pr view --json state,number 2>/dev/null` (PR 존재 여부)
4. Phase 추정:
   - 0 commits + scratch → **Think**
   - `docs/plans/*.md` 존재 + 0 commits → **Plan**
   - commits + tests 미실행 → **Build / Test**
   - tests green + PR open → **Review**
   - PR approved → **Ship**
   - PR merged 직후 → **Reflect**
5. Gate 미통과 항목 + 다음 액션 권고를 사용자에게 표시.

### "Reflect 해야 하나?"

PR merged + NEXT_SESSION.md 마지막 편집 < PR merge 시각 → **Reflect 필요**. 갱신 항목 권고: 산출물 1줄 / 신규 gotcha / 다음 P0.

## Anti-patterns

자동 `gh pr merge` 호출 X. 사용자 의도 없이 다음 phase 자동 진입 X. Phase 추정 틀려도 강제 회귀 X — 추정은 권고일 뿐.

## Reference

- `.claude/rules/flow.md` — 7-phase Gate 표 (always-on)
- `docs/STRATEGY.md §2.7` — canonical 정의
- `docs/STRATEGY.md §5.8` — 7 Harness Principles (gate 근거)
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/feedback_dev_flow.md`
