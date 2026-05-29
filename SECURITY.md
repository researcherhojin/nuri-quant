# Security Policy

## Supported Versions

Only the `main` branch receives security patches. Tagged releases are
snapshots; if you need to apply a fix to a tag, fork from the closest
release tag and cherry-pick from `main`.

| Version | Supported |
|---------|-----------|
| `main`  | ✓         |
| Any tag | ✗ (use `main`) |

## Reporting a Vulnerability

**Do not open a public issue.** Use GitHub's private security advisory
channel:

→ <https://github.com/researcherhojin/nuri-quant/security/advisories/new>

Email reports are not monitored.

### Response SLA

| Phase | Target |
|-------|--------|
| Acknowledgement + initial triage | within **48 hours** |
| HIGH / CRITICAL severity patch | within **7 days** |
| MEDIUM severity patch | within **30 days** or next release |
| LOW severity patch | next release |

If you do not receive an acknowledgement within 48 hours, please ping
the maintainer in a follow-up advisory comment — the notification may
have been missed.

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
| `diskcache` 5.6.3 | [CVE-2025-69872](https://github.com/advisories/GHSA-69872) | MEDIUM | Transitive dependency of `llama-cpp-python`. The vulnerable path is unsafe pickle deserialization on the disk cache; we never deserialize untrusted pickles. The cache stores LLM model artifacts loaded from `LLAMA_MODEL_PATH` (a local filesystem path the user controls), not from any network or user-supplied source. | Upstream `diskcache` patch released; or `llama-cpp-python` removed in favour of pure Ollama HTTP. |

When adding a new accepted risk:

1. File the dismissal in GitHub's Dependabot UI with the same rationale.
2. Append a row to the table above.
3. Set a concrete `Re-check trigger` — never "review later".

## Automated Security Controls

The repository runs the following on every PR and every push to `main`:

| Control | Where | Gates merge? |
|---------|-------|--------------|
| **Trivy CRITICAL vulnerability scan** | `.github/workflows/main-ci-cd.yml` `security-scan` job | Yes (CRITICAL → block) |
| **CodeQL** (Python + JavaScript/TypeScript + GitHub Actions) | GitHub default setup (code scanning) | Yes (alerts must be addressed) |
| **Privacy leak scanner** ([#138](https://github.com/researcherhojin/nuri-quant/issues/138)) | `.github/workflows/main-ci-cd.yml` `privacy-scan` job + `scripts/verify/check_privacy_leak.py` + `scripts/verify/pre_push_check.sh` | Yes (broker name / suspect monetary literal / ticker+signed-% → block) |
| **Dependabot** | `.github/dependabot.yml` | Auto-creates PRs on new advisories |
| **Branch protection on `main`** | GitHub repository settings | All required checks must pass; force-push blocked |

## Personal Financial Data

This is a personal investment platform. Test fixtures, examples, and
documentation must **never** contain real broker names, real account
identifiers, real holdings, real quantities, real prices, or real
balances. The full policy is in
[`docs/STRATEGY.md` §4.4 + §4.4.1](docs/STRATEGY.md), enforced by
`scripts/verify/check_privacy_leak.py`.

If you discover a leak in `main` history, report it via the security
advisory channel above so the maintainer can request GitHub Support
cache invalidation (and, if necessary, coordinate a history rewrite).

## LLM and Model Safety

- **External LLM policy: whitelist per data tier** (updated 2026-04-14).
  Full classification + rules: `docs/STRATEGY.md` §4.4.3.
- **Tier 0 (public data)** — ALLOWED to external. Currently OpenAI
  `gpt-5.4-nano` for RSS headline classification. No ZDR required.
- **Tier 2 (portfolio/LLM daily report)** — ALLOWED to OpenAI
  `gpt-5.4-nano` **only when `OPENAI_ZDR_APPROVED=1` env var is set**
  (attestation that user obtained Zero Data Retention from OpenAI).
  Without ZDR, `chat_text(data_tier="tier2")` raises
  `ExternalLLMPolicyViolation` before any network call. Added in
  PR #294 for prototype phase; local LLM transition planned.
- **Tier 1 (user narrative/memos)** — NOT ALLOWED. Separate policy
  revision + explicit user approval required to enable.
- All external calls go through `nuri/llm/openai_client.py` (direct
  `import openai` elsewhere is forbidden). Per-call audit row in
  `external_llm_calls` table; content never logged.
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

- **Multi-tenant isolation** — single-user personal platform.
- **Authenticated brokerage trading** — paper trading via Alpaca only;
  live broker integration is gated behind explicit credentials in
  `.env`, not committed.
- **Mobile clients** — no first-party mobile app.
- **DDoS / rate-limit attacks** on the FastAPI server — it binds to
  `0.0.0.0` (all interfaces) by default to support the 2-machine
  dev/receiver setup; restrict exposure at the LAN / firewall /
  reverse-proxy layer rather than relying on the app.
