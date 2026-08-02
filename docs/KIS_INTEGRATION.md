# KIS Open API 통합 가이드

한국투자증권 (KIS) Open API 실시간 시세 + 애널리스트 투자의견 통합 모듈.

## 모듈 구조

```
nuri/collectors/
├── kis_realtime.py         # 실시간 시세 (한국 + 미국), 토큰 캐시, rate limit 처리
├── institutional.py        # 기관/외인 수급 (#247 — investor-trade-by-stock-daily)
└── kis_analyst_opinion.py  # KR 애널리스트 투자의견 (#418 — invest-opinion REST endpoint)
```

`kis_analyst_opinion.py` 는 #418 (Playwright 기반 리서치 페이지 스크래퍼 design) 의 후속이다. 공식 KIS Open API REST endpoint `invest-opinion` (tr_id `FHKST663300C0`) 만 사용하므로 Playwright / 로그인 세션 자동화 / DOM 렌더링 우회는 더 이상 필요 없다 (2026-04-28 user challenge → official repo 재조사 → endpoint 발견).

## 자격 증명 (Credentials)

### 우선순위
1. **`.env` 파일** (권장 — git ignored)
2. **`config/kis/kis_devlp.yaml`** (프로젝트 내 gitignored, KIS Open API SDK 호환)
3. **`~/KIS/config/kis_devlp.yaml`** (레거시 위치, 하위 호환 fallback)

### .env 변수

```bash
# 실전 (Production)
KIS_PROD_APP_KEY=PSxxxxxx...
KIS_PROD_APP_SECRET=...
KIS_PROD_ACCOUNT=1000000  # 8자리 종합계좌 (시세만 조회 시 비워둬도 OK)

# 모의 (Paper)
KIS_PAPER_APP_KEY=...
KIS_PAPER_APP_SECRET=...
KIS_PAPER_ACCOUNT=...

# WebSocket (실시간 호가 사용 시)
KIS_HTS_ID=your_hts_id
```

### YAML fallback (`config/kis/kis_devlp.yaml`)

KIS Open API 공식 SDK와 호환되는 형식. nuri-quant는 프로젝트 내 `config/kis/` 하위에 파일을 두는 것을 권장 (gitignored). 레거시 위치 `~/KIS/config/kis_devlp.yaml`도 자동 감지.

```yaml
my_app: "실전 앱키"
my_sec: "실전 시크릿"
paper_app: "모의 앱키"
paper_sec: "모의 시크릿"
my_htsid: "HTS ID"
my_acct_stock: "1000000"        # 실전 종합계좌
my_paper_stock: "1000000"       # 모의 종합계좌
my_prod: "01"                    # 종합계좌 (01) / 선물옵션 (03) / 해외선물옵션 (08)
```

#### KIS Open API 공식 SDK와 동시 사용 시

KIS 공식 SDK (`pykis` 등)는 hardcoded `~/KIS/config/kis_devlp.yaml` 경로를 사용합니다. nuri-quant와 공식 SDK를 동시에 쓰려면 두 위치에 파일이 모두 있어야 합니다:

**옵션 1 — symlink (권장, 1개 파일)**:
```bash
mkdir -p ~/KIS/config ~/KIS/cache
ln -sf "$(pwd)/config/kis/kis_devlp.yaml" ~/KIS/config/kis_devlp.yaml
ln -sf "$(pwd)/config/kis/cache" ~/KIS/cache
```

**옵션 2 — legacy only (nuri-quant fallback 활용)**:
`~/KIS/config/kis_devlp.yaml`에 파일을 두고 `config/kis/`는 비워두면 nuri-quant가 legacy 경로를 자동 감지. SDK는 기본 경로에서 읽음.

**옵션 3 — SDK 미사용**: nuri-quant만 쓰면 `config/kis/`만으로 충분.

## 사용법

### 1. 자격 증명 확인 (API 호출 X)

```bash
make collect-kis-check
# → KIS 자격 증명 OK [prod] app_key=PSxxxxxx... account=(미설정)
```

### 2. 실시간 시세 수집

```bash
make collect-kis                                          # prod 모드 (기본)
.venv/bin/python -m nuri.collectors.kis_realtime --mode paper   # 모의
```

**출력 예시**:
```
KIS 실시간 수집: 23/23 (KIS=21, yfinance fallback=2)
```

