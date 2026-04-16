# nuri/trading/engine/ — SIEGE Gated Execution

## SIEGE v2 Architecture (2026-04-13~)

v2는 3차원 인증 모델: **Account(계좌 전략) × Asset Class(노출 기준) × Execution Market(실행 시장)**. 상세 설계: `docs/SIEGE_V2.md`.

### 원본 SIEGE 생태계 반영 (nutshells3)
- **Gate 정책은 `config/rules.yaml`의 `siege_gates` 섹션** — 코드에 임계값 하드코딩 금지 (§2.2)
- **자산 클래스별 gate**: us_equity(SPY/VIX), kr_equity(KOSPI/USD-KRW), commodity(GC=F), bond(TLT), kr_index(KOSPI)
- **계좌별 전략**: `account_strategies`의 stop_loss/position_limit이 gate에 자동 적용
- **Evidence 추적**: 각 gate 결과에 증거(source, value, threshold, policy_ref) 연결 (OAE 패턴)

## Confidence Scoring Formula

```
base = regime_win_rate * 60% + profit_factor * 40%
     * drift_multiplier (0.3 ~ 1.1)        <- Learning Memory
     * conflict_penalty (0.5x if high)      <- Conflict Detection
     * regime_fit_penalty (0.4x if avoid)    <- Strategy Map
     * position_penalty (0.3x if minimal)    <- Regime position sizing
     * vix_gate (0x if blocked, 0.5x caution)
```

Phase 4 (safeslice 패턴): `drift_multiplier`를 통계적 신뢰 구간(Wilson CI + witness cliff)으로 대체 예정.

## SIEGE Gate Specification (v2)

All recommendations must pass. 1 error-grade failure = REJECTED. `Certificate.certified` = error severity 0건 기준.

**v2 expansion (#248, PR #312)**: Gate 5/7/8 은 portfolio 를 `asset_class` 로 group
한 뒤 per-class 정책 (`config/rules.yaml` `siege_gates`) 적용. 따라서 실행 시 실제
`total_conditions` 는 portfolio 구성에 따라 **11 ~ 30+ 가변**. 예: US + KR + ETF
혼합 포트폴리오면 us_equity/kr_equity/kr_index/commodity/bond 5 class × 3 gate =
15 + 비asset 8 = 23 condition 발행. secondary spillover 지표 (예: KR 보유 시 VIX
spillover) 는 추가 warning.

| # | Condition | Grade | Threshold | v2 변경 |
|---|-----------|-------|-----------|---------|
| 1 | position_limit | error | Per-account strategy | 계좌별 + 전체 이중 체크 |
| 2 | sector_limit | error | Per-account strategy | 계좌별 전략 기준 |
| 3 | stop_loss_growth | error | Per-account strategy | 기존 유지 |
| 4 | stop_loss_value | error | Per-account strategy | 기존 유지 |
| 5 | data_fresh | warning | **Per-asset-class** primary + secondary | ✅ 구현 (#312): us=SPY / kr_equity=KOSPI+[SPY spillover] / kr_index=KOSPI+[SPY] / commodity=GC=F / bond=TLT |
| 6 | leverage_ban | error | No TSLL/TQQQ etc. | 기존 유지 |
| 7 | volatility_gate (구 vix_gate) | warning | **Per-asset-class** primary + secondary | ✅ 구현 (#312): us=VIX / kr_equity=USD/KRW_3d+[VIX] / kr_index=KOSPI_3d+[USD/KRW] / commodity=gold_3d |
| 8 | external_data | warning | **Per-asset-class** threshold + ticker filter | ✅ 구현 (#312): us ≥ 10/3, kr_equity ≥ 5/2 (ticker IN 쿼리로 실제 카운트) |
| 9 | conflict_free | warning | No BUY/SELL conflict | 기존 유지 |
| 10 | drift_safe | warning | No critical drift | 기존 유지 |
| 11 | macro_event_alignment | warning | \|event_score\| >= 10 alert | 기존 유지 (asset-class matrix 는 별도 PR 예정) |

**Legacy fallback**: empty portfolio 또는 `siege_gates` 설정 부재 시 Gate 5/7/8 은
구 SPY/VIX 단일 체크로 안전하게 돌아감.

## Execution Priority

Mechanical ordering: `stop_loss -> take_profit -> trailing_stop_set -> new_buy`
- Within stop_loss: sort by loss% desc (biggest loss first)
- Within take_profit: sort by excess% desc (biggest winner first)
- Rationale: declining momentum loses more per hour delayed; rising momentum is forgiving
