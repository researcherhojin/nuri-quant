"""종목 뉴스 실시간 조회 (#1958) — 분석 직전에 가져와 근거 묶음에 넣는다. DB 에 쓰지 않는다.

TradingAgents 의 News Analyst 처럼 분석 시점에 Yahoo 에서 받는다. 파싱 · 태그 필터 · 응답 판정은 원본
코드를 가져와 쓴다(`nuri/llm/tradingagents/yahoo_news.py`). 원본과 다른 점:

- 원본처럼 `Ticker.get_news` 를 먼저 부르고 비면 Search 의 태그된 기사로 간다. 피드는 원본과 달리
  `stockTickers` 로 거른다 — 그 종목이 태그된 기사가 0건이어도 피드가 왔으면 `ok` 이고 Search 로 가지 않는다.
  `get_news` 는 2026-10-02 부터 빈 목록이라(#1921) 한동안 바로 Search 였고, yfinance 1.8.0(#2058, 상류 #3018)이
  Yahoo 뉴스 GraphQL API 로 고쳤다. 2026-11-10 실측(미국 유니버스 무작위 100종목, 같은 시각, 링크 있는 태그 기사):
  Search 1,820 → get_news 1,951, 1건 이상 종목 98 → 99, 중앙값 0.56 → 0.41초, 실패 0 (#2065).
- 빈 피드는 "뉴스 없음" 과 "응답 없음" 을 가르지 못한다 — 그래서 빈 피드일 때만 Search 의 `answered` 가 판정한다.
- **DB 에 남기지 않는다.** 쌓으면 대화형 실행이 잦은 보유 종목에만 기사가 늘어 보유가 새어 나간다.
  기록은 이 결과를 담은 근거 묶음과 그 `packet_hash` 다. 재실행은 다시 받지 않고 보관된 묶음을 쓴다
  (Yahoo 는 다시 물으면 다른 표본을 준다). 비교하는 팔들은 같은 묶음을 받는다.
- 링크가 없는 기사는 버린다 — 기사 ID 가 URL 해시라서.
- 검색 결과는 **표본**이다. 태그된 기사 0건은 `ok` 이지 "뉴스 없음" 이 아니다. 예외나 무응답은 `failed`.

Yahoo 는 API · 요청 한도 문서를 공개하지 않는다(yfinance 는 비공식 클라이언트). 2026-10-27 MBP 실측(Search 경로):
미국 유니버스 556종목 순차 조회 311.7초, 중앙값 0.57초, 실패 0, 태그된 기사 1건 이상 548종목.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any

from nuri.core.ticker_names import is_kr_ticker
from nuri.core.timezone import kst_now
from nuri.llm.tradingagents.yahoo_news import answered, extract_article_data, feed_tagged, tagged

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
        feed = yf.Ticker(ticker).get_news(count=NEWS_COUNT, tab="news") or []
        if feed:
            found = feed_tagged(feed, ticker)
        else:
            search = yf.Search(ticker, news_count=NEWS_COUNT)
            news, quotes = search.news or [], search.quotes or []
            found = tagged(news, ticker) if answered(news, quotes, ticker) else None
    except Exception as e:
        out["status"], out["reason"] = "failed", type(e).__name__
        found = []
    # 응답을 다 받은 뒤의 시각 — 이보다 이른 cutoff 로는 이 결과를 쓸 수 없다.
    out["fetched_at"] = _now_utc()
    if out["status"] == "failed":
        return out
    if found is None:
        out["status"], out["reason"] = "failed", "no answer"
        return out
    parsed = (extract_article_data(a) for a in found)
    out["articles"] = [a for a in parsed if a["link"]]
    return out