### 3. 단일 종목 시세 조회 (Python)

```python
from nuri.collectors.kis_realtime import load_credentials, get_access_token, inquire_price_us

creds = load_credentials("prod")
token = get_access_token(creds)
result = inquire_price_us(creds, token, "NVDA")
# {'ticker': 'NVDA', 'date': '2026-04-09', 'open': ..., 'close': 184.02, ...}
```

## Rate Limit 처리

### KIS 공식 정책 (2026.03.20 공지)

| 계정 유형 | 신청 후 3일 | 그 이후 |
|---|---|---|
| **실전 신규** | 초당 3건 | 기본 유량 (정확값 미공시) |
| **실전 갱신** | 즉시 기본 유량 | — |
| **모의** | 항상 더 낮은 제한 | — |

### 시스템 적용

| 모드 | 호출 간격 | 초당 |
|---|---|---|
| **prod** | `KIS_REQUEST_INTERVAL_PROD = 0.4s` | 2.5건 (안전 마진) |
| **paper** | `KIS_REQUEST_INTERVAL_PAPER = 1.0s` | 1건 |
| **EXCD 폴백** | `KIS_EXCD_RETRY_INTERVAL_SEC = 0.4s` | NAS→NYS→AMS 사이 |
| **rate limit 후** | `KIS_RATE_LIMIT_RETRY_DELAY_SEC = 1.5s` | 충분히 회복 |

### Rate Limit 감지

`_is_rate_limit(payload)` 함수가 다음 패턴 매칭:

1. **공식 코드**: `msg_cd == "EGW00201"`
2. **메시지**: `msg1`에 "거래건수" 또는 "초당" 포함
3. **응답 구조**: `rt_cd == "1"` (에러 응답)

> **실측**: KIS 해외 시세 API는 `msg_cd=None` 반환, 메시지 매칭이 핵심.

## yfinance Fallback

KIS 시세 실패 시 자동으로 yfinance로 보충 수집. 실패 종목만 회수.

```python
def _yfinance_fallback(tickers):
    """KIS 실패 종목을 yfinance로 보충 수집."""
    for t in tickers:
        hist = yf.Ticker(t).history(period="2d")
        if not hist.empty:
            recovered.append({...})
    return recovered
```

**효과**: KIS 21/23 → yfinance fallback +2 → **총 23/23 (100%)**

## Token 관리

### 1분 Cooldown

KIS는 토큰 발급 시 1분당 1회 제한. 연속 호출 시 거부됨.

### 디스크 캐시

| 경로 | 형식 | TTL | 선택 조건 |
|---|---|---|---|
| `config/kis/cache/token_prod.json` | `{access_token, issued_at, expires_in}` | 23h (실제 24h, 마진 1h) | project-local `config/kis/kis_devlp.yaml` 또는 `.env` 사용 시 (기본) |
| `config/kis/cache/token_paper.json` | 동일 | 동일 | 동일 |
| `~/KIS/cache/token_*.json` | 동일 | 동일 | legacy — `~/KIS/config/kis_devlp.yaml` 만 존재할 때 (SDK 공존 케이스) |

### Cooldown 응답 감지

`_is_token_cooldown(payload, status_code)`:
- HTTP **403** → cooldown
- HTTP 200 + `error_description`에 "1분당" 포함 → cooldown
- `error_code == "EGW00133"` → cooldown

## 미국 시세 (EXCD 폴백)

KIS는 미국 종목을 거래소별로 분리:

| EXCD | 거래소 | 예시 종목 |
|---|---|---|
| **NAS** | NASDAQ | NVDA, GOOGL, AMD, PLTR |
| **NYS** | NYSE | OKLO, BLSH, FIG |
| **AMS** | AMEX/Arca | VOO, ETF 일부 |

`inquire_price_us()`는 NAS → NYS → AMS 순서로 시도. 각 시도 사이 0.4s sleep (rate limit 회피).

## 한국 종목 (Ticker 변환)

```python
"005930.KS" → "005930"  # .KS 접미사 제거
"000660.KQ" → "000660"  # .KQ도 처리
```

`FID_COND_MRKT_DIV_CODE = "J"` (주식 구분).

## 검증 결과

