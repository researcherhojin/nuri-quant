# Harness Engineering — Case Studies

이 문서는 `docs/STRATEGY.md §5` (하네스 원칙) 의 **case-study 부록**이다. 실제 겪은 실패 세션의 구체적 교훈과 재발 방지 장치를 기록한다. 매 세션 auto-import 하지 않고, 비슷한 패턴을 디버깅할 때만 참조한다.

Canonical rules (7 principles, Flow, phantom-fix protocol 등) 는 `STRATEGY.md §5` 에 있다. 이 문서는 원칙이 **어떤 현장 실패에서 도출됐는지** 의 증거 모음이다.

---

## 1. #272 세션 교훈 (2026-04-14, 12 PRs)

**Universe + Agent Coverage 통합**(#272) 작업에서 8시간에 걸쳐 12개 PR 머지하며 누적된 패턴 — 미래 비슷한 작업에서 반복 실수 회피용.

### 1.1 Mock-only 테스트 함정

| 사례 | 상황 | 결과 |
|------|------|------|
| PR #278 universe mode | mock test 28건 통과 → ship → 사용자 실행 시 yfinance ERROR 500줄 | rebuild 필요 |
| PR #282 ThreadPool timeout | unit test 통과 → ship → 사용자 실행 시 여전히 hang | 2차 fix |
| PR #283 sequential fix | live 검증 33초 → 머지 → 끝 | 처음으로 정상 ship |

**룰**: ship 전 사용자 워크플로 1회 직접 실행. mock test와 별개로 `make X --source universe` 같은 실제 명령. `tests/integration/` marker (`@pytest.mark.integration`)로 분리하되 ship 게이트에 포함.

### 1.2 외부 API 동시성 차이

| API | 동시 요청 | 패턴 |
|-----|----------|------|
| yfinance | **10 thread OK** | `ThreadPoolExecutor(max_workers=10)` |
| KRX (pykrx) | **rate-limit, sequential 권장** | 순차 + `time.sleep(0.1)` |
| Wikipedia | 10초 간격 권장 | User-Agent 헤더 + backoff |

**룰**: 새 외부 API 통합 시 동시성 측정 후 결정. ThreadPool은 API 종류에 따라 도움/해악 갈림.

### 1.3 ThreadPool 한계

`ThreadPoolExecutor.future.result(timeout=)`는 future를 cancel만 하고, **underlying C extension call (e.g. pykrx)은 계속 실행** → 누적되어 메모리 leak + slowdown.

**룰**: hang 가능한 외부 호출에 timeout으로 cancel하려 하지 말 것. 진짜 cancellable 필요하면 subprocess 사용. 또는 sleep + 단순 try/except.

### 1.4 Iterative root cause

같은 버그를 3회에 걸쳐 fix:
1. PR #282: ThreadPool timeout 추가 → 부분 해결
2. PR #283: 8 thread parallel → 첫 60건 빠르고 그 후 KRX rate-limit
3. PR #283 (수정): sequential + 0.1s sleep → 진짜 fix

**룰**: 같은 증상 2회 반복 fix 시 근본 원인 의심. 3회 시도 전에 `pytest --pdb` 또는 실제 환경에서 직접 디버깅.

### 1.5 사용자 관점 검증 누락

`make X --flag` 형태로 사용자가 자연스럽게 시도한 명령이 실패 (`make universe-sync --market kr` → make는 arg 안 받음). 사용자가 아는 패턴 ≠ 코드가 지원하는 패턴.

**룰**: Makefile target 추가 시 자주 쓰일 변형(`-us`, `-kr`, `-apply` 등)을 dedicated target으로 명시.

### 1.6 진행 가시성 = 신뢰

543종목 1개씩 처리되는데 progress 표시 없으면 사용자는 "stuck" 판단. tqdm + 명확한 요약은 ship 필수.

**룰**: ≥20 ticker iteration 모든 collector에 tqdm + 요약 (✅ N 성공 / ❌ M 실패) + per-field N/A 진단 추가.

### 1.7 Multi-role flow 강제

PM (spec) → Dev (impl) → Eval (test + smoke) → ship. Eval 단계 건너뛰면 1.1 함정에 빠짐. 본인 self-review가 아닌 별도 단계로 분리할 것.

**룰**: `gstack-codex` 등 외부 review tool 또는 사용자 review 단계 전에 ship 금지. 자동화된 integration test가 review 대체 가능. (STRATEGY §2.7 gstack 7-phase Flow 의 Test 단계로 refine 됨.)

---

## 2. 추천 파이프라인의 도구 사각지대 (JKHY 에피소드, 2026-04-14)

> **2026-04-15 정정 노트** (PR #307): 원 기록의 핵심 진단 2개가 심층 조사 결과 오독으로 밝혀졌다. 원 문장은 교훈용으로 stryke-through 보존하되 실제 root cause 와 대응은 아래 **"정정된 분석"** 참조.

**상황**: 세션 종료 직전 universe-wide BUY 추천 7종목 (TMUS/JKHY/V/MA/BX/ANET/NFLX) 제시. 사용자가 Investing.com 확인 → JKHY "적극 매도" (기술지표 종합). 시스템 추천과 정면 모순.

~~**원인 (3층)**:~~

1. ~~**도구는 있으나 연결 안 됨** — `nuri/quant/chart_analysis.py` (BB/MACD/RSI/추세선) 구현 존재하지만, 추천 파이프라인 (`candidates.py`, `consensus.py`) 에서 호출하지 않음.~~
2. ~~**Fundamentals-only 추천** — 애널리스트 upgrade + ROE/PE 기반 Buy 신호만 사용. 가격 모멘텀/추세 완전 무시.~~
3. ~~**애널리스트 신호의 lag 속성 간과** — JKHY earnings surprise 4Q 연속 +0.0~0.2% = "soft beat" 성장 stall 신호도 놓침.~~

**정정된 분석** (PR #301-#303 + codex challenge 결과):

1. **TechnicalAgent 는 이미 `analyze_chart()` 호출 중** — `nuri/trading/agents/technical.py:12,78` 에서 import + invoke. 원 진단 "도구 연결 안 됨" 은 소스 코드 읽지 않은 추정이었음 (STRATEGY §5.1 "모르면 읽는다" 위반).
2. **실제 실패 모드 = dissent overwhelmed, not missing** — JKHY 에 대해 TechnicalAgent 가 SELL(100 conf) 정확히 투표함. 하지만 9 개 fundamentals-ish 에이전트가 BUY/HOLD 로 outweighted → 합의 BUY. 문제는 TechnicalAgent 의 dissent 가 사용자에게 **surface 도 안 되고 action 에 영향도 안 주는** 것. 즉 "informational only" design 의 근본 한계.
3. **JKHY 는 soft beat 이 아니다** — 실측 최근 4Q surprise_pct = 0.17 / 0.13 / 0.04 / 0.09 **decimal fraction** (= 4% ~ 17% 정상 beat). 원 기록의 "0.0~0.2%" 는 저장 단위 오독. JKHY 는 오히려 Bartov 2002 / Kasznik 2002 에서 말하는 "meet/beat premium" 수혜 대상. 진짜 실패 모드는 **falling knife** — fundamentals 강 + technicals 무너짐 + 시장이 구조적 우려 (SaaS competitive pressure 등) 를 먼저 price-in.

**재발 방지 룰** (정정된 원인에 맞춰):
- 추천 내기 전 **fundamentals + technicals 충돌 여부** 를 explicit 하게 surface 하고, technical 이 강하게 반대하면 mechanical 로 downgrade (STRATEGY §2.6 Escalation Ladder 참조).
- "System has the tool" ≠ "Pipeline uses its output"; tool 이 있어도 **outcome 에 영향 주는 경로** 까지 integration test 로 검증.
- Academic literature 기록된 증거 (meet/beat premium 같은) 와 **가설이 반대 방향** 이면 literature 우선 — codex challenge 로 cross-check.

**방어 실행 현황** (2026-04-15 완료):
- PR #300 (P1 B): universe 1y OHLCV backfill → TechnicalAgent 가 full chart 분석 가능
- PR #301 (P1 A1): `divergence_flag` backend 감지
- PR #302 (P1 A2): UI 배지 + tooltip surface
- PR #303 (P1 A3): mechanical penalty — tech conf ≥ 80 + 반대 → HOLD downgrade
- PR #306 (Q1): `consensus_penalty_applied` 감사 이벤트 + STRATEGY §2.6 Escalation Ladder + `docs/TODO.md` P1 #4 (soft-beat 스펙) Tier 3 이관

**Live 검증**: JKHY 가 이제 `action=HOLD` (was BUY), reasoning "기술지표 반대로 downgrade (tech SELL conf 100 ≥ 80) | ...".

**일반화된 교훈** (정정):
1. "Repo 에 기능이 있다고 해서 production path 에서 outcome 에 영향 주는 건 아님." — 통합 경로 + **mechanical effect** 검증 필수.
2. "초기 진단이 틀리면 후속 모든 처방이 틀린다." — Codex challenge 같은 독립적 adversarial review 를 성급한 fix 전에 넣는 것이 scope + 시간 절약.
