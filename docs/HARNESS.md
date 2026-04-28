# docs/HARNESS.md — Pointer (deprecated content)

The case-study content that previously lived here moved to the **`/nuri-harness-debug` skill** in 2026-04-28 as part of the doc refactor sequence. The skill is the canonical owner of:

- 6 LLM failure patterns (hallucination / confirmation bias / phantom fix / scope creep / test illusion / number drift) — symptoms, real cases, Gotcha-Test Pair protocol detail
- Case study #1 — #272 session lessons (2026-04-14, 12 PRs): mock-only ship trap, API concurrency asymmetry, ThreadPool timeout, user-workflow verification, multi-role flow
- Case study #2 — JKHY episode (PRs #300-#303, #306, #307): dissent overwhelmed, mechanical divergence penalty, initial diagnosis correction
- 7-principle reference card (`docs/STRATEGY.md §5.8` is the always-on canonical)

Kept (not deleted) so existing `docs/HARNESS.md §1` / `§2` references in `STRATEGY.md §5.9` + historical PR/commit messages + `codex-reviews/` archives still resolve.

## Canonical sources

| Topic | Canonical |
|-------|-----------|
| 7 harness principles (always-on) | `docs/STRATEGY.md §5.8` |
| 6 failure-pattern diagnostic flow | `/nuri-harness-debug` skill (`.claude/skills/nuri-harness-debug/SKILL.md`) |
| Gotcha-Test Pair protocol detail | `/nuri-harness-debug` skill |
| #272 session case study (12 PRs) | `/nuri-harness-debug` skill (was `docs/HARNESS.md §1`) |
| JKHY episode case study | `/nuri-harness-debug` skill (was `docs/HARNESS.md §2`) |
| File-ownership map | `docs/SOURCE_OF_TRUTH.md` |

## Invocation

The skill auto-loads when the conversation hits a relevant trigger ("test passes but bug persists", "fix applied 3 times same way", "Claude hallucinated this function", etc.). Manual invocation: `/nuri-harness-debug`.

If you arrived here from an old PR description or commit message expecting a `§1` or `§2` heading: those sections moved to the skill. Open it directly or wait for auto-trigger.
