# Ticker research and public briefings

*Korean edition: [ko/RESEARCH_BRIEFING.md](ko/RESEARCH_BRIEFING.md)*

As of: 2026-10-28. The implementation it describes is merged into `main`.
The canonical source for investment rules and the external egress policy is [STRATEGY](STRATEGY.md); for the runtime structure, it is [ARCHITECTURE](ARCHITECTURE.md).

## Screen and data boundaries

`/ticker-next` is the ticker selection screen, and `/ticker-next/[symbol]` is the ticker detail preview.
The detail screen's tabs are Ticker briefing (종목 브리핑), Trading judgment (매매 판단), Prices and data (가격·자료) and Judgment history (판단 기록).
Companies, ETFs and the insufficient-data state all use the same `ReportFrame` and `ReportSection`.
The explanations differ by ticker, but the body and the table of contents follow the same order.

| Area | Role |
|---|---|
| Key summary (핵심 요약) | What the company or product is, and the confirmed opportunities and uncertainties |
| Business and revenue structure (사업과 수익 구조) | The company's sources of revenue, or the fund's operating structure |
| Recent changes (최근 변화) | Keeps confirmed events, company plans and external outlooks apart |
| Earnings and valuation metrics (실적과 가치 지표) | What the metrics mean, and the limits of missing values and comparisons |
| Growth drivers and risks (성장 요인과 위험) | Evidence → conditions for impact → opposing risks → items to check |
| Dates to check (확인 일정) | Dates confirmed by evidence, and unconfirmed items |
| System judgment and price (시스템 판단과 가격) | The stored system decision and a separate price panel |

The LLM's public briefing does not write trading decisions. The decisions, account profit and loss, and holdings review on screen
are shown separately by the application from the user's stored system data. Refreshing data and generating a briefing
do not rerun consensus or decision recording. Companies and ETFs are not forced into the same financial meaning.
ETF product and composition data also use a fund-specific collection and display path.

## Collection and generation flow

| Entry point | Processing |
|---|---|
| `GET /api/ticker/{symbol}/research` | Reads the stored public data and the briefing status |
| `POST /api/ticker/{symbol}/research/refresh` | Refreshes public company, product and article data |
| `POST /api/ticker/{symbol}/research/briefing` | Accepts a briefing generation request that uses the stored public data |

The router is in `nuri/api/routes/ticker_research.py`. A generation request runs as a background job,
and a process lock plus a DB job lease limit duplicate runs. The generated result is stored in `external_analysis`.
`ready` means generation and validation succeeded, `pending` means in progress, `insufficient` means not enough evidence,
`invalid` means the output failed the source, number and plan checks, and `unavailable` means the external model was unavailable or the job was interrupted. When the evidence, the model or the prompt version changes, the existing result is treated as `stale`.
On failure, an unverified report is never shown as a normal body.

Collection starts only from the **Refresh latest data** (최신 자료 갱신) button on the screen. Opening the page alone causes no DB write or external call
— previously, when there was no data for the day, the page collected automatically on entry, so arbitrary tickers opened from search and CI E2E visits
called external sources. **Test:** `frontend/src/__tests__/pages/ticker-preview.test.tsx` "opening a page without today's research sends no collection request".

## Source configuration and the role of prompts

`config/research_sources.json` is the source configuration that registers the URLs, publication dates, legal-entity identifying names and exclusions
for official documents and news. It is not a few-shot file that sets the output style or the depth of explanation.
Even a registered source is excluded from the evidence if its body, publication date or publisher cannot be confirmed.
Automatically discovered news is also used as evidence only when its body, date and subject company are verified.
Not every ticker has the same coverage of official material.

The explanation approach is managed by `nuri/llm/research_briefing.py`.

- `EXTRACT`: selects source sentence IDs and separates facts, company plans and external outlooks.
- `WRITE`: explains so that a first-time reader understands the business structure and the conditions for impact.
- `WRITE_EXAMPLES`: examples of a fictional manufacturer report and of ETF theses. They are a reference for style and line of reasoning only.
- Pydantic output schema: keeps the summary, business, changes, financials, theses and dates linked to their evidence.

The current model is `gpt-5.4`, and the prompt version is `public-briefing-v9`.
v9 cuts down on plain item lists and has the briefing explain the conditions that lead from the evidence to earnings, costs, cash flow and fund value.
When data is short, it states the limits instead of imitating a long report.
The entities, facts, identifiers and figures in the examples are never reused as evidence in a real report.
A prompt change bumps the version and is kept apart from the existing cache. Changing the model is a separate change.

## Validation and external egress

Generation runs in this order: source sentence selection → deterministic claim validation → Korean report writing → report validation →
semantic review. Repair attempts after a number or unit failure, or after a semantic review failure, are limited.
Validation checks entity attribution, the date ceiling, facts versus plans, numbers, units, currencies and signs, evidence IDs, and trading instructions.
Results of a group or an affiliate are never attributed to the listed issuer just because the entity names are similar.

External calls go only through `nuri/llm/openai_client.py`, and only the public-data allowlist is sent.
Accounts, holdings, profit and loss, and personal questions are excluded from public briefing input. Source text is used as analysis input
but is removed from the public read response. Hiding source text in the response is a separate question from whether the scope of collection, storage and egress is appropriate
— see "Known limitations" below. Passing the single gateway and the privacy checks does not by itself resolve those items.

Related regression tests:

