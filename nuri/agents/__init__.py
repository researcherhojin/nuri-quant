"""nuri.agents — Service-grade 15-actor infrastructure (#529).

Round 5 codex consult 합의 (`data/llm_consults/2026-04-30_round5-service-grade-agents.md`):
- 15 책임 단위 (15 LLMs 아님 — Layer A/B/C 분리)
- Layer A enforcement = 100% rule (LLM 절대 금지, Knight Capital 방지)
- Layer B computation = pure code (HMM, BOCPD, DSR, PSI 통계)
- Layer C interpretation = LLM essential (사용자 보강, async enrichment only)

Mandatory conditions (Codex Round 5):
1. Mac mini single-writer (MBP 는 read replica)
2. Phase 1 부터 firewall + audit + rollback 동시 투입
3. LLM 은 enforcement path 절대 X
4. LLM 은 interpretation layer essential — 모든 actor 가 Layer C surface 보유
"""

from nuri.agents.base import Actor, Layer, Outcome, RunContext

__all__ = ["Actor", "Layer", "Outcome", "RunContext"]
