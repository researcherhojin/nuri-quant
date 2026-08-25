# UX Redesign Plan — Evidence Terminal

대시보드를 "컨슈머 핀테크 카드 UI"에서 Palantir·터미널 계열의 근거 기반 의사결정 도구로
전환하는 실행 계획. 설계 근거·목업·적대 검증(codex 2라운드 AGREED-FINAL)은 2026-08-25
세션 산출물이며, 이 문서는 그 합의를 **작업 순서·게이트·반응형 스펙**으로 고정한다.

**상태 규칙**: 단계가 끝나면 이 문서의 해당 행을 갱신한다 (PR 번호 기입). 코드와 이 문서가
다르면 코드가 정본 — 문서를 고친다.

## 1. 확정된 설계 결정 (재논의 금지 — 변경하려면 새 합의 필요)

| 결정 | 내용 | 근거 |
|---|---|---|
| 표면 램프 | Blueprint 다크 (#111418 / #1C2127 / #252A31 / #2F343C, 블루틴트) — `@theme` zinc 재매핑으로 구현, 원복 = 블록 삭제 | palantir/blueprint colors.ts 실소스. 가역적 토큰 선택으로 codex 합의 |
| 색 예산 | 90/10 — 무채 램프 + 단일 액센트 #4C90F0 + intent 4종. 도넛 캔디 팔레트 폐지 | Bloomberg/Grafana/TradingView 공통 관례 |
| P&L 색 | green=이익 유지 (사용자 확정 2026-08-25). 부호(+/−) 항상 병기 | 코드·테스트 전체 일관 |
| 밀도 | 테이블 행 32px(compact 28), 라벨 11px uppercase, 데이터 13px, radius 4px, 헤어라인 보더 | Blueprint density ladder + WCAG 실측 AAA |
| 타이포 | Pretendard(한글 UI) + Geist Mono(숫자, tabular-nums) | Geist Sans 는 한글 글리프 없음 |
| 통화 | `frontend/src/lib/format.ts` 가 유일한 판정·표기 지점 (.KS/.KQ → ₩) | #1197 — $-on-KRW 버그 계열 종결 |
| 워크플로 | verdict 배너 최상단(stale 시 억제 판단 명시) · 심각도순 액션 큐 · 증거 quick-peek · NEW+ack · 다음 행동 카피 | codex 대안(Morning Triage Board) 비교 후 병합 |

## 2. 반응형 스펙 (2026-08-25 사용자 요청 — 엄밀 정의)

### 2.1 지원 뷰포트 클래스 (실사용 하드웨어 기준)

| 클래스 | 대표 해상도 | 정책 |
|---|---|---|
| V1 분할/최소 | 1024–1279 | 사이드바 자동 접힘(아이콘), 우측 레일은 본문 아래로 스택 |
| V2 노트북 | 1280×800 · 1440×900 | 기준 설계 폭 — 목업이 이 폭 기준 |
| V3 16" MBP | 1728×1117 | V2 + 여유 간격, 컬럼 추가 없음 |
| V4 외장 27"+ | 1920–2560+ | **정보 확장** — 컬럼 추가·레일 상시 노출. 공백 확장 금지 |
| 범위 밖 | <1024 | 공식 지원 아님(터미널 도구). 단 깨지지 않을 것: 세로 스택 + 테이블 자체 가로 스크롤 |

### 2.2 원칙 (실측 결함에서 도출 — 2026-08-25 울트라와이드 스크린샷)

1. **컨테이너 규율**: 카드형 콘텐츠 영역은 `max-width` 캡(main 콘텐츠 1600px) + 중앙
   정렬. 현재 울트라와이드에서 액션 카드가 ~700px 로 늘어나고 헬스 카드가 공백만 확장하는
   것이 금지 대상 1호.
2. **그리드 캡**: 카드 그리드는 `repeat(auto-fill, minmax(340px, 1fr))` + 카드 자체
   `max-width` — 뷰포트가 넓어지면 **열이 늘지 카드가 늘지 않는다**.
3. **정보 확장 > 공백 확장**: V4 에서는 보유 테이블 컬럼 추가(#218 의 2xl sector 패턴을
   계승·확장), 우측 시스템 레일 상시 노출, 액션 테이블 근거 컬럼 폭 확대로 공간을 쓴다.
4. **상단 밴드 justify-spread 금지**: 히어로/상태 바는 고정 간격 클러스터(좌측 정렬 +
   우측 보조)로 — 4-stat 이 화면 폭에 비례해 흩어지지 않는다.
5. **테이블·차트는 스트레치 허용**: 행 기반 콘텐츠는 컨테이너 안에서 전폭 사용이 이득.
6. **breakpoint 토큰**: Tailwind 기본(sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536) +
   `3xl: 1920` 신설. 기존 2xl 조건 사용처는 U1c 에서 전수 감사해 3xl 로 승격 여부 판정.
7. **밀도 불변**: 뷰포트가 넓어져도 폰트·행높이는 불변 — fluid typography 금지.

### 2.3 기계 검증 (반응형 게이트)

- `frontend/e2e/responsive.spec.ts` (U1c 신설): 뷰포트 매트릭스 **1280×800 · 1440×900 ·
  1920×1080 · 2560×1440** × 주요 페이지(/, /decisions, /scan, /portfolio, /engine, /pipeline — ReactFlow 캔버스 포함. 상세 라우트는 U3 에서 추가)에서
  1. 가로 스크롤 금지 — root 와 **main**(실제 스크롤 컨테이너, overflow-auto) 둘 다
     `scrollWidth <= clientWidth` (테이블 자체 스크롤 컨테이너는 예외)
  2. 컨테이너 캡 — `main > div` 래퍼 폭 ≤ 1600px + 래퍼 내부 패널(section·card·table)이
     래퍼 경계를 1px 초과 이탈하지 않을 것 (자식 오버플로 스팟 체크)
  3. 전 페이지 스크린샷 아카이브 (수동 검토물)
- e2e 는 CI 게이트에 배선돼 있지 않으므로(#1118 — 별도 결정 전까지 유지) **모든 UI PR 의
  Test 단계에 "4-뷰포트 스윕 수동 실행 + 스크린샷 확인"을 의무 절차로 넣는다.**
- 반응형 회귀의 정의: 위 1·2 assert 실패, 또는 스크린샷 검토에서 "공백 확장" 재발.

## 3. 작업 단계 (1 issue = 1 PR ≤ 3 commits, 각 PR 은 7-phase Flow + codex review)

| # | 단계 | 범위 | 상태 |
|---|---|---|---|
| U1a | 토큰 셸 | zinc→Blueprint 램프, radius 4px, tabular-nums, Pretendard, 블루 액센트, dark-only 잠금(토글 제거) | **완료 #1196** |
| U1b-1 | 통화 일원화 | `lib/format.ts` 신설, $-on-KRW 버그 계열 수정 (ticker/decisions/client-table/action-items/holding-row/chart tooltip) | **완료 #1198** |
| U1b-2 | 공용 컴포넌트 리테마 | card/status-badge/metric/data-table — intent minimal-tag 맵, 밀도(행 32px), 사이드바 5그룹 재편(액티브 액센트 blue 전환 포함), StatusBadge 30-엔트리 하드코딩 맵 정리 | **완료 #1201** |
| U1c | **반응형 파운데이션** | §2 구현: 컨테이너 캡(main `max-w-[1600px]`) + `3xl` 토큰 + `responsive.spec.ts` 매트릭스. 그리드 캡은 컨테이너 캡으로 충족(액션 카드 3열이 캡 안에서 ~440px) — 카드→테이블 전환은 U2b. **U2 재구조보다 선행** | 완료 (#1203) |
| U2a | 대시보드 추출 | `page.tsx`(668줄) 섹션별 컴포넌트 추출 — 동작 보존, 시각 변화 없음 (5개 인라인 색맵 함수 격리) | 대기 |
| U2b-1 | verdict 배너 + 히어로 축소 | 배너 최상단(placement 잠금 테스트) · MarketStrip verdict 꼬리 제거 · 히어로 3xl→xl | **완료 #1207** |
| U2b-2 | 액션 테이블 + 시스템 레일 | 카드→32px 밀집 행(quick-peek 확장·확신도 micro-bar·증거 링크) · MarketContext 분해(SystemHealthRail·MacroEventsCard·RegimeShiftBanner) · 좌 2/3 + 우 1/3 그리드 | 완료 (#1209) |
| U2b-3 | 구성 스택 바 | 도넛→가로 스택 바 · coverage 접이 | 완료 (#1211) |
| U2b-4 | 델타·ack | NEW+시각 배지 · 확인(ack) 로컬 상태 · 다음 행동 카피 | 진행 중 (#1212) |
| U3 | Decisions | 리스트: 필터·날짜 그룹핑·conf micro-bar·판정일 명시 / 상세: 2컬럼 + 증거 key-value(raw JSON 폐지) + raw float 종결 | 대기 |
| U4 | 주변부 | ticker(빈 패널 접기)·scanner(중복 테이블 병합)·engine(BLOCKED 다음 행동)·pipeline(타임라인 구조화) + 빈 상태 1줄 규칙 전면 | 대기 |
| U5 | 별도 결정 | evidence matplotlib PNG→네이티브 차트 · Cmd-K · IA 통합(라우트 병합) — 각각 사용자 승인 후 착수 | 보류 |

### 단계별 공통 게이트

1. vitest 전건 green + `next build` + eslint (파일 수 212 확인 — overrides 잠금)
2. **4-뷰포트 스윕** (U1c 이후: `responsive.spec.ts` 실행 + 스크린샷 검토)
3. codex review — P1 전건 해소, P2 판단 기록
4. doc counts (`make verify-doc-counts`) + 테스트 수 변동 시 문서 5곳 동기화
5. 실화면 검증: dev 서버 스크린샷 비교 (before/after)

### 배포 포인트

- **D1**: U1c 머지 후 — mini 1차 배포 (토큰+통화+반응형 파운데이션 묶음, 프론트 재빌드 필수)
- **D2**: U2b 머지 후 — 대시보드 재구조 라이브 검증 (사용자 실경로 QA)
- **D3**: U4 머지 후 — 최종 + `/design-review` 라이브 폴리싱 패스

## 4. 리스크 / 제약

- **테스트 잠금**: vitest 1472 + e2e 59 가 구조·클래스·문자열을 잠근다 — 구조 변경 PR 은
  테스트 동반 수정이 정상이며, 잠금을 약화(광범위 mock·조건부 assert)하는 방식은 금지.
- **page.tsx / holding-row.tsx**: bespoke 대형 파일 — U2a 추출 없이 U2b 재구조 금지.
- **Recharts hex ~70개**: 차트 색은 U2b/U4 에서 `--chart-*` CSS 변수로 배선.
- **e2e 미게이트**: 스위트가 머지를 막지 못하므로(#1118) 수동 실행 의무를 이 문서가
  요구한다 — 절차 생략은 반응형 회귀의 재발 경로.
- **strings.ts**: 사용자 대면 문구는 계속 단일 출처 — 새 UI 카피(다음 행동·ack 등)도
  strings.ts 에만 추가.
