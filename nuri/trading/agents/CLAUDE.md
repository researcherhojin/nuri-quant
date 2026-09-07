# nuri/trading/agents/ — 10-Agent Consensus

## Architecture

10 specialist agents with weighted voting. Config in `config/agents.yaml`, loaded via `nuri/core/agent_config.py`. Weights live in `consensus/registry.py:DEFAULT_WEIGHTS` (sum = 1.0).

## BaseAgent Contract

All agents inherit `BaseAgent`. Confidence normalized to 0–100 via `normalize_confidence()`. Required data absent → return HOLD with low confidence, never raise.

## Specialization (honest capacity — B-3 audit 2026-04-17)

Not every agent runs meaningfully on every ticker. Earlier docs framed this as "10-agent weighted consensus" which overstated effective coverage. Actual behavior:

| Category | Agents | Weight Σ | Effective scope |
|---|---|---|---|
| **Always-on** — run on every ticker with real reasoning | technical, fundamental, macro, risk, smart_money, wallstreet, options | 0.827 | Works on US + KR equities with standard fundamentals / prices / macro data |
| **Specialized by ticker type** | korean_market (KR only), crypto (crypto only) | 0.123 | Returns low-conf HOLD outside specialization by design — this is correct behavior, not a bug |
| **Data-coverage dependent** | retail (WSB mention counts) | 0.05 | Active only where WSB mention data exists (~40% of US universe); low-conf HOLD elsewhere |

Live probe (2026-04-17):
- `TSLA` → 10/10 agents return real reasoning (smart_money, technical = BUY; fundamental = SELL; rest = HOLD with varied context). Consensus BUY @ 39 conf, 20% agreement.
- `005930.KS` → korean_market activates (20-day momentum + institutional flows), retail/crypto dormant by design. Consensus HOLD @ 62 conf, 90% agreement.
- `GOOGL` → korean_market neutral for US (conf 50, "US ticker — Korean market agent neutral"), retail active (WSB coverage present, conf 48). Consensus HOLD @ 62, 80%.

## ARK 항목은 Buy/Sell 만 센다 (`smart_money.py`, #1143)

`ark.direction` 은 Buy / Sell / **Hold** 세 값이다. `sells` 를 `len(rows) - buys` 로
구하면 Hold 가 전부 매도가 된다 — ark 테이블이 Hold 만 담고 있던 기간(수집 소스 사망 +
보유 스냅샷 폴백) 동안 거기 있는 티커는 전부 상시 `score -1` 을 받았다. 수집기 쪽 사정과
무관하게 이 집계는 방어적으로 옳아야 한다. 배경은 `nuri/collectors/CLAUDE.md` "ARK".

## smart_money 는 source 별 신선도 억제를 한다 (#1187)

세 소스(13F superinvestors · estimates · ark) 각각 `config/agents.yaml
smart_money.freshness` 의 max-age 를 넘는 행은 점수에서 제외한다. **"낡음 — 제외" 노트는
소스-레벨 프로브가 소스 자체의 staleness 를 확인했을 때만** 낸다 — 티커 행만 늙은 것
(13F 에서 팔린 종목, ARK 가 보유만 유지한 종목)은 정상 부재라 조용히 제외한다 (Codex P2).
ARK 의 소스 프로브는 `ark` 테이블이 아니라 `ark_source_dates` 다 (#1147 — ark 는 보유
교집합이라 소스 신선도의 정본이 아님). `data_points["stale_sources"]` 가 제외 목록을
노출한다. 235일 낡은 ARK Buy 가 "ARK 최근 매수 ±1" 로 표면화된 사고가 기원. **Test:**
`tests/trading/agents/test_smart_money_branches.py::TestSourceFreshnessSuppression` (축별
억제) + `::TestStaleRowsVsFreshSource` (정상 부재 vs 소스 staleness 구분).

## Veto + Divergence

