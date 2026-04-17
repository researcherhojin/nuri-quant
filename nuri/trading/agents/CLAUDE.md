# nuri/trading/agents/ — 10-Agent Consensus

## Architecture

10 specialist agents with weighted voting. Config in `config/agents.yaml`, loaded via `nuri/core/agent_config.py`. Weights live in `consensus.py:DEFAULT_WEIGHTS` (sum = 1.0).

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

## Veto + Divergence

- **Risk agent** (19% weight) has **veto power**: SELL + confidence ≥ 80 overrides all others.
- **Technical divergence penalty** (JKHY defense, PR #303): if TechnicalAgent SELL with conf ≥ 80 disagrees with a consensus BUY, downgrade to HOLD. See STRATEGY §5.10.

## Adding a New Agent

1. Create `nuri/trading/agents/new_agent.py` inheriting `BaseAgent`.
2. Register in `consensus.py` `ALL_AGENTS` list.
3. Add weight to `DEFAULT_WEIGHTS` and thresholds in `config/agents.yaml`.
4. Tests in `tests/trading/agents/`.
5. If the agent has a limited effective scope (like korean_market / crypto), document it in the Specialization table above so the "10-agent" framing stays honest.

## Learning Memory — currently dormant (see A-1 next session)

`strategy_memory` table and `_compute_weights()` exist for dynamic per-agent reweighting based on historical hit rates. However, live DB probe (2026-04-17):

- `signals_with_verdicts = 0` — the save path in `tracker.py` writes signal IDs only, while `_compute_weights` expects `agent_verdicts`.
- `agent_accuracy_snapshots = 0` — no periodic snapshot job running.

Result: weights fall back to `DEFAULT_WEIGHTS` static values on every call. The "dynamic reweighting" claim in older docs was aspirational, not operational. Fix tracked as A-1 in NEXT_SESSION.md.

## References

- Consensus logic: `nuri/trading/agents/consensus.py`
- Weights config: `consensus.py:DEFAULT_WEIGHTS` + `config/agents.yaml`
- Per-agent source: one file per agent in this directory
- B-3 audit script (ad-hoc): `analyze_ticker("TICKER")` from the consensus module
