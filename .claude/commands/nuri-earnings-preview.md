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

- 만기 선택은 `_select_expiration()` 구현을 따른다: 실적일 이상인 첫 만기 우선, 없으면 오늘부터 2일 이상 남은 만기, 그것도 없으면 마지막 만기. 따라서 만료 임박 옵션이 항상 제외되는 것은 아니며 implied move 해석에 주의한다.
- Whisper number (Estimize/StockTwits) 외부 API 필요 — 현재 consensus + options-implied move 만.
- 어닝 일정 없는 ticker → "no upcoming announcement" 표시.

Reference:

- `nuri/collectors/earnings_preview.py`
- `tests/collectors/test_earnings_preview.py`
