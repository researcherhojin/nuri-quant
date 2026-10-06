# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Behavioral guidelines for Claude Code on **Nuri-Quant (누리퀀트)** — open-source quant investment platform (Python 3.12 / `uv` / SQLite). Adapted from [Karpathy's CLAUDE.md](https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md).

Project-specific rules (invariants, 7-phase Flow, load triggers, mechanical enforcement, architecture, gotchas) live in `.claude/rules/` and load alongside this file. Canonical "why" behind decisions: `docs/STRATEGY.md` (load on demand).

**Session start**: read `NEXT_SESSION.md` first if present (gitignored handoff).

## Claude Code environment

- **Hooks** (`.claude/settings.json`): PreToolUse blocks `import sqlite3` outside `nuri/core/db/connection.py`, `git push --force` / `reset --hard` / `clean -f`, and privacy-leaking writes; PostToolUse blocks `datetime.now()`. Details: `.claude/rules/enforcement.md`.
- **`.env` is out of reach in a session**: the settings deny `Read`/`Edit` on `**/.env`, and the file carries the macOS `uchg` flag. Processes started from the session, including `!` commands and editors opened that way, inherit the restriction. Write the result to `.env.new` and have the user swap it in from a terminal app (`chflags nouchg .env && mv -f .env.new .env && chflags uchg .env`).
- **Cross-model review**: the `nuri-codex-review` agent runs Codex for Flow phase 4. Codex reads `AGENTS.md`, not this file — when `.claude/rules/invariants.md` changes, update `AGENTS.md` in the same PR.
- **Project skills and commands** use the `nuri-` prefix (`.claude/skills/`, `.claude/commands/`).
- **Commit and PR titles are English**, even where recent `main` history is not.
- **Project output style** `nuri-attention-kind` (`.claude/output-styles/`, set in `settings.json`): answer first, shortest complete reply. **Completion claims need fresh evidence** — the five-step gate is in `.claude/rules/flow.md`; a subagent's report or a previous run does not count.
- **Push once, after the local gates.** CI runtime is 4–5 min but one run fans out 19 jobs against a 20-job concurrency limit and the workflow cancels the in-progress run on every push, so each re-push re-queues from the back. Run `bash scripts/verify/pre_push_check.sh --skip-tests` plus the affected tests, fold all review findings into one push, and keep working while CI queues.
- **Git hooks live in `.git/hooks` as symlinks into this checkout.** They went dead when the repository moved directories; if a push slips past a local gate, check `ls -la .git/hooks/pre-push` resolves inside the current checkout and re-run `make setup-hooks`.
- **The working tree is shared with subagents and the Codex review agent.** Do not switch branches while one is working in it (uncommitted edits follow the checkout, and a review runs against the wrong tree); use a temporary `git worktree` instead. Stacked PRs are moved with `git rebase --onto origin/main <old base> <branch>` and `git push --force-with-lease` — the hook blocks only a bare `--force`.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
