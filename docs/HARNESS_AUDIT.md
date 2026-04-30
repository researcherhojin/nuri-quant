# Harness Audit — 2026-04-30

**Mode**: read-only audit (`.claude/` 변경 없음)
**Branch**: `chore/harness-bootstrap`
**Source-of-truth**: CLAUDE.md "Harness Engineering 7 Principles" (STRATEGY §5.8) · 4-layer architecture (§5.10) · Escalation Ladder (§2.6) · Privacy scanner (§4.4.1) · Alpha vs Portfolio axis · Auto trading deferred (§7.1)
**Auditor**: harness:harness (revfactory v1.2.0) under read-only constraint

---

## 1. Executive Summary

1. **현존 자산은 대부분 Pattern 3(Expert Pool) + 4(Producer-Reviewer)에 정확히 매핑되며 도메인 적합성 양호**. Pipeline·Fan-out·Supervisor·Hierarchical은 부재 또는 불완전.
2. **Critical bug**: `.claude/skills/` 5개 디렉토리 중 **3개(`nuri-deploy`/`nuri-verify`/`nuri-review`)는 `SKILL.md`가 아닌 `README.md`로만 존재** → 로더가 인식 못 함. `/reload-plugins` 출력 `0 skills` 가 이를 confirm. 컨텐츠는 양호하므로 파일명 1글자 변경으로 복구 가능.
3. **오케스트레이터 부재**: 5개 task-specific skill을 엮는 메타 스킬 없음. STRATEGY §2.7 7-phase Flow는 문서로만 존재 — `nuri-verify → nuri-review → nuri-deploy` 자동 체이닝이 안 됨.
4. **하네스 7원칙 중 5/7은 여전히 doc-only** — hooks는 §5.8-#5(numbers, `make verify-doc-counts`)와 #6(mechanical: sqlite3/datetime/ruff/git) 만 강제. #1·#2·#3·#4·#7은 인간 규율.
5. **진화 메커니즘은 PR + STRATEGY 편집(인간 mediated)으로 이미 작동 중** — `/harness:evolve` 자동 루프는 §7.1(Auto trading deferred)의 "사용자 검증 후 emit" 원칙과 철학적 충돌 가능. 도입 보류 권장.
6. **프로젝트 전체 41개 .md 중 Claude Code 공식 spec 위반은 위 #2의 3건뿐** (`README.md` → `SKILL.md`). 나머지는 spec-compliant 또는 project-convention. §9 참조.

---

## 2. Phase 0 — 기존 자산 × revfactory 6 패턴 매핑

revfactory 6 패턴 정의 (`references/agent-design-patterns.md`):
1. **Pipeline** — 순차 의존
2. **Fan-out/Fan-in** — 병렬 → 통합
3. **Expert Pool** — 상황별 선택 호출
4. **Producer-Reviewer** — 생성 후 검증
5. **Supervisor** — 동적 분배
6. **Hierarchical Delegation** — 재귀 위임

### 2.1 매핑 표

