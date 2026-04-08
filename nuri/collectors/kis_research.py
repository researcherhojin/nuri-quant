"""KIS (한국투자증권) 리서치 보고서 스크래퍼 — Skeleton.

KIS 리서치 페이지의 보고서 메타데이터(제목/날짜/종목/투자의견)만 수집.
본문 PDF는 별도 파싱 단계에서 처리.

상태: SKELETON — 자격 증명 + HTML 파싱 검증 후 활성화 예정.
이슈: KIS 리서치 페이지는 로그인 + JavaScript 렌더링 필요 (Playwright 후속).

사용법:
    python -m nuri.collectors.kis_research --check
    python -m nuri.collectors.kis_research --ticker 005930
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from nuri.collectors.base import BaseCollector
from nuri.collectors.kis_realtime import load_credentials

logger = logging.getLogger(__name__)


@dataclass
class ResearchReport:
    """KIS 리서치 보고서 메타데이터."""
    report_id: str
    ticker: str         # '005930.KS'
    title: str
    date: str           # YYYY-MM-DD
    rating: str         # BUY/HOLD/SELL/N/A
    target_price: float | None
    analyst: str
    summary: str
    url: str | None


class KISResearchCollector(BaseCollector):
    """KIS 리서치 보고서 수집 (skeleton)."""

    def __init__(self, mode: str = "prod"):
        super().__init__("kis_research")
        self.mode = mode

    def check_credentials(self) -> bool:
        creds = load_credentials(self.mode)
        if not creds:
            self.logger.error("KIS 자격 증명 없음")
            return False
        self.logger.info("KIS 자격 증명 OK [%s]", self.mode)
        return True

    def collect(self, **kwargs) -> list[ResearchReport]:
        """리서치 보고서 수집 — SKELETON, 빈 리스트 반환."""
        if not self.check_credentials():
            return []
        ticker = kwargs.get("ticker")
        self.logger.warning(
            "KIS 리서치 스크래퍼 미구현 (skeleton). "
            "ticker=%s, 활성화 시 Playwright 기반 로그인 + 페이지 렌더링 필요.",
            ticker or "all",
        )
        return []

    def save(self, data: list[ResearchReport]) -> int:
        """현재 미저장 (테이블 미설계)."""
        return 0


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="KIS 리서치 보고서 수집 (skeleton)")
    parser.add_argument("--mode", choices=["prod", "paper"], default="prod")
    parser.add_argument("--check", action="store_true", help="자격 증명만 확인")
    parser.add_argument("--ticker", help="단일 종목")
    args = parser.parse_args()

    collector = KISResearchCollector(mode=args.mode)
    if args.check:
        ok = collector.check_credentials()
        raise SystemExit(0 if ok else 1)
    collector.run(ticker=args.ticker)


if __name__ == "__main__":
    main()
