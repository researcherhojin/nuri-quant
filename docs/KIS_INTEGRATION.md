# KIS Open API 통합 가이드

한국투자증권 (KIS) Open API 실시간 시세 + 리서치 보고서 통합 모듈.

## 모듈 구조

```
nuri/collectors/
├── kis_realtime.py  # 실시간 시세 (한국 + 미국), 토큰 캐시, rate limit 처리
└── kis_research.py  # 리서치 보고서 스크래퍼 (skeleton, Playwright 통합 대기)
```

## 자격 증명 (Credentials)

### 우선순위
1. **`.env` 파일** (권장 — git ignored)
2. **`~/KIS/config/kis_devlp.yaml`** (KIS Open API SDK 호환 fallback)

### .env 변수

```bash
# 실전 (Production)
KIS_PROD_APP_KEY=PSO510...
KIS_PROD_APP_SECRET=...
KIS_PROD_ACCOUNT=12345678  # 8자리 종합계좌 (시세만 조회 시 비워둬도 OK)

# 모의 (Paper)
KIS_PAPER_APP_KEY=...
KIS_PAPER_APP_SECRET=...
KIS_PAPER_ACCOUNT=...

# WebSocket (실시간 호가 사용 시)
KIS_HTS_ID=your_hts_id
```

### YAML fallback (`~/KIS/config/kis_devlp.yaml`)

KIS Open API 공식 SDK와 호환되는 형식. SDK 사용자는 추가 설정 없이 동작.

```yaml
my_app: "실전 앱키"
my_sec: "실전 시크릿"
paper_app: "모의 앱키"
paper_sec: "모의 시크릿"
my_htsid: "HTS ID"
my_acct_stock: "12345678"        # 실전 종합계좌
my_paper_stock: "12345678"       # 모의 종합계좌
my_prod: "01"                    # 종합계좌 (01) / 선물옵션 (03) / 해외선물옵션 (08)
```

## 사용법

### 1. 자격 증명 확인 (API 호출 X)

```bash
make collect-kis-check
# → KIS 자격 증명 OK [prod] app_key=PSO510ne... account=(미설정)
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

**효과**: KIS 22/23 → yfinance fallback +2 → **총 23/23 (100%)**

## Token 관리

### 1분 Cooldown

KIS는 토큰 발급 시 1분당 1회 제한. 연속 호출 시 거부됨.

### 디스크 캐시

| 경로 | 형식 | TTL |
|---|---|---|
| `~/KIS/cache/token_prod.json` | `{access_token, issued_at, expires_in}` | 23h (실제 24h, 마진 1h) |
| `~/KIS/cache/token_paper.json` | 동일 | 동일 |

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
| **단위 테스트** | 22 PASS (`tests/test_kis_realtime.py`) |
| **검증 함수** | `_is_rate_limit`, `_is_token_cooldown`, `load_credentials`, `inquire_price_kr/us` |

## 알려진 한계

1. **모의(vps) 데이터 누락**: 일부 미국 종목 (OKLO, IONQ, FIG)은 모의에서 빈 응답. yfinance fallback 자동.
2. **KIS_HTS_ID 필요**: WebSocket 실시간 호가 사용 시 HTS ID 필수 (현재 REST만 사용 시 불필요)
3. **종합계좌 (account) 미설정 OK**: 시세 조회만 사용 시 계좌번호 비워둬도 작동. 매매 주문 시 필요
4. **`kis_research.py` skeleton**: KIS 리서치 페이지는 로그인 + JavaScript 렌더링 필요. Playwright 통합 후속 작업 대기
5. **WebSocket "No close frame received" 오류**: HTS ID 정확성 확인 필요 (KIS 공식 안내)

## 참고 자료

- **KIS Open API 포털**: https://apiportal.koreainvestment.com
- **공식 GitHub (REST 샘플)**: https://github.com/koreainvestment/open-trading-api
- **AI 에이전트 확장**: https://github.com/koreainvestment/kis-ai-extensions
- **공지사항**:
  - 2026.03.20 [중요] 신규 고객 초당 호출 제한 안내 (3일 후 기본 유량)
  - 2026.04.02 OpenAPI Github 샘플코드 신규 업로드
  - 2026.02.25 API 호출 유량 안내 (REST, WebSocket)
