# Overview Preview 구현 및 운영 안내

`/dashboard-next`는 기존 `/` 대시보드와 같은 백엔드를 사용하는 별도 비교 화면이다.
사이드바의 **Overview Preview**에서 진입하고, **기존 대시보드와 비교**로 원래 화면을 연다.
이 문서는 2026-10-06 작업의 최종 구현을 기준으로 한다. 배포 여부와 전체 빌드 성공을 뜻하지 않는다.

## 화면 구성과 용어

| 영역 | 표시 내용과 사용 방법 |
|---|---|
| 시스템 의견 | 백엔드의 종합 의견과 지연 입력을 함께 표시한다. |
| 시장 흐름 | 상승·하락·횡보와 변동성 분류. 설명 창에서 분류 신뢰도의 의미를 확인한다. |
| 경제 여건 점수 | 금리·물가·고용·시장 심리 등 시스템 점수. 입력 부족 시 대체 점수를 숨긴다. |
| 우선 점검 항목 | `/api/actions`의 우선 확인 건수와 검토·포트폴리오 규칙 건수. |
| 보유 종목 점검 | 우선 확인·검토·포트폴리오 규칙·유지 탭. 선택한 종목의 기준일, 근거, 비중, 손익과 두 신호를 표시한다. |
| 내 포트폴리오 | 종목별·업종별·계좌별 도넛과 전체 비중 목록. 평가 기준은 설명 창에서 확인한다. |
| 시장 탐색 | 후보의 1일·5일 가격 변화와 근거. 가격 변화는 판단 변경 이력이 아니다. |
| 데이터 업데이트 | 정상·주의·지연 소스, 전체 소스 설명, 갱신 작업 진입점. |
| 파이프라인 상태 | 최근 실행 이벤트, 판정 원장 산출물, 스케줄러 상태를 구분한다. |

**시장 국면 → 시장 흐름**, **매크로 환경 → 경제 여건 점수**,
**판단 모니터 → 보유 종목 점검**, **자산 배분 → 내 포트폴리오**로 표현을 정리했다.
신뢰도는 수익 확률이 아니며, `alpha_action`과 `portfolio_action`은 독립된 축이다.
화면의 판단은 백엔드가 생성한 결과이고 주문 실행 기능은 없다.

## 데이터 연결과 오류 처리

첫 화면은 다음 조회를 병렬로 요청한다. HTTP 성공 여부와 Zod 응답 구조를 모두 검사하고,
실패한 패널은 확인 불가로 표시하며 정상 패널은 유지한다.

| 조회 API | 사용 영역 |
|---|---|
| `GET /api/dashboard` | 시스템 의견, 시장 분류, 경제 점수, VIX, 환율, 알림 |
| `GET /api/actions` | 점검 목록과 판정 원장 링크 |
| `GET /api/opportunities` | 탐색 후보와 가격 변화 |
| `GET /api/portfolio` | 보유 수량·종목명·최근 가격·현금 |
| `GET /api/freshness` | 데이터 업데이트 상태 |
| `GET /api/pipeline/status` | 단계별 이벤트와 판정 원장 요약 |
| `GET /api/scheduler/health` | 클라이언트가 별도로 조회하는 스케줄러 상태 |

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
쓰기 인증과 감사 로그를 적용하며, 현재 프로세스에서 진행 중인 요청이 있으면 HTTP 409로 거절한다.
실제 백그라운드 실행 구간은 `heavy_slot`으로 제한하고 `run_step()`으로 이벤트를 기록한다.
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
큰 화면에서 과도한 여백과 작은 글자를 만들었다. Preview에만 폭 제한을 해제하고 가용 높이를 사용한다.
뷰포트에 따라 글자·간격·도넛 크기를 조정한다. 기존 화면의 폭 제한은 유지한다.

**Test:** `frontend/e2e/dashboard-next-layout.spec.ts::overview fills available space and keeps content reachable at 2560x1440`

- 폭 1,050px 이하: 세로 배치와 페이지 스크롤.
- 데스크톱 높이 850px 이하: 정보 잘림을 막기 위해 페이지 스크롤 허용.
- 일반·대형 데스크톱: 한 화면 구성을 목표로 핵심 행과 링크의 잘림을 검사.
- 검증 해상도: 1440×900, 1920×1080, 2560×1440, 3440×1440, 1280×800, 390×844.
- 설명 창: Escape·닫기 버튼·바깥 클릭으로 닫기. 내부 여백 클릭은 유지.
- 키보드 포커스 표시, 표 머리글, 차트 설명, 동작 감소 설정을 지원한다.