| 자산 | 종류 | 파일 상태 | revfactory 패턴 | 매핑 근거 | 비고 |
|---|---|---|---|---|---|
| `nuri-codex-second-opinion` | Agent | OK | **#4 Producer-Reviewer** | "main session 결정 → Codex 독립 verdict" — `tools: Bash/Read/Grep/Glob` 만으로 read-only review | description에 후속 키워드 부족 |
| `nuri-thesis-batch` | Agent | OK | **#2 Fan-out/Fan-in** | M7 sweep 등 N ticker 병렬 thesis 생성 후 표 1개로 reduce | max 3 concurrent rate-limit 명시 — 7원칙 #7 준수 |
| `nuri-harness-debug` | Skill | OK (SKILL.md) | **#3 Expert Pool** | 6 실패 패턴 중 해당 케이스만 호출되는 분기형 진단 | STRATEGY §5.8 7원칙을 본문에 인용 — single source of truth |
| `nuri-siege-audit` | Skill | OK (SKILL.md) + `disable-model-invocation: true` | **#3 Expert Pool** (수동 호출 전용) | 60-month rerun 절차 — model 자동 trigger 차단 후 인간이 직접 호출 | E4-0b closed route 보존용 |
| `nuri-deploy` | Skill | **BROKEN** (`README.md` only) | (의도) **#1 Pipeline** | pre-deploy → deploy → post-verify → rollback 순차 | YAML frontmatter는 valid, 파일명만 틀림 |
| `nuri-verify` | Skill | **BROKEN** (`README.md` only) | (의도) **#1 Pipeline** | quick check → full check → manual checklist | 컨텐츠는 STRATEGY §5.8과 정합 |
| `nuri-review` | Skill | **BROKEN** (`README.md` only) | (의도) **#1 Pipeline** | architecture rules → harness rules → trading-specific → quality | "Trading-specific" 섹션이 §3 Alpha vs Portfolio 룰을 직접 인용 |
| `thesis` | Slash command | OK | (보조) #3 Expert Pool entry | `make thesis` CLI 래퍼 | |
| `buy-candidates` | Slash command | OK | (보조) #3 Expert Pool entry | `make buy-candidates` CLI 래퍼 | VIX > 30 차단 명시 — Escalation Ladder Hard veto 인용 |
| `earnings-preview` | Slash command | OK | (보조) #3 Expert Pool entry | `make earnings-preview` CLI 래퍼 | yfinance options edge case 한계 inline |
| `settings.json` PreToolUse hook (sqlite3) | Hook | OK | (Layer 3) | `nuri/*.py`에서 `import sqlite3` 차단 (`db.py` 제외) | STRATEGY §1 invariants 강제 |
| `settings.json` PreToolUse hook (destructive git) | Hook | OK | (Layer 3) | force-push / hard-reset / clean -f 차단 | STRATEGY §5.8-#6 |
| `settings.json` PostToolUse hook (datetime.now) | Hook | OK | (Layer 3) | `nuri/*.py`에 `datetime.now()` 검출 시 block (exit 1) | `kst_now()` 강제 |
| `settings.json` PostToolUse hook (ruff) | Hook | OK | (Layer 3, advisory) | `.py` 파일 저장 시 ruff check 출력 | block 아님, surface only |

### 2.2 패턴 점유율

| Pattern | 자산 수 | 비고 |
|---|---:|---|
| #1 Pipeline | 0 valid (3 broken) | SKILL.md 복구 시 3 |
| #2 Fan-out/Fan-in | 1 | thesis-batch |
| #3 Expert Pool | 2 + 3 commands | harness-debug, siege-audit + 3 slash entry |
| #4 Producer-Reviewer | 1 | codex-second-opinion |
| #5 Supervisor | 0 | 부재 |
| #6 Hierarchical Delegation | 0 | 부재 |

---

## 3. 갭 분석 — 누락 패턴 및 도메인 적합성

### 3.1 #1 Pipeline — 사실상 부재 (BROKEN)

3개 의도된 pipeline skill이 로더에 안 잡히는 상태. `/reload-plugins` 출력 `Reloaded: 1 plugin · 0 skills · 7 agents · 0 hooks` 가 직접 증거. **하네스의 가장 큰 단일 갭**.

**도메인 적합성**: 매우 높음 — Collect→Analyze→Consensus→Certify→Track의 canonical pipeline 자체가 우리 시스템 구조. STRATEGY §2.7 Flow도 7-phase pipeline.

### 3.2 #5 Supervisor — 부재

Supervisor 패턴은 "런타임 상태에 따라 동적으로 작업 분배". 우리 도메인에는:
- `make full-scan` 8-phase가 supervisor-like하지만 `Makefile`이 정적 dispatch (런타임 분기 X).
- Mac mini scheduler `launchd com.nuri-quant.autopull`은 감독자라기보다 단순 cron.

**도메인 적합성**: 중간. SIEGE 10-gate cascade가 supervisor 후보 — gate별 fail에 따라 다른 remediation skill 호출 가능. 그러나 현재 SIEGE는 `make certify`/`make remediate` 2-binary로 충분. 추가 복잡도 ROI 낮음.

### 3.3 #6 Hierarchical Delegation — 부재

3-deep tree (총괄 → 팀장 → 실무자). **도메인 적합성: 낮음**. 우리는 단일 사용자 + 단일 LLM 세션 모델. 하네스 가이드 자체도 "2단계 이내 권장 / 팀 중첩 불가" 명시. **도입 권장 안 함**.

### 3.4 #2 Fan-out/Fan-in — 1개만 존재, 확장 여지 있음

