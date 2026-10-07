# Contributing to Nuri-Quant

Nuri-Quant is maintained by a single maintainer. The rules below apply to
every change, including the maintainer's own. Coding agents also work in this
repository, so most rules are enforced mechanically rather than by convention.

External contributors should open an issue before writing code so that scope
can be agreed first. Read [`docs/STRATEGY.md`](docs/STRATEGY.md), which defines
the project's design principles, before proposing a non-trivial change.

## Quick start

```bash
# Prerequisites: Python 3.12, uv, Node.js 22, TA-Lib (C library)
brew install ta-lib                                      # macOS; CI builds it from source
cp config/portfolio.example.yaml config/portfolio.yaml   # make setup imports it into the DB
make setup                      # .venv + dependencies, migrations, portfolio import, git hooks
cd frontend && npm ci && cd ..  # frontend dependencies
make verify-quick               # pre-commit smoke (84.9s on an M5 Max, 2026-08-14)
```

`make setup` installs the repo-tracked `pre-commit` and `pre-push` hooks
(`make setup-hooks`, idempotent). The pre-commit hook runs `ruff` and `eslint`
auto-fixes on staged files and re-stages the result; it never blocks a commit.

## Checks

### Local gates

The pre-push hook runs `scripts/verify/pre_push_check.sh --skip-tests` (about
7 s). Running the script without the flag adds the full test suite. Its sections:

| Section | What it checks | Blocking |
|---------|----------------|----------|
| 1 | Working-tree drift (`scripts/verify/check_drift.py --strict`): an uncommitted change that makes local checks pass while CI runs the committed version | Yes |
| 2 | `ruff check nuri/ tests/ scripts/` | Yes |
| 2b | `shellcheck` on `scripts/**/*.sh` | Yes when installed; a warning otherwise, CI enforces |
| 2c | Count claims in README, ARCHITECTURE, STRATEGY and the scoped `CLAUDE.md` / rules files match the repository (`make verify-doc-counts`; fixer `scripts/doc/sync_doc_counts.sh`) | Yes |
| 2d | Spellcheck (`.cspell.json`, kept ASCII-sorted) and a `pyright` ratchet on the lines the push adds | Yes when `npx` is available; skipped with a warning otherwise, CI enforces the spellcheck |
| 3 | Tests (only without `--skip-tests`) | Yes |
| 4 / 4b | Privacy scan of the tree and of unpushed commit messages (`scripts/verify/check_privacy_leak.py`) | Yes |
| 5 | Conventional-commit format of the latest commit | No (warning) |

### Required CI checks

Branch protection on `main` requires these 14 checks (authoritative list:
`gh api repos/{owner}/{repo}/branches/main/protection`), with
`enforce_admins` on and no review count required:

| Check | What it enforces |
|-------|------------------|
| Backend Tests | pytest across fast and slow shards (a separate, non-required job aggregates coverage for Codecov) |
| Backend Lint | `ruff check` |
| Frontend Tests / Frontend Lint / Frontend Build | vitest, eslint, `next build` |
| Shell Lint | shellcheck |
| Privacy Leak Scan | `check_privacy_leak.py` on the checked-out tree |
| Security Scan | Trivy, CRITICAL findings only |
| Doc Count Drift Check | same as local section 2c (the CI job has no `.venv`, so the Python-derived counts are checked only by the local hook) |
| Quick Checks | no file over 5 MB; `make spellcheck-ci` |
| Universe Coverage Validation | inline sanity check of `config/universe.yaml`: it parses and keeps at least 478 US and 190 KR tickers (CI has no DB or network for the full coverage report) |
| Local-LLM Build Gate | `llama-cpp-python` still builds on Linux whenever `pyproject.toml` or `uv.lock` changes (any PR, and every push); other PRs pass immediately |
| uv.lock Major Boundary / package-lock.json Major Boundary | a lock file does not cross a major version (or a 0.x boundary for direct dependencies) unnoticed. Escape hatch: the `lock-bump-reviewed` label, read from the API, so adding it later and re-running the failed job is enough |

`required_status_checks.strict` is on: a PR must contain the current `main`
before it can merge, so every merge puts the other open PRs behind. Rebase
(or `gh pr update-branch`) and let CI run again; merge the PR that unblocks
the others first.

### Advisory

- `PR Discipline` workflow: at most 3 commits per PR (escape label
  `scope-expand-approved`, also read from the API). Not a required check.
- Codecov: project status allows a 1 % drop against the base commit; the patch
  status targets 100 % of changed lines. Not required.
- `Frontend E2E` (Playwright, 78 tests in 9 spec files against a seeded DB) runs on PRs that
  touch the frontend or the backend. Not required.
- Claude Code hooks (`.claude/settings.json`) block `import sqlite3` outside
  `nuri/core/db/connection.py`, `datetime.now()`, destructive git commands and
  privacy-leaking writes for agent sessions. They do not run for other tools;
  `tests/core/test_sqlite3_sole_importer.py` and the timezone convention in
  `.claude/rules/invariants.md` are the backstops.

## Workflow: one issue, one PR

The workflow follows `docs/STRATEGY.md` §5.1–5.6 (the "스코프 팽창" row of the failure-pattern table), which identifies scope creep as
the most common failure mode for coding agents.

1. Open an issue describing the problem and the proposed scope.
2. Branch from `main` as `type/short-name` (`feat/`, `fix/`, `docs/`,
   `refactor/`, `chore/`). The issue number goes in the commit subject and
   the PR title as `(#N)`, not in the branch name.
