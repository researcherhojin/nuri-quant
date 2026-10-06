# Overview 구현 및 운영 안내

Overview 는 홈 화면 `/` 이다. `/dashboard-next` 미리보기(#1658)로 시작해 기존 대시보드와 나란히 비교했고,
#1698 에서 기존 화면을 대체했다 — 기존 페이지와 그 전용 컴포넌트·테스트는 삭제됐고 `/dashboard-next` 는
`/` 로 리다이렉트된다(쿼리 유지). 사이드바 항목은 **Overview** 하나다.

## 화면 구성과 용어

| 영역 | 표시 내용과 사용 방법 |
|---|---|
| 시스템 의견 | 백엔드의 종합 의견과 지연 입력을 함께 표시한다. |
| 주요 지수 · 시스템 분류 | 머리글은 S&P 500·NASDAQ·KOSPI·KOSDAQ 의 최근 값, 직전 관측 대비 변화율, 기준일(#1676). 그 아래 한 줄이 시스템 분류(레짐) — 특수 레짐(과열·스태그플레이션·회복 초기·섹터 순환)이면 기본 판정(추세 × 변동성)을 따로 적고, `confidence` 는 "검사 일치" 로 표시한다. 기본 판정을 점검하는 검사(추세 검사 3종 + VIX·볼린저 밴드 폭 변동성 교차 검사, 값 없는 지표는 분모에서 빠짐) 중 통과한 비율이지 특수 분류의 신뢰도가 아니기 때문이다. 분류는 목표 배분을 정하므로 지수로 대체하지 않는다. |
| 경제 여건 점수 | 금리·물가·고용·시장 심리 등 시스템 점수. 라벨은 백엔드 분류를 그대로 번역한 기존 대시보드와 같은 네 단계(양호·보통·부진·취약)와 **입력 부족**이며, 점수로 라벨을 다시 만들지 않는다. coverage 0 의 대체 점수는 숨긴다. |
| 우선 점검 항목 | `/api/actions`의 우선 확인 건수와 검토·포트폴리오 규칙 건수. |
| 보유 종목 점검 | 우선 확인·검토·포트폴리오 규칙·유지 탭. 선택한 종목의 기준일, 근거, 비중, 손익과 두 신호를 표시한다. |
| 내 포트폴리오 | 종목별·업종별·계좌별 도넛과 전체 비중 목록. 평가 기준은 설명 창에서 확인한다. |
| 시장 탐색 | 후보의 1일·5일 가격 변화와 근거. 가격 변화는 판단 변경 이력이 아니다. |
| 데이터 업데이트 | 정상·주의·지연 소스, 전체 소스 설명, 갱신 작업 진입점. |
| 파이프라인 상태 | 최근 실행 이벤트, 판정 원장 산출물, 스케줄러 상태를 구분한다. |

**시장 국면 → 시스템 분류**(주요 지수 아래 한 줄, #1676 — 이전 이름 시장 흐름), **매크로 환경 → 경제 여건 점수**,
**판단 모니터 → 보유 종목 점검**, **자산 배분 → 내 포트폴리오**로 표현을 정리했다.
신뢰도는 수익 확률이 아니며, `alpha_action`과 `portfolio_action`은 독립된 축이다.
화면의 판단은 백엔드가 생성한 결과이고 주문 실행 기능은 없다.

## 데이터 연결과 오류 처리

첫 화면은 다음 조회를 병렬로 요청한다. HTTP 성공 여부와 Zod 응답 구조를 모두 검사하고,
실패한 패널은 확인 불가로 표시하며 정상 패널은 유지한다.

| 조회 API | 사용 영역 |
|---|---|
| `GET /api/dashboard` | 시스템 의견, 주요 지수(`market_indices`), 시장 분류, 경제 점수, VIX, 환율, 알림 |
| `GET /api/actions` | 점검 목록과 판정 원장 링크 |
| `GET /api/opportunities` | 탐색 후보와 가격 변화 · 시스템 판단(`system`, BUY 후보 emitter 분류) · 스캐너 관측 |
| `GET /api/portfolio` | 보유 수량·종목명·최근 가격·현금 |
| `GET /api/freshness` | 데이터 업데이트 상태 |
| `GET /api/pipeline/status` | 단계별 이벤트와 판정 원장 요약 |
| `GET /api/scheduler/health` | 클라이언트가 별도로 조회하는 스케줄러 상태 |

### `market_indices` (#1676)

`/api/dashboard` 의 `market_indices` 는 항상 4개 항목을 이 순서로 낸다 — `sp500` · `nasdaq` · `kospi` · `kosdaq`.
각 항목은 `{key, label, close, prev_close, change_pct, date, source, symbol}` 이다(`source`·`symbol` 은 #1682). `change_pct` 는 `(close / prev_close − 1) × 100` 을 소수 둘째 자리로 반올림한 값이다.

- **출처가 둘이다.** 미국 지수는 `macro` 테이블(`sp500` · `nasdaq_composite`)에서 읽는다. `MacroCollector` 가 매시 `^GSPC` · `^IXIC` 를 수집한다. 한국 지수는 `prices` 의 `KOSPI` · `KOSDAQ` 행이다(`StockKRCollector`).
- **미국 지수는 `prices` 에 넣지 않는다.** `.KS` · `.KQ` 접미사가 없는 이름이라 `is_kr_ticker()` 필터를 통과한다. 그러면 US 종목 universe(decision_alpha 치환 후보 · walkforward 패널)에 거래 가능 종목처럼 섞인다(#710 의 KOSDAQ 과 같은 경로).
- **결측은 null 이다.** 행이 없으면 4개 값이 모두 null 이다. 직전 관측이 없거나 0 이면 `change_pct` 만 null 이다. 조회가 실패해도 항목 shape 는 유지한다. 화면은 null 을 `—` 로 내고 0% 로 바꾸지 않는다.
- **`close` 는 최근 저장값이다.** macro 는 매시, stock_kr 은 장중 5분마다 그날 봉을 덮어쓰므로 장중에는 확정 종가가 아닐 수 있다. 미국과 한국의 `date` 는 다를 수 있다.
- **`source` 는 저장된 값이다.** `macro` 행은 그 행의 `source` 열을 그대로 낸다. `prices` 에는 source 열이 없어 수집기(`StockKRCollector._collect_indices`, yfinance)를 적는다. `symbol` 은 원천 심볼(`^GSPC` 등)이다.

### `macro_inputs` (#1682)

`/api/dashboard` 의 `macro_inputs` 는 경제 여건 점수(`compute_macro_score`)가 읽는 `macro` 지표 9종의 **최신 저장 행의 `date`·`source`** 다 — `MACRO_INPUTS` 순서로 `{key, date, source}`. 행이 없으면 `date`·`source` 가 null 이다. 이벤트 점수는 뉴스·경제 일정에서 따로 계산돼 목록에 없다. 점수 계산이 읽는 지표와 이 목록이 어긋나면 출처 표시가 거짓이 되므로 `tests/api/test_dashboard.py::TestMacroInputsProvenance::test_inputs_match_what_the_macro_score_reads` 가 양쪽을 대조한다.

클라이언트 요청은 상대 `/api/*` 경로를 사용한다.
파이프라인은 진입 시·60초 간격·수동 조회·화면 복귀 시 갱신하고 숨겨진 탭에서는 주기 조회를 건너뛴다.
조회 실패 시 이전 기록을 보존하되 실패 표시를 붙인다. 과거 완료 이벤트는 **성공 기록**으로 표시한다.

## 포트폴리오 평가와 표시

- 최근 저장 가격 × 수량으로 평가하고 현금을 합산한다. KRW 자산은 저장된 USD/KRW 환율로 USD 환산한다.
- 필수 가격·환율·현금 데이터가 누락되면 총액과 비중 산출을 보류한다. 미상 값을 0%로 바꾸지 않는다.
- 모든 집계 항목을 도넛에 반영한다. 상위 항목만 남기거나 나머지를 ‘기타’로 묶지 않는다.
- 목록은 카드 내부에서 스크롤하고 키보드로도 접근한다. 표시 가능 행 수는 화면 높이에 따라 달라진다.
- 한국 주식·ETF(`.KS`, `.KQ`)는 API의 종목명을 우선 사용한다. 이름이 없으면 티커로 표시하며, 미국 종목은 티커를 유지한다.
- 합산 키는 티커이므로 이름이 같은 서로 다른 종목을 합치지 않는다. 상세 창에는 이름과 티커를 함께 표시한다.
- 평가 기준 창은 종목별 가격 기준일의 범위를 표시한다. 현재 보유 구성이며 실시간 시세나 목표 배분이 아니다.

## 데이터 갱신 작업

데이터 업데이트의 **지연 데이터 갱신** 또는 파이프라인의 **데이터 갱신**을 연다.
지연 소스와 일치하는 작업을 먼저 선택하고, **선택한 데이터 갱신**을 눌러야 실행된다.
기술 지표 입력 가격이 오래되었다면 주가 수집도 함께 선택한다. 의존 작업이 자동 추가되지는 않는다.

| 작업 ID | 실행 내용 | 단계 |
|---|---|---|
| `prices` | 미국·한국 주가 수집 | collect |
| `macro` | 경제 지표·환율 수집 | collect |
| `technical` | 기술 지표 계산 | collect |
| `fundamentals` | 기업 재무정보 수집 | collect |
| `factors` | 종합 분석 점수 계산 | analyze |

`GET /api/pipeline/refresh`는 작업 목록과 최근 요청 상태를 반환한다.
`POST /api/pipeline/refresh`는 `{"jobs":["prices","technical"]}`를 받아 HTTP 202로 접수한다.
선택 순서와 관계없이 위 표 순서대로 중복을 제거해 실행한다.
쓰기 인증과 감사 로그(`REFRESH` / `pipeline_refresh`)를 적용하며, 현재 프로세스에서 진행 중인 요청이 있으면 HTTP 409로 거절한다.
heavy slot 은 **접수 시점**에 비블로킹으로 잡는다 — 슬롯이 없으면 다른 무거운 라우트와 같은 HTTP 503 + `Retry-After: 5` 로 거절하고 (Codex #1658 P2: 202 뒤 "실패한 실행" 으로 둔갑하지 않는다), 백그라운드 실행이 끝나면 놓는다.
`run_step()`이 스테이지 lifecycle 이벤트를 남기고, 그와 별도로 `refresh_job_started/completed/failed` 이벤트가 작업 ID·요청 ID·`origin: dashboard_refresh` 를 실어 스케줄러의 같은 스테이지 실행과 구분한다.
작업 실패 시 남은 작업은 실행하지 않는다.

갱신 창이 열려 있는 동안 5초 간격으로 상태를 조회한다.
완료·실패 후 신선도를 재확인하고 화면과 파이프라인 상태를 다시 조회한다.
**작업 완료와 최신 데이터 확보는 별개**다. 원본 관측일이 오래되거나 수집 범위가 부족하면 지연이 남을 수 있다.
합의·판정·성과 추적은 이 버튼에서 실행하지 않는다.

## 판정 기록(Decide)의 의미

Decide는 독립 예약 작업이 없으며 Consensus 내부에서 `record_decisions()`가 실행된다.
따라서 이벤트가 없다는 이유로 판정 자체가 없다고 표시하지 않는다.
`/api/pipeline/status`의 Decide 항목에 다음 정보를 추가했다.

- `execution_mode: "inline_with_consensus"`
- `artifact: {status, date, count}`: 최신 `decisions.date`와 해당 기준일의 기록 수
- 산출물 상태: `available` / `empty` / `unavailable`

원래 실행 `status`와 `last_updated`는 유지한다. 실제 오류가 있으면 오류를 표시하며,
원장 날짜·건수가 존재해도 실행 성공이나 판단의 최신성을 보장하지 않는다.
개발 DB는 운영 판정 원장의 읽기 복제본이므로 날짜가 오래되면 운영 수집·합의와 복제 동기화를 확인한다.

## 반응형과 접근성

기존 공통 컨테이너의 최대 폭 1,600px, 이전 Preview의 최대 높이 900px가
큰 화면에서 과도한 여백과 작은 글자를 만들었다. Overview 는 폭 제한을 해제하고 가용 높이를 사용한다.
뷰포트에 따라 글자·간격·도넛 크기를 조정한다. 다른 화면의 폭 제한(1,600px)은 유지하며, `responsive.spec.ts` 의 캡 검사는 `/` 를 제외한다.

**Test:** `frontend/e2e/overview-layout.spec.ts::overview fills available space and keeps content reachable at 2560x1440`

- 폭 1,050px 이하: 세로 배치와 페이지 스크롤.
- 데스크톱 높이 850px 이하: 정보 잘림을 막기 위해 페이지 스크롤 허용.
- 일반·대형 데스크톱: 한 화면 구성을 목표로 핵심 행과 링크의 잘림을 검사.
- 검증 해상도: 1440×900, 1920×1080, 2560×1440, 3440×1440, 1280×800, 390×844.
- 설명 창: Escape·닫기 버튼·바깥 클릭으로 닫기. 내부 여백 클릭은 유지.
- 키보드 포커스 표시, 표 머리글, 차트 설명, 동작 감소 설정을 지원한다.

## 구현 위치와 검증

| 위치 | 역할 |
|---|---|
| `frontend/src/app/(overview)/` (route group → `/`) · `frontend/next.config.ts` 의 `/dashboard-next` 리다이렉트 | 서버 페이지, API 스키마, 점검·포트폴리오·갱신·파이프라인 컴포넌트, CSS |
| `frontend/src/lib/strings.ts` · `frontend/src/components/ui/sidebar.tsx` | 화면의 **모든** 사용자 노출 문구(`OVERVIEW`, 패널별 하위 객체), 다른 화면과 공용인 분류 라벨(`MACRO_INTERPRETATION` · `REGIME_LABEL`), 탐색 링크. 컴포넌트와 테스트는 리터럴 대신 여기서 읽는다 (#1252) |
| `frontend/src/app/layout.tsx` | Overview 전용 폭 확장을 위한 컨테이너 표시 (`[data-page-container]:has(.dashboard)`) |
| `nuri/api/routes/pipeline.py` | Decide 원장 산출물 조회 |
| `nuri/api/routes/dashboard.py` (`MARKET_INDICES` · `_get_market_indices`) · `tests/api/test_dashboard.py::TestMarketIndices` | 주요 지수 블록과 결측·변화율 회귀 테스트 (#1676) |
| `tests/quant/regime/test_regime_label_coverage.py` | 분류기의 10개 레짐(`ALL_REGIMES`) 과 `REGIME_LABEL` 키를 양방향으로 대조한다 |
| `nuri/api/routes/pipeline_refresh.py` · `nuri/api/main.py` | 갱신 작업 API와 라우터 등록 |
| `tests/api/test_pipeline_refresh.py` | 순서·실패·중복·인증·슬롯·원장 관측 회귀 테스트 |
| `frontend/src/__tests__/pages/overview*.test.tsx` | 패널·신호·결측값·이름·전체 목록·조회·갱신 테스트 |
| `frontend/e2e/overview-layout.spec.ts` | 실제 브라우저의 해상도별 배치·모달 정렬·리다이렉트 회귀 테스트 |

저장소 루트에서 백엔드를, `frontend/`에서 프런트 검증을 실행한다.

```bash
.venv/bin/python -m pytest tests/api/test_pipeline_refresh.py tests/api/test_pipeline.py tests/core/test_cross_stage_imports.py tests/core/test_db_path_forwarding.py tests/core/test_sqlite3_sole_importer.py tests/verify/test_readme_structure.py -q
```

```bash
cd frontend
npx vitest run src/__tests__/pages/overview.test.tsx src/__tests__/pages/overview-pipeline.test.tsx src/__tests__/pages/overview-refresh.test.tsx
npx playwright test e2e/overview-layout.spec.ts --reporter=line
```

2026-10-06 로컬 실행 기록 (디테일 패스 뒤, PR #1658 2번째 커밋 기준):

| 검증 범위 | 결과 |
|---|---|
| `tests/api/test_pipeline_refresh.py` · `test_routes.py` · `test_pipeline.py` · `test_limits.py` · `tests/core/test_pipeline_events.py` · `test_pipeline_observability.py` | 163 passed |
| Preview Vitest 3개 파일 | 22 passed |
| 프런트 전체 `npx vitest run` | 143 files · 1,697 tests passed |
| `npm run lint` (eslint + oxlint) · `tsc --noEmit` | 0 findings |
| Preview 해상도 Playwright (6 viewports) | 6 passed |

이 수치는 위 명령의 실행 결과이며 커버리지 측정값이 아니다.

E2E는 실제 로컬 API를 사용한다. 개인 보유값을 고정한 기대값이나 개인 정보가 담긴 스크린샷은 커밋하지 않는다.

## 제약과 인수인계

- 갱신 상태와 중복 방지는 API 프로세스 메모리 기준이다. 재시작 시 초기화되며 여러 워커 사이에서 공유되지 않는다. 영속 작업 큐는 구현하지 않았다.
- 창을 닫아도 서버에서 접수한 작업은 계속될 수 있다. 응답 확인 실패 후 재요청하기 전에 상태를 확인한다.
- API 인증이 켜진 환경에서는 실행 권한이 필요하다. 프런트 갱신 요청에는 별도 Bearer 토큰 입력 기능이 없다.
- 요약 API·서버 조회 캐시가 있어 작업 결과가 즉시 모든 카드에 반영되지는 않을 수 있다.
- 신선도 작업 매핑은 일부 소스만 지원한다. 특히 `macro` 사전 선택은 `macro_vix`에 매핑되어 있으며 다른 매크로 소스는 자동 선택되지 않는다.
- 변경 범위 테스트 통과와 프로덕션 전체 빌드 성공은 구분한다. 개발 서버가 떠 있는 동안 `tsc --noEmit` 이 내는 `.next/dev/types` 의 page export 오류는 개발 서버 산출물이 만드는 것이며(`.next` 를 치우면 사라진다), CI 의 `next build` 와 `Frontend Build` 검사가 실제 판정이다.
- 초안은 PR #1658 의 첫 커밋으로 그대로 들어갔고 디테일 패스가 뒤 커밋이다. #1698 에서 `/` 로 승격되며 기존 대시보드에만 있던 패널(레짐 전환 배너·매크로 이벤트 카드·커버리지 상태·히어로 지표·구성 탭)은 함께 삭제됐다.

## 디테일 패스 규칙 (#1658)

초안 이후 손본 시각·코드 규칙. 이 화면을 고칠 때 같은 규칙을 지킨다.

- **글자 크기는 사다리 토큰 6개뿐**: `--fs-xs` 10 · `--fs-label` 11 · `--fs-body` 13 · `--fs-title` 14 · `--fs-h3` 18 · `--fs-value` 26 (px). 전부 `--font-step`(1600px 부터 폭 160px 당 +0.32px, 최대 +2px — 1920 에서 +0.6, 2560 에서 +1.9)이 더해져 큰 화면에서 조금만 커진다. 초안은 1920 에서 +2.9px 였고 "큰 화면에서 글자가 크다" 는 피드백(2026-10-06)으로 줄였다. `calc(8px + …)` 같은 임의 값은 쓰지 않는다 — 초안의 8·9px 기반 보조 문구가 1440px 에서 9px 로 떨어졌던 것이 계기다. e2e 는 1920px 이상에서 범례 글자가 라벨 토큰 11px 아래로 떨어지지 않는지 본다.
- **간격 토큰 3개**: `--space`(패널 사이, 12–24px) · `--pad`(패널 안쪽 좌우, 14–20px) · `--row`(목록 행 상하 8px, 대형 화면 11px). 표 행·소스 행·파이프라인 행이 같은 `--row` 를 쓴다.
- **시장 카드 (#1676)**: 지표 행의 2.4칸을 쓰고 1250px 이하에서는 3칸, 1050px 이하에서는 한 줄 전체를 쓰며 600px 이하에서는 지수가 2×2 로 배치된다. 지수 칸은 이름과 기준일(`MM-DD`) · 레벨(`--fs-h3`, 1400px 이하 `--fs-title`) · 변화율의 3줄이다 — 1280px 에서 칸이 약 85px 라 다섯 자리 레벨(27,599.79)이 18px 로는 잘리고, 기준일을 변화율 줄에 두면 옆 칸 숫자와 붙는다(2026-10-07 실측). 기준일 줄은 좁으면 말줄임된다(전체 날짜는 `<time datetime>`). 레짐은 그 아래 한 줄이다.
- **지표 카드 (#1682)**: 네 카드 모두 하단 패널과 같은 "아이콘 + 이름" 머리글(`MetricHeading`)과 ⓘ 아이콘 모달을 쓴다 — 버튼에 "읽는 법" 문구는 보이지 않고 접근 가능한 이름으로만 남는다(`DetailDialog iconOnly`, 보유 종목 점검 패널도 같다). 모달은 설명 뒤에 **출처와 기준일** 표를 둔다(지수는 `market_indices.source`·`symbol`, 경제 점수와 VIX 는 `macro_inputs`, 우선 점검은 항목들의 가장 최근 판정 기준일 `as_of` — 목록 생성 시각은 조회마다 "지금" 이라 판정의 나이를 말해 주지 않아 안내 문장으로만 둔다). 출처가 대용치면 이름도 바뀐다: yfinance 의 2년물 자리는 `^IRX`(13주물)라 "미국 13주물 금리 (2년물 대용)" 로 표시한다(`MACRO_INPUT_PROXY_LABEL`). 카드 하단 줄은 왼쪽 부연, 오른쪽 출처 요약이고 좁으면 출처 요약이 먼저 말줄임된다 — 경제 점수는 "FRED 외 n곳" 처럼 첫 출처와 개수만 쓴다. 저장된 source 코드는 `OVERVIEW.SOURCE_NAME` 으로 표시 이름을 붙이고 모르는 코드는 그대로 보인다(출처를 지어내지 않는다). 머리글 줄이 생겨 시장 카드가 5줄이라 지표 행은 `clamp(118px, 12dvh, 160px)`(높이 ≤850px 은 118px)이다 — 390~1920px 에서 카드 잘림·하단 줄 잘림 0 (2026-10-07 실측). 줄을 늘리려면 `grid-template-rows` 의 지표 행부터 키우고 레이아웃 e2e 를 다시 돌린다.
- **범례 스크롤**: 도넛 옆 범례는 차트 행 트랙을 `minmax(0, 1fr)` 로 고정해 그 높이 안에서만 스크롤한다. 초안은 범례가 아래 "전체 N개 구성" 문구를 덮었다.
- **아이콘**: `↗`·`ⓘ` 문자 대신 lucide 아이콘(`ArrowUpRight`·`Info`)을 `aria-hidden` 으로 붙인다. 접근성 이름과 테스트의 버튼 이름은 문구만이다(`DetailDialog` 의 `icon` prop).
- **근거 영역**: 선택 종목의 지표는 근거 아래에 자연스럽게 이어진다(초안은 패널 바닥에 붙여 큰 빈칸이 생겼다).
- **백엔드**: `POST /api/pipeline/refresh` 의 접수는 감사 로그 `REFRESH` / `pipeline_refresh` 만 남긴다. `pipeline_events` 행은 백그라운드 실행이 남긴다 — 스테이지 lifecycle 은 `run_step`, 작업 단위 `refresh_job_started/completed/failed` 는 `_mark()`(`emit_event` 경유, 유일한 writer). heavy slot 은 접수 때 잡고 실행이 끝나면 놓되, 백그라운드가 `QUEUE_GRACE_SECONDS`(60초) 안에 시작하지 못한 queued 실행은 다음 조회·요청에서 `abandoned` 로 닫고 slot 을 돌려준다(응답 전송이 예외로 끝나면 Starlette 가 BackgroundTasks 를 돌리지 않는 경로). `tests/api/test_routes.py` 가 라우터 mount 를 스모크로 잠근다.

## 디자인 참고

[IBKR PortfolioAnalyst](https://portal.interactivebrokers.com/en/portfolioanalyst/features.php)와
[Portfolio Performance Dashboard](https://help.portfolio-performance.info/en/reference/view/reports/performance/dashboard/)를 참고해
보유 구성과 지표 설명을 분리했다. 도넛·전체 종목 표시·큰 화면 확장은 이 화면에서 사용자 요청에 따라 선택한 구현이다.
