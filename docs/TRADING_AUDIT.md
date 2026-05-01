# nuri/trading/ Audit Report (#552, P3)

**작성일**: 2026-05-01
**대상**: `nuri/trading/` — 41 파일, 10709 LOC, 6 subdir
**범위**: read-only audit (refactor 즉시 X — 별도 PR 결정 후)
**관련 PR**: #551 (P0+P1 scripts/tests cleanup) 후속

## Executive Summary

`nuri/trading/` 는 nuri-quant 의 **2번째로 큰 모듈** (1번째: `nuri/agents/`, 7707 LOC). 
6개 subdir 로 잘 나뉘어 있고 cross-module import 도 적정 수준. 다만:

- **Layer 정의 불명확**: subdir 5개 (agents/engine/execution/recommend/strategy/swing) 의 *역할 경계* 가 docstring 으로만 정의됨, 코드에서 강제 X
- **legacy `decisions` table** (#178) vs **신규 `agent_decisions`** (#33, Phase 2) 둘 다 활성. 중복은 아니지만 *의미 분리* 가 README 에 부재
- **`consensus.py` 943 LOC** — 10-agent 통합 로직 한 파일. 분할 검토 가치
- **swing/ 590 LOC** — 가장 작은 subdir. 별도 분리 가치 vs `strategy/` 흡수 검토

## Subdir 구조 (File count + LOC)

| Subdir | Files | LOC | 역할 (docstring 기반) |
|---|---|---|---|
| `agents/` | 13 | 2486 | 10-agent BUY/SELL/HOLD consensus (Codex Round 5 #529 와 별개 — pre-existing) |
| `engine/` | 8 | 2492 | SIEGE 10-gate certification + remediation + decisions ledger |
| `execution/` | 2 | 245 | broker API stub (현재 `broker.py` 만, 자동 매매 영구 X 정책) |
| `recommend/` | 7 | 2641 | 매매 candidate emit + tracker + price_targets + holdings_monitor |
| `strategy/` | 7 | 2255 | long/short backtest + position sizing + mean reversion + pairs |
| `swing/` | 3 | 590 | swing 매매 rules + scanner |

## Largest files (분할 검토 후보)

| File | LOC | 권고 |
|---|---|---|
| `strategy/ls_backtest.py` | 1081 | 검토 — 단일 backtest 로직이면 OK, 여러 strategy 섞여 있으면 분할 |
| `engine/certification.py` | 955 | SIEGE 10-gate 정의 — gate 별 분할 vs 단일 유지 결정 필요 |
| `agents/consensus.py` | 943 | **분할 권고** — 10-agent 통합 + voting + tiebreak 한 파일 |
| `recommend/price_targets.py` | 547 | OK (entry/stop/target_1/target_2/trailing 5종 계산) |
| `recommend/candidates.py` | 532 | OK |
| `recommend/buy_candidate_emitter.py` | 506 | OK |
| `engine/decisions.py` | 424 | legacy table I/O (#178) — Phase 2 와 중복 위험 검토 (아래 참조) |

## Cross-module import 분석

### Internal (within trading/)

```
agents/base.AgentVerdict + BaseAgent  → 10 곳에서 import (각 agent module)
agents/{wallstreet,technical,smart_money,risk,retail,...} → consensus.py 가 1회씩 import
```

→ 정상 fan-in. `agents/` 내부 의존만 있음.

### External (outside trading/, downstream consumers)

```
nuri.trading.agents.base.AgentVerdict + BaseAgent  → 10 외부 import (대부분 tests)
nuri.trading.engine.certification → 3 외부 (api, scripts, tests)
nuri.trading.strategy.ls_backtest → 2 외부
nuri.trading.recommend.holdings_monitor / buy_candidate_emitter → 각 1
nuri.trading.engine.{decisions,gate,amplifier_gate,remediation} → 각 1
```

→ 외부 의존 spread thin, 어떤 subdir 도 압도적으로 많이 노출되지 않음. **public API 표면 좁음** = refactor 안전.

## Legacy `decisions` table vs Phase 2 `agent_decisions`

### 현재 상태

- `nuri/trading/engine/decisions.py` (424 LOC) — **legacy `decisions` table** (#178 Decision Intelligence) 의 read/write
- `nuri/agents/actors/decision_compiler.py` — **신규 `agent_decisions` table** (#33 Phase 2 capstone) 의 write
- 두 테이블 동시 존재, 별개 schema, 별개 의미

### 의미 차이

| | legacy `decisions` (#178) | 신규 `agent_decisions` (#33) |
|---|---|---|
| Schema | id INT, regime, agent_verdicts (10-agent), pnl_7d/30d/60d/90d, outcome | decision_id TEXT PK, ticker, action, conviction, inputs_json, rationale_json, status |
| Source | `nuri/trading/agents/consensus.py` (10-agent voting) | `nuri/agents/actors/decision_compiler.py` (4-actor chain) |
| 누가 사용? | UI dashboard, tracker.py, candidates.py | DecisionCompiler emit log, ForwardOutcomeTracker tracking source |
| outcome 추적 | `nuri/trading/recommend/tracker.py` (수동/cron) | `nuri/agents/actors/forward_outcome_tracker.py` (자동) |

### 중복 위험 평가

**중복 X — 두 시스템이 병행 운영 의도** (Phase 2 가 #178 을 *대체* 가 아닌 *상위 layer*):
- 10-agent consensus 는 매일 holdings 별 BUY/SELL/HOLD verdict (heuristic-driven)
- 4-actor chain (Phase 2) 은 hypothesis-driven emit (causal-validated)
- 두 시스템이 같은 ticker 에 대해 *다른 결정* 을 내릴 수 있음 — 이게 *의도된 redundancy* (cross-validation)

**행동 권고**:
1. **README.md / STRATEGY.md 에 두 시스템의 의미 명시** (현재 부재)
2. UI dashboard 가 어느 것을 source-of-truth 로 보여줄지 정의
3. 두 시스템 결과 mismatch 시 alert 추가 (별도 PR)

## CLAUDE.md memory tree 일관성

```
nuri/trading/CLAUDE.md            ← 없음 (subdir 들만 있음)
nuri/trading/agents/CLAUDE.md     ← 있음
nuri/trading/engine/CLAUDE.md     ← 있음
nuri/trading/execution/CLAUDE.md  ← 없음
nuri/trading/recommend/CLAUDE.md  ← 없음
nuri/trading/strategy/CLAUDE.md   ← 없음
nuri/trading/swing/CLAUDE.md      ← 없음
```

→ 2/6 subdir 만 CLAUDE.md 보유. **나머지 4 subdir 의 의도 명시 부재** = 신규 코드가 잘못된 위치에 생길 가능성.

**행동 권고**: 4 subdir 각각 CLAUDE.md 생성 (README 수준 docstring, 30-50줄). 별도 PR.

## 권고 (P3 audit 결론)

### 즉시 refactor 권고 X
모든 코드 작동 중, public API 표면 좁음, 중복 시스템도 의도된 cross-validation.

### 별도 PR 후보 (우선순위)

| Priority | 작업 | 예상 시간 | 위험 |
|---|---|---|---|
| **P2.1** | `agents/consensus.py` 943 LOC 분할 (voting / tiebreak / aggregator 등 분리) | 2h | 중간 (10-agent voting 로직 — 회귀 위험) |
| **P2.2** | 4 subdir 에 CLAUDE.md 추가 (execution / recommend / strategy / swing) | 30min | 낮음 (doc only) |
| **P2.3** | README/STRATEGY 에 legacy `decisions` vs Phase 2 `agent_decisions` 의미 명시 | 30min | 낮음 (doc only) |
| **P3** | `engine/certification.py` 955 LOC 분할 vs 유지 결정 (codex consult 권고) | 1h consult + 2h impl | 높음 (SIEGE gate logic — 백테스트 의존) |
| **P3** | `swing/` 흡수 vs 유지 결정 (590 LOC, 가장 작은 subdir — `strategy/` 와 의미 겹침?) | 1h audit | 중간 |

### 즉시 안 함 (의도된 구조)

- `agents/` (10 agent module 분할 그대로) — 1 file = 1 agent 패턴 명확
- `engine/decisions.py` legacy 유지 — Phase 2 와 별개 의미, 둘 다 필요
- `execution/` 단일 파일 (broker.py) — 자동 매매 영구 X (#7.1) 정책 유지

## Next steps

본 audit 후 결정 사항:
1. P2.2 + P2.3 (doc only) → 1 PR 묶어서 빠른 ship
2. P2.1 (consensus.py 분할) → 별도 PR (codex consult 후 진행)
3. P3 (certification.py / swing/) → 별도 issue 분리, 즉시 안 함

본 audit 자체는 docs/TRADING_AUDIT.md 1 파일 commit (read-only artifact).
