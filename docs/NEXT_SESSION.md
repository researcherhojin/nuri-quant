# Next Session Guide

이 문서는 다음 세션에서 바로 시작할 수 있도록 현재 상태와 다음 작업을 정리한다.

## 세션 2026-04-13 완료 사항

### 트레이딩
- 레짐: **RECOVERY** (75% 신뢰도), 포지션 사이징: **AGGRESSIVE**
- KakaoPay 현금 66% (₩35.9M) → 단계적 재진입 계획 수립 (오늘 밤 미장 열리면 실행)
- SOXS 500주 인버스 주문 취소 (SIEGE 3개 gate 위반)
- 삼성전자 카카오페이 1주 매도 접수 (+238%)

### 코드 (5 PR merged)
- **#249**: 매크로 데이터 품질 게이트 (날짜 필터 7일, 신뢰도 ≥0.3, classification_method)
- **#250**: 이벤트 카테고리 확장 (export_surge, demand_growth, currency_shift)
- **#251**: 이벤트 스코어 시간 가중 + 최소 3개 이벤트 regime_hint 임계값
- **#252**: react + react-dom 19.2.5
- **#253**: KOSPI/KOSDAQ 지수 수집 + Korean Agent macro_events 통합

### 핵심 발견
- yfinance가 한국 종목 펀더멘탈을 이미 지원 → KIS API 불필요
- pykrx 수급/펀더멘탈/지수 API 전부 깨짐 → yfinance fallback이 정답
- SIEGE 생태계(nutshells3) 6개 레포 분석 완료 → 아키텍처 재설계 방향 확정

## 다음 세션 작업

### P0: #248 SIEGE v2 — 자산 클래스 기반 인증 시스템

현재 SIEGE 11-gate는 포트폴리오 전체 1회 인증 + 하드코딩 임계값. 원본 SIEGE 생태계의 패턴을 반영하여 3차원 인증 모델로 재설계:

**3차원 모델**: Account(계좌 전략) × Asset Class(노출 기준) × Execution Market(실행 시장)

상세 아키텍처는 `docs/SIEGE_V2.md` 참조.

구현 순서:
1. `config/rules.yaml`에 `siege_gates` 섹션 추가 (자산 클래스 정책 + sector_mapping)
2. `certification.py` 리팩토링 (정책 읽기 + 계좌별 인증)
3. Gate 결과에 evidence 필드 추가 (OAE claim trace 패턴)
4. 테스트 (US-only / KR-only / 혼합 포트폴리오 시나리오)

### P1: 후속 Phase
- Phase 2: Safety gate lattice (CERTIFIED → 5단계 확장)
- Phase 3: safeslice 통계적 신뢰 구간 (drift_multiplier 대체)
- Phase 4: Recursive improvement (failure memory + reuse signal)
- 액션 플랜 합성 + 대시보드 (PR 7)

### 미처리 dependabot PR
- #237~#246: 7개 안전 PR (rebase 요청 완료, 순차 머지 필요)
- #238 (yfinance 1.2.1): 메이저 버전 — 별도 검증 필요
- #240 (openbb 4.7.1): 메이저 버전 — 별도 검증 필요
