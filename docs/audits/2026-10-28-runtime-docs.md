# Runtime documentation reconciliation — 2026-10-28

## Scope

Issue #2006 reconciles the current Markdown guides and agent rules with the
completed report-context (#1960), Reddit-retirement (#1979), interactive-thesis
(#1965) and pilot-infrastructure changes. Application baseline: `2bba37d3`; documentation rebased onto `485ae2d3` (#2007), which changes no application/configuration source. Its ledger inventory and scheduler-timezone corrections are retained.
It does not repeat the earlier broad [Markdown audit](2026-10-23-markdown.md)
or remeasure upstream publications, terms, model inventories or past experiments.

## Corrections and evidence

| Current documentation | Code evidence |
|---|---|
| The registry has 10 slots; retired retail always abstains and does not read old Reddit rows | `retail_agent.py`, `consensus/registry.py`, `tests/collectors/test_reddit.py`, `tests/trading/agents/test_retail.py` |
| Legacy Strata Q&A and Discord local Ollama B are different paths | `thesis_query.py`, `scripts/dev/llm_consult.py`, `thesis_remote.sh`, `thesis_interactive.py` |
| Discord progress and final output are allowlisted; raw context and errors remain local | `thesis_events.py`, `thesis_stream.py`, `bot.py`, handler/stream/interactive tests |
| Interactive execution is unscored; scheduled pilot execution has its own production ledger and freeze | `thesis_pilot.py`, `thesis_freeze.py`, pilot settings and scheduler registration |
| Report context is explicit; Mini can run its registered local Ollama workload | `report.py`, `config/llm_runtime.yaml`, completed #1960 production diagnostic |
| Both sending and receiving checkouts need the remote execution targets | `Makefile`, `thesis_remote.sh`, completed #1965 production-path verification |

English and Korean Architecture, Research Briefing and Strategy editions receive
matching changes. `AGENTS.md` and Claude's invariant rule are updated together.
The old September coverage baseline remains explicitly historical; the current
fast-suite result is distinguished from the larger collection count and from
excluded slow/integration tests. Historical probe observations are retained as
historical, rather than presented as current agent behavior.

Local-only `NEXT_SESSION.md`, `docs/TODO.md`, `docs/OPERATIONS.md` and
`docs/SOURCE_OF_TRUTH.md` are reconciled in the maintainer checkout, without being
added to Git. Private plans, protocol choices, samples and results stay private.
Vendor notices and prior dated audit results are preserved.

## Verification

Fresh local results on the documentation tree:

- `make test-fast`: 9,606 passed, zero skipped, 100% statements/branches; exit 0 (93.22 seconds).
- `.venv/bin/python -m pytest tests/verify/ -q --no-cov`: 134 passed; exit 0.
- `make verify-doc-counts`: 36 passed / 36 checks; exit 0.
- Static Markdown sweep: 62 files, 118 relative link/anchor destinations and 91 explicit Python test-node references; no missing destinations or nodes.
- Strategy pre-registration comparison: 4/4 sections byte-identical to `2bba37d3`; application/configuration files unchanged.

The PR records final pre-push, spelling/privacy and CI results. The static
reference sweep checks relative file/anchor destinations and explicit Python test-node
references across tracked Markdown; bilingual tests additionally check guide
anchors and structural parity. This is not a mutation-coverage or upstream-link
availability claim. No live inference or scored pilot is run for this doc change.

The four pre-registered Strategy sections (§3.11 and §3.12 in both editions),
experiment configuration and application source are compared with the base.
They must remain byte-identical.

## Post-merge follow-up — 2026-10-28

The interactive-runtime correction was merged in #2014, followed by the
English/Korean Research Briefing update in #2015 (`e81aa300`). The briefings
now point to `config/llm_interactive.yaml` for the exploratory runtime pin and
state that the scored pilot retains its independent version and digest
contract. This is a documentation pointer; the runtime values remain canonical
in configuration.

Fresh repository evidence at follow-up:

- `git status --short`: clean before this follow-up note.
- Local branches/worktrees: only `main`; no additional worktrees.
- Open pull requests: none reported by `gh pr list --state open`.
- Latest main CI run `40643484457` (Main CI Catch-up): completed successfully;
  latest workflow for #2015 `40643438654`: completed successfully.
- Two remote Dependabot branches remain visible and are retained as open
  dependency-update work, not deleted as stale feature branches.

No private analysis output, holdings, account data or host identifiers are part
of this public audit record.