현재 `nuri-thesis-batch` 1개만. 후보 확장 영역:
- `nuri-collector-batch` — 21 collectors 중 휴면/오류 상태 일괄 진단 (현재 `make pre-collect-check` 정적)
- `nuri-portfolio-rebalance-fan` — 계좌별(Main/Sub/Toss/Pension) rebalance 병렬 산출 후 통합 표

다만 둘 다 spec/issue가 아직 없으므로 P2.

### 3.5 #4 Producer-Reviewer — 1개 존재, 자동화 여지 있음

`nuri-codex-second-opinion`은 **수동 호출**형. 자동 발화 패턴 부재:
- 신규 collector PR 열릴 때 자동 codex review 트리거 없음
- LLM consult Round 1 결과가 disagreement일 때 Round 2 synthesis 자동 진입 없음 (사용자가 직접 발화 필요)

이 자동화가 §5.8-#3 "사용자 워크플로 검증" 강화에 기여 가능.

### 3.6 STRATEGY §5.8 7원칙 enforcement gap (cross-cutting)

| 원칙 | 강제 여부 | 갭 | 도메인 적합 강제 후보 |
|---|---|---|---|
| #1 모르면 읽는다 | doc only | grep-before-call 측정 안 됨 | 강제 어려움 (LLM internals) |
| #2 2번 실패 접근 변경 | doc only | 3번째 동일 시도 감지 없음 | 세션 transcript 분석 — 비용 큼 |
| #3 사용자 워크플로 검증 | doc only | "make X 실행 로그" PR body 강제 안 됨 | PR template + GH Action regex check |
| #4 스코프 (1 issue = 1 PR ≤ 3 commits) | doc only | commit count CI gate 없음 | `git rev-list --count base..HEAD > 3` fail |
| #5 숫자 grep | ✅ `make verify-doc-counts` CI gate | OK | — |
| #6 시스템이 차단 | ✅ hooks 4개 + CI 4개 | OK | — |
| #7 외부 API 측정 | doc only | 신규 collector concurrency probe 없음 | `nuri-collector-onboard` 스킬 + `make probe-concurrency` |

**Privacy scanner 추가 갭**: §4.4.1 `scripts/check_privacy_leak.py`는 CI + `pre_push_check.sh`만. PreToolUse hook(Write/Edit)에는 부재 → 사용자가 즉시 typing 시점에 알 수 없음. 추가 시 defense-in-depth.

---

## 4. 오케스트레이터 부재 평가

### 4.1 부재 사실 확인

`.claude/skills/` 5개 모두 task-specific (`deploy`/`verify`/`review`/`harness-debug`/`siege-audit`). **메타 스킬 없음**. `harness:harness` (revfactory) 자체가 임시 오케스트레이터 역할 가능하나 외부 플러그인 + 본 프로젝트 컨벤션 모름.

### 4.2 부재의 비용

- STRATEGY §2.7 7-phase Flow가 문서뿐 — Build → Review → Test → Ship 자동 chaining 안 됨
- 사용자가 매번 `/verify` → `/review` → `/deploy`를 수동 발화해야 함 (실제로는 `make` 타겟으로 우회)
- Phase gate 실패 시 "이전 단계 회귀" 메커니즘 부재 (인간 판단)

### 4.3 부재의 이득

- 단일 사용자 + 단일 세션 모델에서 오케스트레이터는 token 비용 추가
- `Makefile` 자체가 deterministic orchestrator 역할 — `make full-scan`이 8-phase 강제
- 우리 프로젝트는 STRATEGY §7.1 Auto trading deferred + §5.8 인간 in-the-loop 원칙 — 자동 chaining이 오히려 검증 약화 가능

### 4.4 결론

**중간 우선순위 (P1)** — `nuri-flow`라는 minimal orchestrator skill 1개 도입 가치 있음. 단, 하이브리드(Skill 추천만, 자동 chain X) 형태로. 자동 chain은 `Makefile`에 위임. 자세한 안은 §6 P1.

---

## 5. 진화 메커니즘 평가

### 5.1 revfactory 권장 자체-진화 루프

`harness:harness` Phase 7 — 매 실행 후 피드백 수집 → 에이전트/스킬 자동 갱신 → 변경 이력 자동 기록. `/harness:evolve` 같은 별도 명령으로 분리 가능.

### 5.2 우리 현존 진화 메커니즘

이미 작동 중 (인간 mediated):

