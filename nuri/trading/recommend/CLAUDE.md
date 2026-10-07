# nuri/trading/recommend/ — Recommendation Emitters

## Scope

The user-facing output layer: BUY candidates, SELL alerts on holdings, price targets, rebalance actions, and outcome tracking. Per STRATEGY §7.1 this directory **emits recommendations only** — it never submits orders. Output formats: markdown brief, DB row, Discord alert.

## Files

| File | Purpose | Trigger | Issue |
|---|---|---|---|
| `buy_candidate_emitter.py` | Daily 0–5 BUY candidates from factor + momentum + RSI + breakout fusion. Closes the sell-bias gap (7+ sell loops, 0 buy loops). `evaluate_universe` 는 읽기 전용 채점·게이트(종목별 disposition) — `emit_buy_candidates` 와 `/api/opportunities` 의 `system` 이 이 한 경로를 공유한다 (#1683). | `python -m nuri.trading.recommend.buy_candidate_emitter` / scheduler premarket brief (`nuri/alerts/premarket_brief.py`) | #507 |
| `holdings_monitor.py` | Post-entry technical-divergence alert (JKHY-class falling-knife defense). REVIEW CTA, never SELL. | scheduler 07:10 KST | PR #303 follow-up |
| `held_add.py` | Held-add shadow emitter — add-candidate evaluation on existing holdings (buy_signals.yaml loader). `evaluate_mode_gates` 가 score 외 조건을 분리 평가 — 라이브 결정과 would-fire 측정이 같은 게이트를 공유한다. | scheduler 08:30 KST (`_run_held_add_shadow`) | #518 Phase 2a |
| `held_add_would_fire.py` | 임계 그리드 전방 측정 원장 — "임계가 X 였다면 발화했을까" 를 매일 기록 (임계 변경 없음). 판정 기준은 **사전등록** (`buy_signals.yaml stage2_adjudication` + STRATEGY §3.12) — 값 드리프트는 잠금 테스트가 차단. | `held_add.py` 내부 (같은 provider 스냅샷) | #1173 (#788 Stage 1) |
| `candidates.py` | E-1 signal-based candidate screener (today's signals × historically validated). | `python -m ...candidates` | E-1 |
| `price_targets.py` | entry / stop / TP1 / TP2 / trailing per holding, pulling from `config/rules.yaml` ladders (growth / value / swing). | upstream of every BUY/SELL alert | core |
| `rebalance.py` | E-2 regime-adapted MVO/RP rebalance (defensive vs offensive sector tilt by regime). | `python -m ...rebalance` | E-2 |
| `tracker.py` | E-3 store recommendations + 7/14/21/30/60/90d outcome backfill into `recommendations` table. | scheduler daily + `--save` | E-3 |
| `adherence.py` | 합의 BUY/SELL 이행 여부 진단 — `portfolio_changes` 순변화로 4분류, 읽기 전용·저장 없음. | `python -m nuri.trading.recommend.adherence` | #1722 |

## Invariants

- **Recommend, never execute** (§7.1). Output is markdown / DB row / Discord — the user runs the order in their app.
- **Price levels mandatory**: every BUY / SELL recommendation must carry `entry / stop_loss / target_1 / target_2 / trailing` (user-level CLAUDE.md "Price Targets Required"). `price_targets.py` is the canonical source — do not re-derive in callers.
- **rules.yaml is source of truth** for stop / TP / trailing %. Hardcoding any threshold in this directory is a config-discipline violation (`.claude/rules/invariants.md` "Always-on Invariants").
- **Outcome tracking writes to `recommendations`, not `agent_decisions`**. The two tables exist by design — see `docs/ARCHITECTURE.md` "Three decision-related tables — intentional, not duplicate".
- **Dedup window** for re-emission: 7 calendar days per `(ticker, trigger_type)` is the convention (`holdings_monitor.py` baseline). New emitters should match unless they justify otherwise.
- **레짐은 `classify_regime()` 에서만 오고, 그 어휘는 `ALL_REGIMES` 10개뿐이다.** `regime_transitions` 는 히스토리지 게이팅 출처가 아니다 — 예약 writer 가 없어 임의로 낡는다(실측 121일). 그리고 config·코드가 `bear` / `crash` / `neutral` / `extreme_fear` 같은 **표에 없는 문자열**을 조회하면 `.get(key, default)` 가 조용히 기본값을 주므로 방어 게이트가 초록인 채 죽는다 — 실제로 3건이 2026-04-30~08-21 동안 한 번도 발화하지 못했다. 레짐 목록은 config 에 두고 코드에 박지 않는다. 분류 불가(`None`)는 레짐이 아니라 `UNKNOWN_REGIME` 이며, 어떤 조정 표에도 매치되지 않고 별도의 보수 배분을 받는다. **Test:** `tests/quant/regime/test_config_regime_vocabulary.py::TestConfigSpeaksTheClassifiersLanguage::test_every_regime_key_is_canonical` (config 4개 사이트) + `::TestGateCodeDoesNotHardcodeRegimes::test_no_literal_regime_set_is_compared_against` (AST) + `tests/trading/recommend/test_buy_candidate_emitter.py::test_stale_regime_transitions_row_no_longer_governs_the_gate`.

## Asset-class scope

| Module | equity_us | equity_kr | crypto | ETF |
|---|---|---|---|---|
| `buy_candidate_emitter` | ✅ | ✅ | — | — |
| `holdings_monitor` | ✅ | ✅ | excluded (different vol profile) | ✅ |
| `candidates` | ✅ | ✅ | — | ✅ |
| `price_targets` | ✅ | ✅ | — | ✅ (with `volatile` ladder) |
| `rebalance` | portfolio-wide | portfolio-wide | — | portfolio-wide |
| `tracker` | universal — any ticker emitted upstream | | | |

## When adding a new emitter

1. Single responsibility: one signal class or one alert type per file.
2. Output format: dataclass list + markdown renderer; the dataclass goes to `recommendations` via `tracker.save_recommendations()`.
3. Tests under `tests/trading/recommend/` with `tmp_path` DB isolation (see `tests/CLAUDE.md`).
4. Discord alert path: route through `nuri/alerts/` — do not write Discord SDK calls here.
5. Confirm `python -m nuri.trading.recommend.buy_candidate_emitter` (or equivalent) finishes < 60s on a cold cache; longer means cache the upstream computation.

## 추천 이행 여부 진단 (`adherence.py`, #1722)

합의 BUY/SELL 을 운영자가 따랐는지 보유 변경 원장(`portfolio_changes`, 트리거 기록 #1720)의 순변화로 `followed` / `contrary` / `not_followed` / `unknown` / `open` 으로 나눈다. 같은 종목·같은 행동은 간격이 `config/rules.yaml adherence.window_days` 이하인 한 한 에피소드 — HOLD 는 끊지 않는다(끊으면 SELL·HOLD·SELL 의 겹친 두 창이 매도 한 번을 두 번 센다). 창은 시작일 **다음 날**부터 마지막 추천일 + `window_days`. 순변화 0 은 그 종목을 담은 계좌를 그 창에 봤을 때만 `not_followed`(처음 사는 종목은 어느 계좌든), 아니면 `unknown` — 가져오기를 안 한 것과 안 따른 것을 구분하지 못하므로 지어내지 않는다. 창이 안 닫혔으면 `open`. `--since` 는 묶은 **뒤** 거른다. **진단 전용**: §3.11 판정은 읽지 않으며 결과를 저장하지 않는다(`python -m nuri.trading.recommend.adherence`, 집계만 출력). 액면분할·병합은 BUY/SELL 로 보인다(기업행동 피드 없음).
**Test:** `tests/trading/recommend/test_adherence.py` — 창 시작을 당일로, 빈 창을 `not_followed` 로, HOLD 로 에피소드를 끊게, 다른 계좌 흔적을 '봤다' 로, 미종결 창을 확정하게, `since` 를 먼저 거르게 바꾸면 각각 FAIL (2026-10-07 Codex 재리뷰).

## References

- STRATEGY §7.1 (auto-trading deferred)
- `config/rules.yaml` — TP/SL/trailing ladders
- `nuri/trading/agents/CLAUDE.md` — consensus pipeline this directory consumes
- `docs/STRATEGY.md §3.7` — alpha vs portfolio action axis (concentration violation routes to REBALANCE, never urgent SELL)
