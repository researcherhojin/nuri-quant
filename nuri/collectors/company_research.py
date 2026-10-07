"""종목 소개와 연간 재무 원자료 수집 — 전략 판단 없이 공급자 값을 저장한다.

`parse_tema_fund` 는 한 ETF 운용사 페이지 전용 어댑터다(구조·FAQ 문구에 맞춰져 있다). 다른 펀드에는 쓰지 않는다.
자세한 한계: `docs/RESEARCH_BRIEFING.md` "알려진 한계".

cspell:words Tema MUTUALFUND Starlink SPCX
"""

import argparse
import json
import math
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree

from nuri.collectors.base import BaseCollector
from nuri.collectors.briefing_sources import collect_briefing_sources
from nuri.collectors.company_briefing import describe_business, public_display_name
from nuri.collectors.korean_research import collect_korean_profile
from nuri.collectors.research_news import enrich_news
from nuri.core.db import get_db
from nuri.core.timezone import KST, kst_now, today_kst

# 공급자 어댑터 주소이며 투자 규칙이 아니다. 공식 페이지의 값·날짜를 매번 읽는다.
TEMA_URL = "https://temaetfs.com/nasa"


# 뉴스 표시 기간이며 투자 임계값이 아니다.
NEWS_LOOKBACK_DAYS = 30


