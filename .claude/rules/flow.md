# 7-phase Flow

`docs/STRATEGY.md §2.7` is canonical. 7 phases, no skipping. Failed gate → regress prior phase. Trivial chores may inline Think+Plan; Build onward is mandatory.

| # | Phase | Output gate (must answer YES to advance) |
|---|-------|-----------------------------------------|
| 1 | **Think** | Can I state "왜 지금" in 1 sentence? Literature / root-cause checked? |
| 2 | **Plan** | Scope unchanged from issue? 1 PR / ≤ 3 commits? Escalation Ladder rung named? |
| 3 | **Build** | No hardcoded values (config/yaml-driven)? Hook + lint pass? `kst_now()` only? |
| 4 | **Review** | Codex `/codex review` + Claude self-review. P1 all resolved? Codex unavailable → self-review + recover next PR |
| 5 | **Test** | `make test-fast` green + at least 1 user-workflow live execution? UI → browser QA |
| 6 | **Ship** | One push after the local gates, then `gh pr merge --squash --auto` (the repository deletes the head branch on merge). Issue closed. Local branch cleaned. TODO Tier 2 / 3 updated if scope shifted |
| 7 | **Reflect** | NEXT_SESSION refreshed. New gotcha → Gotcha-Test Pair (§5.3.1) cite. Memory updated if surprising |

## Completion claims need fresh evidence

Adapted from obra/superpowers `verification-before-completion`. It is an **output requirement**, not a "re-check your reasoning" instruction (see `communication.md` on why that distinction matters): before saying something is done, fixed, passing or merged —

1. **Identify** the command that proves the claim.
2. **Run** it, fresh and complete — not the run from before the last edit.
3. **Read** the output: exit code, pass/fail counts, the actual values.
4. **Verify** that the output supports the claim. If it does not, report the actual state with the evidence.
5. **Only then** make the claim, with the evidence beside it.

Evidence is: test output with its counts, the gate's final line, an exit code, a diff, a ledger query. Not evidence: an earlier run, a partial run, a subagent's success report, "the code changed so it works", one green test without the red step. Words that mark an unverified claim and do not belong in one: *should*, *probably*, *seems to*, *Done!*. 2026-10-06 examples of what this gate prevents: `tests/scripts` not run before pushing a doc change (`84.9 s` broke two CI shards); a watcher loop declared running that had done nothing for an hour because `set -- $var` does not split in zsh.

**Precedence on conflict**: repo truth (code/config) > `NEXT_SESSION.md` > auto-memory. If recalled memory contradicts what you read now, trust the code and update the stale memory. Historical commits → `git log` (do not re-document in markdown).
