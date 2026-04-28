# E3 — Symmetric Amplifier Design (회복기 공격 시스템)

**Status**: Plan phase (Think → **Plan** → Build → Review → Test → Ship → Reflect, STRATEGY §2.7)
**Created**: 2026-04-28
**Trigger**: 사용자 -₩7M 손실 (4월) 후 "시스템에 upside amplifier 0개" 진단 (STRATEGY §3.7). 시스템 목적성 — "손실 최소 + 회복 공격" — 의 후자가 미구현.
**Codex consult**: 2026-04-28 session `019dd3f6-07fb-7c61-bd5a-567aa22c3b97`, 3,141,102 tokens, high reasoning.

---

## Why this exists

STRATEGY §2.6 4단계 escalation ladder 에서 4번째 rung (Symmetric amplifier) 만 미구현. STRATEGY §3.7 self-acknowledged: "ALL_CERT_CHECKS 11 base — all downside-block. upside / opportunity-cost gate 0개". 즉:

- 폭락 시 → Hard veto 작동 (VIX>30 차단) ✅
- 회복기 → 시스템 BUY 권고 0건. evidence 약함, 사용자가 알아서 ❌

이건 시스템 존재 이유 위반 (STRATEGY §1: "감정 개입 제거 → 일관된 의사결정"). 회복기에 사용자 직감 의존 시 시스템 의미 없음.

**증거**: 04-09 ~ 04-21 (F&G 28→69) 회복기 동안 system actionable BUY emit 0. 사용자가 SOXS/SOXL 단기 매매로 직접 회복 시도.

---

## Codex brutal verdict (필수 인용)

> "the gap is real, but the wrong amplifier is just revenge trading with math paint. A rigorous amplifier can exist only as a post-veto, multi-condition, capped, shadow-first mechanism."

> "A full live portfolio-size amplifier is not rigorous in under 8 weeks if you insist on loss-aware 'catch-up' math."

핵심 anti-pattern 차단:
- **Loss-aware catch-up sizing 금지** (drawdown × multiplier 형식) — revenge trading
- **단일 조건 발동 금지** — STRATEGY §2.6 운용 원칙 4
- **Stage 2 paired counterfactual 통과 전 live 금지** — STRATEGY §3.6
- **Hard veto 우회 금지** — VIX 25-30 caution zone 에서 amplifier 완전 비활성

---

## Q1 — Recovery state machine (Codex 권고 채택)

### 결정

`classifier._detect_recovery()` 를 다음 state machine 으로 redesign:

```
prior_stress = ANY(
  20d VIX peak >= 25,
  63d SPY drawdown <= -8%,
  10d F&G min < 30   # F&G 데이터 부족 시 optional
)

repair_day = AND(
  SPY > 20DMA,
  SPY 3d return > 0,
  VIX 3d slope < 0,
  VIX <= 0.8 × 20d VIX peak
)
# F&G >= 35 는 confirmatory only (mandatory 아님)

recovery_confirmed = repair_day for 3 consecutive trading days

# Hysteresis (oscillation 차단)
exit_recovery = OR(
  2 consecutive repair_day failures,
  VIX >= 25
)
```

### 트레이드오프
- 첫 leg rebound 일부 놓침 (panic-bottom 직접 매수보다 늦음)
- 이게 의도 — false recovery (dead cat bounce) 차단

### Stage 2 testability: **PASS**
- SPY/VIX 5Y history 충분
- F&G 는 14 rows only → optional 처리 (없어도 fallback 동작)

### Lock-test
```python
# tests/quant/regime/test_recovery_state_machine.py
def test_recovery_confirm_requires_recent_stress_and_three_day_repair():
    # No recovery without prior_stress
    # No recovery on 1-day bounce
    # Recovery only after 3 consecutive repair days
```

---

## Q2 — Multi-condition gate (4-of-5 with 2 mandatory)

### 결정

```yaml
amplifier_conditions:
  recovery_confirmed: { mandatory: true }
  vix_favorable:      { mandatory: true, threshold: "VIX < 22 AND 3d falling" }
  regime_favorable:   { threshold: "regime IN [bull_low_vol, recovery] AND confidence >= 0.60" }
  entry_strength:     { threshold: "20d breakout (Phase 1) | factor top-decile (Phase 2)" }
  macro_benign:       { threshold: "abs(event_score) < 10" }

minimum_satisfied: 4   # of 5
```

