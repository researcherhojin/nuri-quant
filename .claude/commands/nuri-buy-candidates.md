---
description: Emit BUY candidates from current snapshot (Issue #507 Phase 1). VIX > 30 또는 bear/crash regime 시 0 candidate 반환 (정상). Usage \`/nuri-buy-candidates\`. nuri-quant 전용.
---

당신은 Issue #507 BUY signal emitter 의 invoker 입니다.

처리 절차:
1. Bash 실행: `make buy-candidates` (또는 `python -m nuri.trading.recommend.buy_candidate_emitter`).
2. 출력 markdown 받아 사용자에게 surface — 전체 출력 (block + skipped 일부 + summary).
3. 사용자가 specific candidate 에 추가 분석 원하면 `/nuri-thesis <TICKER>` 권유.

주의:
- VIX > 30 또는 regime ∈ {bear/crash/extreme_fear} 인 경우 0 candidate emit (blocked reason 표시) — 정상 동작.
- 0 candidate 인 경우 사용자에게 cash hold 가 적절함을 확인. 강제로 candidate 만들지 말 것.
- Skipped 종목 (held / cooldown / leverage ETF) 은 일부 (top 5) 만 표시. 전체는 `--print-all` flag 추후 도입.
- 결과 markdown 은 console 출력만 — file archive 는 Phase 3 (`data/buy_candidates/{date}.md`).

Reference:
- `nuri/trading/recommend/buy_candidate_emitter.py` — 모듈
- `config/buy_signals.yaml` — weights / thresholds 튜닝
- `docs/plans/507_buy_candidate_emitter_phase1.md` — spec (gitignored)
