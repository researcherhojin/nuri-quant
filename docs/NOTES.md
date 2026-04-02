# NOTES.md

에이전트 작업 일지. 조사 결과, 발견, 다음 세션 인수인계를 기록한다.

---

## 2026-04-02: 컨텍스트 엔지니어링 + 하네스 적용 세션

### 커밋 이력 (7건)

| # | SHA | 요약 |
|---|-----|------|
| 1 | `4ad4642` | CLAUDE.md 리팩토링 (-69줄), README.md 수정 (59 endpoints, 11 collectors, Architecture 추가) |
| 2 | `42034e4` | CI WAL checkpoint 시도 + docs/NOTES.md 생성 |
| 3 | `8b21b69` | Swing 하드코딩 5개 파라미터 → config/rules.yaml 이동 |
| 4 | `7f0b55c` | ruff I001 import sort 수정 |
| 5 | `c6341dc` | NOTES.md 세션 요약 + 인수인계 |
| 6 | `6dc2593` | Skills 3개 (deploy/verify/review) + Hooks 2개 (ruff + datetime.now() ban) |
| 7 | `6c68c14` | CI 근본 수정: WAL checkpoint → DELETE journal mode 패치 + Hook 스코프 수정 |

### 컨텍스트 구조 결정

- `.claude/rules/strategy.md` 생성 → 희석 복제본 문제로 삭제
- **최종 결정**: `CLAUDE.md`에서 `@docs/STRATEGY.md` 직접 import (단일 소스)
- 이유: STRATEGY.md의 실제 사례(커밋 SHA, 구체적 함수명)가 규칙의 강제력을 높임. 축약하면 "조심하세요" 수준으로 희석됨

### 하네스 4구성 요소 완성

| 구성 요소 | Before | After |
|-----------|--------|-------|
| **Context Files** | CLAUDE.md만 (STRATEGY.md 미연결) | + `@docs/STRATEGY.md` import + `docs/NOTES.md` |
| **MCP Servers** | `.mcp.json` SQLite 1개 | 변경 없음 (이미 적절) |
| **Skill Files** | 범용 29개, 프로젝트 전용 0개 | + `nuri-deploy`, `nuri-verify`, `nuri-review` |
| **Hooks** | 없음 | ruff check + `datetime.now()` ban (`nuri/*.py` 스코프) |

### 코드 대조 검증 결과

**수정한 오류 6건:**

| 주장 | 실제 | 파일 |
|------|------|------|
| "21 collectors inheriting BaseCollector" | 19 inherit + 2 standalone (filings.py, external.py) | CLAUDE.md |
| "17 cron jobs" | 18 (db_maintenance 누락) | CLAUDE.md |
| "58 endpoints" | 59 (router 56 + app 3) | README.md, STRATEGY.md |
| Collect phase: 5 modules | 11 collectors in `make collect` | README.md |
| Validate phase: "memory" | Not a validation module | README.md |
| Swing 5개 파라미터 하드코딩 | config/rules.yaml로 이동 | swing/rules.py |

**검증 통과 (34개 버전 배지 + 숫자 12건 전수 일치):**

- 15 signals, 10 agents, 27 tables, 2928 tests, 5 charts, 15 pages
- Swing -5%, Discord + Telegram, 34 README 버전 배지

### CI 수정 과정

| 시도 | 결과 |
|------|------|
| WAL checkpoint (TRUNCATE) | 1회 성공 → 다음 실패 (불안정) |
| DELETE journal mode 패치 | **안정** — `get_connection` 자체를 패치하여 근본 해결 |

근본 원인: `get_connection()`이 매 연결마다 WAL을 재설정 → checkpoint 후에도 새 연결이 WAL 재활성화 → CI tmpfs에서 데이터 불가시. `_force_delete_journal()`로 monkeypatch하여 테스트 DB는 DELETE 모드 강제.

### Hook 검증

- ruff check: pipe-test 통과, PostToolUse Write|Edit에서 *.py 자동 실행
- datetime.now() ban: pipe-test 통과 → **false positive 발견** (테스트 파일 감지) → 스코프를 `*/nuri/*.py`로 수정하여 소스 코드만 감시

### 논의한 개념

- Context Engineering vs Harness Engineering (정의, 구분)
- Advisory (~80%) vs Deterministic (100%) 강제력 계층
- Structured Note-taking (Tasks / Memory / NOTES.md / Scratchpad)
- 새 프로젝트 셋업 전략 (STRATEGY.md 먼저 → CLAUDE.md 최소 → 하네스 템플릿 → 증거 축적)

### 다음 세션에서 할 작업

- [ ] Hooks 동작 확인 — 다음 세션에서 `/hooks`로 2개 hook 활성 상태 확인
- [ ] STRATEGY.md §7 미완성 항목 진행도 반영 (#42 투자 규칙 UI, #17 Alpaca, #25 브로커 API)
- [ ] Swing stop_loss 위치 검토 — 현재 `take_profit.swing.stop_loss`에 있음, `stop_loss.per_stock_swing`이 의미적으로 정확할 수 있음
- [ ] MCP 확장 검토 — GitHub Issues MCP 연결로 이슈 조회/생성 자동화
- [ ] Hooks 확장 검토 — PreToolUse Bash hook으로 `git push --force` 차단
- [ ] CI Node.js 20 경고 — actions 최신 버전 출시 시 업데이트 (현재 조치 불필요)
- [ ] emelmujiro 프로젝트에 동일 하네스 구조 적용
