# Security Policy

<!-- cspell:words certifi -->

## Supported Versions

Only the `main` branch is supported and receives security fixes. The project
does not publish tagged releases.

## Reporting a Vulnerability

Do not open a public issue. Use GitHub's private security advisory form:

<https://github.com/researcherhojin/nuri-quant/security/advisories/new>

Email reports are not monitored.

### Response SLA

| Phase | Target |
|-------|--------|
| Acknowledgement and initial triage | within 48 hours |
| HIGH / CRITICAL severity fix | within 7 days |
| MEDIUM severity fix | within 30 days |
| LOW severity fix | best effort |

If you do not receive an acknowledgement within 48 hours, add a comment to
the advisory.

### What to include in your report

- Affected file(s) / endpoint(s)
- Reproduction steps or proof of concept
- Impact assessment (confidentiality / integrity / availability)
- Suggested fix, if you have one

We will credit you in the advisory unless you ask to remain anonymous.

## Accepted Risks

Some dependency advisories are intentionally not patched because the
vulnerable code path is not reachable in this project. They are tracked
here so future audits can verify the rationale is still valid.

| Package | CVE | Severity | Why we accept it | Re-check trigger |
|---------|-----|----------|------------------|------------------|
| `diskcache` 5.6.3 | [CVE-2025-69872](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) | MEDIUM | Transitive dependency of `llama-cpp-python` (optional `local-llm` extra). The vulnerable path is unsafe pickle deserialization from the cache directory. `llama-cpp-python` imports `diskcache` only for `LlamaDiskCache`, and nothing in `nuri/` or `scripts/` creates that cache, so no cache is read from disk. The GGUF path also calls `set_cache(None)` before inference and skips inference if that fails (#1896). | Upstream `diskcache` fix released, `LlamaDiskCache` used anywhere in the project, or `llama-cpp-python` removed. |
| `braces` 3.0.3 (npm) | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | HIGH | No patched release exists (`<= 3.0.3`). Since the shadcn runtime dependency was removed (#1894), the only path is lint tooling: `eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch`. `npm audit --omit=dev` reports 0, no application code imports a glob library, and the lint globs come from repository config, not user input. The DoS needs attacker-controlled nested patterns (#1889). | A patched `braces` release, `eslint-config-next` dropping `fast-glob`, or `npm audit --omit=dev` reporting it. |

When adding a new accepted risk:

1. File the dismissal in GitHub's Dependabot UI with the same rationale.
2. Append a row to the table above.
3. Set a concrete `Re-check trigger`, not "review later".

## Automated Security Controls

The repository runs the following on every PR and every push to `main`:

| Control | Where | Gates merge? |
|---------|-------|--------------|
| Trivy filesystem scan, CRITICAL severity | `.github/workflows/main-ci-cd.yml` `security-scan` job (`Security Scan`) | Yes. Fast-passes when no backend or frontend files changed |
| CodeQL (Python, JavaScript/TypeScript, GitHub Actions) | GitHub code scanning default setup, weekly and on PRs | No. Alerts appear in the Security tab |
| Privacy leak scanner ([#138](https://github.com/researcherhojin/nuri-quant/issues/138)) | `scripts/verify/check_privacy_leak.py`, run by the `privacy-scan` job (`Privacy Leak Scan`) and `scripts/verify/pre_push_check.sh` | Yes. Blocks broker names, suspect monetary literals, ticker+signed-% combinations and personal identifiers |
| Dependabot alerts and version updates | Repository settings; `.github/dependabot.yml` (uv and npm weekly, GitHub Actions monthly) | No. Security-fix PRs are not enabled; version-update PRs follow the schedule |
| Branch protection on `main` | GitHub repository settings | All required checks must pass; force push and deletion blocked |

### Dependency graph and alert reconciliation

For Python dependencies, inspect the dynamic `Dependency Graph` workflow and
exported SBOM as well as `uv.lock`. A stale graph can retain alerts after a
patch is installed. The freeze tracked in [#1899](https://github.com/researcherhojin/nuri-quant/issues/1899)
ended after [#1926](https://github.com/researcherhojin/nuri-quant/pull/1926):
[run 39907392741](https://github.com/researcherhojin/nuri-quant/actions/runs/39907392741)
succeeded on 2026-10-23 with lock revision 5. The SBOM reported Pillow 13.0.0,
certifi 2026.10.19, aiohttp 3.14.4, OpenTelemetry API 1.45.1 and Next.js 16.4.1.
The Next.js and OpenTelemetry patches were also verified in production.

Graph refresh does not by itself prove that alert status has reconciled.
Alerts #241–#243 and #254 still showed `open` at the post-deploy check despite
patched versions in main, production and the SBOM; GitHub marked all four
`fixed` at 08:35 UTC, about 2 h 50 min after that graph run. On 2026-10-26
the same step took about one minute: alerts #258–#262 went `fixed` right after
the graph runs for [#1933](https://github.com/researcherhojin/nuri-quant/pull/1933)
and [#1941](https://github.com/researcherhojin/nuri-quant/pull/1941). An alert
still `open` shortly after a graph run is therefore not evidence of a missed
patch. Compare each alert's manifest and version with those sources before
deciding on further action.
These patched dependencies are not accepted risks. An alert dismissal, when
supported by evidence, must retain that evidence and must not be reported as
GitHub automatically marking the alert `fixed`.

## Personal Financial Data

This is a personal investment platform: the repository is public, and
the deployed system runs on the maintainer's real portfolio. Test
fixtures, examples, and documentation must never contain real broker names, real account
identifiers, real holdings, real quantities, real prices, or real
balances. The full policy is in
[`docs/STRATEGY.md` §4.4 + §4.4.1](docs/STRATEGY.md), enforced by
`scripts/verify/check_privacy_leak.py`. The same scanner also refuses
personal identifiers by shape (`<account>@<host>.local`, `/Users/<account>/`,
Korean-default macOS hostnames), so the scanner never has to contain them.

If you discover a leak in `main` history, report it via the security
advisory channel above so the maintainer can request GitHub Support
cache invalidation (and, if necessary, coordinate a history rewrite).

A full-history rewrite was carried out on 2026-09-29: all 1,471 commits on
`main` were rewritten to purge broker names, personal identifiers,
ticker+PnL pairs and monetary literals from commit messages and historical
blobs, and to replace author identities that embedded a machine hostname.
Commit SHAs therefore differ from any reference published before that date;
`docs/STRATEGY.md` §4.4.1 records the measurements and what was preserved.

## LLM and Model Safety

External LLM use is governed by a per-data-tier whitelist (updated
2026-10-23 documentation review). The full classification is in `docs/STRATEGY.md` §4.4.3.

| Data tier | External LLM | Condition |
|-----------|--------------|-----------|
| Tier 0 (public data) | Allowed: OpenAI `gpt-6-luna` for RSS classification and `gpt-5.4` for public ticker briefings | Public-data allowlist; see `docs/RESEARCH_BRIEFING.md` |
| Tier 2 (portfolio data, LLM report) | Not allowed — the report is generated by a local model only | The gateway refuses any `data_tier` other than `tier0` before any network call. The earlier OpenAI path behind `OPENAI_ZDR_APPROVED=1` was removed on 2026-10-08 |
| Tier 1 (user narrative and memos) | Not allowed | Requires a policy revision and explicit user approval |

- Verdicts are rule-based: the agents, the consensus and the decision
  record call no LLM. The only model output that reaches them is the
  Tier 0 headline classification, through the `macro_events` table.
- External calls must go through `nuri/llm/openai_client.py`; importing
  `openai` elsewhere is forbidden. Each call writes an audit row to the
  `external_llm_calls` table; content is never logged.
- `NURI_DISABLE_EXTERNAL_LLM=1` disables the external gateway. It is not
  a process-wide network sandbox and does not govern independent CLI tools.
  Private-context thesis tooling is enforced in code: `nuri/llm/thesis_query.py`
  always runs `scripts/dev/llm_consult.py --local-only`, which refuses a
  non-loopback local-model URL before any network call, ignores environment
  proxies, and has no Codex fallback ([#1943](https://github.com/researcherhojin/nuri-quant/pull/1943),
  [#1944](https://github.com/researcherhojin/nuri-quant/pull/1944)). When the
  local model cannot answer, the run fails rather than falling back.
  Other developer CLI entry points are not covered by this enforcement.
- Outputs from `nuri/llm/report.py` are validated for hallucinations:
  numbers not present in the input data are flagged before the report
  is surfaced.
- The event classifier (`nuri/llm/event_classifier.py`) has a
  deterministic regex fallback so the data pipeline keeps working when
  the LLM provider is unavailable.

## Out of Scope

The following are intentionally not part of the threat model:

- Multi-tenant isolation: this is a single-user platform.
- Authenticated brokerage trading: order execution is out of scope
  (`docs/STRATEGY.md` §7.1). The only broker adapter defaults to the Alpaca paper
  endpoint (`ALPACA_BASE_URL` can override it; nothing in the pipeline calls it), and credentials are read from `.env`, which is not committed.
- Mobile clients: there is no first-party mobile app.
- DDoS and rate-limit attacks on the FastAPI server. In production the API
  binds `127.0.0.1` (`scripts/launchd/com.nuri-quant.api.plist`) and is
  reachable only through the Next.js `/api/*` rewrite proxy on `:3000`,
  which is protected by `DASHBOARD_PASSWORD`. The developer entry points
  (`make api`, `make start`, `.vscode/launch.json`, the Playwright
  configuration) bind `0.0.0.0` and should not be used on a production host.
  Restrict exposure at the network, firewall, or reverse-proxy layer rather
  than relying on application-level rate limiting.
