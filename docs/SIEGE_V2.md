# SIEGE v2 — 자산 클래스 기반 3차원 인증 아키텍처

> 원본 SIEGE 생태계(nutshells3) 6개 레포 분석 기반 재설계.
> 이 문서는 구현의 권위 있는 참조. 코드는 이 문서를 따른다.

## 1. 현재 상태 (v1)의 한계

| 한계 | 설명 |
|------|------|
| 포트폴리오 전체 1회 인증 | `certify()`에 ticker 파라미터 없음. 한국/미국/원자재 구분 없이 동일 gate |
| 하드코딩 임계값 | VIX 30, SPY 72h 등이 `certification.py`에 상수. §2.2 위반 |
| US 중심 gate | VIX gate로 한국 종목 매수 차단, SPY 신선도로 한국 종목 판정 |
| 이진 판정 | CERTIFIED/REJECTED만. 중간 단계 없음 |
| 증거 추적 없음 | pass/fail만 기록, 왜 통과/실패했는지 lineage 없음 |

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
Dimension 1: Account (계좌 전략)
  ├── brokerage_alpha      → core    (-7% SL, 15% pos)
  ├── brokerage_alpha_sub  → active  (-10% SL, 25% pos)
  ├── toss          → long_term (-20% SL, 25% pos)
  └── pension       → pension (-30% SL, 40% pos)

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
   
3. **전체 포트폴리오 노출도 별도 체크**:
   - NVDA: brokerage_alpha 8.3% + sub 6.1% = 14.4% → total_max_single 20% 이내

4. **환헤지 여부는 ETF metadata에서 결정**:
   - (H) ETF: `currency_shift` 이벤트 무관
   - 언헤지 ETF: `currency_shift` 이벤트 영향

## 4. config/rules.yaml 추가 스키마

```yaml
siege_gates:
  asset_class_rules:
    - match: { sector_prefix: "ETF/USIndex" }
      asset_class: us_equity
    - match: { sector_prefix: "ETF/USTech" }
      asset_class: us_equity
    - match: { sector_prefix: "ETF/Commodity" }
      asset_class: commodity
    - match: { sector_prefix: "ETF/Bond" }
      asset_class: bond
    - match: { sector_prefix: "ETF/KRIndex" }
      asset_class: kr_index
    - match: { sector: "ETF" }
      asset_class: us_equity
    - match: { ticker_suffix: ".KS" }
      asset_class: kr_equity
    - match: { ticker_suffix: ".KQ" }
      asset_class: kr_equity
    - match: { default: true }
      asset_class: us_equity

  asset_classes:
    us_equity:
      freshness_ticker: SPY
      freshness_max_hours: 72
      volatility_indicator: vix
      volatility_block: 30
      external_min_records: 10
      external_min_sources: 3
    kr_equity:
      freshness_ticker: KOSPI
      freshness_max_hours: 72
      volatility_indicator: usd_krw_3d_change
      volatility_block: 3.0
      external_min_records: 5
      external_min_sources: 2
    commodity:
      freshness_ticker: GC=F
      freshness_max_hours: 72
      volatility_indicator: gold_3d_change
      volatility_block: 5.0
      external_min_records: 3
      external_min_sources: 1
    bond:
      freshness_ticker: TLT
      freshness_max_hours: 120
      volatility_indicator: yield_3d_change
      volatility_block: 0.3
      external_min_records: 3
      external_min_sources: 1
    kr_index:
      freshness_ticker: KOSPI
      freshness_max_hours: 72
      volatility_indicator: kospi_3d_change
      volatility_block: 5.0
      external_min_records: 3
      external_min_sources: 1

  hedge_status:
    "448300.KS": hedged
    "448290.KS": hedged
    "132030.KS": hedged
    "381170.KS": unhedged
    "447660.KS": hedged

  position_limits:
    per_account: true
    total_portfolio: true
    total_max_single: 20

  execution_markets:
    KRX:
      hours: "09:00-15:30"
      timezone: "Asia/Seoul"
    NYSE:
      hours: "09:30-16:00"
      timezone: "US/Eastern"
```

## 5. certify() 흐름 (v2)

```python
def certify(db_path=None) -> Certificate:
    accounts = _load_portfolio_by_account(db_path)
    gate_config = load_siege_gates_config()  # config/rules.yaml
    all_conditions = []

    # 1. 계좌별 × 자산 클래스별 gate
    for account_name, holdings in accounts.items():
        strategy = get_account_strategy(account_name)
        for asset_class, tickers in _group_by_asset_class(holdings, gate_config).items():
            policy = gate_config["asset_classes"][asset_class]
            all_conditions.append(_check_freshness(asset_class, policy, db_path))
            all_conditions.append(_check_volatility(asset_class, policy, db_path))
            all_conditions.append(_check_external_data(asset_class, policy, db_path))
        # 계좌별 규칙 gate
        all_conditions.append(_check_position_limit(account_name, strategy, holdings, db_path))
        all_conditions.append(_check_stop_loss(account_name, strategy, db_path))

    # 2. 전체 포트폴리오 gate
    if gate_config["position_limits"]["total_portfolio"]:
        all_conditions.append(_check_total_position_limit(gate_config, db_path))

    # 3. 공통 gate (자산 클래스 무관)
    all_conditions.append(_check_leverage_ban(db_path))
    all_conditions.append(_check_conflicts(db_path))
    all_conditions.append(_check_drift_safety(db_path))
    all_conditions.append(_check_macro_event_alignment(db_path))
    all_conditions.append(_check_rules_loaded(db_path))
    ...
```

## 6. 매크로 이벤트 교차 영향 매트릭스

이벤트가 자산 클래스별로 다른 방향으로 작용:

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

| Phase | 내용 | 선행 |
|-------|------|------|
| **1** | Gate 정책 YAML 외부화 + certification.py 리팩토링 | — |
| **2** | Gate evidence 필드 + claim trace (OAE 패턴) | Phase 1 |
| **3** | Safety lattice 5단계 (CERTIFIED → GUARDED → REVIEW_REQUIRED → BLOCKED → REJECTED) | Phase 2 |
| **4** | safeslice 통계적 신뢰 구간 (drift_multiplier → Wilson CI + witness cliff) | Phase 3 |
| **5** | Recursive improvement (failure memory + reuse signal) | Phase 4 |
