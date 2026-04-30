---
name: nuri-flow
description: STRATEGY §2.7 7-phase Flow (Think→Plan→Build→Review→Test→Ship→Reflect) orchestrator. **Recommend-only** — 자동 chain 없이 사용자 현재 phase 추정 후 다음 액션/스킬 권고. 사용자가 "다음 단계 뭐?", "지금 phase 가 뭐야?", "Reflect 해야 하나?", "Build 끝났는데 뭘 해야 해?" 같이 진행 단계 질문 시 발화. nuri-quant 프로젝트의 1 issue = 1 PR ≤ 3 commits 룰 준수 보조.
---

# nuri-flow — 7-phase Flow Orchestrator (Recommend-only)

**Source of truth**: `docs/STRATEGY.md §2.7` (canonical 7-phase definition + gate criteria).
**Origin**: `docs/HARNESS_AUDIT.md` (2026-04-30) §6 P1-1 — 7-phase Flow가 doc-only로 강제 메커니즘 부재. 본 skill은 인지 보조 layer.

## 운영 원칙

1. **자동 chain 절대 금지** — 사용자 명시 지시 없이 다음 phase로 자동 진행 X. 각 phase 사이에 사용자 결정 gate 유지.
2. **추천만, 실행 X** — 다음 phase에 적합한 skill/Make target 권고만. invoke는 사용자 또는 다른 skill이 한다.
3. **STRATEGY §7.1 Auto trading deferred 정신 보존** — 자동 매매 deferred와 같은 이유로 자동 phase chain 도 deferred.
4. **Trivial chore = inline 압축 가능** — Think/Plan은 사용자 한 줄 답으로 통과 OK. Build 이상은 모든 단계 준수.

## Phase 매트릭스 (STRATEGY §2.7 요약)

| # | Phase | Gate (YES → 다음으로) | 우리 도구 |
|---|---|---|---|
| 1 | **Think** | "왜 지금" 1 문장 답 가능? root-cause / literature 확인? | 사용자 질의 / `/nuri-codex-second-opinion` (대형 결정) |
| 2 | **Plan** | scope = 이슈 그대로? 1 PR / ≤ 3 commits? Escalation Ladder 레벨 명시? | `docs/plans/<issue>_*.md` 작성 |
| 3 | **Build** | hardcode 없음? hook + lint 통과? `kst_now()` only? | code edit + `/nuri-verify` |
| 4 | **Review** | Codex `/codex review` + Claude self-review? P1 모두 해결? | `/nuri-codex-second-opinion` agent |
| 5 | **Test** | `make test-fast` green + 사용자 워크플로 1회 실행? UI = browser QA? | `/nuri-verify` + `make test-fast` |
| 6 | **Ship** | `gh pr merge --squash --delete-branch`. 이슈 close. 브랜치 정리. TODO Tier 2/3 갱신 | `/nuri-deploy` (production push만, 별도) + 사용자 manual `gh pr merge` |
| 7 | **Reflect** | NEXT_SESSION refreshed. 신규 gotcha → Gotcha-Test Pair (§5.3.1) cite. 메모리 갱신 | NEXT_SESSION.md 편집 + 신규 gotcha면 `/nuri-harness-debug` cite |

## 사용 흐름

사용자 질문에 따라 분기:

### Case A: "지금 phase가 뭐야?" / "다음 단계?"
1. `git log origin/main..HEAD --oneline` 으로 commit 수 확인
2. `git status` 으로 작업 상태 확인
3. PR 존재 여부 (`gh pr view --json state,number 2>/dev/null`)
4. Phase 추정:
   - 0 commits + scratch → **Think**
   - `docs/plans/*.md` 존재 + 0 commits → **Plan**
   - commits 있음 + tests 미실행 → **Build / Test**
   - tests green + PR open → **Review**
   - PR approved → **Ship**
   - PR merged 직후 → **Reflect**
5. 추정 phase + Gate 미통과 항목 + 다음 액션 권고를 사용자에게 표시.

### Case B: "Build 끝났는데 다음?"
1. Build → Test phase로 권고
2. `/nuri-verify` (lint + test) 실행 권고
3. 통과 시 Review (`/codex review` or `/nuri-codex-second-opinion`)
4. 미통과 시 Build로 회귀 (STRATEGY §2.7: "단계 실패 = 이전 단계 회귀")

### Case C: "Reflect 해야 하나?"
1. PR merged 여부 확인
2. NEXT_SESSION.md 마지막 편집 시각 vs PR merge 시각 비교
3. NEXT_SESSION이 PR merge 이전이면 **Reflect 필요** — 갱신 항목 권고:
   - 이번 세션 산출물 1줄
   - 신규 발견 (gotcha / surprise)
   - 다음 세션 P0 후보

## Trivial chore 처리

다음 조건이면 Think + Plan 압축 OK (사용자 1줄 의도 확인만):
- 단일 파일 typo 수정
- README badge 갱신
- 메모리 / 자동 생성 파일 갱신
- gitignored 파일 (NEXT_SESSION 등) 편집

**Build 이상은 압축 불가** — verify/test/review 단계 모두 강제.

## 권장 instrumentation (Future P2)

현재는 phase 추정이 사용자 + claude 휴리스틱. Future:
- `data/phase_history.jsonl` — 매 commit 시 추정 phase 기록
- `make phase-status` — 현재 phase 자동 detect
- 단, 자동화는 §7.1 Auto trading deferred 정신 위반 risk → 인간 매개 유지 권장.

## Anti-patterns (이 skill 가 하지 말 것)

| 안 함 | 이유 |
|---|---|
| 자동 `gh pr merge` 호출 | Ship gate는 사용자 명시 승인. Auto trading deferred (§7.1) 정신. |
| 사용자 의도 없이 다음 phase로 자동 진입 | 인간 in-the-loop 보존 |
| Phase 추정이 틀렸다고 가정하고 강제 회귀 | 추정은 권고일 뿐, 사용자가 진실 |
| STRATEGY §2.7 본문 재진술 | source of truth 분산 — pointer만 유지 |

## Reference

- `docs/STRATEGY.md §2.7` — canonical 7-phase 정의
- `docs/STRATEGY.md §5.8` — 7 Harness Principles (Build/Test/Review gate 의 근거)
- `docs/HARNESS_AUDIT.md §6 P1-1` — 본 skill 의 origin 결정
- `~/.claude/projects/-Users-ehbebe-workspace-nuri-quant/memory/feedback_dev_flow.md` — 사용자 워크플로 학습 메모리
