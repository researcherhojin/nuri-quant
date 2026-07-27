# 7-phase Flow

`docs/STRATEGY.md §2.7` is canonical. 7 phases, no skipping. Failed gate → regress prior phase. Trivial chores may inline Think+Plan; Build onward is mandatory.

| # | Phase | Output gate (must answer YES to advance) |
|---|-------|-----------------------------------------|
| 1 | **Think** | Can I state "왜 지금" in 1 sentence? Literature / root-cause checked? |
| 2 | **Plan** | Scope unchanged from issue? 1 PR / ≤ 3 commits? Escalation Ladder rung named? |
| 3 | **Build** | No hardcoded values (config/yaml-driven)? Hook + lint pass? `kst_now()` only? |
| 4 | **Review** | Codex `/codex review` + Claude self-review. P1 all resolved? Codex unavailable → self-review + recover next PR |
| 5 | **Test** | `make test-fast` green + at least 1 user-workflow live execution? UI → browser QA |
| 6 | **Ship** | `gh pr merge --squash --delete-branch`. Issue closed. Branch cleaned. TODO Tier 2 / 3 updated if scope shifted |
| 7 | **Reflect** | NEXT_SESSION refreshed. New gotcha → Gotcha-Test Pair (§5.3.1) cite. Memory updated if surprising |

**Precedence on conflict**: repo truth (code/config) > `NEXT_SESSION.md` > auto-memory. If recalled memory contradicts what you read now, trust the code and update the stale memory. Historical commits → `git log` (do not re-document in markdown).