| 트리거 | 결과물 | 빈도 |
|---|---|---|
| 같은 fix-pattern 반복 (`df.copy()` 3 세션) | Gotcha-Test Pair (§5.3.1) cite + lock-test | 발견 시마다 |
| Mock-only ship 함정 3회 | §5.8 #3 강화 + #7 신설 (2026-04-14) | 분기 1회 수준 |
| 세션 PR retrospective | `docs/STRATEGY.md` 갱신 + memory 추가 | 대형 incident마다 |
| Frontier alignment | §5.10 OpenAI 2026-02 + Anthropic Best Practices 반영 | 외부 업데이트 시 |

### 5.3 자동화의 위험

1. **§7.1 Auto trading deferred 정신과 충돌**: "추천만 emit, 사용자가 검증 후 실행"의 design philosophy. 하네스 자체가 자가-진화하면 사용자 검증 단계 우회.
2. **Privacy 위험**: 자동 변경 이력에 portfolio/금액 leak 가능 (§4.4.1).
3. **Drift 위험**: STRATEGY 본문(canonical)과 자동 갱신 .claude/ 사이 divergence. CLAUDE.md "Precedence on conflict: repo truth > NEXT_SESSION > auto-memory" 룰의 reverse engineering 어려워짐.

### 5.4 결론

**도입 보류 권장 (P2 이하)**. 현재 인간-mediated 진화가 양호하게 작동하며, 자동화 ROI가 위험을 정당화하지 못함. 단, **변경 이력 표 자체는 채택 가능** — `docs/HARNESS.md`에 손으로 maintain하는 형태로.

---

## 6. 제안 (우선순위별)

각 제안은 우리 룰(7원칙 / 4-layer / Escalation Ladder / Privacy / Alpha-Portfolio axis / Auto trading deferred) 충돌 여부 명시.

### P0 — 즉시 수정 (Critical bug)

#### P0-1. 3개 broken skill 파일명 복구

**Action**: `nuri-deploy/README.md` → `SKILL.md` 등 3건 rename.
**근거**: `/reload-plugins` `0 skills` 실측. 컨텐츠 자체는 valid frontmatter + 본문 양호.
**룰 충돌**: 없음. STRATEGY §5.10 4-layer L2 Skills 회복.
**리스크**: 낮음 — git mv로 history 보존.
**별도 PR**: `fix(harness): rename README.md → SKILL.md for 3 skills (loader discovery)` — 1 commit.

### P1 — 다음 세션 검토 (High value, fits architecture)

#### P1-1. `nuri-flow` orchestrator skill 신설 (recommend-only, no auto-chain)

**Action**: `.claude/skills/nuri-flow/SKILL.md` 생성. STRATEGY §2.7 7-phase Flow를 LLM이 인식하도록 조각화하고, 현재 phase 추정 후 다음 phase의 적절한 skill/Make target 추천. **자동 호출 X — 추천만**.
**근거**: §4 결론 — 사용자가 7-phase를 수동 추적하는 인지 부담 감소.
**룰 충돌**: 없음 — recommend-only이므로 §7.1 Auto trading deferred 정신 보존.
**의존**: P0-1 선행 (다른 skill을 추천하려면 그것들이 discoverable해야 함).
**리스크**: skill description trigger 충돌 (`harness-debug`와 키워드 겹침 가능) — Phase 6-4 트리거 검증 필수.

#### P1-2. Privacy scanner를 PreToolUse hook으로 승격 (defense-in-depth)

**Action**: `settings.json` PreToolUse `Edit|Write` hook 추가 — `scripts/check_privacy_leak.py --stdin` 호출, 위반 시 `decision: block`.
**근거**: 현재 CI + `pre_push_check.sh`만 — 사용자가 typing 시점에 즉시 피드백 못 받음. `df.copy()` 재발 사례처럼 "감지가 늦으면 다시 같은 실수"가 §5.8 #2 위반.
**룰 충돌**: 없음 — §4.4.1은 "CI에서 enforced"라 기술하지만 hook 추가는 strictly more enforcement (defense in depth). CI는 authoritative로 유지.
**리스크**: hook timeout (5s 기본) — `check_privacy_leak.py`가 stdin mode 필요할 수 있음. 별도 PR로 스크립트 보강 선행.

#### P1-3. STRATEGY §5.8 #4 (commit count gate) CI enforcement

