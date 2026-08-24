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
smart_money.freshness` 의 max-age 를 넘는 행은 점수에서 제외하고, "행이 있었는데 전부
낡아 제외" 는 reasoning 에 `"<라벨> 낡음(최신 날짜) — 제외"` 로 명시한다 (조용한 결손
금지). `data_points["stale_sources"]` 가 제외 목록을 노출한다. 235일 낡은 ARK Buy 가
"ARK 최근 매수 ±1" 로 표면화된 사고가 기원. **Test:**
`tests/trading/agents/test_smart_money_branches.py::TestSourceFreshnessSuppression` —
축별 전용 테스트 (한 소스의 컷오프를 지우면 그 축 테스트만 FAIL).

## Veto + Divergence

- **Risk agent** (19% weight) has **veto power**: SELL + confidence ≥ 80 overrides all others.
- **Technical divergence penalty** (JKHY defense, PR #303): if TechnicalAgent SELL with conf ≥ 80 disagrees with a consensus BUY, downgrade to HOLD. See STRATEGY §2.6 (Soft penalty rung, PR #303 `divergence_technical_threshold`) + §5.9 Case #2 (JKHY).

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
