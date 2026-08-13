---
description: Thesis Q&A on a ticker (DB context + LLM synthesis via codex + local model). Usage \`/nuri-thesis INTC\` or \`/nuri-thesis MSFT what is the AI moat\`. nuri-quant 전용 — gstack 충돌 회피 위해 nuri- prefix.
---

당신은 Issue #508 thesis Q&A engine 의 invoker 입니다.

User invocation: `/nuri-thesis $ARGUMENTS`

`$ARGUMENTS` 첫 토큰이 ticker (대문자), 나머지 단어들이 question 본문입니다.

처리 절차:
1. 첫 token = ticker (예: `INTC`, `MSFT`).
2. 나머지 = question. 비어있으면 default = "investment thesis (long/short/avoid) + portfolio implications".
3. Bash 실행: `.venv/bin/python -m nuri.llm.thesis_query --ticker <TICKER> --question "<question>"` — `nuri/llm/thesis_query.py` 가 DB context (factors / signals / prices / fundamentals / portfolio) + LLM synthesis (codex + Qwen3.5) 후 `data/thesis_query/{date}_{ticker}_<slug>.md` 에 archive.
4. 결과 markdown 의 핵심 verdict + 1-2 sentence rationale 만 사용자에게 surface. Full transcript 는 아카이브 file 로 reference.

주의:
- $ARGUMENTS 에 ticker 가 없으면 사용자에게 ticker 를 명시 요청.
- `data/thesis_query/` 는 gitignored — 사적 financial reference 포함 가능. 외부 노출 금지.
- LM Studio (port 1234) 가 alive 한지 확인 후 invoke. 미가용 시 fallback `--codex-only`.
