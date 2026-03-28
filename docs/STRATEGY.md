# Nuri-Quant 전략 정의서

## 핵심 문제

현재 Nuri-Quant은 **결과만 보여주고 과정이 보이지 않습니다.**

```
사용자가 보는 것:  "SELL BULL (conf 90)"
사용자가 봐야 하는 것:
  1. 어떤 데이터를 수집했는지 (15 collectors + 6 sites)
  2. 시그널 검증 결과 (3,400+ 트레이드 중 이 시그널의 승률/PF)
  3. 7개 에이전트가 각각 왜 그 판단을 했는지
  4. SIEGE 10-condition 중 어떤 것이 통과/실패했는지
  5. 그래서 최종 추천이 어떻게 나왔는지
```

**과정이 투명하지 않으면 추천을 신뢰할 수 없습니다.**

## 설계 원칙

1. **과정 > 결과** — 각 단계의 입력→처리→출력을 시각화
2. **Why 기반** — "SELL"이 아니라 "왜 SELL인지" 보여주기
3. **인터랙티브** — 클릭하면 상세 데이터 드릴다운
4. **한 화면 요약** — 메인 대시보드에서 전체 상태 한눈에

## 현재 상태 분석

### 백엔드 (50 API endpoints) — ✅ 충분
- 15 collectors, 7 agents, SIEGE engine, certification, external data
- 대부분의 데이터 파이프라인은 구현 완료

### 프론트엔드 (14 pages) — ❌ 부족
| 문제 | 상세 |
|------|------|
| Nav에 5개 페이지 누락 | targets, advisor, evidence, login, ticker |
| 과정 시각화 없음 | 에이전트 판단 과정, SIEGE gate 과정, 백테스트 과정 |
| 메인 대시보드 정보 부족 | 포트폴리오 평가액/손익, SIEGE 인증, 리밸런스 요약 없음 |
| API 7개 프론트 미연결 | external, certify, regime, macro, ticker 등 |

### README — ❌ 설명 부족
| 문제 | 상세 |
|------|------|
| 기능 나열만 | "무엇을 하는지"는 있지만 "왜, 어떻게 쓰는지" 없음 |
| 완료 로드맵 불필요 | 이슈로 이동하면 됨 |
| SIEGE 레퍼런스 불명확 | 원본과의 관계/차이 설명 부족 |

## 작업 정의

### Issue #8: README 리팩토링 — 설명 중심
- 각 기능에 "이것이 무엇이고, 어떻게 사용하는지" 추가
- Completed Roadmap 섹션 제거 (이슈로 이동)
- SIEGE 레퍼런스: 원본 링크 + 우리의 적용 방식 명시
- 오픈소스 레퍼런스 출처 명시 (O'Neil, Minervini 등)

### Issue #9: Nav + 메인 대시보드 강화
- Nav에 누락 페이지 추가 (grouped navigation)
- 메인 대시보드에 포트폴리오 요약 + SIEGE 인증 + 리밸런스 요약
- Nuri-Quant 로고 클릭 → Overview 이동

### Issue #10: 파이프라인 과정 시각화
- 7-Agent 합의 과정 (에이전트별 판단 근거 + 투표 시각화)
- SIEGE 10-Condition Gate 시각화 (각 조건 pass/fail 이유)
- 시그널 백테스트 결과 시각화 (승률/PF 차트)

### Issue #11: 미연결 API 프론트 연동
- /api/external → 외부 데이터 조회 UI
- /api/certify (신규) → SIEGE 인증 API + 대시보드 배지
- /api/ticker/{symbol} → 종목 상세 페이지 개선

## 오픈소스 레퍼런스

| 프로젝트 | 적용 부분 | 참고 |
|----------|----------|------|
| **O'Neil CAN SLIM** | 손절 -7%, 익절 +20%/+40% | 투자 규칙 |
| **Minervini SEPA** | 트레일링 -15%, 8주 규칙 | 투자 규칙 |
| **SIEGE** (nutshells3) | 10-condition gate, certification | 아키텍처 |
| **Riskfolio-Lib** | MVO/Risk Parity 최적화 | 리밸런싱 |
| **VectorBT** | 벡터 기반 백테스트 | 성과 검증 |
| **처분효과 연구** (Shefrin & Statman 1985) | 수익 종목 너무 일찍 파는 편향 경고 | 투자 행동 |

## 작업 순서

```
1. README 리팩토링 (설명 중심, 완료 로드맵 제거)
2. GitHub Issues 생성 (#8~#11)
3. Nav + 메인 대시보드 강화 (빠른 수정)
4. 미연결 API 프론트 연동
5. 파이프라인 과정 시각화 (큰 작업)
```