def parse_news_feed(xml: str, ticker: str) -> list[dict]:
    """발행일과 실제 언론사 이름을 보존한다. 잘못된 날짜를 오늘로 바꾸지 않는다."""
    root = ElementTree.fromstring(xml)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("News source did not return an RSS feed")
    records = []
    for item in root.findall("./channel/item"):
        title, url = item.findtext("title", "").strip(), item.findtext("link", "").strip()
        source = item.findtext("source", "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if not title or not url.startswith("https://"):
            continue
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        records.append(
            {
                "ticker": ticker,
                "date": published.astimezone(KST).date().isoformat(),
                "title": title,
                "url": url,
                "source": source,
            }
        )
    return records


def _collect_recent_news(ticker: str, name: str) -> list[dict]:
    import requests

    # 티커 단독 검색은 정부기관·동명이인과 혼동되므로 확인된 상품/회사명을 사용한다.
    query = f'"{name.replace(chr(34), "")}" when:{NEWS_LOOKBACK_DAYS}d'
    korean = ticker.endswith((".KS", ".KQ"))
    url = "https://news.google.com/rss/search?" + urlencode(
        {
            "q": query,
            "hl": "ko" if korean else "en-US",
            "gl": "KR" if korean else "US",
            "ceid": "KR:ko" if korean else "US:en",
        }
    )
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return parse_news_feed(response.text, ticker)


def recent_news(records: list[dict], start: str, end: str) -> list[dict]:
    seen = set()
    result = []
    for item in sorted(records, key=lambda item: item["date"], reverse=True):
        key = " ".join(item["title"].casefold().split())
        if start <= item["date"] <= end and key not in seen:
            seen.add(key)
            result.append(item)
    return result[:8]


def _source_date(raw: str) -> str | None:
    try:
        return datetime.strptime(raw.replace("As of", "").strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_tema_fund(html: str, symbol: str) -> dict:
    """상품 정보·보유내역·위험 고지의 기준일을 독립적으로 보존한다."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    def section(title):
        heading = soup.find("h3", string=lambda text: text is not None and text.strip() == title)
        # 상품 정보는 inner-left-part, 보유내역은 inner-box, 특성은 별도 영역이다.
        return (
            next((parent for parent in heading.parents if parent.select_one(".col-specification")), None)
            if heading
            else None
        )

    details = section("Fund Details")
    holdings = section("Top 10 Holdings")
    summary = soup.select_one(".summary-block .summary")
    characteristics = section("ETF Characteristics")
    labels = {}
    if details:
        for box in details.select(".box"):
            key, value = box.select_one(".col-specification"), box.select_one(".col-details")
            if key and value:
                labels[key.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    if labels.get("Ticker") != symbol or not summary:
        raise ValueError("Official fund identity or structure is unavailable")
    valuation = {}
    if characteristics:
        for box in characteristics.select(".box"):
            label, value = box.select_one(".col-specification > span"), box.select_one(".col-details")
            if label and value:
                valuation[label.get_text(strip=True)] = _number(value.get_text(strip=True).replace("x", ""))

    def numeric(label):
        return _number(re.sub(r"[$,%\s]", "", labels.get(label, "")))

    def date_of(block):
        heading = block.find("h6") if block else None
        return _source_date(heading.get_text(" ", strip=True)) if heading else None

    top = []
    if holdings:
        for box in holdings.select(".outer-wrap .box"):
            name, weight = box.select_one(".col-specification"), box.select_one(".col-details")
            value = _number(weight.get_text(strip=True).replace("%", "")) if weight else None
            if name and value is not None and 0 <= value <= 100:
                top.append({"name": name.get_text(" ", strip=True), "weight_pct": value})
    risks = []
    for paragraph in soup.find_all("p"):
        title = paragraph.find("strong")
        if title and "Risk" in title.get_text():
            risks.append(
                {"title": " ".join(title.get_text().split()).rstrip(":"), "text": paragraph.get_text(" ", strip=True)}
            )
    links = soup.find_all("a", href=True)
    prospectus = next((link["href"] for link in links if "Summary Prospectus" in link.get_text()), None)
    heading = soup.find("h1")
    description = summary.get_text(" ", strip=True)
    themes = [
        translated
        for original, translated in [
            ("space exploration", "우주 탐사"),
            ("rockets", "로켓"),
            ("propulsion", "추진 시스템"),
            ("satellite", "위성 기술"),
        ]
        if original in description.lower()
    ]
    strategy = None
    if themes:
        style = "운용사가 투자 대상을 선택하는 액티브 방식으로 " if "actively managed" in description.lower() else ""
        strategy = f"운용사 설명에 따르면 {style}{'·'.join(themes)} 관련 사업에 투자하는 ETF입니다. ETF를 구매하면 구성 자산들의 성과에 함께 노출됩니다."
    highlights = []
    for paragraph in soup.select(".three-column-block-text p"):
        match = re.match(r"^(.+?)\s+\(([^)]+)\)\s+(.+)", paragraph.get_text(" ", strip=True))
        if not match:
            continue
        name, ticker, business = match.groups()
        roles = []
        lower = business.lower()
        if "starlink" in lower and "rocket" in lower:
            roles.append(
                "로켓 개발·발사와 Starlink 위성 인터넷 사업을 함께 운영합니다. 발사 사업과 통신 서비스의 변화가 함께 영향을 줄 수 있습니다."
            )
        if "smartphone" in lower and ("satellite" in lower or "space-based" in lower):
            roles.append(
                "일반 스마트폰을 위성과 직접 연결하는 통신망을 개발합니다. 위성 배치와 서비스 상용화 진행을 확인할 대상입니다."
            )
        if "radio frequency" in lower or "rf components" in lower:
            roles.append(
                "위성 통신 등에 쓰이는 고주파 부품과 시스템을 공급합니다. 통신 인프라 투자와 고객 수요의 영향을 받습니다."
            )
        highlights.append(
            {"name": name, "symbol": ticker, "description": business, "explanation": " ".join(roles) or None}
        )
    faq = []
    for item in soup.select(".faq-accordion-dropdown-section-v2"):
        question, answer = item.select_one("h4"), item.select_one(".faq-accordion-content-text")
        if question and answer:
            faq.append({"question": question.get_text(" ", strip=True), "answer": answer.get_text(" ", strip=True)})
    faq_date = soup.select_one(".faq-title h2 span")
    spv = next((item["answer"] for item in faq if item["question"] == "How does NASA invest in SpaceX?"), "")
    valuation_answer = next(
        (item["answer"] for item in faq if item["question"] == "How is your position in SpaceX valued?"), ""
    )
    # 과거 IPO 예상 문구를 현재 상장 여부로 변환하지 않는다.
    consistency_note = bool(
        "not publicly traded" in valuation_answer.lower() and any(item["symbol"] == "SPCX" for item in highlights)
    )
    return {
        "name": heading.get_text(" ", strip=True).removeprefix(symbol).strip() if heading else None,
        "description": description,
        "strategy_text": strategy,
        "highlights": highlights,
        "faq": faq,
        "faq_as_of": _source_date(faq_date.get_text(" ", strip=True)) if faq_date else None,
        "exposure_text": "운용사는 SpaceX 노출을 특수목적기구(SPV)를 통해 확보한다고 설명합니다. ETF를 사는 것과 SpaceX 주식을 직접 보유하는 것은 구조가 다릅니다. 실제 처분 가능 시점과 평가 방식은 투자설명서·최신 공시를 확인해야 합니다."
        if "special purpose vehicle" in spv.lower()
        else None,
        "source_consistency_issue": consistency_note,
        "valuation_as_of": date_of(characteristics),
        "pe": valuation.get("Price-to-Earnings (P/E)"),
        "pb": valuation.get("Price-to-Book Value (P/BV)"),
        "ps": valuation.get("Price-to-Sales (P/S)"),
        "source_name": "Tema ETFs",
        "source_url": TEMA_URL,
        "details_as_of": date_of(details),
        "holdings_as_of": date_of(holdings),
        "inception": labels.get("Inception Date"),
        "expense_pct": numeric("Total Expense Ratio"),
        "aum": numeric("AUM"),
        "currency": "USD",
        "holding_count": numeric("# of Holdings"),
        "exchange": labels.get("Primary Exchange"),
        "holdings": top,
        "risks": risks,
        "prospectus_url": prospectus,
    }


def _collect_tema_fund(symbol: str) -> dict:
    import requests

    response = requests.get(TEMA_URL, timeout=20)
    response.raise_for_status()
    return parse_tema_fund(response.text, symbol)


def _prices(frame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    result = []
    for date, row in frame.sort_index().iterrows():
        values = {
            key: _number(row.get(label))
            for key, label in [
                ("open", "Open"),
                ("high", "High"),
                ("low", "Low"),
                ("close", "Close"),
                ("volume", "Volume"),
            ]
        }
        if all(value is not None for value in values.values()):
            result.append({"date": date.date().isoformat(), **values})
    return result


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _statement(frame, fields: dict[str, str]) -> list[dict]:
    if frame is None or frame.empty:
        return []
    rows = []
    for period in sorted(frame.columns, reverse=True)[:4]:
        row: dict[str, str | float | None] = {"period": str(period)[:10]}
        for key, label in fields.items():
            row[key] = _number(frame.loc[label, period]) if label in frame.index else None
        rows.append(row)
    return rows


class CompanyResearchCollector(BaseCollector):
    def __init__(self):
        super().__init__("company_research")

    def collect(self, ticker: str, **kwargs) -> list[dict]:
        import yfinance as yf

        symbol = ticker.upper()
        stock = yf.Ticker(symbol)
        missing = []
        fund = None
        korean = None
        if symbol.endswith((".KS", ".KQ")):
            try:
                korean = collect_korean_profile(symbol)
                fund = korean.get("fund")
            except Exception:
                missing.append("korean_profile")
        if symbol == "NASA":
            try:
                fund = _collect_tema_fund(symbol)
            except Exception:
                self.logger.warning("공식 ETF 자료 조회 실패: %s", symbol)
                missing.append("fund")
        try:
            info = stock.info or {}
        except Exception:
            if not fund and not korean:
                raise
            info = {}
            missing.append("profile")
        # 공급자가 반환한 심볼과 회사명이 없으면 다른 회사를 추측하지 않는다.
        if (
            not fund
            and not korean
            and (str(info.get("symbol", "")).upper() != symbol or not (info.get("longName") or info.get("shortName")))
        ):
            return []
        if str(info.get("symbol", "")).upper() != symbol:
            info = {}
        profile = {
            "name": (fund or {}).get("name")
            or info.get("longName")
            or info.get("shortName")
            or (korean or {}).get("name"),
            "symbol": symbol,
            "description": (fund or {}).get("description")
            or info.get("longBusinessSummary")
            or (korean or {}).get("description"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country") or ("South Korea" if korean else None),
            "website": info.get("website"),
            "exchange": (fund or {}).get("exchange")
            or info.get("fullExchangeName")
            or info.get("exchange")
            or (korean or {}).get("exchange"),
            "quote_type": "ETF" if fund else info.get("quoteType") or (korean or {}).get("quote_type"),
            "currency": info.get("currency") or (fund or {}).get("currency") or ("KRW" if korean else None),
            "financial_currency": info.get("financialCurrency"),
            "market_cap": _number(info.get("marketCap")),
            "display_name": (korean or {}).get("name") or public_display_name(symbol),
            "identity_source_url": (korean or {}).get("source_url"),
        }
        if profile["quote_type"] in {"ETF", "MUTUALFUND"} and not fund:
            try:
                holdings = stock.funds_data.top_holdings
                fund = {
                    "source_name": "Yahoo Finance",
                    "source_url": f"https://finance.yahoo.com/quote/{symbol}/holdings/",
                    "details_as_of": None,
                    "holdings_as_of": None,
                    "expense_pct": None,
                    "aum": _number(info.get("totalAssets")),
                    "currency": info.get("currency"),
                    "holding_count": None,
                    "inception": None,
                    "risks": [],
                    "prospectus_url": None,
                    "holdings": [
                        {"name": str(row.get("Name") or ticker), "weight_pct": value * 100}
                        for ticker, row in holdings.iterrows()
                        if (value := _number(row.get("Holding Percent"))) is not None
                    ],
                }
            except Exception:
                missing.append("fund")
        statements = {}
        for key, fetch, fields in [
            (
                "income",
                stock.get_income_stmt,
                {"revenue": "TotalRevenue", "operating_income": "OperatingIncome", "net_income": "NetIncome"},
            ),
            (
                "cashflow",
                stock.get_cashflow,
                {"operating_cashflow": "OperatingCashFlow", "free_cashflow": "FreeCashFlow"},
            ),
            (
                "balance",
                stock.get_balance_sheet,
                {"cash": "CashCashEquivalentsAndShortTermInvestments", "debt": "TotalDebt"},
            ),
        ]:
            if profile["quote_type"] in {"ETF", "MUTUALFUND"}:
                statements[key] = []
                continue
            try:
                statements[key] = _statement(fetch(), fields)
                if not statements[key]:
                    missing.append(key)
            except Exception:
                self.logger.warning("기업 재무자료 일부 조회 실패: %s/%s", symbol, key)
                statements[key] = []
                missing.append(key)
        price_history = []
        news = []
        try:
            price_history = _prices(stock.history(period="1y", auto_adjust=False, timeout=15))
            if not price_history:
                missing.append("prices")
        except Exception:
            missing.append("prices")
        news_failures = []
        try:
            from nuri.collectors.news import NewsCollector

            raw = stock.get_news(count=8) or []
            # 누락·잘못된 발행일에 오늘 날짜를 붙이지 않는다.
            dated = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, dict):
                    published = content.get("pubDate") or content.get("displayTime") or ""
                    valid = isinstance(published, str) and NewsCollector._iso_utc_to_kst_date(published) is not None
                else:
                    epoch = item.get("providerPublishTime")
                    valid = isinstance(epoch, (int, float)) and math.isfinite(epoch) and epoch > 0
                if valid:
                    dated.append(item)
            seen = set()
            for item in NewsCollector()._parse_yfinance_news(dated, symbol):
                key = (item["date"], item["title"])
                if key not in seen:
                    news.append(item)
                    seen.add(key)
        except Exception:
            news_failures.append("Yahoo Finance")
        try:
            news.extend(_collect_recent_news(symbol, profile.get("display_name") or profile["name"]))
        except Exception:
            self.logger.warning("최근 뉴스 검색 실패: %s", symbol)
            news_failures.append("Google News")
        checked = kst_now()
        window_start = (checked - timedelta(days=NEWS_LOOKBACK_DAYS)).date().isoformat()
        news = recent_news(news, window_start, checked.date().isoformat())
        aliases = [name for name in [profile["name"], profile.get("display_name")] if name]
        news = enrich_news(news, aliases, symbol)
        if news_failures:
            missing.append("news")
        return [
            {
                "ticker": symbol,
                "schema_version": 6,
                "briefing_evidence": collect_briefing_sources(profile, news),
                "profile": profile,
                "business": describe_business(profile) if profile["quote_type"] not in {"ETF", "MUTUALFUND"} else None,
                "statements": statements,
                "unavailable": missing,
                "fund": fund,
                "price_history": price_history,
                "news": news,
                "news_check": {
                    "checked_at": checked.isoformat(),
                    "window_start": window_start,
                    "window_end": checked.date().isoformat(),
                    "sources": ["Yahoo Finance", "Google News"],
                    "failed_sources": news_failures,
                },
                "collected_at": kst_now().isoformat(),
            }
        ]

    def save(self, data: list[dict]) -> int:
        if not data:
            return 0
        with get_db() as conn:
            for item in data:
                conn.execute(
                    "INSERT OR REPLACE INTO external_analysis "
                    "(date, source, ticker, data_type, value, details, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        today_kst(),
                        "yahoo_finance",
                        item["ticker"],
                        "company_research",
                        item["profile"]["name"],
                        json.dumps(item, ensure_ascii=False, allow_nan=False),
                        item["collected_at"],
                    ),
                )
        return len(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect source-backed company research")
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    CompanyResearchCollector().run(ticker=args.ticker)
