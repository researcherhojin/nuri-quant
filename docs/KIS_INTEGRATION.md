# KIS Open API 통합 가이드

한국투자증권 (KIS) Open API 로 실시간 시세, 투자자별 매매동향, 애널리스트 투자의견을 수집하는 모듈을 설명한다.

## 모듈 구조

```
nuri/collectors/
├── kis_realtime.py         # 실시간 시세 (한국 + 미국), 토큰 캐시, rate limit 처리
├── institutional.py        # 기관/외인 수급 (#247 — investor-trade-by-stock-daily)
└── kis_analyst_opinion.py  # KR 애널리스트 투자의견 (#418 — invest-opinion REST endpoint)
```

`kis_analyst_opinion.py` 는 #418 (Playwright 기반 리서치 페이지 스크래퍼 설계)을 대체한다. 공식 KIS Open API REST endpoint `invest-opinion` (tr_id `FHKST663300C0`)만 사용하므로 Playwright, 로그인 세션 자동화, DOM 렌더링 우회가 필요 없다.

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

KIS Open API 공식 SDK 와 호환되는 형식이다. 프로젝트 내 `config/kis/` 하위(gitignored)에 두는 것을 권장하며, 레거시 위치 `~/KIS/config/kis_devlp.yaml` 도 자동 감지한다.

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

KIS 공식 SDK (`pykis` 등)는 `~/KIS/config/kis_devlp.yaml` 경로를 고정으로 사용한다. nuri-quant 와 공식 SDK 를 함께 쓰려면 두 위치 모두에서 파일을 읽을 수 있어야 한다.

**옵션 1 — symlink (권장, 1개 파일)**:

```bash
mkdir -p ~/KIS/config ~/KIS/cache
ln -sf "$(pwd)/config/kis/kis_devlp.yaml" ~/KIS/config/kis_devlp.yaml
ln -sf "$(pwd)/config/kis/cache" ~/KIS/cache
```

**옵션 2 — legacy only (nuri-quant fallback 활용)**:
`~/KIS/config/kis_devlp.yaml` 에 파일을 두고 `config/kis/` 에 yaml 을 두지 않으면 nuri-quant 가 legacy 경로에서 자격 증명을 읽는다. SDK 는 기본 경로에서 읽는다. token cache 는 이 경우에도 `config/kis/cache/` 를 쓴다.

**옵션 3 — SDK 미사용**: nuri-quant 만 쓰면 `config/kis/` 만으로 충분하다.

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

`_is_rate_limit(payload)` 는 에러 응답(`rt_cd == "1"`)이면서 다음 중 하나에 해당할 때 rate limit 으로 판정한다.

1. **공식 코드**: `msg_cd == "EGW00201"`
2. **메시지**: `msg1` 에 "거래건수" 또는 "초당" 포함

> 실측상 KIS 해외 시세 API 는 `msg_cd=None` 을 반환하므로 메시지 매칭이 주된 판정 경로다.

## yfinance Fallback

KIS 시세 조회에 실패한 종목만 yfinance 로 보충 수집한다.

```python
def _yfinance_fallback(tickers):
    """KIS 실패 종목을 yfinance로 보충 수집."""
    for t in tickers:
        hist = yf.Ticker(t).history(period="2d")
        if not hist.empty:
            recovered.append({...})
    return recovered
```

**효과**: KIS 21/23 + yfinance fallback 2 = 23/23 (100%)

## Token 관리

### 1분 Cooldown

KIS 는 토큰 발급을 1분당 1회로 제한하며, 연속 호출은 거부된다.

### 디스크 캐시