- **Risk agent** (19% weight) has **veto power**: SELL + confidence ≥ 80 overrides all others.
- **Technical divergence penalty** (JKHY defense, PR #303): if TechnicalAgent SELL with conf ≥ 80 disagrees with a consensus BUY, downgrade to HOLD. See STRATEGY §2.6 (Soft penalty rung, PR #303 `divergence_technical_threshold`) + §5.9 Case #2 (JKHY).

## 자리표시자 verdict 는 두 축이다 — `degraded` 와 `abstained` (#1028, #1436)

패널이 무너지지 않게 판단 못 한 에이전트도 HOLD/0 을 채운다 (#130). 그 대체물이 진짜 HOLD 와
섞이면 동의율이 부풀고 거부권 부재가 안 보인다. 그래서 `scoring.py` 의 `live` 는 둘 다 뺀다.

| 축 | 뜻 | 판정 | 성격 |
|---|---|---|---|
| `degraded` | 예외·타임아웃으로 **죽었다** | `consensus/__init__.py` 가 `degraded=True` | 인시던트 |
| `abstained` | 정상 실행, **의견 없음** | 각 에이전트가 자리표시자 반환 지점에서 `abstained=True` (13 곳) | 상시 |

**섞지 않는 이유**: 실측 180 셀 중 기권이 **51 (28.3%)** 이다 — `crypto` 18, `smart_money` 14,
`retail` 12, `wallstreet` 4, `fundamental` 2, `technical` 1. 이걸 `degraded_agents` 에 넣으면
목록이 매 행 가득 차 **진짜 크래시가 노이즈에 묻힌다** — #1028 이 만든 신호가 죽는다.

⚠️ **확신도로 판정하지 말 것.** `normalize_confidence` 가 낮은 원점수를 0 으로 깎는다
(`risk` raw 0~40, `macro` 0~30 → 0.0). 확신도 0 으로 유도하면 `risk` 의 "리스크 정상"(평가해서
위험 없음을 확인한 **판단**) 3 건을 기권으로 뒤집고, 반대로 `smart_money`(conf 30) 14 건과
`wallstreet`(conf 20) 4 건은 놓친다. 생산 지점이 선언한다.

**행동은 안 바뀐다**: 기권 플래그는 `action_scores` 계산을 아예 안 건드린다 (그 축이 #1437).
"확신도가 0 이라 0 을 더한다" 는 **근거로 쓰면 안 된다** — 바로 위 문단이 적었듯 자리표시자
확신도는 0 이 아니다(`smart_money` 30 · `wallstreet` 20). 결론은 같지만 이유가 다르다.
거부권도 자리표시자 확신도가 80 미만이라 그대로다.
바뀌는 것은 `agreement_rate` · `dissent` · `panel_coverage` · `risk_veto_available` 이며 전부
기록·표시용이다 (`agent_agreement` 도 `swing/rules.py` 에서 저장만 되고 게이트가 아니다).
프로덕션 18 건 재계산: `final_action` 변경 0, `final_confidence` 반올림 1 (37.3→37.4).

⚠️ **실패 누적기는 `analyze()` 의 모든 출구가 봐야 한다.** `_safe_query` 는 예외를 삼키되
`QueryRows.failed` 에 남기고, `BaseAgent._no_data(rows, …)` 가 그걸 보고 `degraded` 와
`abstained` 를 가른다. 그런데 다중 소스 에이전트는 출구가 둘이다 — 앞의 "전부 비었음" 과
뒤의 "신호 없음" — 이고, **앞에서만 누적기를 보고 뒤에서는 `abstained=True` 를 하드코딩한**
결함이 crypto · retail · wallstreet · smart_money 4 곳에 있었다 (codex R5). 형제 쿼리가
성공하되 임계를 못 넘기면(지배력 50, 게시물 10건) 뒤 출구로 빠져 DB 장애가 정상 기권이 된다.
연결 전체를 끊는 프로브로는 안 잡힌다 — 그때는 앞 출구가 대신 잡아주기 때문이다.

`risk` 는 방향이 가장 나쁘다: 실패를 "리스크 정상" 으로 두면 `risk_veto_available=True` 가
되어 **거부권을 평가하지도 못한 채 평가했다고 기록**한다. 게이트는 `db_failed and not
stop_loss_fired` — 예외는 **실제로 감지된 손절선 돌파** 하나뿐이다(유일한 기계적 alpha 신호라
조회 하나가 실패했다고 버릴 수 없다). 처음엔 `not reasons` 로 썼는데 너무 넓었다 (codex R6):
`reasons` 는 변동성·집중도로도 차서, 보유 조회가 실패해도 `prices` 가 살아 있으면 "저변동성"
이 게이트를 열어준다 — **실패를 가리는 근거가 실패 자신이 만든 근거**였다. 반대 방향(진짜
판단을 기권으로 깎기)이 codex R1 이 잡은 회귀이므로 둘 다 잠근다.

**degraded 는 확신도 0 이다.** `action_scores[action] += w * (conf/100)` 이라 0 이 아니면 죽은
에이전트가 계속 투표한다. 러너가 만드는 degraded 는 처음부터 0 이었는데, `_no_data` 가
에이전트별 `no_data`(smart_money 30 · wallstreet 20 · macro 30)를 물려주면서 **0 이 아닌 첫
degraded** 가 생겼다 — 실측으로 final_confidence 가 79.3 → 71.9 로 밀렸고, 그동안 UI 는
degraded 를 "가중치 0 — 합의에 미반영" 이라고 적고 있었다. 기권과 달리 이건 안 미룬다:
실패한 조회에 표를 주는 것은 어느 축에서도 옳지 않다.

**진단 노트는 의견이 아니다.** `smart_money` 는 점수를 만든 근거(`reasons`)와 제외 진단
노트(`notes`)를 따로 담는다. 한 리스트에 섞으면 "낡아서 전부 제외했다" 가 `not reasons` 를
거짓으로 만들어, **아무 증거도 못 쓴 판정이 살아 있는 의견으로** 집계된다 (codex R7). 조회
실패가 섞이면 더 나쁘다 — 실패로 degrade 해야 할 자리에서 노트가 게이트를 열어준다. `risk` 의
`not reasons` 결함과 같은 형태다(실패를 가리는 근거가 실패 자신이 만든 근거). 노트는 자리표시자
의 근거 문구로 실어 보내 #1187 이 요구한 표면화를 유지한다.

**프로브 실패는 사실 주장이 아니다.** `smart_money._source_is_fresh` 는 `(is_fresh,
probe_failed)` 를 돌려준다. 억제는 두 경우 모두 하되 "낡음 — 제외" 라고 **말하는** 것은
프로브가 실제로 낡음을 확인했을 때뿐이다. 빈 결과는 수집 기록이 없다는 뜻이라 낡음 주장이
성립하지만, 조회 실패는 모르는 것이다 — 전 판은 둘을 뭉뚱그려 검증 못 한 staleness 를
적었고, 그 문구가 `reasons` 를 채워 실패 분기까지 우회시켰다.

`korean_market` 은 DB 를 헬퍼 5 개로만 읽는다. 그 헬퍼들이 예외를 삼키고 `None`/`""`/`0` 을
돌려주면 반환값만으로는 부재와 실패가 구분되지 않는다 — #1446 이 `failures` out-param 으로
그 신호를 `analyze()` 까지 올렸다. 총체적 장애가 그전에 안 새어나간 것은
`_calibrate_fx_thresholds` 가 `_safe_query` 가 아니라 raw `query_df` 를 써서 예외가 올라간
**우연** 덕이었고, 그 호출을 '방어적으로' 바꿨다면 조용해졌을 것이다. 이제 그 우연에 기대지
않는다. **부분 실패라도 읽은 값이 하나라도 있으면 살아 있는 판단이다** — 거기서 degrade 하면
이 이슈에서 세 번 밟은 과교정의 재발이다.

**Test:** `tests/trading/agents/test_abstained_verdicts.py::TestFailureIsNeverReportedAsAbstention`
— `::test_partial_failure_is_not_an_abstention` (형제 성공 + 한 소스 실패, 5 경로) ·
`::test_degraded_verdicts_carry_zero_confidence` · `::test_a_failed_read_is_not_masked_by_a_reason_the_failure_itself_produced`
· `::test_a_failed_freshness_probe_does_not_claim_staleness` · 짝
`::test_a_real_risk_judgment_still_carries_the_veto`.
#1437 유예는 `TestAbstainedExcludedFromPanel::test_abstention_still_moves_the_score_because_1437_is_deferred`
가 **점수로** 잠근다 — 직렬화된 `contribution` 필드만 보면 `action_scores` 루프에
`if v.abstained: continue` 를 넣는 회귀가 전부 통과하면서 판정을 뒤집는다.
프로브 축의 짝은 `tests/trading/agents/test_smart_money_branches.py::TestStaleRowsVsFreshSource`
의 `::test_probe_empty_result_counts_as_not_fresh` (빈 결과 → 낡음 주장 유지) 와
`::test_probe_failure_makes_no_staleness_claim` (실패 → 주장 없음 + degraded).

## Adding a New Agent

1. Create `nuri/trading/agents/new_agent.py` inheriting `BaseAgent`.
2. Register via `build_all_agents()` in `consensus/registry.py` (`ALL_AGENTS` binding lives in `consensus/__init__.py` for monkeypatch).
3. Add weight to `DEFAULT_WEIGHTS` and thresholds in `config/agents.yaml`.
4. Tests in `tests/trading/agents/`.
5. If the agent has a limited effective scope (like korean_market / crypto), document it in the Specialization table above so the "10-agent" framing stays honest.

## Learning Memory — shipped, warming up (2026-04-17 probe)

Read/write path both live:
- **A-1a (PR #361)** — `_compute_weights()` now reads `recommendations.agent_verdicts` (previously read `signals.verdicts` which was never populated). Live DB: 144 rows accumulated.
- **A-1b (PR #372)** — `rows_parsed` gate excludes HOLD-only rows → prevents silent fallback when `min_records=10` is met by HOLD noise only.
- **Scheduler (PR #363)** — `agent_accuracy` job (Sunday 08:00 KST) calls `save_agent_accuracy_snapshot` → writes to `strategy_memory` with `signal_id='agent_{name}_accuracy'`. No dedicated `agent_accuracy_snapshots` table — strategy_memory is reused.

Current state (probed 2026-04-17): `recommendations.agent_verdicts` = **144 rows**, `strategy_memory.agent_*_accuracy` = **0 rows**. Snapshot job populates only when `compute_agent_accuracy` has `outcome_30d` data — first recommendations date ~2026-04-17, so first real weight drift expected **~2026-05-17** (TODO.md Tier 1 row 20). Until then, `_compute_weights()` returns `DEFAULT_WEIGHTS` because `min_agent_records` threshold not met. Re-probe before citing these counts — they move daily.

Weight drift is capped at ±30% per `adjustment_range` in `config/agents.yaml` (formula at `consensus/learning_memory.py:122`: `adjustment = (rate - 0.5) * 1.5`, clamped to `[-0.30, +0.30]`).

## References

- Consensus logic: `nuri/trading/agents/consensus/` package (`registry` / `scoring` / `learning_memory` / `persistence` / `presentation` / `events`)
- Weights config: `consensus/registry.py:DEFAULT_WEIGHTS` + `config/agents.yaml`
- Per-agent source: one file per agent in this directory
- B-3 audit script (ad-hoc): `analyze_ticker("TICKER")` from the consensus module
