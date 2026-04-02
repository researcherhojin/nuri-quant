# NOTES.md

에이전트 작업 일지. 조사 결과, 발견, 다음 세션 인수인계를 기록한다.

---

## 2026-04-02: CLAUDE.md + README.md 코드 대조 검증

### 발견된 숫자 오류 (수정 완료)

| 주장 | 실제 | 파일 |
|------|------|------|
| "21 data collectors inheriting BaseCollector" | 19 inherit + 2 standalone (filings.py, external.py) | CLAUDE.md |
| "17 cron jobs" | 18 (db_maintenance 누락) | CLAUDE.md |
| "58 endpoints" | 59 (router 56 + app 3) | README.md |
| Collect phase: 5 modules listed | 11 collectors run in `make collect` | README.md |
| Validate phase: "memory" | Not a validation module. Actual: signal_backtest, superinvestor_backtest, analyst_backtest, scorecard | README.md |

### 검증 통과 (변경 불필요)

- 15 signals (10 price + 3 macro + 2 data) — SIGNAL_DEFINITIONS 레지스트리 확인
- 10 agents — DEFAULT_WEIGHTS 확인, risk 20% veto, korean HOLD for US, retail 0%
- 27 tables (v11 migrations) — _SCHEMA + _MIGRATIONS 카운트
- 2928 backend tests / 32 files — test_*.py 파일 카운트
- 5 Plotly evidence charts — evidence_charts.py 함수 5개
- 15 frontend pages — page.tsx 15개
- Swing stop-loss -5% — nuri/trading/swing/rules.py:30 STOP_LOSS_PCT = -5.0
- Discord + Telegram — 둘 다 구현 확인 (alerts/telegram.py)
- 34개 README 버전 배지 — uv.lock + package.json 전수 대조 일치

### 컨텍스트 구조 결정

- `.claude/rules/strategy.md` 생성 → 희석 복제본 문제로 삭제
- 최종 결정: `CLAUDE.md`에서 `@docs/STRATEGY.md` 직접 import (단일 소스)
- 이유: STRATEGY.md의 실제 사례(커밋 SHA, 구체적 함수명)가 규칙의 강제력을 높임. 축약하면 "조심하세요" 수준으로 희석됨

### 구조적 발견

- `filings.py`, `external.py`는 BaseCollector를 상속하지 않는 standalone 모듈
- `nuri/trading/engine/memory --snapshot`은 `make validate`의 마지막 단계로 실행되지만, validation 모듈이 아닌 engine 모듈
- Swing stop-loss -5%는 `config/rules.yaml`이 아닌 `nuri/trading/swing/rules.py`에 하드코딩 — 설계 원칙 "config-driven rules" 위반 가능성

### 다음 작업

- [ ] Swing STOP_LOSS_PCT를 config/rules.yaml로 이동 검토 (하드코딩 → config)
- [ ] STRATEGY.md §7 "현재 상태" 섹션 업데이트 (미완성 항목 진행도 반영)