| 경로 | 형식 | TTL | 선택 조건 |
|---|---|---|---|
| `config/kis/cache/token_prod.json` | `{access_token, issued_at, expires_in}` | 23h (실제 24h, 마진 1h) | 항상 (자격 증명 출처와 무관, #532) |
| `config/kis/cache/token_paper.json` | 동일 | 동일 | 동일 |
| `~/KIS/cache/token_*.json` | 동일 | 동일 | 사용하지 않음 (legacy 위치 — `make clean-all` 이 정리만 한다) |

### Cooldown 응답 감지

`_is_token_cooldown(payload, status_code)`:

- HTTP **403** → cooldown
- HTTP 200 + `error_description`에 "1분당" 포함 → cooldown
- `error_code == "EGW00133"` → cooldown

## 미국 시세 (EXCD 폴백)

KIS 는 미국 종목을 거래소별로 구분한다.

| EXCD | 거래소 | 예시 종목 |
|---|---|---|
| **NAS** | NASDAQ | NVDA, GOOGL, AMD, PLTR |
| **NYS** | NYSE | OKLO, BLSH, FIG |
| **AMS** | AMEX/Arca | VOO, ETF 일부 |

`inquire_price_us()` 는 NAS → NYS → AMS 순서로 시도하며, 시도 사이에 0.4s 대기한다(rate limit 회피).

## 한국 종목 (Ticker 변환)

```python
"005930.KS" → "005930"  # .KS 접미사 제거
"000660.KQ" → "000660"  # .KQ도 처리
```

`FID_COND_MRKT_DIV_CODE = "J"` (주식 구분).

## 날짜와 저장 규칙 (#1636)

- **미국 시세의 `date` 는 뉴욕 거래일이다.** KIS 해외 현재가 응답에는 날짜가 없다. 예전에는 `today_kst()` 를 찍어, 미국 장이 열려 있는 KST 아침마다 같은 세션이 일일 수집기(yfinance, 미국 거래일)보다 하루 뒤 날짜로 저장됐다. `us_session_date()` 가 America/New_York 으로 변환해 정규장 개장(09:30) 전이면 직전 세션, 주말과 NYSE 휴장일(연방 공휴일 − Columbus/Veterans Day + Good Friday, New Year's 는 일→월만)은 직전 영업일로 당긴다. 특별 휴장은 모델에 없다. 한국 시세는 `today_kst()` 가 맞다.
- **O/H/L 없는 현재가는 완전한 봉을 덮지 않는다.** 해외 현재가(HHDFS00000300)는 `last`/`tvol` 만 주어 open/high/low 가 0 이다. `upsert_prices` 는 INSERT OR REPLACE 라, 날짜가 맞아진 뒤에는 이 행이 yfinance 일봉을 통째로 덮을 수 있다. `KISRealtimeCollector.save()` 는 (ticker, date) 에 `open != 0` 인 봉이 있으면 그 행을 쓰지 않고, 봉이 없거나 앞선 관측도 O/H/L 이 없으면 쓴다. 한국 현재가와 yfinance fallback 행은 OHLC 를 갖고 오므로 그대로 갱신된다.
- **yfinance fallback 의 `date` 는 봉의 인덱스 날짜다.**

**Test:** `tests/collectors/test_kis_us_session_date.py` — 달력 12 케이스 · 행 날짜 · fallback 날짜 · save 가드 4 케이스.

## 검증 결과

| 테스트 | 결과 |
|---|---|
| **23개 보유 종목 수집** | 100% (KIS 21 + yfinance fallback 2) |
| **단위 테스트** | 62 collected across `tests/collectors/test_kis_realtime.py` · `test_kis_realtime_branches.py` · `test_kis_token_cache.py` · `test_kis_us_session_date.py` (2026-10-06) |
| **검증 함수** | `_is_rate_limit`, `_is_token_cooldown`, `load_credentials`, `inquire_price_kr/us` |

## 알려진 한계

1. **모의(vps) 데이터 누락**: 일부 미국 종목(OKLO, IONQ, FIG)은 모의 환경에서 빈 응답을 반환한다. yfinance fallback 이 자동 적용된다.
2. **KIS_HTS_ID**: WebSocket 실시간 호가에는 HTS ID 가 필요하다. 현재처럼 REST 만 쓰면 필요 없다.
3. **종합계좌 (account) 미설정 가능**: 시세 조회만 하면 계좌번호를 비워도 동작한다. 매매 주문에는 필요하다.
4. **WebSocket "No close frame received" 오류**: HTS ID 가 정확한지 확인한다 (KIS 공식 안내).

## 애널리스트 투자의견 (#418)

`nuri/collectors/kis_analyst_opinion.py` 는 KIS Open API `invest-opinion` (tr_id `FHKST663300C0`) endpoint 로 KR 종목별 애널리스트 투자의견을 수집한다. scheduler 의 `kis_analyst_opinion` job 이 매주 일요일 00:30 KST 에 실행한다.

### Endpoint

```
GET /uapi/domestic-stock/v1/quotations/invest-opinion
tr_id: FHKST663300C0
```

**Parameters**:

- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_COND_SCR_DIV_CODE=16633` (Primary key)
- `FID_INPUT_ISCD`: 6자리 ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1` / `FID_INPUT_DATE_2`: YYYYMMDD 시작/종료. 기본값은 6개월(180일) rolling window. T-0(당일)도 정상 동작하며, `investor-trade-by-stock-daily` 의 T-1 제약과 다르다 (2026-04-28 live probe 확인).

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

1. **`analyst_ratings` 는 여전히 `nuri/core/coverage.py::US_ONLY_TABLES` 에 있다.** KR 행이 DB 에 들어오지만 coverage 통계에는 "(KR n/a — 소스 미지원)" 으로 표시된다. KR 지원 재분류는 후속 PR 대상이다.
2. **`WallStreetAgent` 는 `.KS` ticker 를 건너뛴다** (`nuri/trading/agents/wallstreet.py` 의 skip 조건). 따라서 KR 의견은 consensus 에 반영되지 않고 UI ticker detail 에만 표시된다. read-path 활성화는 후속 PR 대상이다.
3. **Privacy scanner 의 `BROKER_NAMES_KO`**: DB row 의 broker 이름은 scanner pattern 과 일치한다. scanner 는 committed code/docs/PR/commit 만 검사하고 DB 와 runtime log 는 검사하지 않는다. test fixture 와 docs 에서는 합성 broker 이름("Test Securities A" 등)을 쓰며, 이 문서도 broker 이름을 generic 하게 표기한다.

### 실패 모드 (STRATEGY §2.6 Surface rung)

| 상황 | 동작 | pipeline_events |
|---|---|---|
| KIS creds 미설정 | 즉시 `[]`, warning | `step_blocked` + `kis_creds_missing` |
| Token 발급 실패 | 즉시 `[]`, error | `step_failed` + `kis_token_failed` |
| 전체 실행 완료 | 결과 반환 | `kis_analyst_opinion_run` (covered / empty / failed / rows) |
| `tr_cont` recursion ≥ 8 | ticker 당 한 번 surface, 계속 진행 | `kis_analyst_opinion_truncation_risk` (ticker_code, depth_reached, max_depth) |
| HTTP 4xx/5xx, `rt_cd != 0`, exception | 해당 ticker skip, debug 로그 | (없음 — per-ticker level) |
| Empty `output` | 해당 ticker `empty++`, continue | (없음 — 통합 run 이벤트에 합산) |

## 투자자매매동향 (기관/외인 수급, #247)

`nuri/collectors/institutional.py` 는 KIS Open API `investor-trade-by-stock-daily` endpoint 로 한국 종목의 기관/외국인/개인 일별 순매수 데이터를 수집한다.

### Endpoint

```
GET /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily
tr_id: FHPTJ04160001
```

**Parameters**:

- `FID_COND_MRKT_DIV_CODE=J` (KRX)
- `FID_INPUT_ISCD`: 6자리 ticker code (e.g. `005930`)
- `FID_INPUT_DATE_1`: YYYYMMDD. T-1 을 사용한다 (당일 날짜는 15:40 KST daily settlement 전에 `OPSQ2001 TIME LIMIT` 에러).
- `FID_ORG_ADJ_PRC`, `FID_ETC_CLS_CODE`: 공란

**Response** (`output2`): 30일 history 배열, 101개 필드/row. 핵심 필드:

- `stck_bsop_date` — YYYYMMDD
- `frgn_ntby_qty` — 외국인 순매수 수량
- `orgn_ntby_qty` — 기관계 순매수 수량
- `prsn_ntby_qty` — 개인 순매수 수량

### Rate Limit

`KIS_REQUEST_INTERVAL_PROD = 0.4s` (2.5 req/sec 안전 마진) + rate limit 감지 시 1.5s 대기 후 1회 재시도.

universe 의 KR ticker 203개 × 0.4s ≈ 81초/run.

### 실패 모드 (STRATEGY §2.6 Surface rung)

| 상황 | 동작 | pipeline_events |
|---|---|---|
| KIS creds 미설정 | 즉시 `return []`, warning 로그 | `step_blocked` + `kis_creds_missing` |
| Token 발급 실패 | 즉시 `return []`, error 로그 | `step_failed` + `kis_token_failed` |
| HTTP 4xx/5xx | 해당 ticker skip, loop 지속 | (없음 — per-ticker 레벨) |
| `rt_cd != 0` | 해당 ticker skip, debug 로그 | (없음) |
| Connection error | 해당 ticker skip, debug 로그 | (없음) |

**Surface only**: collector 인프라 장애는 market signal 이 아니므로 게이트 warning 이나 pipeline block 으로 승격하지 않는다. `institutional_flows` 테이블이 비어도 한국장 분석은 degraded mode 로 진행한다.

### UPSERT (B1 lesson, PR #311)

`UNIQUE(ticker, date, market)` + `ON CONFLICT DO UPDATE SET ...` 를 사용한다. `INSERT OR REPLACE` 는 row id 를 바꿔 FK 를 깨뜨리므로 쓰지 않는다.

## 참고 자료

- **KIS Open API 포털**: https://apiportal.koreainvestment.com
- **공식 GitHub (REST 샘플)**: https://github.com/koreainvestment/open-trading-api
- **AI 에이전트 확장**: https://github.com/koreainvestment/kis-ai-extensions
- **공지사항**:
  - 2026.03.20 [중요] 신규 고객 초당 호출 제한 안내 (3일 후 기본 유량)
  - 2026.04.02 OpenAPI Github 샘플코드 신규 업로드
  - 2026.02.25 API 호출 유량 안내 (REST, WebSocket)
