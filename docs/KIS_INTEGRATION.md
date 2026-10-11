# KIS Open API Integration Guide

*Korean edition: [ko/KIS_INTEGRATION.md](ko/KIS_INTEGRATION.md)*

This guide describes the modules that collect real-time quotes, trading activity by investor type, and analyst investment opinions through the Korea Investment & Securities (KIS) Open API.

## Module structure

```
nuri/collectors/
├── kis_realtime.py         # Real-time quotes (Korea + US), token cache, rate-limit handling
├── institutional.py        # Institutional/foreign investor flows (#247 — investor-trade-by-stock-daily)
└── kis_analyst_opinion.py  # KR analyst investment opinions (#418 — invest-opinion REST endpoint)
```

`kis_analyst_opinion.py` replaces #418 (a design for a Playwright-based research-page scraper). It uses only the official KIS Open API REST endpoint `invest-opinion` (tr_id `FHKST663300C0`), so it needs no Playwright, no login-session automation, and no workaround for DOM rendering.

## Credentials

### Priority order

1. **`.env` file** (recommended — git ignored)
2. **`config/kis/kis_devlp.yaml`** (gitignored, inside the project; compatible with the KIS Open API SDK)
3. **`~/KIS/config/kis_devlp.yaml`** (legacy location; backward-compatible fallback)

### .env variables

```bash
# Production (live)
KIS_PROD_APP_KEY=PSxxxxxx...
KIS_PROD_APP_SECRET=...
KIS_PROD_ACCOUNT=1000000  # 8-digit comprehensive account (OK to leave blank for quote-only use)

# Paper (simulated)
KIS_PAPER_APP_KEY=...
KIS_PAPER_APP_SECRET=...
KIS_PAPER_ACCOUNT=...

# WebSocket (when using real-time bid/ask quotes)
KIS_HTS_ID=your_hts_id
```

### YAML fallback (`config/kis/kis_devlp.yaml`)

The format is compatible with the official KIS Open API SDK. The recommended location is under `config/kis/` inside the project (gitignored); the legacy location `~/KIS/config/kis_devlp.yaml` is also detected automatically.

```yaml
my_app: "실전 앱키"
my_sec: "실전 시크릿"
paper_app: "모의 앱키"
paper_sec: "모의 시크릿"
my_htsid: "HTS ID"
my_acct_stock: "1000000"        # Production comprehensive account
my_paper_stock: "1000000"       # Paper comprehensive account
my_prod: "01"                    # Comprehensive account (01) / futures & options (03) / overseas futures & options (08)
```

#### When used alongside the official KIS Open API SDK

The official KIS SDK (`pykis` and others) always uses the fixed path `~/KIS/config/kis_devlp.yaml`. To use nuri-quant and the official SDK together, the file must be readable from both locations.

**Option 1 — symlink (recommended, one file)**:

```bash
mkdir -p ~/KIS/config
ln -sf "$(pwd)/config/kis/kis_devlp.yaml" ~/KIS/config/kis_devlp.yaml
ln -sfn "$(pwd)/config/kis/cache" ~/KIS/cache   # if ~/KIS/cache is already a directory, ln puts the link inside it
```

**Option 2 — legacy only (uses the nuri-quant fallback)**:
If the file is at `~/KIS/config/kis_devlp.yaml` and `config/kis/` holds no YAML file, nuri-quant reads the credentials from the legacy path. The SDK reads from its default path. The token cache still uses `config/kis/cache/` in this case.

**Option 3 — no SDK**: If you use only nuri-quant, `config/kis/` alone is sufficient.

## Usage

### 1. Check credentials (no API call)

```bash
make collect-kis-check
# → KIS 자격 증명 OK [prod] app_key=PSxxxxxx... account=(미설정)
```

### 2. Collect real-time quotes

```bash
make collect-kis                                          # prod mode (default)
.venv/bin/python -m nuri.collectors.kis_realtime --mode paper   # paper
```

**Sample output**:

```
KIS 실시간 수집: 23/23 (KIS=21, yfinance fallback=2)
```

### 3. Query a single ticker's quote (Python)

```python
from nuri.collectors.kis_realtime import load_credentials, get_access_token, inquire_price_us

creds = load_credentials("prod")
token = get_access_token(creds)
result = inquire_price_us(creds, token, "NVDA")
# {'ticker': 'NVDA', 'date': '2026-04-09', 'open': ..., 'close': 184.02, ...}
```

