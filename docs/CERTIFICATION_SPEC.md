# Certification Spec (SIEGE v2) — 3-Dimensional Gated Execution

> 원본 SIEGE 생태계(nutshells3) 6개 레포 분석을 바탕으로 재설계한 인증 사양이다. 구현(`nuri/trading/engine/certification.py`)은 이 문서를 따른다.

## 1. v1 한계 → v2 해결

| 한계 (v1) | 상태 | 해결 경로 |
|---|---|---|
| 포트폴리오 전체 1회 인증 (ticker 구분 없음) | ✅ shipped (PR #312) | `_group_holdings_by_asset_class` → asset_class 별 gate 5/7/8 분기 |
| 하드코딩 임계값 (VIX 30, SPY 72h 등) | ✅ shipped | `config/rules.yaml siege_gates.asset_classes.<class>` 외부화. STRATEGY §2.2 위반 해소 |
| US 중심 gate (한국 종목도 VIX/SPY 기준) | ✅ shipped | kr_equity primary=KOSPI/USD-KRW, secondary=SPY/VIX spillover |
| 이진 판정 (CERTIFIED / REJECTED) | ⏳ Phase 3 backlog | 5단계 safety lattice (GUARDED/REVIEW_REQUIRED), 미착수 |
| 증거 추적 없음 | ⏳ Phase 2 backlog | evidence field + claim trace, 미착수 |

## 2. 외부 패턴 채택

| 출처 | 패턴 | 적용 |
|---|---|---|
| SIEGE core (planning-engine) | Gate = typed condition + severity + policy-driven | YAML 외부화 ✅ |
| SIEGE core (recursive-improvement) | Failure memory + reuse/adapt/avoid signal | Phase 5 backlog |
| SIEGE core (safety_gates.rs) | 5단계 safety lattice | Phase 3 backlog |
| OAE (orchestration-assurance-engine) | Claim trace — 증거 + gap 감지 | Phase 2 backlog (evidence 필드) |
| fwp (formal-workbench-protocol) | Protocol seam — 무엇 vs 어떻게 분리 | 신호 생성 ↔ 검증 분리 ✅ |
| safeslice | 통계적 신뢰 구간 + witness cliff | Phase 4 backlog (drift_multiplier 대체) |

## 3. 3-Dimensional 인증 모델

```
Dimension 1: Account (계좌 전략 프로파일) — config/rules.yaml account_strategies
  ├── core      → -7% SL, 15% pos, 35% sector  (기본)
  ├── active    → -10% SL, 25% pos, 45% sector · trailing_stop_arm +15%
  ├── swing     → -15% SL, 30% pos, 50% sector
  ├── long_term → -20% SL, 25% pos, 50% sector
  └── pension   → -30% SL, 40% pos, 60% sector

Dimension 2: Asset Class (노출 기준, 실행 시장 아님)
  ├── us_equity     → SPY 신선도, VIX gate
  ├── kr_equity     → KOSPI 신선도, USD/KRW 변동성 gate
  ├── commodity     → GC=F 신선도, gold 변동성 gate
  ├── bond          → TLT 신선도, yield 변동성 gate
  └── kr_index      → KOSPI 신선도, KOSPI 변동성 gate

Dimension 3: Execution Market (실행 시장)
  ├── KRX           → 09:00-15:30 KST
  └── NYSE          → 09:30-16:00 ET (21:30-05:00 KST)
```

### 핵심 규칙

1. **Asset class 는 섹터와 ticker 로 결정한다** (실행 시장이 아니다). ETF 섹터 prefix 는 해당 class, `.KS`/`.KQ` 비-ETF 는 kr_equity, 나머지는 us_equity 로 분류한다.
2. **같은 종목이 여러 계좌에 있으면 계좌마다 해당 계좌 전략을 적용한다**: 예) 005930.KS 가 brokerage_alpha(core, -7%)와 brokerage_beta(long_term, -20%)에 있으면 손절 기준이 각각 다르다.
3. **전체 포트폴리오 cross-account 합산**: `_check_position_limits` 는 동일 ticker 의 비중을 계좌 전체에서 합산하고, 그 ticker 를 보유한 계좌들의 `max_single_position` 중 가장 관대한 값(regime multiplier 적용)과 비교한다. 별도의 전역 상한(`position_limits.total_portfolio`)은 Phase 2 backlog 다.
4. **환헤지 분기**: Phase 2 backlog. 현재 `_check_macro_event_alignment` 에는 hedge 분기가 없다.

## 4. config/rules.yaml siege_gates 스키마

