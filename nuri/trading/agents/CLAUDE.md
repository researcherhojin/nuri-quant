# nuri/trading/agents/ — 10-Agent Consensus

## Architecture

10 specialist agents with weighted voting. Config in `config/agents.yaml`, loaded via `nuri/core/agent_config.py`.

## BaseAgent Contract

All agents inherit `BaseAgent`. Confidence normalized to 0-100 via `normalize_confidence()`.

## Key Behaviors

- **Risk agent** (20% weight) has **veto power**: SELL + confidence >= 80 overrides all others
- **Korean market agent** returns neutral HOLD for US tickers (no Korean market data)
- **Retail agent** weight is 5% (WSB 역발상 시그널 활성화, `consensus.py:45` `retail: 0.05`)
- New agents must return graceful HOLD when required data is unavailable

## Adding a New Agent

1. Create `nuri/trading/agents/new_agent.py` inheriting `BaseAgent`
2. Register in `consensus.py` `ALL_AGENTS` list
3. Add weight + thresholds in `config/agents.yaml`
4. Tests in `tests/trading/agents/`

## Learning Memory

Past hit rates tracked in `strategy_memory` table. Weights dynamically adjusted within +-30% range based on historical accuracy.
