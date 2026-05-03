"""한국 종목코드 → 종목명 해석.

.KS 티커(예: 132030.KS)는 사람이 알아볼 수 없으므로 종목명을 조회한다.
1차: portfolio.metadata.note (사용자가 YAML에 입력한 이름)
2차: pykrx get_market_ticker_name (주식, LRU 캐시)
US 티커(MSFT, TSLA 등)는 이미 식별 가능하므로 None 반환.
"""

import json
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=500)
def get_ticker_name(ticker: str) -> str | None:
    """한국 종목 이름 반환. US 티커는 None."""
    if not ticker.endswith((".KS", ".KQ")):
        return None

    # 1차: DB portfolio metadata에서 name/note 필드 조회.
    # `name` 명시값 우선. `note` 는 보통 "<canonical> — <buy thesis>" 패턴이라
    # 첫 dash 앞부분만 canonical name 으로 본다 (그렇지 않으면 brief 가
    # 매수 narrative 전체를 ticker 자리에 표시해 가독성이 무너짐).
    try:
        from nuri.core.db import query

        rows = query(
            "SELECT metadata FROM portfolio WHERE ticker = ? AND metadata IS NOT NULL LIMIT 1",
            (ticker,),
        )
        if rows:
            meta = json.loads(rows[0]["metadata"])
            name = meta.get("name")
            if name:
                return str(name).strip()
            note = meta.get("note")
            if note:
                for sep in (" — ", " - ", "—"):
                    if sep in note:
                        return note.split(sep, 1)[0].strip()
                return note[:24].strip()
    except Exception as e:
        logger.debug("DB name lookup failed for %s: %s", ticker, e)

    # 2차: pykrx 주식 이름 조회 (ETF는 미지원)
    code = ticker.replace(".KS", "").replace(".KQ", "")
    try:
        from pykrx import stock as krx

        name = krx.get_market_ticker_name(code)
        return name if name else None
    except Exception as e:
        logger.debug("pykrx name lookup failed for %s: %s", ticker, e)
        return None
