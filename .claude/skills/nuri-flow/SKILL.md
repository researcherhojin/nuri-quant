---
name: nuri-flow
description: STRATEGY §2.7 7-phase Flow (Think→Plan→Build→Review→Test→Ship→Reflect) orchestrator. **Recommend-only** — 자동 chain 없이 사용자 현재 phase 추정 후 다음 액션/스킬 권고. 사용자가 "다음 단계 뭐?", "지금 phase 가 뭐야?", "Reflect 해야 하나?", "Build 끝났는데 뭘 해야 해?" 같이 진행 단계 질문 시 발화. nuri-quant 프로젝트의 1 issue = 1 PR ≤ 3 commits 룰 준수 보조.
---

# nuri-flow — 7-phase Flow Orchestrator (Recommend-only)

**Source**: `docs/STRATEGY.md §2.7` canonical. `.claude/rules/flow.md` 에 phase matrix 상시 load. 본 skill 은 phase 추정 + 권고.

## 운영 원칙

- **자동 chain 절대 금지** — 사용자 명시 지시 없이 다음 phase 자동 진행 X (`gh pr merge` 자동 호출 포함). STRATEGY §7.1 Auto trading deferred 정신.
- **추천만, 실행 X** — 다음 phase 적합 skill / Make target 권고만. invoke 는 사용자 또는 다른 skill 이.
- **추정 틀려도 강제 회귀 X** — phase 추정은 권고일 뿐.

## 도구 매핑 (STRATEGY §2.7 phase 별)

| Phase | 우리 도구 |
|---|---|
| Think | 사용자 질의 / `nuri-codex-review` agent (대형 결정) |
| Plan | 이슈 본문에 `## Done when` (항목마다 명령·측정으로 확인 가능) + `## Out of scope` — 없는 옛 이슈는 Build 전에 코멘트로 단다. 긴 설계 메모는 `docs/plans/<issue>_*.md` (gitignored) |
| Build | code edit + `/nuri-verify` |
| Review | `/nuri-codex-review` agent / `gstack /codex review` — 이슈의 `Done when` 항목별 met / not met 판정 포함 |
| Test | `make test-fast` + 사용자 워크플로 1회 실행 |
| Ship | local gate 뒤 한 번 push → `gh pr merge --squash --auto` (merge 시 레포가 head branch 를 지운다) + `/nuri-deploy`. 이슈 close · 로컬 branch 정리 · scope 가 바뀌었으면 TODO Tier 2 / 3 갱신 |
| Reflect | NEXT_SESSION.md 편집 + 신규 gotcha → `/nuri-harness-debug` cite |

## 사용 흐름

### "지금 phase 가 뭐야?" / "다음 단계?"

1. `git log origin/main..HEAD --oneline` (commit 수)
2. `git status` (작업 상태)
3. `gh pr view --json state,number 2>/dev/null` (PR 존재 여부)
4. `gh issue view <N> --json body,comments` (연결 이슈의 `Done when` · `Out of scope` 유무). `<N>` 은 PR 의 `Closes #N` → branch 이름의 이슈 번호 → 사용자에게 질문 순으로 정한다
5. Phase 추정:
   - 0 commits + 연결 이슈 없음 → **Think**
   - 0 commits + 이슈에 `Done when` / `Out of scope` 없음 → **Plan** 미완 (Build 금지)
   - 0 commits + 둘 다 있음 → **Build** 대기
   - commits + tests 미실행 → **Build / Test**
   - tests green + PR open → **Review**
   - PR approved → **Ship**
   - PR merged 직후 → **Reflect**
6. Gate 미통과 항목 + 다음 액션 권고를 사용자에게 표시.

### "Reflect 해야 하나?"

PR merged + NEXT_SESSION.md 마지막 편집 < PR merge 시각 → **Reflect 필요**. 갱신 항목 권고: 산출물 1줄 / 신규 gotcha / 다음 P0.

## Reference

- `docs/STRATEGY.md §5.8` — 7 Harness Principles (gate 근거)
- `.claude/rules/flow.md` — 7-phase gate 표 (always-on)
