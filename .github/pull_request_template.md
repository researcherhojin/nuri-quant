<!--
PR Template — fill in each section before requesting review.
Discipline checklist below catches the failure modes that wasted ~120 min in
the previous session (drift bugs, atomicity, scope creep).
-->

## Summary

<!-- 1-3 bullets explaining what changed and why. Link related issues: Closes #__ -->

-

## Test plan

<!-- How did you verify this works? -->

- [ ] `bash scripts/verify/pre_push_check.sh` passes locally (drift + lint + tests)
- [ ] `bash scripts/dev/ci_local.sh` passes (exact CI command parity)
- [ ] If multi-commit: `bash scripts/verify/check_atomic.sh` passes (each commit standalone)
- [ ] `make lint` passes
- [ ] `make test` passes (or `make verify-quick`)

## Drift check (catches "passes locally / fails CI" bugs)

- [ ] `python scripts/verify/check_drift.py` shows ≤5 unrelated uncommitted files
- [ ] No file in this PR references an uncommitted file outside this PR scope
- [ ] If touching `pyproject.toml` / `tests/conftest.py` / `nuri/core/db/`,
      verified the committed version on this branch matches local working tree

## Scope discipline

- [ ] PR addresses a single concern (no scope creep)
- [ ] Commits ≤ 3 (or justified in summary)
- [ ] Conventional commit format on each commit (`type(scope): message`)
- [ ] No previous-session work bundled in (separate PR)
- [ ] Follows STRATEGY.md principles (evidence-first, mechanical execution)
- [ ] Config in `config/*.yaml` (no hardcoded values)
- [ ] Numbers updated if changed (README, CLAUDE.md, STRATEGY.md)

## Privacy (STRATEGY.md §4.4.1 — enforced by `scripts/verify/check_privacy_leak.py`)

- [ ] No broker names, account holdings, avg price, quantity, or ticker + PnL
      in diff, tests, commit messages, or PR body
- [ ] Scanner clean: `.venv/bin/python scripts/verify/check_privacy_leak.py --unpushed-commits`

## Risk

<!-- What could go wrong? What's the rollback path? -->

- Rollback:
