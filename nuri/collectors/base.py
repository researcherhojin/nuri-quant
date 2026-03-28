"""
BaseCollector — 모든 데이터 수집기의 추상 기반 클래스.

모든 collector는 이 클래스를 상속하고 collect()와 save()를 구현한다.
외부에서는 항상 run()을 호출한다.

수집 실패 처리: expected_count를 설정하면 실패율 >10% 시 save를 거부한다.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

# 실패율 임계값 (10%)
MAX_FAILURE_RATE = 0.10


class CollectionFailureError(Exception):
    """수집 실패율 초과 에러."""


class BaseCollector(ABC):
    """데이터 수집기 공통 인터페이스."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"nuri.collectors.{name}")
        self._last_run: Optional[datetime] = None
        self._expected_count: int = 0  # 서브클래스에서 설정 (0이면 검사 안 함)
        self._failed_tickers: list[str] = []

    @abstractmethod
    def collect(self, **kwargs) -> Any:
        """데이터 수집 실행. 서브클래스에서 구현."""
        ...

    @abstractmethod
    def save(self, data: Any) -> int:
        """수집된 데이터를 DB에 저장. 저장된 레코드 수 반환."""
        ...

    def run(self, **kwargs) -> int:
        """collect → save 통합 실행. 실패율 체크 포함."""
        self.logger.info("[%s] 수집 시작", self.name)
        start = datetime.now()
        self._failed_tickers = []
        try:
            data = self.collect(**kwargs)

            # 실패율 체크: expected_count 설정 시 + 결과가 리스트/DataFrame일 때
            if self._expected_count > 0 and hasattr(data, "__len__"):
                actual = len(data)
                failure_rate = 1 - (actual / self._expected_count) if self._expected_count > 0 else 0
                if failure_rate > MAX_FAILURE_RATE:
                    msg = (
                        f"[{self.name}] 수집 실패율 {failure_rate:.0%} > {MAX_FAILURE_RATE:.0%} "
                        f"({actual}/{self._expected_count}건). 저장 거부 (asymmetric data age 방지)"
                    )
                    self.logger.error(msg)
                    if self._failed_tickers:
                        self.logger.error("[%s] 실패 종목: %s", self.name, ", ".join(self._failed_tickers[:10]))
                    raise CollectionFailureError(msg)

            count = self.save(data)
            elapsed = (datetime.now() - start).total_seconds()
            self.logger.info("[%s] 완료: %d건, %.1f초", self.name, count, elapsed)
            self._last_run = datetime.now()
            return count
        except CollectionFailureError:
            raise
        except Exception as e:
            self.logger.error("[%s] 실패: %s", self.name, e, exc_info=True)
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