정본은 `config/rules.yaml siege_gates` 다. 이 문서는 구조만 기술하며 실제 값은 config 를 따른다. Phase 1(PR #312)에서 배선 완료:

- `asset_class_rules` — 위에서부터 순서대로 matching 하므로 더 구체적인 rule 을 위에 둔다
- `asset_classes.<class>` — primary + secondary 지표 (cross-market spillover)
  - `freshness_primary` / `freshness_secondary` / `freshness_max_hours`
  - `volatility_primary` + threshold / `volatility_secondary` + threshold
  - external 게이트: `external_applicable: false` 인 class 는 N/A 로 통과한다(애널리스트 컨센서스/13F 가 적용되지 않는 commodity/bond/kr_index, `external_min_*` 미지정). 적용 class(us_equity/kr_equity)는 `external_min_records` / `external_min_sources` 로 평가한다.

**Phase 2 backlog** (`config/rules.yaml` 미배선, 사양만 존재):

- `hedge_status` (per-ticker) — currency_shift 분기용
- `position_limits.total_portfolio` + `total_max_single` — cross-account 합산 상한
- `execution_markets.{KRX,NYSE}.hours/timezone` — 시장 개장 gate

## 5. certify() 흐름 (Phase 1 — 실제 구현)

`nuri/trading/engine/certification.py` 의 `ALL_CERT_CHECKS` 정의와 `certify()`(결과 flatten).

11개 base check 함수: position_limits / sector_limits / stop_loss_compliance / data_freshness (per-class list) / leverage_ban / volatility_gates (per-class list) / external_data (per-class list) / conflicts / drift_safety / macro_event_alignment / rules_loaded.

**핵심**:

- Gate 5/7/8 은 `_group_holdings_by_asset_class` 를 호출해 asset_class 별 primary + secondary `CertCondition` 을 만든다.
- `certify()` 는 list 결과를 flatten 하므로 `total_conditions` 는 포트폴리오 구성에 따라 달라진다(11 ~ 30+).
- `certified` 는 severity `error` 실패가 0건일 때 참이다. warning 은 집계만 한다.

## 6. 매크로 이벤트 × asset class 매트릭스 (Phase 2 backlog)

현재 `_check_macro_event_alignment` 는 `|event_score| ≥ 10` 단순 threshold 다. asset_class 별 가중치는 미배선이며, Phase 2 에서 `config/macro_impacts.yaml` 로 외부화하고 per-class 체크로 확장한다.

설계 의도 매트릭스 (이벤트 × class 가중치, ±range):

| 이벤트 | us_equity | kr_equity | commodity | bond |
|---|---|---|---|---|
| geopolitical_escalation / de-escalation | ∓0.6 / ±0.5 | ∓0.4 / ±0.3 | ±0.5 / ∓0.3 | ±0.3 / ∓0.2 |
| fed_dovish / hawkish | ±0.6 / ∓0.5 | ±0.3 / ∓0.3 | ±0.4 / ∓0.3 | ∓0.5 / ±0.4 |
| oil_supply_shock | -0.3 | -0.4 | +0.7 | +0.2 |
| export_surge / demand_growth | +0.2 / +0.4 | +0.65 / +0.55 | 0 / +0.2 | 0 / 0 |
| currency_shift / trade_war | ±0.2 / -0.5 | ±0.35 / -0.7 | ±0.3 / +0.3 | ±0.1 / +0.2 |

## 7. 구현 Phase 로드맵

| Phase | 내용 | 선행 | 상태 |
|---|---|---|---|
| **1** | Gate 정책 YAML 외부화 + certification.py 리팩토링 | — | ✅ PR #312 (issue #248) |
| **2** | Gate evidence 필드 + claim trace (OAE 패턴) + macro impact matrix 배선 | Phase 1 | ⏳ backlog |
| **3** | Safety lattice 5단계 (CERTIFIED → GUARDED → REVIEW_REQUIRED → BLOCKED → REJECTED) | Phase 2 | ⏳ backlog |
| **4** | safeslice 통계적 신뢰 구간 (drift_multiplier → Wilson CI + witness cliff) | Phase 3 | ⏳ backlog |
| **5** | Recursive improvement (failure memory + reuse signal) | Phase 4 | ⏳ backlog |

**Phase 1 deliverables (shipped, #312)**:

- `config/rules.yaml siege_gates` (asset_class_rules + per-class policies)
- `nuri/trading/engine/certification.py`: `_classify_asset_class`, `_group_holdings_by_asset_class`, per-class gate 5/7/8
- Cross-market spillover (primary + secondary 구조)
- Legacy fallback (빈 portfolio / 설정 부재)
- Tests: `TestAssetClassification` (4) + `TestAssetClassGates` (10)

Phase 2-5 의 상세 사양은 필요한 시점에 이 문서를 확장하거나 별도 issue 본문에 작성한다. 미배선 사양이 낡지 않도록 현재는 backlog 항목만 기재한다.
