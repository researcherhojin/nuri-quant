# Contributing to Nuri-Quant

This is a single-maintainer personal investment platform, but the
contribution rules below apply to the maintainer too — most of them
exist because Claude Code agents work on this repo and need explicit,
mechanical guardrails.

If you are an external contributor: please open an issue first so we
can discuss scope before you write code. The project's design
principles are in [`docs/STRATEGY.md`](docs/STRATEGY.md) — read it
before proposing any non-trivial change.

## Quick start

```bash
# Prerequisites: Python 3.12, Node 22, Homebrew (for ta-lib)
brew install ta-lib
make setup                     # creates .venv, installs deps, initializes DB
cd frontend && npm ci          # frontend deps
make verify-quick              # ~10s smoke test (no network)
```

## The hard rules

These are enforced by `scripts/pre_push_check.sh` and CI. Violating
them gets your push rejected:

| Rule | Where it's enforced |
|------|---------------------|
| `ruff check nuri/ tests/ scripts/` clean | `pre_push_check.sh` Section 2 + CI Backend Lint |
| All tests pass | `pre_push_check.sh` Section 3 + CI Backend Tests |
| No personal financial data leaks (broker names, suspect monetary literals) | `pre_push_check.sh` Section 4 + CI `privacy-scan` |
| Conventional commit format | `pre_push_check.sh` Section 5 + CI PR Checks |
| No `datetime.now()` — use `kst_now()` / `today_kst()` | Project hook + reviewers |
| Force push to `main` | Blocked by branch protection (no exceptions) |

## Workflow — one issue, one PR

Adapted from `docs/STRATEGY.md` §5.4 (scope creep is the most common
LLM failure mode):

1. **Open an issue first** describing the problem and the proposed scope.
2. **Branch from `main`**: `git checkout -b feat/N-short-name` (or `fix/`, `chore/`, `docs/`).
3. **Keep the PR to ≤3 commits.** If you discover an unrelated bug while
   working, open a separate issue and PR for it. Do not bundle.
4. **Run `bash scripts/pre_push_check.sh`** before pushing.
5. **Open the PR with a "Closes #N" footer** and a Test Plan section.
6. **Wait for CI green** before requesting merge. Branch protection
   requires all 5 required checks (Backend Lint, Backend Tests,
   Frontend Tests, Frontend Build, Security Scan, Privacy Leak Scan).
7. **Squash-merge** is the default. Maintain a clean linear history.

## Commit message format

Conventional Commits, English, imperative mood:

```
type(scope): subject under 70 chars

Optional body with the WHY (not the what — the diff is the what).

Closes: #N
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`,
`chore`, `perf`, `ci`, `build`, `revert`. Compound types are allowed
with `+`: e.g. `feat+test(macro): ...`.

## Test discipline

- Backend: `pytest tests/ -n auto --dist worksteal`. Coverage tracked
  by Codecov; the gate is a 1% relative regression vs the prior commit
  (no fixed minimum percentage).
- Frontend: `cd frontend && npm test`. Watch out for the recharts
  `vi.mock` hoisting trap — keep recharts-dependent and recharts-free
  tests in separate files.
- E2E: `cd frontend && npx playwright test`.
- All tests must run **network-free**. `tests/conftest.py` mocks
  `yfinance.download` and `yfinance.Ticker` globally; new tests should
  override these monkeypatches per-test rather than removing the
  global mock.

## Where to put new code

| You're adding... | Put it here |
|------------------|-------------|
| A new data source | `nuri/collectors/` (subclass `BaseCollector`) |
| A new SQL table | New `_MIGRATIONS` entry in `nuri/core/db.py` — never edit existing migrations |
| A new agent | `nuri/trading/agents/` + register in `consensus.py` `ALL_AGENTS` + add weight in `config/agents.yaml` |
| A new investment rule | `config/rules.yaml` — never hardcode |
| A new API endpoint | `nuri/api/routes/` |
| A new dashboard page | `frontend/src/app/<route>/page.tsx` |
| A new LLM call | `nuri/llm/` only — portfolio data must stay local (Ollama) |
| A new shell script | `scripts/` + source `_common.sh` |

## What goes in `config/` vs hardcoded

`docs/STRATEGY.md` §2.2 ("기계적 실행"): rules go in YAML, code
**executes** the rules. If you find yourself adding a magic number to a
Python file, stop and ask whether it belongs in `config/agents.yaml`,
`config/rules.yaml`, or `config/signals.yaml`.

## Privacy — personal financial data

This is the most important rule. **Never** put any of the following
into git, an issue, a PR description, a commit message, a test
fixture, a code comment, or a CI log:

- Broker names (real brokerages, even your own)
- Real account identifiers
- Real holdings, quantities, prices, sectors
- Cash balances or total invested amounts

Use the placeholders defined in
[`docs/STRATEGY.md` §4.4.1](docs/STRATEGY.md): `Brokerage Alpha`,
`Brokerage Beta`, round-million numbers like `1_000_000`. The
`scripts/check_privacy_leak.py` scanner enforces this on every push
and every PR.

## When in doubt

- **Architecture / design questions** → read `docs/STRATEGY.md` first.
- **Day-to-day rules** → read `CLAUDE.md`.
- **Frontend specifics** → `frontend/CLAUDE.md`.
- **Where a function lives** → use `Grep` / `Glob`, don't guess.

The harness lessons in `docs/STRATEGY.md` §5 are written for Claude
Code agents but apply to humans too: if your second attempt fails the
same way as your first, **change your approach instead of trying a
third time**.
