<!-- 이 파일은 다음 세션 시작 시 호진님이 Claude Code에 붙여넣는 프롬프트. -->

⏺ docs/STRATEGY.md, docs/NEXT_SESSION.md, docs/SIEGE_V2.md, CLAUDE.md 모두 읽고 시작합니다.

  ⚠ 시작 전 필수 — 너가 따라야 할 시스템 선언:

  1. 역할 분리 (트리아지)
     - What/방향: 호진님 결정 (특히 UX/우선순위)
     - How/구현: 너 (Claude)
     - Gate/통과: 시스템 (lint, CI, codecov, gate)

  2. GAN 워크플로우
     PM → Generator → Discriminator → 통과 시 PR
     - PM: ASCII 와이어프레임 → 호진님 명시 승인 (UX 작업 시 절대 건너뛰지 않음)
     - Generator: 승인된 와이어프레임대로 1회 구현
     - Discriminator: lint + tsc + pytest + Playwright probe + 시각 확인
     - 최대 7 round, 2연속 clean이면 조기 종료

  3. 직전 세션 학습 (2026-04-13 세션, 10 PR merged)
     - #249 매크로 데이터 품질 게이트 (날짜 필터 7일, 신뢰도 ≥0.3, classification_method)
     - #250 이벤트 카테고리 확장 (export_surge, demand_growth, currency_shift)
     - #251 이벤트 스코어 시간 가중 + 최소 3개 이벤트 regime_hint 임계값
     - #252 react + react-dom 19.2.5
     - #253 KOSPI/KOSDAQ 지수 수집 + Korean Agent macro_events 통합
     - #254 SIEGE v2 아키텍처 문서 + README Mermaid 리팩토링
     - 핵심 발견: yfinance 한국 펀더멘탈 이미 지원, pykrx 수급 API 깨짐
     - SIEGE 생태계(nutshells3) 6개 레포 분석 → 3차원 인증 모델 결정
     - 트레이딩: RECOVERY 레짐, AGGRESSIVE 포지션. Brokerage Alpha 현금 66% 재진입 계획
     - SOXS 500주 취소, 삼성전자 Brokerage Alpha 1주 매도 (+238%)

  4. 핵심 원칙 (STRATEGY.md)
     - §2.1 증거 우선
     - §2.2 기계적 실행 (rules in YAML, code에 분기 금지)
     - §2.3 느슨한 결합 (페이즈 간 DB/CSV만)
     - §2.4 관찰 가능성

  5. 할루시네이션 방어
     1) 모르면 읽는다
     2) 2번 실패하면 접근을 바꾼다
     3) 수정 후 실행한다
     4) 스코프를 지킨다 — 새 발견은 별도 이슈
     5) 문자열도 grep
     6) 시스템이 차단 (린터 > 문서)
     7) 새 코드 = 테스트 동시 작성
     8) PR 순차 머지

  6. PR 디시플린
     - 이슈 1 = PR 1, 커밋 ≤ 3 (UX iteration 누적은 예외)
     - PR commit message에 ticker + PnL 절대 금지
     - main 외 stale 브랜치 즉시 정리

  7. 미완료 작업 (이번 세션에서 처리)
     - #254 SIEGE v2 문서 PR 머지
     - dependabot PR 7개 순차 머지 (#237~#246)
     - #248 SIEGE v2 Phase 1 구현 — Gate 정책 YAML 외부화 + certification.py 리팩토링
       (docs/SIEGE_V2.md §4의 config/rules.yaml 스키마 → certification.py가 읽어서 적용)
     - #238 yfinance 1.2.1 메이저 업데이트 검증
     - #240 openbb 4.7.1 메이저 업데이트 검증
     - 미장 재진입 계획 실행 (RECOVERY + AGGRESSIVE 기반)

  위 시스템 선언 후, 다음 작업 중 어느 것을 할지 호진님께 물어봐:

  [1] #254 머지 + dependabot PR 정리 (~10분)
      SIEGE v2 문서 PR CI 확인 후 머지. dependabot 7개 순차 머지.

  [2] #248 SIEGE v2 Phase 1 구현 (~3h)
      config/rules.yaml에 siege_gates 섹션 추가.
      certification.py 리팩토링: 자산 클래스 × 계좌 기반 인증.
      Gate evidence 필드 추가 (OAE claim trace 패턴).
      PM phase: docs/SIEGE_V2.md §4 스키마 리뷰 → 호진님 승인 → 구현.

  [3] 트레이딩 준비 (장 시작 전)
      make collect → make full-scan → 레짐 확인.
      Brokerage Alpha 현금 66% → 35% 재진입 구체 계획 (3회 분할).
      오늘 밤 미장 기준 NVDA/AMD 추매 타겟 + 손절가.

  [4] SIEGE v2 Phase 2 — Safety Lattice (~2h)
      CERTIFIED → 5단계 확장 (CERTIFIED/GUARDED/REVIEW_REQUIRED/BLOCKED/REJECTED).
      Phase 1 완료 후 진행.

  [5] SIEGE v2 Phase 3 — safeslice 통계적 신뢰 구간 (~3h)
      drift_multiplier → Wilson CI + witness cliff.
      regime별 승률의 정적 임계값 → 통계적 인증서.
      Phase 2 완료 후 진행.

  [6] 액션 플랜 합성 + 대시보드 위젯 (~4h)
      "오늘의 액션 플랜" — 계좌별 × 자산 클래스별 조치 리스트.
      PM wireframe → 호진님 승인 → 구현.
      Phase 1 + 매크로 파이프라인 완료 후 진행.

  원칙: Phase 순서 준수, 새 발견은 별도 이슈로 분리.
