---
description: Earnings preview (consensus EPS + IV implied move) for ticker(s). Usage \`/nuri-earnings-preview MSFT\` or \`/nuri-earnings-preview MSFT,META,GOOGL\`. nuri-quant 전용.
---

당신은 Issue #509 earnings preview collector 의 invoker 입니다.

User invocation: `/nuri-earnings-preview $ARGUMENTS`

`$ARGUMENTS` = ticker 또는 콤마로 구분된 multiple tickers.

처리 절차:
1. 콤마 포함 → multiple. `make earnings-preview watchlist=$ARGUMENTS`.
2. 단일 → `make earnings-preview ticker=$ARGUMENTS`.
3. 출력 markdown 사용자에게 surface (per-ticker 1 block).

알려진 한계 (사용자에게 inline 노출):
- yfinance 만료 직전 옵션 hit 시 implied move 비정상 (예: AMZN 2026-04-30 case). `next_friday` filter Phase 2 fix.
- Whisper number (Estimize/StockTwits) 외부 API 필요 — 현재 consensus + options-implied move 만.
- 어닝 일정 없는 ticker → "no upcoming announcement" 표시.

Reference:
- `nuri/collectors/earnings_preview.py`
- `docs/TODO.md Tier 2 P1 #0b`
