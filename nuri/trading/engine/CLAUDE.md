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

## SIEGE 11-Gate Specification

All recommendations must pass. 1 error-grade failure = REJECTED.

| # | Condition | Grade | Threshold | v2 변경 |
|---|-----------|-------|-----------|---------|
| 1 | position_limit | error | Per-account strategy | v2: 계좌별 + 전체 이중 체크 |
| 2 | sector_limit | error | Per-account strategy | v2: 계좌별 전략 기준 |
| 3 | stop_loss_growth | error | Per-account strategy | 기존 유지 |
| 4 | stop_loss_value | error | Per-account strategy | 기존 유지 |
| 5 | data_fresh | warning | Per-asset-class ticker | v2: SPY or KOSPI or GC=F |
| 6 | leverage_ban | error | No TSLL/TQQQ etc. | 기존 유지 |
| 7 | vix_gate | warning | Per-asset-class indicator | v2: VIX or USD/KRW or gold vol |
| 8 | external_data | warning | Per-asset-class threshold | v2: 자산별 기준 분리 |
| 9 | conflict_free | warning | No BUY/SELL conflict | 기존 유지 |
| 10 | drift_safe | warning | No critical drift | 기존 유지 |
| 11 | macro_event_alignment | warning | \|event_score\| >= 10 alert | 기존 유지 |

## Execution Priority

Mechanical ordering: `stop_loss -> take_profit -> trailing_stop_set -> new_buy`
- Within stop_loss: sort by loss% desc (biggest loss first)
- Within take_profit: sort by excess% desc (biggest winner first)
- Rationale: declining momentum loses more per hour delayed; rising momentum is forgiving