| 테스트 | 결과 |
|---|---|
| **23개 보유 종목 수집** | 100% (KIS 21 + yfinance fallback 2) |
| **단위 테스트** | 36 PASS (`tests/collectors/test_kis_realtime.py`) |
| **검증 함수** | `_is_rate_limit`, `_is_token_cooldown`, `load_credentials`, `inquire_price_kr/us` |

## 알려진 한계

1. **모의(vps) 데이터 누락**: 일부 미국 종목 (OKLO, IONQ, FIG)은 모의에서 빈 응답. yfinance fallback 자동.
2. **KIS_HTS_ID 필요**: WebSocket 실시간 호가 사용 시 HTS ID 필수 (현재 REST만 사용 시 불필요)
3. **종합계좌 (account) 미설정 OK**: 시세 조회만 사용 시 계좌번호 비워둬도 작동. 매매 주문 시 필요
4. **WebSocket "No close frame received" 오류**: HTS ID 정확성 확인 필요 (KIS 공식 안내)

## 애널리스트 투자의견 (#418)

`nuri/collectors/kis_analyst_opinion.py` 는 KIS Open API `invest-opinion` (tr_id `FHKST663300C0`) endpoint 를 사용해 KR 종목별 애널리스트 투자의견을 수집한다.

### Endpoint
```
GET /uapi/domestic-stock/v1/quotations/invest-opinion
tr_id: FHKST663300C0
```

**Parameters**:
- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_COND_SCR_DIV_CODE=16633` (Primary key)
- `FID_INPUT_ISCD`: 6자리 ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1` / `FID_INPUT_DATE_2`: YYYYMMDD 시작/종료. 6 month rolling window default. T-0 (당일) 도 정상 동작 — `investor-trade-by-stock-daily` 의 T-1 제약과 다름 (live probe 2026-04-28 verified).

**Output** (`output[]`, broker-level rows):
- `stck_bsop_date` — YYYYMMDD
- `invt_opnn` / `invt_opnn_cls_code` — 현재 의견 + 코드
- `rgbf_invt_opnn` / `rgbf_invt_opnn_cls_code` — 직전 의견 + 코드
- `mbcr_name` — 발표 증권사명 (한국어 raw text)
- `hts_goal_prc` — 목표가 (KRW)
- `stck_nday_esdg` / `nday_dprt` / `stft_esdg` / `dprt` — 괴리도/괴리율 (현 단계 미저장)

### 설계 결정 (codex Round 1+2 consult, 2026-04-28)

| 결정 | 이유 |
|---|---|
| `cls_code` 무시, `invt_opnn` 텍스트로 정규화 | live probe — 같은 cls_code 가 broker 별로 BUY / HOLD / Outperform / Neutral 으로 다르게 매핑 (broker-inconsistent ranking). 텍스트 normalization 으로 canonical bucket 추출. |
| `firm` = 원본 broker 이름, 빈 값은 stable fallback (`KIS_UNKNOWN`) | `INSERT OR IGNORE` UPSERT 의 UNIQUE `(ticker, date, firm)` 가 NULL≠NULL SQLite quirk 로 깨지지 않도록 보장. |
| `to_grade` / `from_grade` 원본 KIS 텍스트 그대로 | 기존 US 행 (브로커별 영문) 과 동일 패턴; 정규화는 consumer 책임. |
| `action` 4-value derivation: `init` / `main` / `up` / `down` | 기존 `analyst_ratings.action` vocabulary (`init`, `up`, `down`, `main`, `reit`) 와 호환. KIS 의 `reit` 의미는 없어 `main` 으로 흡수. |
| 6 month rolling window, 매 Sunday 재실행 idempotent | strict T-7d watermark 보다 안전 — scheduler miss 이후 hole 방지. UPSERT IGNORE 가 dup 흡수. |

### 운영 한계 (Round 2 codex flagged, 후속 이슈 대상)

1. **`analyst_ratings` 는 `nuri/core/coverage.py::US_ONLY_TABLES` 에 그대로** — KR 행이 DB 에는 들어오지만 coverage 통계에서는 여전히 "n/a (US-only)" 로 표시됨. 후속 PR 에서 KR 지원 reclassify.
2. **`WallStreetAgent` 는 `.KS` ticker hard-skip 유지** (`nuri/trading/agents/wallstreet.py` 라인 ~40) — KR 의견이 consensus 까지 흐르지 않음. UI ticker detail 에는 표시. 후속 PR 에서 read-path 활성화.
3. **Privacy scanner 의 `BROKER_NAMES_KO`** — DB row 의 broker 이름은 scanner pattern 과 일치. **DB / runtime log 은 검사 대상 아님** (scanner 는 committed code/docs/PR/commit 만 검사), 그러나 test fixture 와 docs 에서는 합성 broker 이름 ("Test Securities A" 등) 사용. 본 문서의 broker 이름 언급도 generic.

