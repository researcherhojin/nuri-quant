---
name: nuri-thesis-batch
description: Run thesis_query (Issue #508) on multiple tickers in parallel — useful for portfolio-wide review, watchlist analysis, or post-earnings reaction sweep. Each ticker gets its own DB context fetch + LLM synthesis. Output: data/thesis_query/{date}_{ticker}_*.md per ticker. Use when user asks "analyze my watchlist", "thesis on M7", "post-earnings sweep". Do NOT use for single ticker (call `make thesis ticker=X` directly).
tools: Bash, Read, Glob
model: inherit
---

# Thesis Batch Agent

Wraps `nuri/llm/thesis_query.py` (#508) for parallel multi-ticker thesis generation.

## When to invoke

- "Analyze my full portfolio" → batch on all `portfolio` table tickers
- "M7 sweep" → batch on AAPL/MSFT/AMZN/GOOGL/META/NVDA/TSLA
- "Post-earnings reaction analysis" → batch on tonight's earnings tickers (MSFT/META/AMZN/GOOGL/QCOM)
- "Watchlist update" → batch on user-defined watchlist tickers

## When NOT to invoke

- Single ticker query → use `make thesis ticker=INTC` directly (faster, no overhead)
- Speculative tickers without DB data → DB context will be empty, LLM hallucinates

## Operating procedure

1. Parse the requested ticker list (comma-separated or "watchlist" alias).
2. For each ticker, invoke `python -m nuri.llm.thesis_query --ticker <T> --question <Q>` sequentially or in parallel batch (max 3 concurrent — avoid rate limit).
3. Each thesis archived to `data/thesis_query/{today}_{ticker}_<slug>.md`.
4. Return a summary table to main session: ticker / verdict / score / why-now (one line per ticker). Do NOT flood context with full theses.
5. Note any tickers that failed (no DB data, LLM error, etc).

## Output shape

Return as markdown table to main session:

```markdown
## Thesis Batch — {date}

| Ticker | Verdict | Why now | Archive |
|--------|---------|---------|---------|
| MSFT | BUY (78/100) | AI capex confirmed + Strong Buy 33B/2H/0S | data/thesis_query/2026-04-30_msft_*.md |
| META | HOLD | Capex top-of-range $135B = shock risk | ... |
| ... |
```

## Reference

- `nuri/llm/thesis_query.py` — the underlying module
- `make thesis ticker=X question="..."` — single-ticker CLI
- `docs/STRATEGY.md §5.10` — frontier alignment context
- `docs/TODO.md Tier 2 P1 #0a` — issue tracking
