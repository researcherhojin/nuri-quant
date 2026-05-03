---
name: nuri-thesis-batch
description: Run thesis_query (Issue #508) on multiple tickers in parallel — useful for portfolio-wide review, watchlist analysis, or post-earnings reaction sweep. Each ticker gets its own DB context fetch + LLM synthesis. Output: data/thesis_query/{date}_{ticker}_*.md per ticker. Use when user asks "analyze my watchlist", "thesis on M7", "post-earnings sweep". Do NOT use for single ticker (call `make thesis ticker=X` directly).
tools: Bash, Read, Glob
model: inherit
---

# Thesis Batch Agent

`nuri/llm/thesis_query.py` (#508) wrapper — 다중 ticker 병렬 thesis 생성.

## 발화 / 미발화

- **발화**: "전체 portfolio 분석" / "M7 sweep" / "post-earnings 분석" / "watchlist 갱신"
- **미발화 (직접 CLI)**: 단일 ticker → `make thesis ticker=INTC` (overhead 없음). DB 데이터 부재 ticker → context 비어 hallucinate.

## 운영 절차

1. ticker 리스트 parse (comma-separated 또는 "watchlist" alias)
2. 각 ticker: `python -m nuri.llm.thesis_query --ticker <T> --question <Q>` 순차 또는 병렬 (max 3 concurrent — rate limit)
3. archive: `data/thesis_query/{today}_{ticker}_<slug>.md`
4. main session 에 표 1개 반환 (full thesis flood X) — ticker / verdict / score / why-now
5. 실패 ticker (DB 부재 / LLM error) 별도 표시

## Reference

- `nuri/llm/thesis_query.py` — 본체
- `make thesis ticker=X question="..."` — 단일 ticker CLI
- `docs/STRATEGY.md §5.10` — frontier alignment