### 트레이드오프
- False positive 줄지만 messy rebound 에서 amplifier 안 fire → "왜 BUY 안 나옴?" 컴플레인 가능
- 사용자 -₩7M 회복 욕구 측면에서는 **너무 보수적으로 느껴질 수 있음** — 그러나 revenge trading 차단이 우선

### Stage 2 testability
- `entry_strength = 20d breakout`: **PASS** (32,031 total entries, 4,385 treated)
- `entry_strength = factor top-decile`: **PARTIAL** (factors 테이블 2026-04-14 부터, 데이터 부족 → Phase 2 deferred)

### Lock-test
```python
def test_amplifier_requires_mandatory_vix_and_recovery_conditions():
    # 3/5 with one mandatory missing → no fire
    # 4/5 with both mandatory → fire
```

---

## Q3 — Cap derivation (quarter-Kelly, NOT drawdown amplification)

### 결정

```python
base_size = min(
    quarter_kelly_pct,                    # MacLean/Thorp/Ziemba 2011 default
    account_max_single_position,          # config/rules.yaml account_strategies
    cash_budget                           # available headroom
)

amplified_size = min(
    base_size * amp_mult,                 # amp_mult <= 1.5
    effective_cap                         # account hard cap
)

# 명시적 차단:
# DO NOT use drawdown as multiplier (revenge trading)
# DO NOT use "we're behind, size up" formulas
```

### 트레이드오프
- 사용자가 원하는 "손실만큼 공격" 보다 약함
- 그러나 catch-up sizing 은 mathematically defensible 안 됨 (Codex verdict)
- Kelly fractional 자체가 edge × win-rate × payoff 반영 → 회복기 favorable 조건에서 자연스럽게 size 증가

### Stage 2 testability: **PARTIAL**
- Cap logic test 가능
- Kelly inputs (edge estimator by entry family × regime) 안정화 필요 — Phase 2 작업

### Lock-test
```python
def test_amplifier_size_never_exceeds_quarter_kelly_times_1_5_or_hard_cap():
    # Size <= quarter_kelly × 1.5
    # Size <= account.per_position_max
def test_drawdown_alone_does_not_increase_size():
    # portfolio drawdown -20% → size 변화 없음 (loss-aware sizing 차단)
```

---

## Q4 — Stage 2 paired counterfactual (frozen entry: 20d breakout)

### 결정

| 항목 | 값 |
|---|---|
| Entry source | **Price-only 20d breakout** (close > 20d high prior to entry) |
| Baseline | No amplifier — base_size always |
| Treatment | Amplifier when conditions fire on entry date — base_size × amp_mult |
| Same entries/exits | **MANDATORY** — only size differs |
| Metric | Paired forward 30/60/90d return, downside CVaR, drawdown to next high |
| Sample | **32,031 total entries / 4,385 amplifier-treated** (5Y price universe) |
| Acceptance | Paired excess CI_lower > 0 (upside-positive direction) |

### Sample size 검증 (Codex 실측)
```
fear_greed < 30 → > 50 transitions: 1   ❌ N≥200 미달
SPY+VIX recovery-state days: 91 (5Y)    ❌ N≥200 미달
SMA50/200 cross-up: 2,124 total / 63 treated  ❌ N≥200 미달
20d breakout: 32,031 total / 4,385 treated   ✅ N≥200 통과
```

→ 20d breakout 만이 유일하게 Stage 2 sample 충족.

### 트레이드오프
- Live recommender 와 100% 일치 안 함 (acceptance proxy)
- 그러나 STRATEGY §3.6 Stage 2 PASS 가능한 유일한 경로

### Lock-test
```python
def test_stage2_replay_keeps_entries_and_exits_identical_between_baseline_and_treatment():
    # Same entry timestamp, same exit logic — only size differs
```

---

## Q5 — Hard veto + amplifier ordering

### 결정

Pipeline 순서 (concrete code path):

