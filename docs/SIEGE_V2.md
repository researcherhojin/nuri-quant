# SIEGE v2 — 자산 클래스 기반 3차원 인증 아키텍처

> 원본 SIEGE 생태계(nutshells3) 6개 레포 분석 기반 재설계.
> 이 문서는 구현의 권위 있는 참조. 코드는 이 문서를 따른다.

## 1. v1 한계 → v2 해결 상태

| 한계 (v1) | 상태 | 해결 경로 |
|-----------|------|----------|
| 포트폴리오 전체 1회 인증 (ticker 구분 없음) | ✅ **해결** (Phase 1, PR #312) | `_group_holdings_by_asset_class` 로 asset_class 별 gate 5/7/8 분기 |
| 하드코딩 임계값 (VIX 30, SPY 72h 등) | ✅ **해결** (Phase 1, PR #312) | `config/rules.yaml siege_gates.asset_classes.<class>` 로 외부화. STRATEGY §2.2 위반 해소 |
| US 중심 gate (한국 종목도 VIX/SPY 기준) | ✅ **해결** (Phase 1, PR #312) | kr_equity primary=KOSPI/USD-KRW, secondary=SPY/VIX spillover |
| 이진 판정 (CERTIFIED / REJECTED) | ⏳ **미해결** | Phase 3 (safety lattice 5단계 GUARDED/REVIEW_REQUIRED) 대상, 미착수 |
| 증거 추적 없음 | ⏳ **미해결** | Phase 2 (evidence field + claim trace) 대상, 미착수 |

## 2. 원본 SIEGE 생태계에서 채택한 패턴

| 출처 | 패턴 | 적용 |
|------|------|------|
| SIEGE core (planning-engine) | Gate는 typed condition + severity + policy-driven | Gate 정책 YAML 외부화 |
| SIEGE core (recursive-improvement) | Failure memory + reuse/adapt/avoid signal | Phase 5 (후속) |
| SIEGE core (safety_gates.rs) | 5단계 safety lattice | Phase 3 (후속) |
| OAE (orchestration-assurance-engine) | Claim trace — 증거 연결 + gap 감지 | Gate evidence 필드 |
| fwp (formal-workbench-protocol) | Protocol seam — "무엇을" vs "어떻게" 분리 | 신호 생성 ↔ 신호 검증 분리 |
| safeslice | 통계적 신뢰 구간 + witness cliff 감지 | Phase 4 — drift_multiplier 대체 |

## 3. 3차원 인증 모델

```
Dimension 1: Account (계좌 전략 프로파일)
  Strategy 은 config/rules.yaml account_strategies 에 정의된 5 종 — 계좌
  이름은 사용자별 portfolio.yaml 에서 매핑 (account.strategy 필드).
  │
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

1. **자산 클래스는 섹터 + 티커로 결정** (시장 아님):
   - ETF 섹터 prefix (`ETF/USIndex`, `ETF/Commodity` 등) → 해당 자산 클래스
   - `.KS`/`.KQ` 접미사 + 비-ETF 섹터 → `kr_equity`
   - 나머지 → `us_equity` (fallback)
   
2. **같은 종목이 다른 계좌에 있으면 각각 계좌 전략 적용**:
   - 삼성전자 in brokerage_alpha (core, -7%) ≠ 삼성전자 in toss (long_term, -20%)
   
3. **전체 포트폴리오 노출 합산 체크**:
   - 예: 동일 ticker 가 여러 계좌 에 있으면 position_pct 합산 → 계좌 한도 + 전역 한도 둘 다 체크
   - 현재 `_check_position_limits` 는 계좌별 per_position_max 만 체크. 전역 `total_max_single` 은 Phase 2 proposed 스키마 (§4).

4. **환헤지 여부 분기** (**Phase 2 proposed — 현재 미구현**):
   - `hedge_status` 스키마는 §4 에 sketch. 현재 `_check_macro_event_alignment` 는 hedge 여부 분기 안 함.

## 4. config/rules.yaml 스키마

### 4.1 Phase 1 shipped (PR #312) — 실제 `config/rules.yaml siege_gates` 에 존재

**canonical source**: `config/rules.yaml` (doc 은 snippet, config 가 최신).

```yaml
siege_gates:
  asset_class_rules:                    # 순서대로 matching, 더 구체적인 rule 우선
    - match: {sector_prefix: "ETF/USIndex"}
      asset_class: us_equity
    - match: {sector_prefix: "ETF/USTech"}
      asset_class: us_equity
    - match: {sector_prefix: "ETF/Commodity"}
      asset_class: commodity
    - match: {sector_prefix: "ETF/Bond"}
      asset_class: bond
    - match: {sector_prefix: "ETF/KRIndex"}
      asset_class: kr_index
    - match: {ticker_suffix: ".KS"}
      asset_class: kr_equity
    - match: {ticker_suffix: ".KQ"}
      asset_class: kr_equity
    - match: {sector: "ETF"}
      asset_class: us_equity
    - match: {default: true}
      asset_class: us_equity

  asset_classes:                        # primary + secondary 지표 구조 (cross-market spillover)
    us_equity:
      freshness_primary: SPY
      freshness_secondary: []
      freshness_max_hours: 72
      volatility_primary: vix
      volatility_primary_threshold: 30
      volatility_secondary: []
      external_min_records: 10
      external_min_sources: 3
    kr_equity:
      freshness_primary: KOSPI
      freshness_secondary: [SPY]        # US leader spillover
      freshness_max_hours: 72
      volatility_primary: usd_krw_3d_change
      volatility_primary_threshold: 3.0
      volatility_secondary: [vix]
      volatility_secondary_threshold: 30
      external_min_records: 5
      external_min_sources: 2
    kr_index:
      freshness_primary: KOSPI
      freshness_secondary: [SPY]
      freshness_max_hours: 72
      volatility_primary: kospi_3d_change
      volatility_primary_threshold: 5.0
      volatility_secondary: [usd_krw_3d_change]
      volatility_secondary_threshold: 3.0
      external_min_records: 3
      external_min_sources: 1
    commodity:
      freshness_primary: "GC=F"
      freshness_max_hours: 72
      volatility_primary: gold_3d_change
      volatility_primary_threshold: 5.0
      external_min_records: 3
      external_min_sources: 1
    bond:
      freshness_primary: TLT
      freshness_max_hours: 120
      volatility_primary: yield_3d_change
      volatility_primary_threshold: 0.3
      external_min_records: 3
      external_min_sources: 1
```

### 4.2 Phase 2 proposed — **미착수, config 에 없음**

아래 스키마는 spec 용 sketch. 실제 `config/rules.yaml` 에는 존재하지 않으며 `certify()` 도 참조하지 않는다. Phase 2 작업 시 이 스키마를 기준으로 확장한다.

```yaml
# Phase 2 proposed — 현재 config/rules.yaml 에 NOT present
siege_gates:
  hedge_status:                         # §6 macro impact 의 currency_shift 분기용
    "448300.KS": hedged
    "132030.KS": hedged
    "381170.KS": unhedged

  position_limits:                      # 전체 포트폴리오 cross-account 합산 체크
    per_account: true                   # 기존 per-account (shipped)
    total_portfolio: true               # NEW — 동일 ticker 여러 계좌 합산
    total_max_single: 20                # NEW — 전역 단일 종목 상한

  execution_markets:                    # 시장 개장 시간 gate (Phase 3 후보)
    KRX:
      hours: "09:00-15:30"
      timezone: "Asia/Seoul"
    NYSE:
      hours: "09:30-16:00"
      timezone: "US/Eastern"
```

## 5. certify() 흐름 (v2 — 실제 구현)

**실제 코드**: `nuri/trading/engine/certification.py:553-601` (ALL_CERT_CHECKS def + certify() flatten). Phase 1, PR #312.

```python
# 모든 gate 함수는 CertCondition 또는 list[CertCondition] 반환.
# per-asset-class gate (5/7/8) 는 내부에서 portfolio 를 group 하고 list 반환.
ALL_CERT_CHECKS = [
    _check_position_limits,          # 1. 계좌별 single-position 한도
    _check_sector_limits,            # 2. 섹터 비중
    _check_stop_loss_compliance,     # 3-4. 계좌별 strategy stop_loss
    _check_data_freshness,           # 5. → list (per-class primary + secondary)
    _check_leverage_ban,             # 6. LEVERAGE_ETFS 보유 금지
    _check_volatility_gates,         # 7. → list (per-class primary + secondary)
    _check_external_data,            # 8. → list (per-class record/source minimum)
    _check_conflicts,                # 9. BUY/SELL 충돌
    _check_drift_safety,             # 10. critical drift 없음
    _check_macro_event_alignment,    # 11. |event_score| ≥ 10 alert
    _check_rules_loaded,             # sanity
]

def certify(db_path=None) -> Certificate:
    conditions: list[CertCondition] = []
    for check in ALL_CERT_CHECKS:
        result = check(db_path=db_path)
        if isinstance(result, list):
            conditions.extend(result)     # per-class flatten
        else:
            conditions.append(result)
    failed = sum(1 for c in conditions if not c.passed and c.severity == "error")
    certified = failed == 0               # error 0건이면 CERTIFIED
    return Certificate(..., conditions=conditions, certified=certified)
```

**핵심**:
- Gate 5 / 7 / 8 가 `_group_holdings_by_asset_class` 호출 → asset_class 별로 policy 읽고 primary + secondary 각각 CertCondition emit.
- `certify()` 는 이 list 를 flatten → 최종 `total_conditions` 는 portfolio 구성에 따라 가변 (11 ~ 30+).
- `certified = failed(error) == 0`. warning 은 누적만.
- Phase 2 의 per-account × per-class 이중 loop (기존 §5 pseudocode 에 있던 것) 는 **미구현** — 현재 gate 함수들은 portfolio 전체를 한 번에 훑는 shape.

## 6. 매크로 이벤트 교차 영향 매트릭스 (**Phase 2 proposed — 미구현**)

> 현재 `_check_macro_event_alignment` (certification.py:502) 는 `|event_score| ≥ 10` 단순 threshold 알람만 emit. 아래 매트릭스는 asset_class × event type 가중치 sketch — 실제 가중치는 코드/config 어디에도 배선 안 됨. Phase 2 작업 시 `config/macro_impacts.yaml` 로 외부화하고 `_check_macro_event_alignment` 를 per-asset-class 체크로 확장한다.

이벤트가 자산 클래스별로 다른 방향으로 작용 (설계 의도):

| 이벤트 | us_equity | kr_equity | commodity | bond |
|--------|-----------|-----------|-----------|------|
| geopolitical_escalation | -0.6 | -0.4 | +0.5 | +0.3 |
| geopolitical_de_escalation | +0.5 | +0.3 | -0.3 | -0.2 |
| fed_dovish | +0.6 | +0.3 | +0.4 | -0.5 |
| fed_hawkish | -0.5 | -0.3 | -0.3 | +0.4 |
| oil_supply_shock | -0.3 | -0.4 | +0.7 | +0.2 |
| export_surge | +0.2 | +0.65 | 0 | 0 |
| demand_growth | +0.4 | +0.55 | +0.2 | 0 |
| currency_shift | ±0.2 | ±0.35 | ±0.3 | ±0.1 |
| trade_war | -0.5 | -0.7 | +0.3 | +0.2 |

향후 `config/macro_impacts.yaml`로 외부화.

## 7. 구현 Phase

| Phase | 내용 | 선행 | 상태 |
|-------|------|------|------|
| **1** | Gate 정책 YAML 외부화 + certification.py 리팩토링 | — | ✅ **완료** (PR #312, issue #248) |
| **2** | Gate evidence 필드 + claim trace (OAE 패턴) | Phase 1 | 미착수 |
| **3** | Safety lattice 5단계 (CERTIFIED → GUARDED → REVIEW_REQUIRED → BLOCKED → REJECTED) | Phase 2 | 미착수 |
| **4** | safeslice 통계적 신뢰 구간 (drift_multiplier → Wilson CI + witness cliff) | Phase 3 | 미착수 |
| **5** | Recursive improvement (failure memory + reuse signal) | Phase 4 | 미착수 |

**Phase 1 deliverables (#312)**:
- `config/rules.yaml` `siege_gates` section (asset_class_rules + per-class policies)
- `nuri/trading/engine/certification.py`: `_classify_asset_class`, `_group_holdings_by_asset_class`, per-class gate 5/7/8
- Cross-market spillover (primary + secondary 지표 구조)
- Legacy fallback (빈 portfolio / 설정 부재)
- Tests: `TestAssetClassification` (4) + `TestAssetClassGates` (7)

**Phase 1 scope out** (후속 PR 후보): Gate #11 macro event asset-class matrix (§6 표).
