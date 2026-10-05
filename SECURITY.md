# Security Policy

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
| `diskcache` 5.6.3 | [CVE-2025-69872](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) | MEDIUM | Transitive dependency of `llama-cpp-python` (optional `local-llm` extra). The vulnerable path is unsafe pickle deserialization from the cache directory. `llama-cpp-python` imports `diskcache` only for `LlamaDiskCache`, and nothing in `nuri/` or `scripts/` creates that cache, so no cache is read from disk. | Upstream `diskcache` fix released, `LlamaDiskCache` used anywhere in the project, or `llama-cpp-python` removed. |

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

## Personal Financial Data

This is a personal investment platform. Test fixtures, examples, and
documentation must never contain real broker names, real account
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
2026-04-14). The full classification is in `docs/STRATEGY.md` §4.4.3.

| Data tier | External LLM | Condition |
|-----------|--------------|-----------|
| Tier 0 (public data) | Allowed: OpenAI `gpt-5.4-nano` for RSS headline classification | None |
| Tier 2 (portfolio data, daily LLM report) | Allowed: OpenAI `gpt-5.4-nano` | `OPENAI_ZDR_APPROVED=1`, attesting that Zero Data Retention was obtained from OpenAI. Without it, `chat_text(data_tier="tier2")` raises `ExternalLLMPolicyViolation` before any network call (#294) |
| Tier 1 (user narrative and memos) | Not allowed | Requires a policy revision and explicit user approval |

- All external calls go through `nuri/llm/openai_client.py`; importing
  `openai` elsewhere is forbidden. Each call writes an audit row to the
  `external_llm_calls` table; content is never logged.
- `NURI_DISABLE_EXTERNAL_LLM=1` disables all external LLM calls
  (CI, offline, privacy mode).
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
  (`docs/STRATEGY.md` §7.1). The only broker adapter targets the Alpaca paper
  endpoint, and credentials are read from `.env`, which is not committed.
- Mobile clients: there is no first-party mobile app.
- DDoS and rate-limit attacks on the FastAPI server. In production the API
  binds `127.0.0.1` (`scripts/launchd/com.nuri-quant.api.plist`) and is
  reachable only through the Next.js `/api/*` rewrite proxy on `:3000`,
  which is protected by `DASHBOARD_PASSWORD`. The developer entry points
  (`make api`, `make start`, `.vscode/launch.json`, the Playwright
  configuration) bind `0.0.0.0` and should not be used on a production host.
  Restrict exposure at the network, firewall, or reverse-proxy layer rather
  than relying on application-level rate limiting.