## 구현 위치와 검증

| 위치 | 역할 |
|---|---|
| `frontend/src/app/dashboard-next/` | 서버 페이지, API 스키마, 점검·포트폴리오·갱신·파이프라인 컴포넌트, CSS |
| `frontend/src/lib/strings.ts` · `frontend/src/components/ui/sidebar.tsx` | Preview 문구와 탐색 링크 |
| `frontend/src/app/layout.tsx` | Preview 전용 폭 확장을 위한 컨테이너 표시 |
| `nuri/api/routes/pipeline.py` | Decide 원장 산출물 조회 |
| `nuri/api/routes/pipeline_refresh.py` · `nuri/api/main.py` | 갱신 작업 API와 라우터 등록 |
| `tests/api/test_pipeline_refresh.py` | 순서·실패·중복·인증·슬롯·원장 관측 회귀 테스트 |
| `frontend/src/__tests__/pages/dashboard-next*.test.tsx` | 패널·신호·결측값·이름·전체 목록·조회·갱신 테스트 |
| `frontend/e2e/dashboard-next-layout.spec.ts` | 실제 브라우저의 해상도별 배치 회귀 테스트 |

저장소 루트에서 백엔드를, `frontend/`에서 프런트 검증을 실행한다.

```bash
.venv/bin/python -m pytest tests/api/test_pipeline_refresh.py tests/api/test_pipeline.py tests/core/test_cross_stage_imports.py tests/core/test_db_path_forwarding.py tests/core/test_sqlite3_sole_importer.py tests/verify/test_readme_structure.py -q
```

```bash
cd frontend
npx vitest run src/__tests__/pages/dashboard-next.test.tsx src/__tests__/pages/dashboard-next-pipeline.test.tsx src/__tests__/pages/dashboard-next-refresh.test.tsx
npx playwright test e2e/dashboard-next-layout.spec.ts e2e/dashboard.spec.ts --reporter=line
```

2026-10-06 로컬 실행 기록:

| 검증 범위 | 결과 |
|---|---|
| 백엔드 API·코어 규칙·README 구조 검사 | 84 passed |
| Preview Vitest 파일 | 20 passed |
| Preview 해상도·기존 대시보드 Playwright | 11 passed |

이 수치는 위 명령의 변경 범위 검사 결과이며 전체 저장소 테스트 통과나 커버리지 측정값이 아니다.

E2E는 실제 로컬 API를 사용한다. 개인 보유값을 고정한 기대값이나 개인 정보가 담긴 스크린샷은 커밋하지 않는다.

## 제약과 인수인계

- 갱신 상태와 중복 방지는 API 프로세스 메모리 기준이다. 재시작 시 초기화되며 여러 워커 사이에서 공유되지 않는다. 영속 작업 큐는 구현하지 않았다.
- 창을 닫아도 서버에서 접수한 작업은 계속될 수 있다. 응답 확인 실패 후 재요청하기 전에 상태를 확인한다.
- API 인증이 켜진 환경에서는 실행 권한이 필요하다. 프런트 갱신 요청에는 별도 Bearer 토큰 입력 기능이 없다.
- 요약 API·서버 조회 캐시가 있어 작업 결과가 즉시 모든 카드에 반영되지는 않을 수 있다.
- 신선도 작업 매핑은 일부 소스만 지원한다. 특히 `macro` 사전 선택은 `macro_vix`에 매핑되어 있으며 다른 매크로 소스는 자동 선택되지 않는다.
- 변경 범위 테스트 통과와 프로덕션 전체 빌드 성공은 구분한다. 작업 중 전체 타입 검사에서는 기존 다른 페이지의 허용되지 않은 page export 오류가 확인되었다. 배포 전 전체 빌드를 다시 검증해야 한다.
- 아직 기존 홈 화면을 대체하거나 배포·커밋·푸시한 작업이 아니다.

## 디자인 참고

[IBKR PortfolioAnalyst](https://portal.interactivebrokers.com/en/portfolioanalyst/features.php)와
[Portfolio Performance Dashboard](https://help.portfolio-performance.info/en/reference/view/reports/performance/dashboard/)를 참고해
보유 구성과 지표 설명을 분리했다. 도넛·전체 종목 표시·큰 화면 확장은 이 Preview에서 사용자 요청에 따라 선택한 구현이다.
