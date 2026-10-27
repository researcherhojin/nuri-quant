"""종목 뉴스 실시간 조회 (#1958) — 분석 직전에 가져와 근거 묶음에 넣는다. DB 에 쓰지 않는다.

TradingAgents 의 News Analyst 처럼 분석 시점에 Yahoo 에서 받는다. 파싱 · 태그 필터 · 응답 판정은 원본
코드를 가져와 쓴다(`nuri/llm/tradingagents/yahoo_news.py`). 원본과 다른 점:

- 원본은 `Ticker.get_news` 를 먼저 부르고 비면 Search 의 태그된 기사로 간다. 여기서는 바로 Search 다 —
  `Ticker.get_news` 는 2026-10-02 부터 빈 목록이고(#1921), 2026-10-27 yfinance 1.7.0 에서 5종목 모두 0건을
  다시 확인했다.
- **DB 에 남기지 않는다.** 쌓으면 대화형 실행이 잦은 보유 종목에만 기사가 늘어 보유가 새어 나간다.
  기록은 이 결과를 담은 근거 묶음과 그 `packet_hash` 다. 재실행은 다시 받지 않고 보관된 묶음을 쓴다
  (Yahoo 는 다시 물으면 다른 표본을 준다). 비교하는 팔들은 같은 묶음을 받는다.
- 링크가 없는 기사는 버린다 — 기사 ID 가 URL 해시라서.
- 검색 결과는 **표본**이다. 태그된 기사 0건은 `ok` 이지 "뉴스 없음" 이 아니다. 예외나 무응답은 `failed`.

Yahoo 는 API · 요청 한도 문서를 공개하지 않는다(yfinance 는 비공식 클라이언트). 2026-10-27 MBP 실측:
미국 유니버스 556종목 순차 조회 311.7초, 중앙값 0.57초, 실패 0, 태그된 기사 1건 이상 548종목.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any

from nuri.core.ticker_names import is_kr_ticker
from nuri.core.timezone import kst_now
from nuri.llm.tradingagents.yahoo_news import answered, extract_article_data, tagged

#: 종목당 요청 기사 수 — TradingAgents `news_article_limit` 기본값.
NEWS_COUNT = 20


def _now_utc() -> str:
    """지금(UTC), 마이크로초까지 — 묶음이 cutoff 와 datetime 으로 비교한다(#1973: 초 단위 반올림은 같은 초에 만든
    묶음을 거부했다)."""
    return kst_now().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def fetch(ticker: str) -> dict[str, Any]:
    """{ticker, status, fetched_at(UTC), articles} — status 는 ok / failed / excluded(KR)."""
    out: dict[str, Any] = {"ticker": ticker, "status": "ok", "articles": []}
    if is_kr_ticker(ticker):
        # Yahoo 는 한국 상장 종목에 기사를 거의 태그하지 않는다 (원본도 같은 이유로 "unavailable").
        out["status"], out["fetched_at"] = "excluded", _now_utc()
        return out
    import yfinance as yf

    try:
        search = yf.Search(ticker, news_count=NEWS_COUNT)
        news, quotes = search.news or [], search.quotes or []
    except Exception as e:
        out["status"], out["reason"] = "failed", type(e).__name__
        news, quotes = [], []
    # 응답을 다 받은 뒤의 시각 — 이보다 이른 cutoff 로는 이 결과를 쓸 수 없다.
    out["fetched_at"] = _now_utc()
    if out["status"] == "failed":
        return out
    if not answered(news, quotes, ticker):
        out["status"], out["reason"] = "failed", "no answer"
        return out
    parsed = (extract_article_data(a) for a in tagged(news, ticker))
    out["articles"] = [a for a in parsed if a["link"]]
    return out
