---
name: nuri-siege-audit
description: SIEGE predictivity measurement (E4-0b v2) audit 재실행 + 해석 절차. Use when re-running 60-month predictivity audit, interpreting gate-level Δ results, or adding new variant templates. audit route 는 2026-04-22 currently closed state — 재활성화 조건 확인용.
disable-model-invocation: true
allowed-tools: Bash(ssh *) Bash(.venv/bin/python *)
---

# SIEGE Predictivity Audit — Closed Route 재실행 프로토콜

**Source**: `docs/STRATEGY.md §3.8` canonical (60-month trajectory authoritative). 본 skill 은 재실행 / 해석 / 재활성화 조건.

## 재현 명령

```bash
# Mac mini (production DB, 60-month 권장)
ssh $DEV2_HOST 'cd ~/workspace/nuri-quant && .venv/bin/python scripts/siege_predictivity_audit.py --months 60 --save'

# MBP (pilot rerun, 36-month)
.venv/bin/python scripts/siege_predictivity_audit.py --months 36 --save
```

Artifact: `data/reports/YYYY-MM-DD/e4_0b_siege_predictivity.md` (gitignored). 다른 머신/run 과 diverge 시 STRATEGY §3.8 본문 숫자가 reference.

## v2 Methodology

**Variant ladder** (4 templates × N months): momentum_top10 / equal_weight_sample / sector_concentrated / concentrated_top5 — 각 gate fire/not-fire 양쪽 sample 확보.

**Gate eligibility matrix** (codex Biggest Risk fix):

| 분류 | Gates | 상태 |
|---|---|---|
| `auditable_now` | position_limit, sector_limit, leverage_ban | snapshot-native, 측정 대상 |
| `audit_incoherent` | data_fresh_*, external_data_*, volatility_gate_*, drift_safe, macro_event_alignment, conflict_free | DB state 의존, snapshot coherence 없음, skip |
| `requires_replayed_state` | stop_loss, rules_loaded | historical pnl/metadata 부재, 측정 불가 |

**Hybrid metrics**: Binary Δ (fired − not_fired mean fwd return + 95% bootstrap CI) primary + continuous severity OLS slope secondary.

**Acceptance** (codex Q5 — CI upper bound):
- `primary_keep`: 30d `CI_high < 0` AND 60d point < 0
- `strong_keep`: 30d + 60d 모두 `CI_high < 0`

## 60-month Gate-level 결과 (2026-04-22 production)

| Gate | Fire/Not | Δ30d CI | Δ60d CI | Primary_keep |
|---|---|---|---|---|
| `position_limit` | 47/94 | [-3.43, +8.77] | [-6.79, +12.85] | ❌ |
| `sector_limit` | 141/0 | non-fire 부재 | — | N/A |
| `leverage_ban` | 0/141 | fire 부재 | — | N/A |

**핵심 finding**: `position_limit` point estimate 양수 (fired > not-fired) 안정적 — §3.7 downside-predictive 가설과 **반대 sign**. CI 0 가로지름이나 wrong-sign 은 sample size 로 해결 안 됨 — point 가 음수 flip 해야 CI_upper<0 가능.

## Prudential vs predictive 축 분리 (필수 인용 규칙)

`position_limit` / `sector_limit` / `leverage_ban` 는 **prudential portfolio constraints + user-preference defaults** 로 유효 — 사용자 감정 통제, STRATEGY §7 자동 매매 deferred, O'Neil/Minervini lineage.

**그러나 synthetic audit 은 forward-downside-predictive gate 로 기능한다는 주장 미증명**. rule 은 prudential 근거로만 인용, downside-predictive framing 은 §3.8 에서 tentatively refuted 로 인용.

## 재활성화 조건

이 route 재실행은 의미 없음. 다음 중 하나 충족 시 새 Plan consult + STRATEGY 개정:

1. **Actual-portfolio replay** — tracker outcomes 누적 후 real-history 기반 측정
2. **§2.6 Symmetric amplifier** 이후 upside-measurement 전용 경로 설계
3. **audit design 근본 redesign** — variant ladder × momentum snapshot 외 source

v1 → v2 narrative + 재설계 이유 (#417 closure): `gh pr view 443` / `codex-reviews/PRe4-0b-v2-roundplan-20260421T175538Z.md`.
