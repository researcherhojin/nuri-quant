# pyright: reportAttributeAccessIssue=false
"""
BaseCollector — 모든 데이터 수집기의 추상 기반 클래스.

모든 collector는 이 클래스를 상속하고 collect()와 save()를 구현한다.
외부에서는 항상 run()을 호출한다.

수집 실패 처리: expected_count를 설정하면 실패율 >10% 시 save를 거부한다.
실패 알림은 `nuri.agents.discord.outbox.stage_ops()` 경유 (Single-writer rule).
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
        """collect → save 통합 실행. 재시도(max 3) + 실패율 체크 포함."""
        import time as _time

        from nuri.core.timezone import kst_now

        max_retries = 3
        self.logger.info("[%s] 수집 시작", self.name)
        start = kst_now()
        self._failed_tickers = []

        last_error = None
        for attempt in range(1, max_retries + 1):
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
                elapsed = (kst_now() - start).total_seconds()
                self.logger.info("[%s] 완료: %d건, %.1f초", self.name, count, elapsed)
                self._last_run = kst_now()
                return count
            except CollectionFailureError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = 2**attempt  # 2, 4초 backoff
                    self.logger.warning(
                        "[%s] 시도 %d/%d 실패, %d초 후 재시도: %s", self.name, attempt, max_retries, wait, e
                    )
                    _time.sleep(wait)

        # 모든 재시도 실패
        self.logger.error("[%s] %d회 재시도 모두 실패: %s", self.name, max_retries, last_error, exc_info=True)
        self._send_failure_alert(str(last_error))
        raise last_error  # type: ignore[misc]

    def _send_failure_alert(self, error_msg: str):
        """수집기 실패 → outbox.stage_ops (Single-writer Discord, invariants.md).

        직접 webhook 호출 금지 — `nuri.agents.discord.outbox.stage_*()` 만 channel
        publish 진입점. dispatcher 가 cron 주기에 종합 발송.
        """
        try:
            from nuri.agents.discord.outbox import stage_ops
            from nuri.core.timezone import today_kst

            stage_ops(
                payload={
                    # `summary` 가 렌더 계약이다 (#571) — 없으면 digest 가 화이트리스트
                    # 폴백으로 떨어져 `? | ALERT` 에 가까운 줄이 된다. 27개 collector
                    # 전부가 이 한 경로로 실패를 알리므로 여기서 문장을 만들어 보낸다.
                    "summary": f"⚠️ {self.name} 수집 실패 — {error_msg[:160]}",
                    "event": "collector_failure",
                    "collector": self.name,
                    "error": error_msg[:200],
                    "kind": "alert",
                },
                dedupe_key=f"collector_fail_{self.name}_{today_kst()}",
                priority="high",
                actor_name=f"collector.{self.name}",
            )
        except Exception:
            self.logger.debug("Discord outbox stage 실패 (DB 미초기화 가능)")

    def _get_tickers(self, market: Optional[str] = None, source: str = "portfolio") -> list[str]:
        """티커 목록 조회. source로 범위 선택, market으로 한국/미국 필터링.

        Args:
            market: 'us' | 'kr' | None (전체). KR 판정은 `is_kr_ticker()` 경유 — `.KS`+`.KQ` (#764)
            source: 'portfolio' (default, 보유 종목만)
                  | 'universe'  (config/universe.yaml 전체, us_core + us_sp500_extended + kr_kospi200)
                  | 'all'       (portfolio ∪ universe)

        #272 Phase 2b: universe/all 모드는 agent data silo 해결용. fundamental/analyst/
        insider 데이터를 universe 전체에 대해 fetch하면 consensus 신뢰도 상승.
        Default는 'portfolio' 유지 — backwards compat.
        """
        from nuri.core.db import get_tickers
        from nuri.core.ticker_names import is_kr_ticker

        portfolio_tickers = get_tickers()

        if source == "portfolio":
            tickers = portfolio_tickers
        elif source == "universe":
            tickers = _load_universe_tickers()
        elif source == "all":
            tickers = sorted(set(portfolio_tickers) | set(_load_universe_tickers()))
        else:
            raise ValueError(f"Unknown source: {source!r}. Must be 'portfolio' | 'universe' | 'all'")

        # canonical KR 게이트 (#764) — `.KS` 만 보면 KOSDAQ(`.KQ`) 이 **양쪽에서 틀린다**:
        # kr 에서 누락돼 pykrx 순차 경로가 영영 못 보고, 여집합인 us 에는 포함돼
        # 미국장 시간대(KST 23:30~06:00, KOSDAQ 휴장)에 수집된다.
        if market == "kr":
            return [t for t in tickers if is_kr_ticker(t)]
        elif market == "us":
            return [t for t in tickers if not is_kr_ticker(t)]
        return tickers


def _load_universe_tickers() -> list[str]:
    """config/universe.yaml에서 전체 universe ticker 로드.

    us_core + us_sp500_extended + kr_kospi200 합산. 누락된 key 는 빈 리스트로 처리.
    """
    from pathlib import Path

    import yaml

    path = Path("config/universe.yaml")
    if not path.exists():
        return []

    with path.open() as f:
        u = yaml.safe_load(f) or {}

    tickers: set[str] = set()
    for key in ("us_core", "us_sp500_extended", "kr_kospi200"):
        section = u.get(key) or {}
        tickers.update(section.get("tickers") or [])
    return sorted(tickers)
