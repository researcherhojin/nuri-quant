<!--
Fill in each section before requesting review. The checklist covers the
failure modes this repository has seen most often: drift between the working
tree and the commit, non-atomic commits, and scope creep.
-->

## Summary

<!-- 1-3 bullets on what changed and why. Link the issue: Closes #__ -->

-

## Test plan

<!-- How did you verify this works? -->

- [ ] `bash scripts/verify/pre_push_check.sh` passes locally (full run, including tests)
- [ ] `bash scripts/dev/ci_local.sh` passes (CI test command parity)
- [ ] If multi-commit: `bash scripts/verify/check_atomic.sh` passes (each commit stands alone)
- [ ] `make lint` passes
- [ ] `make test` passes (or `make verify-quick`)

## Drift check

- [ ] `.venv/bin/python scripts/verify/check_drift.py` reports no drift risk (it warns above 5 uncommitted files)
- [ ] No file in this PR references an uncommitted file outside this PR's scope
- [ ] If touching `pyproject.toml`, `tests/conftest.py` or `nuri/core/db/`,
      the committed version on this branch matches the local working tree

## Scope

- [ ] The PR addresses a single concern
- [ ] At most 3 commits (or justified in the summary)
- [ ] Each commit uses the conventional format (`type(scope): message`)
- [ ] No unrelated earlier work is bundled in
- [ ] Follows `docs/STRATEGY.md` principles (evidence first, mechanical execution)
- [ ] Thresholds and rules live in `config/*.yaml`, not in code
- [ ] Counts in docs updated if changed (`make verify-doc-counts`)

## Privacy

Per `docs/STRATEGY.md` §4.4.1, enforced by `scripts/verify/check_privacy_leak.py`.

- [ ] No broker names, holdings, average prices, quantities, ticker+PnL
      combinations or personal identifiers in the diff, tests, commit
      messages or PR body
- [ ] Scanner clean: `.venv/bin/python scripts/verify/check_privacy_leak.py --unpushed-commits`

## Risk

<!-- What could go wrong? What is the rollback path? -->

- Rollback:
