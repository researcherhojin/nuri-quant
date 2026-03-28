"""
FINVIZ 기술적 스크리너 수집기 — finvizfinance 라이브러리.

FINVIZ에서 시장 전반 기술적 지표를 수집하여 market-wide 스캔에 활용.
보유 종목의 FINVIZ 시그널 상태 (oversold, overbought, new high 등)를 저장.

사용법:
    python -m nuri.collectors.finviz
"""
import logging
from datetime import datetime
from typing import Optional

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db

# finvizfinance 시그널 이름 → 내부 시그널 ID 매핑
FINVIZ_SIGNALS = {
    "oversold_rsi": "Oversold",          # RSI < 30
    "overbought_rsi": "Overbought",      # RSI > 70
    "new_high": "New High",              # 52주 신고가
    "new_low": "New Low",                # 52주 신저가
    "most_volatile": "Most Volatile",    # 고변동성
    "unusual_volume": "Unusual Volume",  # 비정상 거래량
}


class FINVIZCollector(BaseCollector):
    """FINVIZ 기술적 스크리너 수집 (finvizfinance)."""

    def __init__(self):
        super().__init__("finviz")

    def collect(self, **kwargs) -> list[dict]:
        """보유 종목의 FINVIZ 시그널 상태 수집."""
        held_tickers = set(self._get_tickers(market="us"))
        if not held_tickers:
            self.logger.warning("보유 US 종목 없음")
            return []

        records = []
        today = datetime.now().strftime("%Y-%m-%d")

        for signal_name, finviz_signal in FINVIZ_SIGNALS.items():
            try:
                tickers = self._fetch_signal_tickers(finviz_signal)
                # 보유 종목과 교집합
                matched = tickers & held_tickers
                for ticker in matched:
                    records.append({
                        "date": today,
                        "ticker": ticker,
                        "signal": signal_name,
                        "source": "FINVIZ",
                    })
                if matched:
                    self.logger.info("FINVIZ %s: %s", signal_name, ", ".join(sorted(matched)))
            except Exception as e:
                self.logger.warning("FINVIZ %s 수집 실패: %s", signal_name, e)

        self.logger.info("FINVIZ 시그널 %d건 (보유 종목 필터)", len(records))
        return records

    def _fetch_signal_tickers(self, signal: str) -> set[str]:
        """시그널 종목 목록 조회. finvizfinance 우선, 실패 시 직접 스크래핑."""
        # 1차: finvizfinance 라이브러리
        try:
            from finvizfinance.screener.ticker import Ticker
            screener = Ticker()
            screener.set_filter(signal=signal)
            result = screener.screener_view(limit=500, verbose=0, sleep_sec=0.5)
            if isinstance(result, list) and result:
                return set(result)
        except Exception as e:
            self.logger.debug("finvizfinance 실패 (%s), 직접 스크래핑 시도: %s", signal, e)

        # 2차: 직접 HTML 스크래핑 폴백
        return self._scrape_signal_fallback(signal)

    def _scrape_signal_fallback(self, signal: str) -> set[str]:
        """FINVIZ 스크리너 HTML에서 직접 종목 추출."""
        import requests
        from bs4 import BeautifulSoup

        # finvizfinance signal name → FINVIZ URL signal param
        signal_map = {
            "Oversold": "ta_oversold",
            "Overbought": "ta_overbought",
            "New High": "ta_newhigh",
            "New Low": "ta_newlow",
            "Most Volatile": "ta_mostvolatile",
            "Unusual Volume": "ta_unusualvolume",
        }
        url_signal = signal_map.get(signal, signal)

        resp = requests.get(
            "https://finviz.com/screener.ashx",
            params={"v": "111", "s": url_signal},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            },
            timeout=20,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        tickers = set()
        # FINVIZ 스크리너 테이블에서 quote.ashx 링크의 티커 추출
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "quote.ashx?t=" in href:
                ticker = link.text.strip()
                if ticker and ticker.isalpha() and 1 <= len(ticker) <= 5:
                    tickers.add(ticker)
        return tickers

    def save(self, data: list[dict], db_path=None) -> int:
        """외부 분석 테이블에 FINVIZ 시그널 저장."""
        if not data:
            return 0
        with get_db(db_path) as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO external_analysis
                   (date, source, ticker, data_type, value, numeric_value, details)
                   VALUES (:date, :source, :ticker, 'finviz_signal', :signal, NULL, NULL)""",
                data,
            )
            return len(data)


def get_finviz_signals(ticker: str, db_path: Optional[str] = None) -> list[dict]:
    """특정 종목의 최근 FINVIZ 시그널 조회."""
    from nuri.core.db import query
    rows = query(
        """SELECT date, value as signal FROM external_analysis
           WHERE source = 'FINVIZ' AND ticker = ?
           ORDER BY date DESC LIMIT 10""",
        (ticker,), db_path=db_path,
    )
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = FINVIZCollector()
    collector.run()
