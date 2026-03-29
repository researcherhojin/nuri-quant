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

import requests

# 실패율 임계값 (10%)
MAX_FAILURE_RATE = 0.10

# 공통 HTTP 헤더 (모든 collector에서 사용)
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def parse_date(raw: str) -> str | None:
    """날짜 문자열을 YYYY-MM-DD로 변환. MM/DD/YYYY, YYYY-MM-DD 지원. 실패 시 None."""
    s = str(raw).strip()
    if not s:
        return None
    try:
        if "/" in s:
            return datetime.strptime(s, "%m/%d/%Y").strftime("%Y-%m-%d")
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except ValueError:
        return None


def today_str() -> str:
    """오늘 날짜 YYYY-MM-DD 문자열 (KST 기준 — Mac Mini가 한국 시간대)."""
    from nuri.core.timezone import today_kst

    return today_kst()


def fetch_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 20) -> dict:
    """JSON API 호출 헬퍼. raise_for_status() 포함."""
    resp = requests.get(url, params=params, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


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