## Rate-limit handling

### KIS official policy (notice of 2026.03.20)

| Account type | First 3 days after application | After that |
|---|---|---|
| **Production, new** | 3 requests per second | Standard rate (exact value not published) |
| **Production, renewed** | Standard rate immediately | — |
| **Paper** | Always a lower limit | — |

### System settings

| Mode | Call interval | Per second |
|---|---|---|
| **prod** | `KIS_REQUEST_INTERVAL_PROD = 0.4s` | 2.5 calls (safety margin) |
| **paper** | `KIS_REQUEST_INTERVAL_PAPER = 1.0s` | 1 call |
| **EXCD fallback** | `KIS_EXCD_RETRY_INTERVAL_SEC = 0.4s` | Between NAS→NYS→AMS |
| **After a rate limit** | `KIS_RATE_LIMIT_RETRY_DELAY_SEC = 1.5s` | Enough time to recover |

### Rate-limit detection

`_is_rate_limit(payload)` treats a response as a rate limit when it is an error response (`rt_cd == "1"`) and matches one of the following.

1. **Official code**: `msg_cd == "EGW00201"`
2. **Message**: `msg1` contains "거래건수" (transaction count) or "초당" (per second)

> In observed responses, the KIS overseas quote API returns `msg_cd=None`, so message matching is the primary detection path.

## yfinance fallback

Only the tickers whose KIS quote lookup failed are filled in from yfinance.

```python
def _yfinance_fallback(tickers):
    """KIS 실패 종목을 yfinance로 보충 수집."""
    for t in tickers:
        hist = yf.Ticker(t).history(period="2d")
        if not hist.empty:
            recovered.append({...})
    return recovered
```

**Effect**: KIS 21/23 + yfinance fallback 2 = 23/23 (100%)

## Token management

### 1-minute cooldown

KIS limits token issuance to once per minute and rejects back-to-back requests.

### Disk cache