**Action**: `.github/workflows/main-ci-cd.yml`에 `pr-discipline` job 추가 — `git rev-list --count base..HEAD > 3`이면 fail. Escape hatch: `[scope-expand-approved]` PR label.
**근거**: 7원칙 중 doc-only 5개 중 가장 자주 위반 + mechanical 가능. 최근 #16 사례 (5건 + frontend까지 한 PR).
**룰 충돌**: 없음.
**리스크**: 정당한 multi-commit 작업(refactor 시리즈 등)에 false-positive — label escape hatch로 완화.

### P2 — 백로그 (조건부 가치)

#### P2-1. `nuri-codex-second-opinion` 자동 발화 트리거 (Producer-Reviewer 강화)

**Action**: PR open 시 GitHub Action으로 codex review 자동 invoke (현재 사람이 `/codex review` 발화).
**근거**: §3.5 자동화 여지.
**룰 충돌**: 없음, but **token budget 위험** (HERMES.md billing 사건 학습 — 자동 trigger는 외부 결제 경로 탐).
**리스크**: 매우 큼. **별도 issue 분리 + dry-run 측정 후 결정**.
**대안**: 수동 트리거 keyword 확장만 (자동 invoke X).

#### P2-2. CLAUDE.md ".claude/ 4-Layer Architecture" 표 정확성 보정

**Action**: 현재 표는 `agents/ 2개`, `skills/ 5개` (broken 포함), `commands/ 3개` 기재. P0-1 후 5/5 valid로 갱신 + commands 인벤토리 추가.
**근거**: §5.8 #5 (숫자 grep) — `5/5 valid`가 진실이 되어야 doc 정확.
**룰 충돌**: 없음.
**별도 PR**: P0-1과 같은 PR에 동시 갱신 권장.

#### P2-3. `nuri-collector-onboard` skill (#7 외부 API 측정 강제)

**Action**: 새 collector 추가 시 concurrency/timeout/rate-limit probe 절차 표준화 skill.
**근거**: STRATEGY §5.8 #7 — yfinance 10-thread OK ≠ KRX 10-thread OK 사례.
**룰 충돌**: 없음.
**조건**: 6개월 내 신규 collector 추가 계획 있을 때만 가치.

---

## 7. Anti-recommendations (제안하지 않는 것)

| 안 하는 것 | 이유 |
|---|---|
| **`/harness:evolve` 자동 self-improvement loop 도입** | §5 결론 — §7.1 Auto trading deferred 정신 + privacy + drift 위험. 인간-mediated 진화가 양호. |
| **Hierarchical Delegation 패턴 도입** | 단일 사용자 + 단일 세션 모델. 가이드 자체가 "2단계 이내 권장". ROI 마이너스. |
| **Supervisor 패턴 신설** | `Makefile` deterministic dispatch가 충분. SIEGE 10-gate를 supervisor화하면 §3.8 closed audit route를 다시 자극 — wrong-sign 결과 인지 후 보존된 상태 깨뜨릴 위험. |
| **에이전트 팀 모드(`TeamCreate`) 디폴트화** | revfactory는 팀 모드를 권장하나 우리 도메인은 비용 대비 효과 낮음. 단일 사용자 + Makefile orchestrator가 이미 있음. 토큰 비용 + HERMES.md-style billing 사건 위험. |
| **기존 5개 SKILL의 description 재작성 (pushy화)** | revfactory 권장이지만 현재 description이 우리 도메인 keyword를 정확히 반영. pushy화하면 trigger 충돌 위험. P0-1로 discoverable 회복 후 실측 데이터 보고 결정. |
| **Privacy scanner를 hook only로 이전 (CI에서 제거)** | §4.4.1 "CI is authoritative" 룰. Hook은 추가 layer일 뿐, 단독 신뢰 금지. |
| **AGENTS.md / `.cursor/rules/` 동기화** | 본 audit scope 외부 (cross-tool). 별도 이슈로 분리. |
| **`docs/harness_audit_*.md` 정기 자동 생성** | 본 보고서는 1회성. 진화 트리거(§5.4 결론)는 인간 판단으로 발화. |

---

## 8. Phase 0 산출물 요약 (사용자 의사결정용)

