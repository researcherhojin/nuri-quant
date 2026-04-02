# NOTES.md

에이전트 작업 일지. 조사 결과, 발견, 다음 세션 인수인계를 기록한다.

---

## 2026-04-02: 컨텍스트 엔지니어링 + 하네스 적용 세션

### 커밋 이력

| SHA | 요약 |
|-----|------|
| `4ad4642` | CLAUDE.md 리팩토링 (-69줄), README.md 수정 (59 endpoints, 11 collectors, Architecture 추가) |
| `42034e4` | CI flaky test 수정 (WAL checkpoint for tmpfs), docs/NOTES.md 생성 |
| `8b21b69` | Swing 하드코딩 5개 파라미터 → config/rules.yaml 이동 |
| `7f0b55c` | ruff I001 import sort 수정 |

### 컨텍스트 구조 결정

- `.claude/rules/strategy.md` 생성 → 희석 복제본 문제로 삭제
- **최종 결정**: `CLAUDE.md`에서 `@docs/STRATEGY.md` 직접 import (단일 소스)
- 이유: STRATEGY.md의 실제 사례(커밋 SHA, 구체적 함수명)가 규칙의 강제력을 높임. 축약하면 "조심하세요" 수준으로 희석됨

### 코드 대조 검증 결과

**수정한 오류:**

| 주장 | 실제 | 파일 |
|------|------|------|
| "21 data collectors inheriting BaseCollector" | 19 inherit + 2 standalone (filings.py, external.py) | CLAUDE.md |
| "17 cron jobs" | 18 (db_maintenance 누락) | CLAUDE.md |
| "58 endpoints" | 59 (router 56 + app 3) | README.md, STRATEGY.md |
| Collect phase: 5 modules | 11 collectors in `make collect` | README.md |
| Validate phase: "memory" | Not a validation module | README.md |
| Swing 5개 파라미터 하드코딩 | config/rules.yaml로 이동 | swing/rules.py |

**검증 통과 (34개 버전 배지 + 숫자 12건 전수 일치):**

- 15 signals (10 price + 3 macro + 2 data) — SIGNAL_DEFINITIONS 레지스트리
- 10 agents — DEFAULT_WEIGHTS, risk 20% veto, korean HOLD for US, retail 0%
- 27 tables (v11 migrations) — _SCHEMA + _MIGRATIONS 카운트
- 2928 backend tests / 32 files
- 5 Plotly evidence charts, 15 frontend pages
- Swing stop-loss -5% — config/rules.yaml로 이동 완료
- Discord + Telegram — 둘 다 구현 확인
- 34개 README 버전 배지 — uv.lock + package.json 전수 일치

### CI 수정

- `_wal_checkpoint(TRUNCATE)` 추가 — CI Ubuntu tmpfs에서 SQLite WAL 데이터 가시성 문제
- 3개 gate 테스트 (populated_db_passes_basics, regime_gate_with_spy, estimates_accumulation_fresh)
- 로컬 통과 + CI 실패 → WAL checkpoint 후 CI 통과 확인

### 완료된 작업

- [x] Swing STOP_LOSS_PCT를 config/rules.yaml로 이동 (하드코딩 → config)
- [x] STRATEGY.md §7 endpoint 수 58 → 59 수정
- [x] CI flaky test 수정

### 다음 세션에서 할 작업

- [ ] CI Node.js 20 경고 — 현재 조치 불필요 (actions 최신 버전, FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 적용). action 유지보수자가 Node.js 24 지원 시 업데이트
- [ ] 컨텍스트 엔지니어링 4구성 요소 정리 — Context Files, MCP Servers, Skill Files, Mechanical Enforcement (세션 중 논의했으나 미착수)
- [ ] STRATEGY.md §7 미완성 항목 진행도 반영 (#42 투자 규칙 UI, #17 Alpaca 실전, #25 브로커 API)
