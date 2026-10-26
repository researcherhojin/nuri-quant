---
name: nuri-thesis-batch
description: "Run thesis_query (Issue #508) on multiple tickers in parallel — useful for portfolio-wide review, watchlist analysis, or post-earnings reaction sweep. Each ticker gets its own DB context fetch + LLM synthesis. Output: data/thesis_query/{date}_{ticker}_*.md per ticker. Use when user asks \"analyze my watchlist\", \"thesis on M7\", \"post-earnings sweep\". Do NOT use for single ticker (call `.venv/bin/python -m nuri.llm.thesis_query --ticker X` directly)."
tools: Bash, Read, Glob
model: sonnet
---

# Thesis Batch Agent

`nuri/llm/thesis_query.py` (#508) wrapper — 다중 ticker 병렬 thesis 생성.

## 발화 / 미발화

- **발화**: "전체 portfolio 분석" / "M7 sweep" / "post-earnings 분석" / "watchlist 갱신"
- **미발화 (직접 CLI)**: 단일 ticker → `.venv/bin/python -m nuri.llm.thesis_query --ticker INTC` (overhead 없음). DB 데이터 부재 ticker → context 비어 hallucinate.

## 운영 절차

1. ticker 리스트 parse (comma-separated 또는 "watchlist" alias)
2. **병렬 전에 Strata 를 먼저 켠다** — `strata status` 가 stopped 였으면 `strata start quiet` 하고 끝나면 `strata stop`, 이미 running 이었으면 그대로 둔다. 각 실행은 꺼진 Strata 를 스스로 켜고 *자기가 켰으면 끝날 때 끈다* — 켜 두지 않고 병렬로 돌리면 먼저 끝난 실행이 나머지가 쓰는 서버를 내린다. 이미 켜져 있으면 어느 실행도 끄지 않는다.
3. 각 ticker: `python -m nuri.llm.thesis_query --ticker <T> --question <Q>` 순차 또는 병렬 (max 3 concurrent — 로컬 모델 한 대)
4. archive: `data/thesis_query/{today}_{ticker}_<slug>.md`
5. main session 에 표 1개 반환 (full thesis flood X) — ticker / 확인된 사실 / 불확실성 / 기존 시스템 판단
6. 실패 ticker (DB 부재 / LLM error) 별도 표시

## Reference

- `nuri/llm/thesis_query.py` — 본체
- `.venv/bin/python -m nuri.llm.thesis_query --ticker X --question "..."` — 단일 ticker CLI
- `docs/STRATEGY.md §5.10` — frontier alignment

DB context includes private portfolio data. `thesis_query` always runs the consult with `--local-only` (loopback local model only, environment proxies ignored, no Codex path); `--qwen-only` is an accepted no-op. If the local model cannot answer, the run fails — stop; never route the prompt to an external model. Do not invent trade levels or allocations from thesis prose.