| 항목 | 현재 | 권장 다음 액션 |
|---|---|---|
| Skills valid | 2/5 | P0-1: 3 rename → 5/5 |
| Orchestrator | 없음 | P1-1: `nuri-flow` 추가 (recommend-only) |
| Hooks (mechanical) | 4 | P1-2: privacy scanner 추가 → 5 |
| CI gates (mechanical) | 4 (privacy, doc-counts, security, tests) | P1-3: pr-discipline 추가 → 5 |
| Agents | 2 | 변경 없음 (자동 trigger는 P2 보류) |
| 패턴 커버리지 | 4/6 (#1 broken, #5/#6 부재) | P0-1로 #1 회복 → 5/6. #5/#6은 도메인 부적합 |
| 진화 메커니즘 | 인간-mediated (PR + STRATEGY) | 유지. 자동화 비추천 |

**다음 PR 후보 (별도 이슈 / PR Discipline 준수)**:
1. `fix(harness): rename README.md → SKILL.md for 3 skills` (P0-1) — 1 commit
2. `feat(harness): add nuri-flow orchestrator (recommend-only)` (P1-1) — ≤ 3 commits
3. `feat(harness): privacy scanner PreToolUse hook` (P1-2) — ≤ 2 commits
4. `ci: enforce 1 issue = 1 PR ≤ 3 commits gate` (P1-3) — 1 commit

---

---

## 9. 프로젝트 전체 .md × Claude Code 공식 spec compliance

사용자 요청 — `.claude/` 외부의 `.md`까지 포함한 종합 감사. **검증 범위**: workspace 내 41개 `.md` (node_modules / .venv / data / codex-reviews / .git / .pytest_cache 제외).

### 9.1 Claude Code 공식 spec (canonical 정의)

Anthropic 공식 (2026-04 기준):

| 자산 | 경로 | 파일명 | 형식 |
|---|---|---|---|
| Memory | `**/CLAUDE.md` | `CLAUDE.md` (대문자, 정확) | recursive append (subdir → parent) |
| User memory | `~/.claude/CLAUDE.md` | 동일 | global |
| Skill | `.claude/skills/{kebab-name}/SKILL.md` | `SKILL.md` (대문자, 정확) | YAML frontmatter `name`+`description` 필수 |
| Skill bundles | `.claude/skills/{name}/{scripts,references,assets}/` | 자유 | optional progressive disclosure |
| Agent | `.claude/agents/{kebab-name}.md` | kebab-case + `.md` | YAML `name`+`description` 필수 |
| Slash command | `.claude/commands/{kebab-name}.md` | kebab-case + `.md` | YAML `description` 필수, body는 prompt template |
| Hook | `.claude/settings.json::hooks` | (별도 파일 없음) | inline JSON |
| Settings (project) | `.claude/settings.json` | 정확 | gitignored 파트너: `settings.local.json` |

비공식 cross-tool convention:
- `AGENTS.md` (root, sub-package) — Cursor / Copilot / Codex CLI 공통 인식. **Claude Code의 `.claude/agents/`와 무관**한 별개 spec.

### 9.2 전체 .md 분류 표

| 파일 | 위치 | 분류 | spec 적합성 | 비고 |
|---|---|---|---|---|
| `CLAUDE.md` | root | Memory | ✅ 정확 | recursive root |
| `CLAUDE.md` | `nuri/core/` | Memory | ✅ | scoped, auto-append |
| `CLAUDE.md` | `nuri/collectors/` | Memory | ✅ | |
| `CLAUDE.md` | `nuri/trading/agents/` | Memory | ✅ | |
| `CLAUDE.md` | `nuri/trading/engine/` | Memory | ✅ | |
| `CLAUDE.md` | `config/` | Memory | ✅ | |
| `CLAUDE.md` | `tests/` | Memory | ✅ | |
| `CLAUDE.md` | `frontend/` | Memory | ✅ | |
| `nuri-codex-second-opinion.md` | `.claude/agents/` | Agent | ✅ | kebab + `.md` + valid YAML |
| `nuri-thesis-batch.md` | `.claude/agents/` | Agent | ✅ | |
| `thesis.md` | `.claude/commands/` | Command | ✅ | `$ARGUMENTS` 사용 |
| `buy-candidates.md` | `.claude/commands/` | Command | ✅ | |
| `earnings-preview.md` | `.claude/commands/` | Command | ✅ | |
| `SKILL.md` | `.claude/skills/nuri-harness-debug/` | Skill | ✅ | YAML valid |
| `SKILL.md` | `.claude/skills/nuri-siege-audit/` | Skill | ✅ | `disable-model-invocation: true` 정확한 spec field |
| **`README.md`** | `.claude/skills/nuri-deploy/` | Skill | **❌ 위반** | 파일명이 `SKILL.md`여야 함 |
| **`README.md`** | `.claude/skills/nuri-verify/` | Skill | **❌ 위반** | 동일 |
| **`README.md`** | `.claude/skills/nuri-review/` | Skill | **❌ 위반** | 동일 |
| `AGENTS.md` | root | Cross-tool | (외부 spec) | Cursor/Copilot/Codex CLI용 — Claude Code spec 외 |
| `AGENTS.md` | `frontend/` | Cross-tool | (외부 spec) | 동일 |
| `README.md` | root | 일반 docs | ✅ (일반 관행) | GitHub landing |
| `README.md` | `frontend/` | 일반 docs | ✅ (npm 관행) | |
| `CONTRIBUTING.md` | root | 일반 docs | ✅ | GitHub 관행 |
| `SECURITY.md` | root | 일반 docs | ✅ | GitHub vulnerability reporting |
| `NEXT_SESSION.md` | root | 프로젝트 핸드오프 | ✅ (프로젝트 convention) | gitignored, CLAUDE.md에 명시 |
| `SESSION_PROMPT.md` | root | 프로젝트 부트스트랩 | ⚠️ 가능한 refactor 대상 | §9.4 참조 |
| `pull_request_template.md` | `.github/` | GitHub 관행 | ✅ | |
| `STRATEGY.md` | `docs/` | 프로젝트 docs | ✅ ALL_CAPS 관행 | canonical policy |
| `ARCHITECTURE.md` | `docs/` | 프로젝트 docs | ✅ | |
| `OPERATIONS.md` | `docs/` | 프로젝트 docs | ✅ | |
| `SIEGE_V2.md` | `docs/` | 프로젝트 docs | ✅ | |
| `KIS_INTEGRATION.md` | `docs/` | 프로젝트 docs | ✅ | |
| `HARNESS.md` | `docs/` | 프로젝트 docs | ⚠️ 가능한 통합 | §9.4 참조 (`nuri-harness-debug/references/`로 이동 가능) |
| `SOURCE_OF_TRUTH.md` | `docs/` | 프로젝트 docs | ✅ | |
| `SMOKE_RUN.md` | `docs/` | 프로젝트 docs | ✅ | |
| `DX_GUIDE.md` | `docs/` | 프로젝트 docs | ✅ | |
| `TODO.md` | `docs/` | 프로젝트 docs (gitignored) | ✅ | |
| `HARNESS_AUDIT.md` | `docs/` | 본 보고서 | ✅ ALL_CAPS canonical | 매 audit마다 overwrite, 이력은 git log로 보존 |
| `507_buy_candidate_emitter_phase1.md` | `docs/plans/` | 플랜 (gitignored) | ✅ 하위 convention | 이슈 번호 prefix |
| `507_buy_candidate_emitter_phase2_spec.md` | `docs/plans/` | 플랜 (gitignored) | ✅ | |

**총 41개 중 Claude Code 공식 spec 위반: 3건** (모두 §2.1 매핑 표의 broken skill).

### 9.3 spec-violation 외의 정합성 risk (refactor 후보, P2 이하)

| 항목 | 현 상태 | 잠재 issue | 권장 |
|---|---|---|---|
| `AGENTS.md` (root + frontend) | Cross-tool spec | 신규 contributor가 `.claude/agents/`와 혼동 가능 | 유지 + CLAUDE.md "Reference"에 "AGENTS.md ≠ .claude/agents/" 명시 1줄 추가 (P2) |
| `SESSION_PROMPT.md` (root) | 7.7k bootstrap text | 매 새 세션 사용자가 수동 복붙 → slash command화 가능 | `.claude/commands/session-prompt.md` 신설 가치 평가 (P2) |
| `docs/HARNESS.md` | case studies 14k | `nuri-harness-debug/SKILL.md`가 `docs/HARNESS.md` 참조 — 외부 의존 | progressive disclosure 권장 위치는 `.claude/skills/nuri-harness-debug/references/case-studies.md`. 단 docs/도 다른 사람이 직접 read 가능한 이점 → 이동보다 **양쪽 sync** 또는 **symlink** 검토 (P2) |
| ~~`docs/harness_audit_20260430.md`~~ → `docs/HARNESS_AUDIT.md` | 초기 snake_case + date | docs/ ALL_CAPS 관행과 inconsistent | **본 audit에서 정정 완료** — single canonical, 이력은 git log |
| `docs/plans/*.md` | 이슈 번호 prefix + lower_snake | plans/ 내부 convention | OK — gitignored, 작업용 |

### 9.4 Refactor 권장사항 (P0/P1/P2 → §6에 통합)

추가 제안 (§6와 통합):

#### P0-1 (재확인) — 3 SKILL.md rename은 본 audit에서 **유일한 spec 위반**

이미 §6 P0-1에 등재됨. 1 PR로 즉시 처리 가능. 명령:
```bash
git mv .claude/skills/nuri-deploy/README.md   .claude/skills/nuri-deploy/SKILL.md
git mv .claude/skills/nuri-verify/README.md   .claude/skills/nuri-verify/SKILL.md
git mv .claude/skills/nuri-review/README.md   .claude/skills/nuri-review/SKILL.md
```
git history 보존 (rename 90% similarity 자동 인식).

#### P2-4 (신설) — `docs/HARNESS.md` ↔ `nuri-harness-debug/references/` 이중 source 정리

현재 SKILL.md가 "Case Studies — `docs/HARNESS.md` 참조"로 외부 링크. progressive disclosure 원칙(스킬은 자기 완결)과 부분 충돌. 옵션:
- (a) `docs/HARNESS.md`를 `.claude/skills/nuri-harness-debug/references/case-studies.md`로 이동 + `docs/HARNESS.md`는 1줄 redirect
- (b) 양쪽 sync (SOURCE_OF_TRUTH.md에 ownership 명시) — 현 상태
- (c) 현 상태 유지 (audit 결과 spec 위반 아님)

**권장**: (b) — `docs/SOURCE_OF_TRUTH.md`에 한 줄 추가만. (a)는 `docs/`만 보는 외부 reader 경로 손실. (c)는 drift 위험.

#### P2-5 (신설) — `SESSION_PROMPT.md` slash command화

현재 root에 7.7k bootstrap text. `/session-prompt` slash command로 만들면 매 세션 자동 로드 가능. 단, 이미 `NEXT_SESSION.md`(gitignored)와 역할 중복 가능 — 사용자 워크플로 측정 후 결정.

#### P2-6 (신설) — `AGENTS.md` 혼동 방지 1줄

CLAUDE.md "Reference" 섹션:
```markdown
- `AGENTS.md` — cross-tool rules (Cursor / Copilot / Codex CLI), **Claude Code의 .claude/agents/와 별개**, not auto-loaded by Claude Code
```
"별개" 강조만 추가. 기존 문장 거의 그대로.

### 9.5 결론 (사용자 질문에 대한 직답)

**Q**: "우리 파일명을 클로드코드 공식 spec에 엄밀히 맞춰 update/refactor해야 하나?"

**A**: **3건 외에는 거의 필요 없다**. 41개 중 38개는 이미 spec-compliant 또는 GitHub/일반 관행에 부합. 위반 3건(P0-1)만 수정하면 spec compliance 100%. 나머지는 cosmetic refactor (P2-4~P2-6) — ROI 낮음, 해도 좋고 안 해도 작동.

**해야 하는 것**:
1. **P0-1 rename 3건** — 즉시. 이게 핵심.

**해도 되는 것** (선택):
2. P2-6 — CLAUDE.md `AGENTS.md` 1줄 정정 (5초 작업)
3. P2-4 — SOURCE_OF_TRUTH.md `docs/HARNESS.md` ownership 1줄 추가
4. P2-5 — SESSION_PROMPT.md slash 변환은 워크플로 검토 후

**안 해도 되는 것**:
- 모든 docs/*.md 이름 통일 (이미 ALL_CAPS 관행 일관)
- 모든 README.md 제거 (npm/GitHub convention 보존 필요)
- AGENTS.md 제거 (Cursor/Codex CLI에서 사용)

본 보고서는 사용자 우려에 대한 종합 답변 — **광범위 refactor는 불필요. P0-1 단일 PR이면 spec 100% 충족**.

---

**End of audit.** `.claude/` 변경 0건. 본 보고서 1개 파일만 생성/갱신.