### 실패 모드 (STRATEGY §2.6 Surface rung)

| 상황 | 동작 | pipeline_events |
|---|---|---|
| KIS creds 미설정 | 즉시 `[]`, warning | `step_blocked` + `kis_creds_missing` |
| Token 발급 실패 | 즉시 `[]`, error | `step_failed` + `kis_token_failed` |
| 전체 실행 완료 | 결과 반환 | `kis_analyst_opinion_run` (covered / empty / failed / rows) |
| `tr_cont` recursion ≥ 8 | 한 번 surface, 계속 진행 | `kis_analyst_opinion_truncation_risk` (ticker_code, depth) |
| HTTP 4xx/5xx, `rt_cd != 0`, exception | 해당 ticker skip, debug 로그 | (없음 — per-ticker level) |
| Empty `output` | 해당 ticker `empty++`, continue | (없음 — 통합 run 이벤트에 합산) |

## 투자자매매동향 (기관/외인 수급, #247)

`nuri/collectors/institutional.py`는 KIS Open API `investor-trade-by-stock-daily` endpoint를 사용해 한국 종목의 기관/외국인/개인 일별 순매수 데이터를 수집한다.

### Endpoint

```
GET /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily
tr_id: FHPTJ04160001
```

**Parameters**:
- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_INPUT_ISCD`: 6자리 ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1`: YYYYMMDD — **T-1 필수** (당일 날짜는 daily settlement 전 `OPSQ2001 TIME LIMIT` 에러)
- `FID_ORG_ADJ_PRC`, `FID_ETC_CLS_CODE`: 공란

**Response** (`output2`): 30일 history 배열, 101개 필드/row. 핵심:
- `stck_bsop_date` — YYYYMMDD
- `frgn_ntby_qty` — 외국인 순매수 수량
- `orgn_ntby_qty` — 기관계 순매수 수량
- `prsn_ntby_qty` — 개인 순매수 수량

### Rate Limit

`KIS_REQUEST_INTERVAL_PROD = 0.4s` (2.5 req/sec 안전 마진) + rate limit 감지 시 1.5s 대기 후 1회 재시도.

universe 203 KR tickers × 0.4s = ~81초/run.

### 실패 모드 (STRATEGY §2.6 Surface rung)

| 상황 | 동작 | pipeline_events |
|---|---|---|
| KIS creds 미설정 | 즉시 `return []`, warning 로그 | `step_blocked` + `kis_creds_missing` |
| Token 발급 실패 | 즉시 `return []`, error 로그 | `step_failed` + `kis_token_failed` |
| HTTP 4xx/5xx | 해당 ticker skip, loop 지속 | (없음 — per-ticker 레벨) |
| `rt_cd != 0` | 해당 ticker skip, debug 로그 | (없음) |
| Connection error | 해당 ticker skip, debug 로그 | (없음) |

**Surface only** — collector infra failure는 market signal이 아니므로 certify warning이나 pipeline block 으로 승격하지 않음. `institutional_flows` 테이블이 비어도 한국장 분석은 degraded mode 로 진행.

### UPSERT (B1 lesson, PR #311)

`UNIQUE(ticker, date, market)` + `ON CONFLICT DO UPDATE SET ...` — `INSERT OR REPLACE` 금지. id 보존으로 FK 안전.

## 참고 자료

- **KIS Open API 포털**: https://apiportal.koreainvestment.com
- **공식 GitHub (REST 샘플)**: https://github.com/koreainvestment/open-trading-api
- **AI 에이전트 확장**: https://github.com/koreainvestment/kis-ai-extensions
- **공지사항**:
  - 2026.03.20 [중요] 신규 고객 초당 호출 제한 안내 (3일 후 기본 유량)
  - 2026.04.02 OpenAPI Github 샘플코드 신규 업로드
  - 2026.02.25 API 호출 유량 안내 (REST, WebSocket)
