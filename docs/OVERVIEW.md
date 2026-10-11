# Overview implementation and operations guide

*Korean edition: [ko/OVERVIEW.md](ko/OVERVIEW.md)*

Overview is the home screen, `/`. It started as the `/dashboard-next` preview (#1658) and ran side by side with the old dashboard for comparison.
It replaced the old screen in #1698 — the old page and its dedicated components and tests were deleted, and `/dashboard-next` redirects to `/` (the query string is kept).
The sidebar has a single entry for this screen: **Overview**.

## Screen layout and terminology

| Area | What it shows and how to use it |
|---|---|
| System view (시스템 의견) | Shows the backend's overall view together with its stale inputs. |
| Major indices · System classification (주요 지수 · 시스템 분류) | The header shows the latest value of the S&P 500, NASDAQ, KOSPI and KOSDAQ, the percent change from the previous observation, and the as-of date (#1676). The line below it is the system classification (regime). For a special regime (overheating, stagflation, early recovery, sector rotation), the base classification (trend × volatility) is written out separately, and `confidence` is labeled "check agreement" (검사 일치). This is because the value is the share of passed checks among the checks that test the base classification (3 trend checks + a VIX · Bollinger Band width volatility cross-check; an indicator with no value drops out of the denominator), not the confidence of the special classification. The classification sets the target allocation, so the indices do not replace it. |
| Economic conditions score (경제 여건 점수) | The system score built from interest rates, inflation, employment, market sentiment and similar inputs. The labels are the same four levels as the old dashboard, which translated the backend classification as is — Favorable, Neutral, Cautious, Adverse (양호·보통·부진·취약) — plus **Insufficient input** (입력 부족). Labels are not rebuilt from the score. The fallback score at coverage 0 is hidden. |
| Priority checks (우선 점검 항목) | The priority count from `/api/actions`, plus the review and portfolio-rule counts. |
| Holdings review (보유 종목 점검) | Priority (우선 확인), Review (검토), Portfolio rules (포트폴리오 규칙) and Hold (유지) tabs. For the selected holding, it shows the as-of date, evidence, weight, profit and loss, and the two signals. |
| My portfolio (내 포트폴리오) | Donuts by holding, by sector and by account, plus a list of every weight. The valuation basis is in the explanation dialog. |
| Market exploration (시장 탐색) | 1-day and 5-day price changes of candidates, with their evidence. A price change is not a history of judgment changes. |
| Data updates (데이터 업데이트) | Healthy, warning and stale sources, a description of every source, and the entry point for refresh jobs. |
| Pipeline status (파이프라인 상태) | Keeps recent run events, decision-ledger artifacts and scheduler status apart. |

Labels were renamed: **Market phase → System classification** (the line under the major indices, #1676 — previously named Market flow), **Macro environment → Economic conditions score**,
**Decision monitor → Holdings review** and **Asset allocation → My portfolio**.
Confidence is not a probability of profit, and `alpha_action` and `portfolio_action` are independent axes.
The judgments on screen are produced by the backend, and the screen has no order execution.

## Data connections and error handling

The first screen sends the following requests in parallel. It checks both HTTP success and the Zod response shape.
A failed panel is marked as unavailable (확인 불가), and the healthy panels stay as they are.

| API request | Used by |
|---|---|
| `GET /api/dashboard` | System view, major indices (`market_indices`), market classification, economic score, VIX, exchange rate, alerts |
| `GET /api/actions` | Review list and decision-ledger links |
| `GET /api/opportunities` | Exploration candidates and price changes · system judgment (`system`, BUY candidate emitter classification) · scanner observations |
| `GET /api/portfolio` | Holding quantities, names, latest prices and cash |
| `GET /api/freshness` | Data update status |
| `GET /api/pipeline/status` | Per-stage events and the decision-ledger summary |
| `GET /api/scheduler/health` | Scheduler status, which the client fetches separately |

### `market_indices` (#1676)

`market_indices` in `/api/dashboard` always returns 4 entries, in this order — `sp500` · `nasdaq` · `kospi` · `kosdaq`.
Each entry is `{key, label, close, prev_close, change_pct, date, source, symbol}` (`source` and `symbol` are from #1682). `change_pct` is `(close / prev_close − 1) × 100`, rounded to two decimal places.

- **There are two sources.** US indices are read from the `macro` table (`sp500` · `nasdaq_composite`). `MacroCollector` collects `^GSPC` · `^IXIC` every hour. Korean indices are the `KOSPI` · `KOSDAQ` rows in `prices` (`StockKRCollector`).
- **US indices are not stored in `prices`.** Their names have no `.KS` · `.KQ` suffix, so they pass the `is_kr_ticker()` filter. They would then mix into the US ticker universe (decision_alpha substitution candidates · walkforward panel) as if they were tradable tickers (the same path KOSDAQ took in #710).
- **Missing values are null.** With no row, all 4 values are null. With no previous observation, or a previous value of 0, only `change_pct` is null. The entry shape stays the same even when the query fails. The screen renders null as `—` and never turns it into 0%.
- **`close` is the latest stored value.** macro overwrites the day's bar every hour, and stock_kr every 5 minutes during market hours, so during the session it may not be the final close. The US and Korean `date` values can differ.
- **`source` is the stored value.** A `macro` row returns its own `source` column as is. `prices` has no source column, so the entry names the collector (`StockKRCollector._collect_indices`, yfinance). `symbol` is the upstream symbol (`^GSPC` and so on).

### `macro_inputs` (#1682)

`macro_inputs` in `/api/dashboard` is the **`date` and `source` of the latest stored row** for each of the 9 `macro` indicators that the economic conditions score (`compute_macro_score`) reads — `{key, date, source}` in `MACRO_INPUTS` order. With no row, `date` and `source` are null. The event score is computed separately from news and the economic calendar, so it is not in the list. If this list drifts from the indicators the score reads, the source display becomes false, so `tests/api/test_dashboard.py::TestMacroInputsProvenance::test_inputs_match_what_the_macro_score_reads` compares the two.

Client requests use relative `/api/*` paths.
The pipeline panel refreshes on entry, every 60 seconds, on manual refresh and when the user returns to the screen; it skips the periodic poll in a hidden tab.
When a query fails, the previous records are kept and marked as failed. Past completed events are shown as a **success record** (성공 기록).

## Portfolio valuation and display

- Holdings are valued at the latest stored price × quantity, and cash is added. KRW assets are converted to USD at the stored USD/KRW rate.
- If required price, exchange-rate or cash data is missing, the total and the weights are withheld. An unknown value is never turned into 0%.
- The donut includes every aggregated item. It does not keep only the top items or group the rest into ‘Other’.
- The list scrolls inside the card and is reachable by keyboard. The number of visible rows depends on the screen height.
- Korean stocks and ETFs (`.KS`, `.KQ`) use the name from the API first. Without a name they show the ticker; US holdings keep the ticker.
- The aggregation key is the ticker, so different holdings with the same name are not merged. The detail dialog shows the name and the ticker together.
- The valuation-basis dialog shows the range of price as-of dates across holdings. It shows the current holdings, not real-time quotes or the target allocation.

## Data refresh jobs

Open **Refresh stale data** (지연 데이터 갱신) in Data updates, or **Refresh data** (데이터 갱신) in the pipeline panel.
The jobs that match the stale sources are preselected, and nothing runs until you press **Refresh selected data** (선택한 데이터 갱신).
If the prices that feed the technical indicators are old, select price collection as well. Dependent jobs are not added automatically.

| Job ID | What it runs | Stage |
|---|---|---|
| `prices` | US and Korean price collection | collect |
| `macro` | Economic indicator and exchange-rate collection | collect |
| `technical` | Technical indicator calculation | collect |
| `fundamentals` | Company financials collection | collect |
| `factors` | Composite analysis score calculation | analyze |

`GET /api/pipeline/refresh` returns the job list and the status of the latest request.
`POST /api/pipeline/refresh` takes `{"jobs":["prices","technical"]}` and accepts it with HTTP 202.
Jobs run in the table order above, with duplicates removed, regardless of the order in which they were selected.
Write authentication and the audit log (`REFRESH` / `pipeline_refresh`) apply, and a request is rejected with HTTP 409 while another request is in progress in the current process.
The heavy slot is taken, without blocking, **at acceptance time** — with no free slot, the request is rejected with the same HTTP 503 + `Retry-After: 5` as other heavy routes (Codex #1658 P2: it does not turn into a "failed run" after a 202), and the slot is released when the background run finishes.
`run_step()` records the stage lifecycle events; separately, `refresh_job_started/completed/failed` events carry the job ID, the request ID and `origin: dashboard_refresh`, which tells them apart from the scheduler's runs of the same stage.
If a job fails, the remaining jobs do not run.

While the refresh dialog is open, it polls the status every 5 seconds.
After completion or failure, it rechecks freshness and reloads the screen and the pipeline status.
**A finished job and fresh data are two different things.** If the upstream observation date is old or the collection coverage is short, the data can stay stale.
This button does not run consensus, decision recording or performance tracking.

## What the decision record (Decide) means

Decide has no scheduled job of its own; `record_decisions()` runs inside Consensus.
So the absence of an event is not shown as the absence of decisions.
The Decide entry of `/api/pipeline/status` carries the following added fields.

- `execution_mode: "inline_with_consensus"`
- `artifact: {status, date, count}`: the latest `decisions.date` and the number of records for that date
- Artifact status: `available` / `empty` / `unavailable`

The original run `status` and `last_updated` stay as they are. A real error is shown as an error,
and a ledger date and count do not guarantee a successful run or current judgments.
The development DB is a read replica of the production decision ledger, so when the date is old, check production collection and consensus, and the replica sync.

## Responsiveness and accessibility

The shared container's maximum width of 1,600px and the former Preview's maximum height of 900px
left excessive margins and small text on large screens. Overview lifts the width limit and uses the available height.
Type, spacing and donut size scale with the viewport. Other screens keep the width limit (1,600px), and the cap check in `responsive.spec.ts` excludes `/`.

**Test:** `frontend/e2e/overview-layout.spec.ts::overview fills available space and keeps content reachable at 2560x1440`

- Width 1,050px or less: stacked layout and page scrolling.
- Desktop height 850px or less: page scrolling is allowed so that no information is clipped.
- Regular and large desktops: the goal is a single-screen layout, and tests check key rows and links for clipping.
- Tested resolutions: 1440×900, 1920×1080, 2560×1440, 3440×1440, 1280×800, 390×844.
- Explanation dialogs: close with Escape, the close button or a click outside. A click on the inner padding keeps them open.
- Visible keyboard focus, table headers, chart descriptions and the reduced-motion setting are supported.

## Implementation locations and verification

| Location | Role |
|---|---|
| `frontend/src/app/(overview)/` (route group → `/`) · the `/dashboard-next` redirect in `frontend/next.config.ts` | Server page, API schemas, review · portfolio · refresh · pipeline components, CSS |
| `frontend/src/lib/strings.ts` · `frontend/src/components/ui/sidebar.tsx` | **All** user-facing copy on the screen (`OVERVIEW`, with a sub-object per panel), the classification labels shared with other screens (`MACRO_INTERPRETATION` · `REGIME_LABEL`), and the navigation link. Components and tests read from here instead of literals (#1252) |
| `frontend/src/app/layout.tsx` | Container marker for the Overview-only width expansion (`[data-page-container]:has(.dashboard)`) |
| `nuri/api/routes/pipeline.py` | Decide ledger artifact query |
| `nuri/api/routes/dashboard.py` (`MARKET_INDICES` · `_get_market_indices`) · `tests/api/test_dashboard.py::TestMarketIndices` | Major indices block, and regression tests for missing values and percent change (#1676) |
| `tests/quant/regime/test_regime_label_coverage.py` | Compares the classifier's 10 regimes (`ALL_REGIMES`) with the `REGIME_LABEL` keys in both directions |
| `nuri/api/routes/pipeline_refresh.py` · `nuri/api/main.py` | Refresh job API and router registration |
| `tests/api/test_pipeline_refresh.py` | Regression tests for order, failure, duplicates, authentication, slots and ledger observation |
| `frontend/src/__tests__/pages/overview*.test.tsx` | Tests for panels, signals, missing values, names, full lists, queries and refresh |
| `frontend/e2e/overview-layout.spec.ts` | Real-browser regression tests for per-resolution layout, modal alignment and the redirect |

Run the backend checks from the repository root and the frontend checks from `frontend/`.

```bash
.venv/bin/python -m pytest tests/api/test_pipeline_refresh.py tests/api/test_pipeline.py tests/core/test_cross_stage_imports.py tests/core/test_db_path_forwarding.py tests/core/test_sqlite3_sole_importer.py tests/verify/test_readme_structure.py -q
```

```bash
cd frontend
npx vitest run src/__tests__/pages/overview.test.tsx src/__tests__/pages/overview-pipeline.test.tsx src/__tests__/pages/overview-refresh.test.tsx
npx playwright test e2e/overview-layout.spec.ts --reporter=line
```

Local run record of 2026-10-06 (after the detail pass, at the 2nd commit of PR #1658):

| Scope | Result |
|---|---|
| `tests/api/test_pipeline_refresh.py` · `test_routes.py` · `test_pipeline.py` · `test_limits.py` · `tests/core/test_pipeline_events.py` · `test_pipeline_observability.py` | 163 passed |
| Preview Vitest, 3 files | 22 passed |
| Full frontend `npx vitest run` | 143 files · 1,697 tests passed |
| `npm run lint` (eslint + oxlint) · `tsc --noEmit` | 0 findings |
| Preview resolution Playwright (6 viewports) | 6 passed |

These numbers are the results of running the commands above, not coverage measurements.

E2E uses the real local API. Do not commit expected values pinned to personal holdings, or screenshots that contain personal information.

## Constraints and handoff notes

- Refresh state and duplicate prevention live in the API process's memory. They reset on restart and are not shared across workers. There is no persistent job queue.
- A job the server has accepted can keep running after the dialog is closed. If a response could not be confirmed, check the status before sending the request again.
- Where API authentication is on, running a refresh requires permission. The frontend refresh request has no way to enter a separate Bearer token.
- Because of the summary API and the server-side query caches, job results may not reach every card immediately.
- The freshness-to-job mapping covers only some sources. In particular, `macro` is preselected through its mapping to `macro_vix`, and other macro sources are not selected automatically.
- Passing the tests for the changed scope is distinct from a successful full production build. The page export errors in `.next/dev/types` that `tsc --noEmit` reports while the dev server is running come from dev server output (they disappear once `.next` is cleared); the CI `next build` and the `Frontend Build` check are the real verdict.
- The draft went in unchanged as the first commit of PR #1658, and the detail pass is the later commit. When #1698 promoted the screen to `/`, the panels that existed only on the old dashboard (regime transition banner, macro event card, coverage status, hero metrics, composition tabs) were deleted along with it.

## Detail-pass rules (#1658)

Visual and code rules refined after the draft. Follow the same rules when changing this screen.

- **Font sizes use only the 6 ladder tokens**: `--fs-xs` 10 · `--fs-label` 11 · `--fs-body` 13 · `--fs-title` 14 · `--fs-h3` 18 · `--fs-value` 26 (px). Each one adds `--font-step` (+0.32px per 160px of width from 1600px, at most +2px — +0.6 at 1920, +1.9 at 2560), so text grows only slightly on large screens. The draft added +2.9px at 1920; it was reduced after the feedback "text is too large on big screens" (2026-10-06). Arbitrary values such as `calc(8px + …)` are not used — this rule came from the draft's secondary text built on 8 and 9px bases, which dropped to 9px at 1440px. The e2e test checks that legend text does not fall below the 11px label token at 1920px and wider.
- **3 spacing tokens**: `--space` (between panels, 12–24px) · `--pad` (horizontal padding inside panels, 14–20px) · `--row` (vertical padding of list rows, 8px; 11px on large screens). Table rows, source rows and pipeline rows all use the same `--row`.
- **Market card (#1676)**: it takes 2.4 columns of the metrics row, 3 columns at 1250px or less and the full row at 1050px or less; at 600px or less the indices are laid out 2×2. Each index cell has 3 lines: name and as-of date (`MM-DD`) · level (`--fs-h3`; `--fs-title` at 1400px or less) · percent change. At 1280px a cell is about 85px wide, so a five-digit level (27,599.79) is clipped at 18px, and putting the as-of date on the percent-change line runs it into the number in the next cell (measured 2026-10-07). The as-of date line is truncated with an ellipsis when narrow (the full date is in `<time datetime>`). The regime is the one line below it.
- **Metric cards (#1682)**: all four cards use the same "icon + name" header as the lower panels (`MetricHeading`) and an ⓘ icon modal — the button shows no "How to read" (읽는 법) text, which remains only as the accessible name (`DetailDialog iconOnly`; the Holdings review panel works the same way). After the explanation, the modal shows a **source and as-of date** table (indices: `market_indices.source` · `symbol`; economic score and VIX: `macro_inputs`; priority checks: `as_of`, the most recent decision as-of date among the items — the list generation time is "now" on every query and says nothing about the age of the decisions, so it appears only in an explanatory note). When the source is a proxy, the name changes too: the yfinance slot for the 2-year yield is `^IRX` (13-week), so it is shown as "US 13-week rate (2-year proxy)" (미국 13주물 금리 (2년물 대용)) (`MACRO_INPUT_PROXY_LABEL`). The bottom line of a card has a note on the left and a source summary on the right; when space is tight, the source summary is truncated first — the economic score shows only the first source and a count, as in "FRED + n others" (FRED 외 n곳). Stored source codes get display names through `OVERVIEW.SOURCE_NAME`, and an unknown code is shown as is (sources are never invented). The header line makes the market card 5 lines tall, so the metrics row is `clamp(118px, 12dvh, 160px)` (118px at heights ≤850px) — card clipping and bottom-line clipping: 0 from 390 to 1920px (measured 2026-10-07). To add lines, grow the metrics row in `grid-template-rows` first and rerun the layout e2e test.
- **Legend scrolling**: the legend next to the donut pins the chart row track to `minmax(0, 1fr)` and scrolls only within that height. In the draft, the legend covered the "N items in total" (전체 N개 구성) text below it.
- **Icons**: lucide icons (`ArrowUpRight` · `Info`) are attached with `aria-hidden` instead of the `↗` · `ⓘ` characters. The accessible name and the button name in tests are the text only (the `icon` prop of `DetailDialog`).
- **Evidence area**: the selected holding's metrics follow directly below the evidence (the draft pinned them to the bottom of the panel, which left a large gap).
- **Backend**: accepting `POST /api/pipeline/refresh` writes only the audit log entry `REFRESH` / `pipeline_refresh`. The `pipeline_events` rows come from the background run — the stage lifecycle from `run_step`, and the per-job `refresh_job_started/completed/failed` from `_mark()` (via `emit_event`, the only writer). The heavy slot is taken at acceptance and released when the run ends; a queued run that the background task has not started within `QUEUE_GRACE_SECONDS` (60 seconds) is closed as `abandoned` on the next query or request, and its slot is returned (the path where Starlette does not run BackgroundTasks because sending the response ended in an exception). `tests/api/test_routes.py` locks the router mount with a smoke test.

## Ticker detail and portfolio sync

`/ticker-next/[symbol]`, which the holdings review links to, uses one body and table of contents for companies and funds alike.
The public briefing and the stored trading judgments are separate inputs. Collecting data or generating a briefing does not, by itself,
bring the decisions up to date. For implementation, verification and limitations, see the [ticker research guide](RESEARCH_BRIEFING.md).

Portfolio freshness is the sync state of the holdings record, and it is separate from price freshness.
When applying a screenshot, cross-check the account mapping, quantities, average costs and totals, and do not overwrite
the cost-inclusive valuation with market prices. Keep a back-calculated average cost apart from the executed average cost, and record its basis. Do not show cash that is not on the screen
as updated to a confirmed value. Cash is read from `config/portfolio.yaml`.
Keep the production source and the local replica apart, and do not record a local-only edit as a completed production sync.
Back up before editing; after saving, re-query the API and the screen and confirm that caches were refreshed. Personal financial data never goes into Git.

## Design references

Drawing on [IBKR PortfolioAnalyst](https://portal.interactivebrokers.com/en/portfolioanalyst/features.php) and
[Portfolio Performance Dashboard](https://help.portfolio-performance.info/en/reference/view/reports/performance/dashboard/),
the holdings composition is kept separate from the metric explanations. The donut, the full holdings display and the large-screen expansion are implementation choices made for this screen at the user's request.