| Path | Format | TTL | When used |
|---|---|---|---|
| `config/kis/cache/token_prod.json` | `{access_token, issued_at, expires_in}` | 23h (actual 24h, 1h margin) | Always (regardless of the credential source, #532) |
| `config/kis/cache/token_paper.json` | Same | Same | Same |
| `~/KIS/cache/token_*.json` | Same | Same | Not used (legacy location — `make clean-all` only cleans it up) |

### Cooldown response detection

`_is_token_cooldown(payload, status_code)`:

- HTTP **403** → cooldown
- any other status with "1분당" (per minute) in `error_description` → cooldown
- `error_code == "EGW00133"` → cooldown

## US quotes (EXCD fallback)

KIS distinguishes US tickers by exchange.

| EXCD | Exchange | Example tickers |
|---|---|---|
| **NAS** | NASDAQ | NVDA, GOOGL, AMD, PLTR |
| **NYS** | NYSE | OKLO, BLSH, FIG |
| **AMS** | AMEX/Arca | VOO, some ETFs |

`inquire_price_us()` tries NAS → NYS → AMS in that order and waits 0.4s between attempts (to avoid the rate limit).

## Korean tickers (ticker conversion)

```python
"005930.KS" → "005930"  # strip the .KS suffix
"000660.KQ" → "000660"  # .KQ is handled too
```

`FID_COND_MRKT_DIV_CODE = "J"` (market division: stocks).

## Date and storage rules (#1636)

- **The `date` of a US quote is the New York trading day.** The KIS overseas current-price response carries no date. The collector used to stamp `today_kst()`, so on every KST morning while the US market was open, the same session was stored under a date one day later than in the daily collector (yfinance, US trading day). `us_session_date()` converts to America/New_York: before the regular-session open (09:30) it uses the previous session, and it moves weekends and NYSE holidays (federal holidays − Columbus/Veterans Day + Good Friday; New Year's moves only Sunday→Monday) back to the previous business day. Special closures are not modeled. For Korean quotes, `today_kst()` is correct.
- **A current price without O/H/L does not overwrite a complete bar.** The overseas current-price API (HHDFS00000300) returns only `last`/`tvol`, so open/high/low are 0. `upsert_prices` is INSERT OR REPLACE, so once the dates line up, this row could overwrite an entire yfinance daily bar. `KISRealtimeCollector.save()` does not write the row when a bar with `open != 0` exists for (ticker, date); it writes the row when no bar exists or when the earlier observation also lacks O/H/L. Korean current-price rows and yfinance fallback rows carry OHLC, so they are updated as before.
- **The `date` of a yfinance fallback row is the bar's index date.**

**Test:** `tests/collectors/test_kis_us_session_date.py` — 12 calendar cases · row date · fallback date · 4 save-guard cases.

## Verification results

| Test | Result |
|---|---|
| **Collection of 23 held tickers** | 100% (KIS 21 + yfinance fallback 2) |
| **Unit tests** | 62 collected across `tests/collectors/test_kis_realtime.py` · `test_kis_realtime_branches.py` · `test_kis_token_cache.py` · `test_kis_us_session_date.py` (2026-10-06) |
| **Functions verified** | `_is_rate_limit`, `_is_token_cooldown`, `load_credentials`, `inquire_price_kr/us` |

## Known limitations

1. **Missing data in paper (vps)**: Some US tickers (OKLO, IONQ, FIG) return empty responses in the paper environment. The yfinance fallback applies automatically.
2. **KIS_HTS_ID**: WebSocket real-time bid/ask quotes require an HTS ID. It is not needed when only REST is used, as is currently the case.
3. **Comprehensive account (account) can stay unset**: Quote lookups work with a blank account number. Trade orders require it.
4. **WebSocket "No close frame received" error**: Check that the HTS ID is correct (official KIS guidance).

## Analyst investment opinions (#418)

`nuri/collectors/kis_analyst_opinion.py` collects analyst investment opinions per KR ticker through the KIS Open API `invest-opinion` endpoint (tr_id `FHKST663300C0`). The scheduler's `kis_analyst_opinion` job runs it every Sunday at 00:30 KST.

### Endpoint

```
GET /uapi/domestic-stock/v1/quotations/invest-opinion
tr_id: FHKST663300C0
```

**Parameters**:

- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_COND_SCR_DIV_CODE=16633` (Primary key)
- `FID_INPUT_ISCD`: 6-digit ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1` / `FID_INPUT_DATE_2`: YYYYMMDD start/end. The default is a 6-month (180-day) rolling window. T-0 (the current day) also works, unlike the T-1 constraint of `investor-trade-by-stock-daily` (confirmed by a live probe on 2026-04-28).

**Output** (`output[]`, broker-level rows):

- `stck_bsop_date` — YYYYMMDD
- `invt_opnn` / `invt_opnn_cls_code` — current opinion + code
- `rgbf_invt_opnn` / `rgbf_invt_opnn_cls_code` — previous opinion + code
- `mbcr_name` — name of the issuing brokerage (raw Korean text)
- `hts_goal_prc` — target price (KRW)
- `stck_nday_esdg` / `nday_dprt` / `stft_esdg` / `dprt` — price gap / gap ratio (not stored at this stage)

### Design decisions (Codex Round 1+2 consult, 2026-04-28)

| Decision | Reason |
|---|---|
| Ignore `cls_code`; normalize from the `invt_opnn` text | Live probe — the same cls_code maps to BUY / HOLD / Outperform / Neutral differently per broker (broker-inconsistent ranking). Text normalization extracts the canonical bucket. |
| `firm` = the original broker name; empty values get a stable fallback (`KIS_UNKNOWN`) | Ensures that the UNIQUE `(ticker, date, firm)` of the `INSERT OR IGNORE` UPSERT is not broken by the NULL≠NULL SQLite quirk. |
| `to_grade` / `from_grade` keep the original KIS text as is | Same pattern as the existing US rows (per-broker English text); normalization is the consumer's responsibility. |
| `action` 4-value derivation: `init` / `main` / `up` / `down` | Compatible with the existing `analyst_ratings.action` vocabulary (`init`, `up`, `down`, `main`, `reit`). KIS has no `reit` meaning, so it is folded into `main`. |
| 6-month rolling window; rerunning every Sunday is idempotent | Safer than a strict T-7d watermark — prevents holes after a scheduler miss. UPSERT IGNORE absorbs duplicates. |

### Operational limitations (flagged by Codex in Round 2, targets for follow-up issues)

1. **`analyst_ratings` is still in `nuri/core/coverage.py::US_ONLY_TABLES`.** KR rows reach the DB, but coverage statistics show them as "(KR n/a — 소스 미지원)" (source not supported). Reclassifying the table as KR-supported is a follow-up PR.
2. **`WallStreetAgent` skips `.KS` and `.KQ` tickers** (the skip condition in `nuri/trading/agents/wallstreet.py`). KR opinions therefore do not reach consensus and appear only in the UI ticker detail. Enabling the read path is a follow-up PR.
3. **The privacy scanner's `BROKER_NAMES_KO`**: The broker names in DB rows match the scanner patterns. The scanner checks only committed code/docs/PRs/commits, not the DB or runtime logs. Test fixtures and docs use synthetic broker names ("Test Securities A" and the like), and this document also refers to brokers generically.

### Failure modes (STRATEGY §2.6 Surface rung)

| Situation | Behavior | pipeline_events |
|---|---|---|
| KIS creds not set | Immediate `[]`, warning | `step_blocked` + `kis_creds_missing` |
| Token issuance fails | Immediate `[]`, error | `step_failed` + `kis_token_failed` |
| Full run completes | Returns the results | `kis_analyst_opinion_run` (covered / empty / failed / rows) |
| `tr_cont` recursion ≥ 8 | Surfaced once per ticker, collection continues | `kis_analyst_opinion_truncation_risk` (ticker_code, depth_reached, max_depth) |
| HTTP 4xx/5xx, `rt_cd != 0`, exception | Skip that ticker, debug log | (none — per-ticker level) |
| Empty `output` | `empty++` for that ticker, continue | (none — counted in the aggregate run event) |

## Investor trading trends (institutional/foreign flows, #247)

`nuri/collectors/institutional.py` collects daily net-buying data by institutions, foreigners, and individuals for Korean stocks through the KIS Open API `investor-trade-by-stock-daily` endpoint.

### Endpoint

```
GET /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily
tr_id: FHPTJ04160001
```

**Parameters**:

- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_INPUT_ISCD`: 6-digit ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1`: YYYYMMDD. Uses T-1 (the current day's date returns an `OPSQ2001 TIME LIMIT` error before the 15:40 KST daily settlement).
- `FID_ORG_ADJ_PRC`, `FID_ETC_CLS_CODE`: blank

**Response** (`output2`): a 30-day history array, 101 fields per row. Key fields:

- `stck_bsop_date` — YYYYMMDD
- `frgn_ntby_qty` — foreign net-buy quantity
- `orgn_ntby_qty` — institutional (total) net-buy quantity
- `prsn_ntby_qty` — individual net-buy quantity

### Rate limit

`KIS_REQUEST_INTERVAL_PROD = 0.4s` (2.5 req/sec, safety margin), plus a 1.5s wait and one retry when a rate limit is detected.

The collector requests each held Korean ticker once (`_get_tickers(market="kr")`, portfolio source), so a run takes about 0.4 s × the number of held Korean tickers.

### Failure modes (STRATEGY §2.6 Surface rung)

| Situation | Behavior | pipeline_events |
|---|---|---|
| KIS creds not set | Immediate `return []`, warning log | `step_blocked` + `kis_creds_missing` |
| Token issuance fails | Immediate `return []`, error log | `step_failed` + `kis_token_failed` |
| HTTP 4xx/5xx | Skip that ticker, loop continues | (none — per-ticker level) |
| `rt_cd != 0` | Skip that ticker, debug log | (none) |
| Connection error | Skip that ticker, debug log | (none) |

**Surface only**: A collector infrastructure failure is not a market signal, so it is not promoted to a gate warning or a pipeline block. Even when the `institutional_flows` table is empty, Korean-market analysis proceeds in degraded mode.

### UPSERT (B1 lesson, PR #311)

The collector uses `UNIQUE(ticker, date, market)` + `ON CONFLICT DO UPDATE SET ...`. It does not use `INSERT OR REPLACE`, because that changes the row id and breaks FKs.

## References

- **KIS Open API portal**: https://apiportal.koreainvestment.com
- **Official GitHub (REST samples)**: https://github.com/koreainvestment/open-trading-api
- **AI agent extensions**: https://github.com/koreainvestment/kis-ai-extensions
- **Notices**:
  - 2026.03.20 [Important] Per-second call limit for new customers (standard rate after 3 days)
  - 2026.04.02 New OpenAPI GitHub sample code uploaded
  - 2026.02.25 API call rate guidance (REST, WebSocket)
