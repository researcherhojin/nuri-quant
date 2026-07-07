# Certification Spec (SIEGE v2) — 3-Dimensional Gated Execution

> 원본 SIEGE 생태계 (nutshells3) 6 개 레포 분석 기반 재설계. 이 문서는 구현 권위 참조 — 코드 (`nuri/trading/engine/certification.py`) 는 본문을 따른다.

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

1. **Asset class 결정 = 섹터 + ticker** (시장 아님): ETF 섹터 prefix → 해당 class / `.KS`/`.KQ` + 비-ETF → kr_equity / 나머지 → us_equity fallback
2. **같은 종목 다른 계좌면 각각 계좌 전략 적용**: 005930.KS in brokerage_alpha (core, -7%) ≠ in toss (long_term, -20%)
3. **전체 포트폴리오 cross-account 합산**: 동일 ticker 여러 계좌 → position_pct 합산 (현재 per-account 만 — 전역 합산은 Phase 2 backlog)
4. **환헤지 분기**: Phase 2 backlog. 현재 `_check_macro_event_alignment` 는 hedge 분기 미포함

## 4. config/rules.yaml siege_gates 스키마

**canonical source**: `config/rules.yaml siege_gates` — 본 doc 은 shape 만, 실제 값은 config 가 진실. Phase 1 (PR #312) 이미 shipped:

- `asset_class_rules` — 순서대로 matching, 더 구체적 rule 우선
- `asset_classes.<class>` — primary + secondary 지표 (cross-market spillover)
  - `freshness_primary` / `freshness_secondary` / `freshness_max_hours`
  - `volatility_primary` + threshold / `volatility_secondary` + threshold
  - external 게이트: `external_applicable:false` 면 N/A vacuous pass(애널리스트 컨센서스/13F 비적용 자산군 commodity/bond/kr_index — 해당 class 는 `external_min_*` 미지정). 적용 class(us_equity/kr_equity)는 `external_min_records` / `external_min_sources` 로 평가

**Phase 2 backlog** — `config/rules.yaml` 미배선 (spec only):
- `hedge_status` (per-ticker) — currency_shift 분기용
- `position_limits.total_portfolio` + `total_max_single` — cross-account 합산 상한
- `execution_markets.{KRX,NYSE}.hours/timezone` — 시장 개장 gate

## 5. certify() 흐름 (Phase 1 — 실제 구현)

`nuri/trading/engine/certification.py:739` (`ALL_CERT_CHECKS` def) + `:861` (`certify()` flatten).

11 base check 함수: position_limits / sector_limits / stop_loss_compliance / **data_freshness** (per-class list) / leverage_ban / **volatility_gates** (per-class list) / **external_data** (per-class list) / conflicts / drift_safety / macro_event_alignment / rules_loaded.

**핵심**:
- Gate 5/7/8 가 `_group_holdings_by_asset_class` 호출 → asset_class 별 primary + secondary CertCondition emit
- `certify()` 는 list flatten → `total_conditions` portfolio 구성 따라 가변 (11 ~ 30+)
- `certified = failed(error) == 0`. warning 은 누적만 (소프트 panel)

## 6. 매크로 이벤트 × asset class 매트릭스 (Phase 2 backlog)

현재 `_check_macro_event_alignment` (certification.py:688) 는 `|event_score| ≥ 10` 단순 threshold. asset_class 별 가중치는 미배선 — Phase 2 작업 시 `config/macro_impacts.yaml` 외부화 + per-class 체크 확장.

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

Phase 2-5 spec 상세 sketch 가 필요한 시점에 본 문서 확장 OR 별 issue 본문에 작성. 현재 본문은 backlog 만 명시 — 미배선 spec 의 stale risk 차단.
