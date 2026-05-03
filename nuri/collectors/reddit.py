"""
Reddit/WSB 센티먼트 수집기 — Arctic Shift API.

WallStreetBets 서브레딧에서 종목 언급 빈도와 센티먼트를 수집.
Arctic Shift는 Reddit 데이터의 무료 아카이브 API (인증 불필요).

사용법:
    python -m nuri.collectors.reddit
"""

import logging
import re
from collections import Counter
from datetime import timedelta

import requests

from nuri.collectors.base import BaseCollector, today_str
from nuri.core.db import upsert_macro

# Arctic Shift API (Reddit 아카이브)
ARCTIC_SHIFT_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"

_HEADERS = {"User-Agent": "nuri-quant/0.1 (investment research)"}

# WSB에서 노이즈로 무시할 일반 단어 (ticker와 혼동 방지)
_TICKER_NOISE = {
    "A",
    "I",
    "AM",
    "AN",
    "AS",
    "AT",
    "BE",
    "BY",
    "DO",
    "GO",
    "IF",
    "IN",
    "IS",
    "IT",
    "ME",
    "MY",
    "NO",
    "OF",
    "ON",
    "OR",
    "PM",
    "SO",
    "TO",
    "UP",
    "US",
    "WE",
    "ALL",
    "ARE",
    "CAN",
    "CEO",
    "DD",
    "EPS",
    "ETF",
    "FOR",
    "GDP",
    "HAS",
    "IMO",
    "IPO",
    "IRS",
    "LLC",
    "LOL",
    "NOW",
    "OLD",
    "ONE",
    "OTC",
    "OUT",
    "PUT",
    "SEC",
    "THE",
    "TOP",
    "USA",
    "WSB",
    "YOY",
    "ATH",
    "DCA",
    "FED",
    "OTM",
    "ITM",
    "RIP",
    "TBH",
    "FYI",
    "PSA",
    "NOT",
    "BUT",
    "HOW",
    "NEW",
    "TWO",
    "WAY",
    "ANY",
    "APE",
    "BAD",
    "BIG",
    "BUY",
    "DAY",
    "DIP",
    "FUD",
    "GAP",
    "HIT",
    "KEY",
    "LOW",
    "MAX",
    "MOM",
    "OWN",
    "PAY",
    "RUN",
    "SAY",
    "SET",
    "TAX",
    "TIP",
    "WIN",
}

# 티커 패턴: $ 접두사 또는 대문자 1-5자
_TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)")


class RedditCollector(BaseCollector):
    """Reddit/WSB 센티먼트 수집."""

    def __init__(self):
        super().__init__("reddit")

    def collect(self, days: int = 1, **kwargs) -> list[dict]:
        """WSB에서 종목 언급 빈도 수집."""
        held_tickers = set(self._get_tickers(market="us"))
        if not held_tickers:
            self.logger.warning("보유 US 종목 없음")
            return []

        # Arctic Shift에서 최근 포스트 검색
        try:
            posts = self._fetch_posts(days=days)
        except Exception as e:
            self.logger.warning("Arctic Shift API 실패: %s", e)
            return []

        if not posts:
            self.logger.info("WSB 포스트 없음 (최근 %d일)", days)
            return []

        # 종목 언급 카운트
        mention_counts = self._count_mentions(posts, held_tickers)

        today = today_str()
        records = []

        # 전체 WSB 포스트 수 (시장 활동 지표)
        records.append(
            {
                "indicator": "wsb_post_count",
                "date": today,
                "value": float(len(posts)),
                "source": "Reddit_WSB",
            }
        )

        # 보유 종목 중 WSB 언급 종목 수
        mentioned_held = sum(1 for t in held_tickers if mention_counts.get(t, 0) > 0)
        records.append(
            {
                "indicator": "wsb_held_mentions",
                "date": today,
                "value": float(mentioned_held),
                "source": "Reddit_WSB",
            }
        )

        # 상위 10 종목 언급 빈도 (보유 종목 한정)
        top_mentions = sorted(
            [(t, c) for t, c in mention_counts.items() if t in held_tickers and c > 0],
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        for ticker, count in top_mentions:
            records.append(
                {
                    "indicator": f"wsb_mention_{ticker}",
                    "date": today,
                    "value": float(count),
                    "source": "Reddit_WSB",
                }
            )
            self.logger.info("WSB %s: %d mentions", ticker, count)

        # 전체 상위 10 (시장 관심 지표 — 티커를 indicator에 포함)
        all_top = mention_counts.most_common(10)
        for rank, (ticker, count) in enumerate(all_top, 1):
            records.append(
                {
                    "indicator": f"wsb_top{rank}_{ticker}",
                    "date": today,
                    "value": float(count),
                    "source": "Reddit_WSB",
                }
            )

        self.logger.info("WSB 분석: %d 포스트, 보유종목 %d개 언급", len(posts), mentioned_held)
        return records

    def _fetch_posts(self, days: int = 1) -> list[dict]:
        """Arctic Shift API에서 WSB 포스트 가져오기 (페이징, 최대 500건)."""
        from nuri.core.timezone import kst_now

        after = kst_now().replace(tzinfo=None) - timedelta(days=days)
        after_epoch = int(after.timestamp())

        all_posts = []
        for _ in range(5):  # 최대 5페이지 (100건 × 5 = 500건)
            params = {
                "subreddit": "wallstreetbets",
                "after": after_epoch,
                "limit": 100,
            }
            resp = requests.get(ARCTIC_SHIFT_URL, params=params, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            posts = resp.json().get("data", [])
            if not posts:
                break
            all_posts.extend(posts)
            # 다음 페이지: 마지막 포스트의 created_utc 이후
            last_utc = posts[-1].get("created_utc")
            if last_utc:
                after_epoch = int(last_utc) + 1
            else:
                break

        return all_posts

    def _count_mentions(self, posts: list[dict], held_tickers: set[str]) -> Counter:
        """포스트에서 종목 언급 횟수 카운트."""
        counts: Counter = Counter()

        for post in posts:
            title = post.get("title", "")
            body = post.get("selftext", "")
            text = f"{title} {body}"

            # 티커 추출
            tickers_found = set()
            for match in _TICKER_PATTERN.finditer(text):
                ticker = match.group(1) or match.group(2)
                if ticker and ticker not in _TICKER_NOISE:
                    tickers_found.add(ticker)

            for ticker in tickers_found:
                counts[ticker] += 1

        return counts

    def save(self, data: list[dict]) -> int:
        """매크로 테이블에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = RedditCollector()
    collector.run()