3. Keep the PR to at most 3 commits. If you find an unrelated bug, open a
   separate issue and PR for it. A series that needs several PRs stacks them
   and rebases each one onto `main` after the previous one merges
   (`git rebase --onto origin/main <old base> <branch>`, then
   `git push --force-with-lease`).
4. Push; the pre-push hook runs the local gates above.
5. Open the PR with a `Closes #N` line and the checks you ran.
6. Non-trivial changes get a cross-model review before merge. In agent
   sessions this is the Codex review of `.claude/rules/flow.md` phase 4; for
   contributors the maintainer runs it.
7. Merge with `gh pr merge --squash --auto` once CI is green. The repository
   deletes the head branch on merge (`delete_branch_on_merge`), so delete only
   your local branch afterwards.

## Commit message format

Conventional Commits, subject in English and imperative mood, at most 70
characters. The issue number closes the subject:

```
type(scope): subject (#N)

Optional body explaining why; the diff shows what.
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`,
`perf`, `ci`, `build`, `revert`. Compound types join with `+`, for example
`feat+test(macro): ...`. The local gate checks only the latest commit's shape
(`type(scope): ...`) and warns; Korean subjects in older history are drift,
not precedent. Comments inside code may be Korean; identifiers are English.

## Test discipline

- Backend: `make test` (`pytest tests/ -n auto --dist worksteal` with branch
  coverage) or `make test-fast` to skip tests marked `slow` / `integration`.
  A single test: `.venv/bin/python -m pytest <path>::<test> -v`.
- Frontend: `cd frontend && npm test`. `vi.mock("recharts")` is hoisted and
  affects every test in the same worker, so keep recharts-dependent and
  recharts-free tests in separate files.
- E2E: `cd frontend && npx playwright test` (starts the API and the dev server
  itself; locally it runs against the dev DB).
- Tests run without network access. `tests/conftest.py` mocks
  `yfinance.download` and `yfinance.Ticker` for every test; override the
  monkeypatch per test rather than removing the global mock.
- Defensive code needs a regression test that fails if the fix is reverted
  (`docs/STRATEGY.md` §5.3.1). A gotcha without such a test is removed the
  next time nobody remembers why it exists.

## Dependencies

Dependabot opens weekly PRs for `uv` and npm and monthly ones for GitHub Actions (`.github/dependabot.yml`), and
`dependabot-auto-merge.yml` enables auto-merge for patch and minor updates
whose lock file stays inside the major boundary. Lock-file PRs merge one at a
time because of the strict up-to-date rule: rebase (`@dependabot rebase`),
wait for CI, merge, repeat. `@dependabot recreate` force-pushes and turns
auto-merge off. Details and the gotchas behind the lock gates:
`.claude/rules/ci-deps.md`.

## Where to put new code

| You're adding... | Put it here |
|------------------|-------------|
| A new data source | `nuri/collectors/` (subclass `BaseCollector`) |
| A new SQL table | New `_MIGRATIONS` entry in `nuri/core/db_migrations.py`; never edit existing migrations |
| A new agent | `nuri/trading/agents/`, registered in `build_all_agents()` in `nuri/trading/agents/consensus/registry.py`, with its weight in `config/agents.yaml` |
| A new investment rule | `config/rules.yaml`; never hardcode |
| A new API endpoint | `nuri/api/routes/` (see `nuri/api/CLAUDE.md` for router registration) |
| A new dashboard page | `frontend/src/app/<route>/page.tsx` |
| A new LLM call | `nuri/llm/`. External LLM calls go through `nuri/llm/openai_client.py` only; portfolio data may be sent only under the Tier 2 rule (`OPENAI_ZDR_APPROVED=1`). See `docs/STRATEGY.md` §4.4.3 |
| A new MCP read model | `nuri/mcp/readmodels.py`; every column must be in `ALLOWED`, every query `readonly=True` (#1306) |
| A new shell script | `scripts/<category>/`, sourcing `scripts/_common.sh` (see [`scripts/README.md`](scripts/README.md)) |
| A one-off analysis script | `scripts/analysis/` is gitignored by default; a reviewed script is tracked by adding a negation for it in `.gitignore` and a row in `scripts/README.md` |

## What goes in `config/` vs hardcoded

Per `docs/STRATEGY.md` §2.2, rules live in YAML and code executes them. A
magic number in a Python file usually belongs in `config/agents.yaml`,
`config/rules.yaml`, or `config/signals.yaml`. Infrastructure thresholds
(timeouts, cache TTLs, staleness of a replica file) are code constants, not
investment rules.

## Privacy: personal financial data

Never put any of the following into git, an issue, a PR description, a commit
message, a test fixture, a code comment, or a CI log:

- Broker names (real brokerages, including your own)
- Real account identifiers, hostnames or home-directory paths that carry a
  person's name
- Real holdings, quantities, prices, or sectors
- Cash balances or total invested amounts

Use the placeholders defined in
[`docs/STRATEGY.md` §4.4.1](docs/STRATEGY.md): `Brokerage Alpha`,
`Brokerage Beta`, round-million numbers such as `1_000_000`,
`user@macmini.local` and `/Users/USER/`.
`scripts/verify/check_privacy_leak.py` enforces this on every push and every
PR; `.gitignore` is the first layer (`config/portfolio*`, `.env*`, the local
docs and `data/` archives listed there).

## When in doubt

- Architecture and design: `docs/STRATEGY.md`; runtime layout:
  `docs/ARCHITECTURE.md`.
- Day-to-day rules for agent sessions: `CLAUDE.md`, `.claude/rules/` and
  `AGENTS.md` (the copy other tools read; change both together).
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
