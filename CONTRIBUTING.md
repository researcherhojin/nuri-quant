# Contributing to Nuri-Quant

Nuri-Quant is maintained by a single maintainer. The rules below apply to
every change, including the maintainer's own. Coding agents also work in this
repository, so most rules are enforced mechanically rather than by convention.

External contributors should open an issue before writing code so that scope
can be agreed first. Read [`docs/STRATEGY.md`](docs/STRATEGY.md), which defines
the project's design principles, before proposing a non-trivial change.

## Quick start

```bash
# Prerequisites: Python 3.12, uv, Node 22, Homebrew (for ta-lib)
brew install ta-lib
cp config/portfolio.example.yaml config/portfolio.yaml  # required by make setup
make setup                     # .venv, dependencies, DB, portfolio import, git hooks
cd frontend && npm ci          # frontend deps
make verify-quick              # smoke test, no network (84.9s on an M5 Max, 2026-08-14)
```

`make setup` installs the `pre-commit` and `pre-push` hooks from
`scripts/hooks/` (`make setup-hooks`).

## Checks

| Rule | Where it is checked | Blocking |
|------|---------------------|----------|
| `ruff check nuri/ tests/ scripts/` clean | `scripts/verify/pre_push_check.sh` Section 2, CI `Backend Lint` | Yes |
| All tests pass | CI `Backend Tests`; `pre_push_check.sh` Section 3 on a full run only (the pre-push hook passes `--skip-tests`) | Yes (CI) |
| No personal financial data (broker names, suspect monetary literals, ticker+PnL) or personal identifiers (`account@host.local`, `/Users/<account>/`, real-name hostnames, matched by shape) | `pre_push_check.sh` Sections 4 and 4b, CI `Privacy Leak Scan`, Claude Code PreToolUse hook | Yes |
| No unregistered words (`.cspell.json`, kept ASCII-sorted) | `pre_push_check.sh` Section 2d, CI `Quick Checks` (`make spellcheck-ci`) | Yes |
| Conventional commit format | `pre_push_check.sh` Section 5 (latest commit only) | No (warning) |
| At most 3 commits per PR | CI `PR Discipline` workflow (escape label: `scope-expand-approved`) | No (not a required check) |
| No `datetime.now()`; use `kst_now()` / `today_kst()` | Claude Code PostToolUse hook (`.claude/settings.json`), code review | Review |
| No force push to `main` | Branch protection | Yes |

## Workflow: one issue, one PR

The workflow follows `docs/STRATEGY.md` §5.4, which identifies scope creep as
the most common failure mode for coding agents.

1. Open an issue describing the problem and the proposed scope.
2. Branch from `main`: `git checkout -b feat/N-short-name` (or `fix/`, `chore/`, `docs/`).
3. Keep the PR to at most 3 commits. If you find an unrelated bug, open a
   separate issue and PR for it.
4. The pre-push hook runs `scripts/verify/pre_push_check.sh --skip-tests`.
   Run `bash scripts/verify/pre_push_check.sh` without flags to include the
   test suite.
5. Open the PR with a `Closes #N` footer and a test plan.
6. Wait for CI to pass. Branch protection requires these checks:
   Backend Tests, Backend Lint, Frontend Tests, Frontend Lint, Frontend Build,
   Security Scan, Universe Coverage Validation, Shell Lint, Doc Count Drift
   Check, Privacy Leak Scan, Local-LLM Build Gate, uv.lock Major Boundary,
   package-lock.json Major Boundary, Quick Checks. The authoritative list is
   `gh api repos/{owner}/{repo}/branches/main/protection`.
7. Merge with `gh pr merge --squash --delete-branch`.
8. Expect merges to serialize. `main` requires branches to be up to date, so
   each merge puts the remaining open PRs behind. Each one then needs
   `gh pr update-branch` and a full CI run before it can merge. Merge the PR
   that unblocks the others first.

## Commit message format

Conventional Commits, English, imperative mood:

```
type(scope): subject under 70 chars

Optional body explaining why; the diff shows what.

Closes: #N
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`,
`perf`, `ci`, `build`, `revert`. Compound types are joined with `+`, for
example `feat+test(macro): ...`.

## Test discipline

- Backend: `pytest tests/ -n auto --dist worksteal`. Codecov reports coverage
  but is not a required check. The project status allows a 1% drop against
  the base commit; the patch status targets 100% of changed lines.
- Frontend: `cd frontend && npm test`. `vi.mock("recharts")` is hoisted and
  affects every test in the same worker, so keep recharts-dependent and
  recharts-free tests in separate files.
- E2E: `cd frontend && npx playwright test`.
- All tests must run without network access. `tests/conftest.py` mocks
  `yfinance.download` and `yfinance.Ticker` globally; override these
  monkeypatches per test rather than removing the global mock.

## Where to put new code

| You're adding... | Put it here |
|------------------|-------------|
| A new data source | `nuri/collectors/` (subclass `BaseCollector`) |
| A new SQL table | New `_MIGRATIONS` entry in `nuri/core/db_migrations.py`; never edit existing migrations |
| A new agent | `nuri/trading/agents/`, registered in `build_all_agents()` in `nuri/trading/agents/consensus/registry.py`, with its weight in `config/agents.yaml` |
| A new investment rule | `config/rules.yaml`; never hardcode |
| A new API endpoint | `nuri/api/routes/` |
| A new dashboard page | `frontend/src/app/<route>/page.tsx` |
| A new LLM call | `nuri/llm/`. External LLM calls go through `nuri/llm/openai_client.py` only; portfolio data may be sent only under the Tier 2 rule (`OPENAI_ZDR_APPROVED=1`). See `docs/STRATEGY.md` §4.4.3. |
| A new shell script | `scripts/<category>/`, sourcing `scripts/_common.sh` (see [`scripts/README.md`](scripts/README.md)) |

## What goes in `config/` vs hardcoded

Per `docs/STRATEGY.md` §2.2, rules live in YAML and code executes them. A
magic number in a Python file usually belongs in `config/agents.yaml`,
`config/rules.yaml`, or `config/signals.yaml`.

## Privacy: personal financial data

Never put any of the following into git, an issue, a PR description, a commit
message, a test fixture, a code comment, or a CI log:

- Broker names (real brokerages, including your own)
- Real account identifiers
- Real holdings, quantities, prices, or sectors
- Cash balances or total invested amounts

Use the placeholders defined in
[`docs/STRATEGY.md` §4.4.1](docs/STRATEGY.md): `Brokerage Alpha`,
`Brokerage Beta`, and round-million numbers such as `1_000_000`.
`scripts/verify/check_privacy_leak.py` enforces this on every push and every
PR.

## When in doubt

- Architecture and design: `docs/STRATEGY.md`.
- Day-to-day rules: `CLAUDE.md` and `.claude/rules/`.
- Frontend conventions: `frontend/CLAUDE.md`.
- Locating code: search the repository (`git grep`) rather than guessing.

`docs/STRATEGY.md` §5 records lessons from agent-driven development. One
applies equally to people: if a second attempt fails the same way as the
first, change the approach before trying again.

## Reporting bugs

Use the issue templates in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/). Report security
vulnerabilities as described in [`SECURITY.md`](SECURITY.md), not in a public
issue.