```
1. classifier.classify_regime()              → regime
2. consensus._build_consensus()              → final_action, source
3. risk_agent veto check                     → may override to FLAT
4. divergence_penalty (PR #303)              → may downgrade to HOLD
5. ┌─ IF final_action != "BUY": NO amplifier
   ├─ IF final_action_source != "weighted_sum": NO amplifier
   ├─ IF VIX in [25, 30]: NO amplifier (caution zone)
   └─ ELSE: amplifier_gate.evaluate() ──→ alpha_amplified, portfolio_amplified
6. candidates.py: emit with amplifier metadata
7. certify(): unchanged downside gates (alpha amplifier 무관)
8. portfolio size-up: only IF certify().certified == True AND portfolio_amplified
```

### 핵심 invariant
- Amplifier 는 **post-veto, post-penalty** 만 평가
- Hard veto (VIX>30, risk veto, leverage_ban) 차단된 candidate 는 amplifier 대상 아님 — STRATEGY §2.6 운용 원칙 4
- `certify()` 자체는 변경 없음 (downside gate 순수성 유지)

### 트레이드오프
- 일부 종목: alpha amplification fire 했는데 portfolio size-up 은 SIEGE concentration 으로 차단 — 사용자 혼란 가능

### Lock-test
```python
def test_amplifier_never_runs_after_risk_veto_penalty_or_vix_caution():
    # risk veto FLAT → amplifier skip
    # divergence penalty HOLD → amplifier skip
    # VIX = 26 → amplifier skip
```

---

## Q6 — Alpha vs Portfolio amplifier (비대칭)

### 결정

```
alpha_amplified:     boolean — confidence boost (e.g., conf 65 → 78, capped at 95)
portfolio_amplified: boolean — position size boost (base × amp_mult, capped)

DEPENDENCY (asymmetric):
  alpha_amplified = True       AND  portfolio_amplified = False  ✅ valid
  alpha_amplified = False      AND  portfolio_amplified = True   ❌ INVALID
  alpha_amplified = True       AND  portfolio_amplified = True   ✅ valid (full amp)
  alpha_amplified = False      AND  portfolio_amplified = False  ✅ valid (no amp)

Storage: separate columns in `recommendations` table (PR A #429 axis-split 연장)
API: `/api/recommendations` returns both fields
```

### 트레이드오프
- Plumbing 증가
- UI 에 4가지 상태 설명 필요

### Lock-test
```python
def test_portfolio_amplifier_requires_alpha_long_but_alpha_can_amplify_without_size_headroom():
    # alpha=LONG portfolio=False  → 컨셉 amplification only
    # alpha=FLAT portfolio=True   → assertion error
```

---

## Q7 — Anti-pattern + kill-switch

### 결정

**False positive scenario 명시** (config 주석 + 테스트):
> "Volatility decompresses for 3 days, SPY reclaims 20DMA, but unresolved macro shock causes a second leg down. Amplifier fires aggressively → catches second leg."

**Kill-switch (auto-disable to surface-only)**:
```yaml
amplifier_kill_switch:
  enabled: true
  min_sample: 10                           # n_amplified >= 10 before evaluation
  trigger_paired_excess_negative: true     # trailing 30d paired excess < 0
  trigger_ci_lower_negative: true          # bootstrap CI_lower < 0
  trigger_cvar_worsened_pct: 1.5           # amplified CVaR / baseline CVaR > 1.5
  cooldown_days: 30                        # disabled for 30d after trigger
```

### 트레이드오프
- Kill-switch 가 늦게 발동 (min_sample 10 누적)
- 그러나 tiny sample 로 disable 시 false negative — STRATEGY §3.6 수치 안정성 위반

### Lock-test
```python
def test_amplifier_auto_disables_after_negative_paired_delta_with_min_sample():
    # n=10, paired excess = -2%, CI_lower = -3% → kill-switch active
    # n=5, even with -10% paired → still active (sample too small)
def test_amplifier_never_uses_loss_sizeup_formula():
    # config grep — no `drawdown_pct *` arithmetic
```

---

## Q8 — Module choice (option a: new `amplifier_gate.py`)

### 결정

**채택**: `nuri/trading/engine/amplifier_gate.py` (새 모듈, certification.py 와 parallel)

