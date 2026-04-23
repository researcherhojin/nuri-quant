---
name: nuri-siege-audit
description: SIEGE predictivity measurement (E4-0b v2) audit 재실행 + 해석 절차. Use when re-running 60-month predictivity audit, interpreting gate-level Δ results, or adding new variant templates. audit route 는 2026-04-22 currently closed state — 재활성화 조건 확인용.
disable-model-invocation: true
allowed-tools: Bash(ssh *) Bash(.venv/bin/python *)
---

# SIEGE Predictivity Audit (E4-0b v2) — Closed Route 재실행 프로토콜

**Context**: `docs/STRATEGY.md §3.8` 의 audit 가 variant ladder × momentum-based snapshot route 로 2026-04-22 60-month rerun 에서 acceptance 미달 (point estimate wrong-sign). 본 skill 은 해당 methodology 의 재실행·해석·확장 절차 — STRATEGY 본문 덜어낸 상세.

## 재현 명령

```bash
# Mac mini (production DB, 60-month 권장)
ssh $DEV2_HOST 'cd ~/workspace/nuri-quant && .venv/bin/python scripts/siege_predictivity_audit.py --months 60 --save'

# MBP (pilot rerun, 36-month)
.venv/bin/python scripts/siege_predictivity_audit.py --months 36 --save
```

Artifact: `data/reports/YYYY-MM-DD/e4_0b_siege_predictivity.md` (gitignored — data sovereignty). STRATEGY §3.8 의 60-month trajectory table 이 authoritative — 로컬 artifact 가 다른 machine/run 에서 diverge 시 STRATEGY 본문 숫자를 reference 로 사용.

## v2 Methodology

**Variant ladder** (4 templates × N months): momentum_top10 / equal_weight_sample / sector_concentrated / concentrated_top5. Construction-by-design 으로 각 gate 에 fire/not-fire 양쪽 sample 확보.

**Gate eligibility matrix** (codex Biggest Risk fix):

| 분류 | Gates | 상태 |
|---|---|---|
| `auditable_now` | position_limit, sector_limit, leverage_ban | snapshot-native portfolio-rule, 측정 대상 |
| `audit_incoherent` | data_fresh_*, external_data_*, volatility_gate_*, drift_safe, macro_event_alignment, conflict_free | current DB state 의존, snapshot coherence 없음, skip |
| `requires_replayed_state` | stop_loss, rules_loaded | historical portfolio pnl/metadata 부재, 측정 불가 |

**Hybrid metrics**: Binary Δ primary (fired − not_fired mean fwd return + 95% bootstrap CI) + continuous severity OLS slope secondary (auditable gates 만).

**Acceptance** (codex Q5 correction — CI upper bound, NOT lower):
- `Δ = fired − not_fired` 이므로 downside predictivity 는 CI 전체가 0 아래
- `primary_keep`: 30d `CI_high < 0` AND 60d point estimate < 0
- `strong_keep`: 30d + 60d 모두 `CI_high < 0`

## v1 → v2 재설계 이유 (#417 → closure)

v1 failure mode: 48 rows Δ 전부 null. 3 축 invariance — (a) 모든 snapshot 이 us_core top-10 momentum × equal 10% → position_limit/leverage/stop 0 fire, (b) `_age_hours()` 가 `kst_now()` 기준 → freshness/external/drift 47/0 fire (historical-date 평가 bias), (c) top-10 momentum 의 sector 밀집이 invariant.

## 60-month Gate-level 결과 (2026-04-22 production)

| Gate | Fire/Not | Δ30d CI | Δ60d CI | Δ90d CI | Primary_keep |
|---|---|---|---|---|---|
| `position_limit` | 47/94 | [-3.43, +8.77] | [-6.79, +12.85] | [-8.17, +17.82] | ❌ |
| `sector_limit` | 141/0 | non-fire 부재 | — | — | N/A |
| `leverage_ban` | 0/141 | fire 부재 | — | — | N/A |

## 핵심 finding (interpretation)

- `position_limit` pilot + 60-month **point estimate 양수** (fired > not-fired, 30/60/90d 전부). §3.7 downside-predictive hypothesis 와 **반대 sign 안정적**. Magnitude 축소 (Δ30d +4.34% → +2.45%). CI 0 가로지름이나 wrong-sign 은 sample size 로 해결 안 됨 — point 가 먼저 음수 flip 해야 CI_upper<0 가능.
- `sector_concentrated` variant 가 60-month 에서 0/60 unbuildable — codex Round 1 "Unknown" exclusion fix 후 us_core 85 ticker 중 real GICS sector tag 가 5 뿐 (pilot 36/36 success 는 pre-fix bug artifact).
- `leverage_ban` fire sample 0 — leveraged ETF 미포함 variant.

## Prudential vs predictive 축 분리 (필수 인용 규칙)

`position_limit` / `sector_limit` / `leverage_ban` 는 여전히 **prudential portfolio constraints + user-preference defaults** 로 유효 — 사용자 감정 통제, STRATEGY §7 자동 매매 deferred, O'Neil/Minervini lineage.

**그러나 synthetic audit 은 forward-downside-predictive gate 로 기능한다는 주장 미증명**. 두 축 혼동 금지 — rule 은 prudential 근거로만 인용, downside-predictive framing 은 §3.8 에서 tentatively refuted 로 인용.

## Deferred low-value extensions (codex Round 2 verdict)

재활성화는 해당 route 의 breadth 확장 아닌 **audit design 자체 redesign** 필요:

- `leverage_included` variant 추가 → `leverage_ban` fire sample 확보 가능하지만 central wrong-sign 해결 안 함. 독립 date 수도 증가 없음 (same-date variant 는 correlated observation).
- GICS sector backfill (us_core 85 tickers) → `sector_concentrated` 재활성화 가능하지만 same rationale.
- Sample 확장 (60 → 84+ months) → 실제 독립 date 는 ~48 (older dates universe history 부족). Statistical power 한계 structural.

## 재활성화 조건

이 route 재실행은 의미 없음. 다음 중 하나 충족 시 새 Plan consult + STRATEGY 개정:

1. **Actual-portfolio replay** — tracker outcomes 누적 후 real-history 기반 측정
2. **§2.6 Symmetric amplifier 이후 upside-measurement 전용 경로** 설계
3. **audit design 근본 redesign** — variant ladder × momentum snapshot 이 아닌 다른 source

## Codex consult archive

- `codex-reviews/PRe4-0b-v2-roundplan-20260421T175538Z.md` — v2 Plan
- `codex-reviews/PRe4-0b-60month-round1-20260422T022809Z.md` — 60-month closure consult
- `codex-reviews/PR443-round2-20260422T024801Z.md` — STRATEGY §3.8 honest rewrite round 2
