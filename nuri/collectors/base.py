"""
BaseCollector — 모든 데이터 수집기의 추상 기반 클래스.

모든 collector는 이 클래스를 상속하고 collect()와 save()를 구현한다.
외부에서는 항상 run()을 호출한다.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional


class BaseCollector(ABC):
    """데이터 수집기 공통 인터페이스."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"nuri.collectors.{name}")
        self._last_run: Optional[datetime] = None

    @abstractmethod
    def collect(self, **kwargs) -> Any:
        """데이터 수집 실행. 서브클래스에서 구현."""
        ...

    @abstractmethod
    def save(self, data: Any) -> int:
        """수집된 데이터를 DB에 저장. 저장된 레코드 수 반환."""
        ...

    def run(self, **kwargs) -> int:
        """collect → save 통합 실행. 로깅 포함."""
        self.logger.info(f"[{self.name}] 수집 시작")
        start = datetime.now()
        try:
            data = self.collect(**kwargs)
            count = self.save(data)
            elapsed = (datetime.now() - start).total_seconds()
            self.logger.info(f"[{self.name}] 완료: {count}건, {elapsed:.1f}초")
            self._last_run = datetime.now()
            return count
        except Exception as e:
            self.logger.error(f"[{self.name}] 실패: {e}", exc_info=True)
            raise

    def _get_tickers(self, market: Optional[str] = None) -> list[str]:
        """DB에서 보유 종목 티커 목록 조회. market으로 한국/미국 필터링."""
        from nuri.core.db import get_tickers

        tickers = get_tickers()
        if market == "kr":
            return [t for t in tickers if t.endswith(".KS")]
        elif market == "us":
            return [t for t in tickers if not t.endswith(".KS")]
        return tickers