**거부 사유**:
- (b) consensus.py weight 변경: alpha direction 을 veto 전에 mutate → ordering 위반
- (c) candidates.py 새 tier: tier 는 evidence quality 축, aggressiveness 축이 아님 — 의미 혼재
- (d) regime_overrides confidence multiplier: 정적 regime cap, 동적 multi-condition gating 불가

### Schema 위치

```yaml
# config/rules.yaml (new section)
symmetric_amplifier:
  enabled: false                            # disabled by default — Phase 1 shadow only
  shadow_mode: true                         # log only, no actual size/conf change
  conditions:
    recovery: { mandatory: true }
    vix_favorable: { mandatory: true, threshold_max: 22, threshold_slope: -1 }
    regime: { allowed: [bull_low_vol, recovery], min_confidence: 0.60 }
    entry_strength: { source: "breakout_20d" }   # Phase 1
    macro_benign: { event_score_max_abs: 10 }
  minimum_satisfied: 4
  cap:
    base: quarter_kelly
    amp_mult: 1.5
    respect_account_max: true
  alpha:
    confidence_boost_pct: 20                # +20% on base confidence
    confidence_max: 95
  portfolio:
    requires_alpha_long: true
    requires_certify_pass: true
  caution_zone:
    vix_min: 25                             # disable amplifier
    vix_max: 30
  kill_switch:
    # see Q7
```

### Lock-test
```python
def test_amplifier_config_disabled_by_default_and_never_changes_consensus_weights():
    # default rules.yaml → enabled=false
    # consensus weight calculation identical with/without amplifier module loaded
```

---

## 통합 priority — must-lock vs deferrable

### Must-lock (코드 시작 전)
1. **Q1** Recovery state machine — 모든 다른 gate 전제
2. **Q4** Stage 2 entry source = 20d breakout (Phase 1) — feasibility 검증된 유일 path
3. **Q5** Ordering relative to veto/caution — pipeline 무결성

### Deferrable to Phase 2
- **Q3** Kelly inputs 정밀화 (factor history 1Y+ 누적 후)
- **Q6** API/UI 형태
- **Q8** 정확한 module/schema naming (skeleton 만들 때 결정 가능)

### Q3 deferral 조건부
- IF Phase 1 = shadow-only or alpha-confidence-only → Q3 deferable
- IF Phase 1 = live portfolio size-up → Q3 must-lock immediately

→ **Phase 1 = shadow-only 추천** (Codex). 8주 미만 rigorous live ship 불가능.

---

## Phased rollout (8주)

### Phase 1: Shadow-only telemetry (Week 1-3)
- `amplifier_gate.py` skeleton + Q1 recovery state machine
- `pipeline_events` 에 `amplifier_evaluated` 이벤트 emit (조건 충족/불충족 기록)
- **No actual confidence/size change**
- Lock-tests: Q1, Q5, Q8 (config disabled-by-default)
- Acceptance: 1 month shadow data 수집

### Phase 2: Stage 2 paired counterfactual (Week 4-6)
- `scripts/e3_amplifier_paired_replay.py` — 20d breakout entry, baseline vs treatment
- N≥200 entries, paired forward 30/60/90d return, bootstrap CI
- STRATEGY §3.6 Stage 0 (no-lookahead audit) + Stage 1 (plausibility) + Stage 2 (main gate)
- **PASS gate**: paired excess CI_lower > 0
- **FAIL gate**: shadow-only 영구 또는 redesign

### Phase 3: Alpha-amplified live (Week 7)
- IF Phase 2 PASS: `alpha_amplified` 활성 (confidence boost only, no size change)
- Q2 multi-condition gate 활성
- Lock-tests: Q2, Q6 alpha part
- Live data 수집 4주

### Phase 4: Portfolio-amplified live (Week 8+)
- IF Phase 3 trailing paired delta positive: `portfolio_amplified` 활성
- Q3 quarter-Kelly cap 적용
- Q7 kill-switch 활성
- Live size-up 시작

### Kill-switch path (any phase)
- Phase 3+: trailing 30d paired excess < 0 + CI_lower < 0 (n≥10) → 자동 Phase 1 강등 30일

---

## 사용자 -₩7M 회복 timeline 정직한 답