- `tests/llm/test_research_briefing.py`: claims, reports, the egress allowlist, and blocking example evidence from entering
- `tests/llm/test_openai_client.py`: real SDK serialization, auditing and the JSON schema request contract
- `tests/collectors/test_briefing_sources.py`: source dates and entity identification
- `tests/collectors/test_research_news.py`, `test_company_briefing.py`: handling of articles and business descriptions
- `tests/api/test_ticker_research.py`: storage, reads and job status
- `frontend/src/__tests__/pages/public-briefing.test.tsx`: the shared body contract for companies and funds
- `frontend/e2e/ticker-preview.spec.ts`: the real detail screen and navigation paths

## Local thesis modes

Private-context thesis analysis is separate from the public briefing flow above.
These entry points share neither an output contract nor a scoring purpose:

| Mode | Entry point | Runtime and output |
|---|---|---|
| Legacy question and answer | `make thesis ticker=TEST`, `/nuri-thesis` | `thesis_query.py` → `llm_consult.py --local-only`; local Strata by default, private Markdown archive |
| Discord interactive | `/thesis ticker:TEST` → `make thesis-remote` | Mini delegates to the development host's `make thesis-progress`; unscored local Ollama B arm, progress thread and allowlisted final card. Runtime version is explicitly pinned in `config/llm_interactive.yaml`; the scored pilot keeps its independent version and digest contract in `config/llm_runtime.yaml` |
| Scheduled pilot | `thesis_pilot` scheduler job | Scored local execution on the production host, pinned source tree and experiment guard; production thesis ledger |
| Report and retro lessons | `report.py` Ollama backend | Local Ollama; the request explicitly uses `report.num_ctx` from `config/llm_runtime.yaml` (#1960) |

The interactive handler defers immediately and posts the analyst, bull/bear researcher and manager stages in a thread.
Its subprocess budget is `interactive.timeout_s` in `config/llm_runtime.yaml` (currently 3,600 seconds).
The final card uses bot credentials rather than the expiring interaction token. Only the validated rating,
completion/review state and shortened run hash appear with the exploratory label; stage text uses fixed labels and statuses.
Raw reasoning, holdings-aware text and error details stay in local archives under `data/thesis_runtime/`.
Interactive execution does not write the scored thesis ledger or change consensus decisions (#1965).

Both the sending Mini checkout and the receiving development checkout must contain the new targets.
On the receiving checkout, `make -n thesis-progress ticker=TEST` checks target availability without inference.
`thesis_remote.sh` selects the newest replica DB, but warns and falls back to the development DB if no replica exists;
a completed run alone therefore does not establish data freshness.

The local client validates the loopback endpoint, local model identity, registered runtime and prompt budget before generation. The interactive CLI applies its explicit version pin to a deep copy of the scored runtime config, preserving the scored pilot version and model digest; updating the interactive pin is a reviewed config change.
A loopback address alone does not establish local execution: the model guard rejects remote/cloud or unlisted models.
There is no external-model fallback. Pilot enablement is in `config/thesis_pilot.yaml`, declared fingerprints are in
`config/thesis_freeze.yaml`, and scheduling is in `nuri/scheduler.py`. Changing a declared arm/runtime is not a documentation fix.
Pilot configuration or a passing rehearsal does not prove that a scheduled night ran; inspect the production ledger with
`NURI_ROLE=production .venv/bin/python -m nuri.llm.thesis_pilot_ops report`.
Protocol choices, samples and results remain private. The analysis entry point is `python -m nuri.llm.thesis_dates --help`;
its arguments must follow the separately registered protocol, not an improvised effect size.

Regression coverage: `tests/agents/test_discord_bot_handlers.py`, `tests/agents/test_thesis_stream.py`,
`tests/llm/test_thesis_interactive.py`, `tests/llm/test_local_model_guard.py`, `tests/llm/test_thesis_freeze.py`
and `tests/llm/test_thesis_pilot.py`. Software completion is distinct from investment-effect validation.

## Verification record

Record of the runs on 2026-10-08.

| Check | Observed result |
|---|---|
| Live call with strict JSON schemas (`gpt-5.4`; Extraction, Report, Verification and number-free repair schemas) | All 4 accepted |
| Live v9 generation from public company data | `ready`, 4 theses, 4 external calls succeeded |

A live call is evidence that the model and the schemas were accepted at that time. It does not guarantee evidence coverage for every ticker,
or generation quality and success rate. Verify again after any new change.
Personal accounts, quantities, prices, profit and loss, screenshots and remote host names are not recorded in this document or in test evidence.

## Known limitations

- **Fund-specific adapter** — the ETF manager page parser in `company_research.py` serves a single product (it is fitted to that page's structure and FAQ
  wording). Generalizing to other funds needs a per-manager adapter. The same-name article filter in `research_news.py` is also a branch for that one product.
- **Unofficial access paths** — resolving Google News article URLs to the original uses an internal RPC, not a public API, and Korean ticker profiles read a portal's
  mobile JSON response. Either can break without notice. Publisher article bodies are fetched without checking robots.txt; part of each body is
  stored and sent to OpenAI as analysis input — the articles are public, but a terms-of-use review is still pending.
- **The request itself is a signal** — which tickers get briefing requests forms a sample of the tickers the user watches or holds. Sending only public data stays within the Tier 0
  policy, but this point is recorded in STRATEGY §4.4.3.