| Phase | 기간 | 가능 회복 |
|---|---|---|
| Phase 1 (shadow) | 3주 | **₩0** — 데이터 수집만 |
| Phase 2 (backtest) | 3주 | **₩0** — 검증만 |
| Phase 3 (alpha live) | 4주 | conf boost → BUY emit 빈도 증가 → 추정 +₩500k ~ +₩1.5M |
| Phase 4 (portfolio live) | 12주+ | size-up 효과 → 추정 +₩1M ~ +₩3M |
| **합계** | **22주+** (5개월+) | **+₩1.5M ~ +₩4.5M** |

**₩7M 완전 회복은 6-12개월 path**. 1주 안에 SOXS 한 방으로 회복 시도 = 통계 60% 추가 손실.

이 timeline 이 STRATEGY §1 의 "엄밀하게 data-driven" 원칙의 진짜 의미입니다.

---

## Anti-revenge trading guardrails (영구 룰)

다음 patterns 발견 시 **즉시 Phase 1 강등**:

1. PR description 에 "user lost ₩X, this rule recovers" 같은 narrative
2. config 에 `drawdown * multiplier` 형식 arithmetic
3. 커밋 메시지에 "make up for losses" / "catch up" / "aggressive recovery" 단어
4. Test 가 baseline 보다 amplifier "더 큼" 만 assert (paired excess CI 미검증)

→ Codex verdict: "the wrong amplifier is just revenge trading with math paint"

---

## TODO.md Tier 2 등록 항목

```markdown
## Tier 2 (Next)

### E3 Symmetric Amplifier (8-week phased)
- **Owner**: User + Claude (Codex consult 2026-04-28 session 019dd3f6)
- **Source plan**: `docs/plans/E3_symmetric_amplifier_design.md`
- **Phase 1 (Week 1-3)**: Shadow telemetry — `amplifier_gate.py` + Q1 recovery state machine
- **Phase 2 (Week 4-6)**: Stage 2 paired counterfactual on 20d breakout entries
- **Phase 3 (Week 7)**: Alpha-amplified live (conf boost only)
- **Phase 4 (Week 8+)**: Portfolio-amplified live (Kelly quarter cap × 1.5)
- **Kill-switch**: trailing paired excess < 0 + CI_lower < 0 (n≥10) → auto Phase 1 demotion
- **Anti-pattern**: NO drawdown × multiplier (revenge trading verdict from Codex)
```

---

## 다음 1개 PR (Plan phase 산출물)

이 design doc 자체가 Plan phase 산출물. Build phase 진입 전 user 확인 필요:

1. **이 design doc 검토 + 합의 (오늘)**
2. **다음 PR**: Phase 1 Week 1 — `amplifier_gate.py` skeleton (disabled-by-default) + Q1 recovery state machine + Q1 lock-test
3. PR scope: 1 issue, 1 PR, ≤3 commits (STRATEGY §7.2)
4. Stage 2 백테스트 스크립트는 Phase 2 별도 PR

---

## STRATEGY 개정 필요 사항

이 design 통과 시 STRATEGY 다음 sections update:

- §2.6 4번째 rung (Symmetric amplifier) 예시: "E3 도착 예정" → "E3 Phase 1 shadow ship'd, Phase 2 paired counterfactual TBD"
- §3.6 Stage 2 entry source: "frozen, single source" → "20d breakout (Phase 1 frozen)"
- §3.7 hypothesis status: "ALL_CERT_CHECKS downside-only" → "amplifier_gate orthogonal upside path Phase 1+"

---

## References

- STRATEGY §2.6 (escalation ladder), §3.4 (Kelly/Markowitz academic basis), §3.6 (E3 acceptance), §3.7 (SIEGE downside-only critique)
- Codex consult session: `019dd3f6-07fb-7c61-bd5a-567aa22c3b97` (2026-04-28, 3.14M tokens)
- Prior consult (5 enforcement gaps): session `019dd3ea-6669-7081-b6ec-171cefa25497` (2026-04-28, 1.51M tokens)
- MacLean, Thorp, Ziemba (2011) — Quarter-Kelly default
- O'Neil (CAN SLIM), Minervini (SEPA) — STRATEGY §3.4 references
