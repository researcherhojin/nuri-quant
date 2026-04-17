"""nuri.core.live_price — intraday live oracle + divergence detection (Phase 2 A-5)."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz


def _kst(hour: int, minute: int = 0, weekday_offset: int = 0):
    """KST datetime 생성 헬퍼 (기본: 2026-04-20 월요일 기준)."""
    kst = pytz.timezone("Asia/Seoul")
    # 2026-04-20 = 월요일
    base = kst.localize(datetime(2026, 4, 20, hour, minute, 0))
    # weekday_offset: 0=월, 5=토, 6=일
    from datetime import timedelta
    return base + timedelta(days=weekday_offset)


class TestMarketHours:
    """시장 시간 판정 — fetch 해봐야 stored 와 같은 (T-1) 값일 likely한 시간 대에는
    fetch 를 skip 해 rate limit 보존."""

    def test_us_market_open_during_evening_kst(self):
        from nuri.core.live_price import is_market_open_us
        # 23:00 KST 월요일 → US 장중
        assert is_market_open_us(_kst(23, 0)) is True

    def test_us_market_open_early_morning_kst_when_prev_day_weekday(self):
        """화요일 05:00 KST = 월요일 US 장의 연장 → open."""
        from nuri.core.live_price import is_market_open_us
        assert is_market_open_us(_kst(5, 0, weekday_offset=1)) is True  # Tuesday

    def test_us_market_closed_monday_early_morning(self):
        """월요일 05:00 KST = 일요일 US time → closed.
        Codex Round 1 P2 regression lock: wrap-around 가 전날 요일 기반이어야 함."""
        from nuri.core.live_price import is_market_open_us
        assert is_market_open_us(_kst(5, 0)) is False  # Monday 05:00 KST

    def test_us_market_closed_midday_kst(self):
        """15:00 KST = US 전날 장 종료 이후 + 당일 장 시작 전 (10시간 공백)."""
        from nuri.core.live_price import is_market_open_us
        assert is_market_open_us(_kst(15, 0)) is False

    def test_us_market_closed_weekend(self):
        from nuri.core.live_price import is_market_open_us
        assert is_market_open_us(_kst(23, 0, weekday_offset=5)) is False  # Sat

    def test_kr_market_open(self):
        from nuri.core.live_price import is_market_open_kr
        assert is_market_open_kr(_kst(10, 0)) is True

    def test_kr_market_closed_evening(self):
        from nuri.core.live_price import is_market_open_kr
        assert is_market_open_kr(_kst(20, 0)) is False

    def test_kr_market_closed_weekend(self):
        from nuri.core.live_price import is_market_open_kr
        assert is_market_open_kr(_kst(10, 0, weekday_offset=6)) is False  # Sun

    def test_is_market_open_for_routes_kr_ticker(self):
        from nuri.core.live_price import is_market_open_for
        # KR 10:00 → KR ticker open, US ticker closed
        assert is_market_open_for("005930.KS", _kst(10, 0)) is True
        assert is_market_open_for("TSLA", _kst(10, 0)) is False

    def test_is_market_open_for_routes_us_ticker(self):
        from nuri.core.live_price import is_market_open_for
        # 23:00 KST → US open, KR closed
        assert is_market_open_for("TSLA", _kst(23, 0)) is True
        assert is_market_open_for("005930.KS", _kst(23, 0)) is False


class TestFetchLivePrice:
    """yfinance fast_info 래퍼. 실제 네트워크 호출은 mock."""

    def test_returns_price_when_market_open(self):
        from nuri.core import live_price as lp

        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 407.5

        with patch.object(lp, "is_market_open_for", return_value=True), \
             patch.dict("sys.modules", {"yfinance": MagicMock(Ticker=MagicMock(return_value=mock_ticker))}):
            price = lp.fetch_live_price("TSLA")

        assert price == 407.5

    def test_skips_when_market_closed(self):
        from nuri.core import live_price as lp

        with patch.object(lp, "is_market_open_for", return_value=False):
            assert lp.fetch_live_price("TSLA") is None

    def test_returns_none_on_exception(self):
        """네트워크 실패/잘못된 ticker 등 예외 → None (degrade gracefully)."""
        from nuri.core import live_price as lp

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("yfinance boom")

        with patch.object(lp, "is_market_open_for", return_value=True), \
             patch.dict("sys.modules", {"yfinance": mock_yf}):
            assert lp.fetch_live_price("TSLA") is None

    def test_returns_none_on_zero_price(self):
        """fast_info 가 0 또는 None 리턴 시 None."""
        from nuri.core import live_price as lp

        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 0

        with patch.object(lp, "is_market_open_for", return_value=True), \
             patch.dict("sys.modules", {"yfinance": MagicMock(Ticker=MagicMock(return_value=mock_ticker))}):
            assert lp.fetch_live_price("TSLA") is None


class TestCheckDivergence:
    """divergence 계산 — NFLX 사례(+10.87%) 방지가 핵심 intent."""

    def test_above_threshold_flagged(self):
        """live $107.79 vs stored $97.23 → +10.87% divergence > 3% → flagged."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=107.79):
            diverged, pct, live = lp.check_divergence("NFLX", stored_price=97.23)

        assert diverged is True
        assert 10.8 < pct < 10.9
        assert live == 107.79

    def test_below_threshold_not_flagged(self):
        """live $100 vs stored $99 → +1.01% < 3% → not flagged."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=100.0):
            diverged, pct, live = lp.check_divergence("XYZ", stored_price=99.0)

        assert diverged is False
        assert 1.0 < pct < 1.1

    def test_negative_divergence_flagged(self):
        """live $90 vs stored $100 → -10% → flagged."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=90.0):
            diverged, pct, live = lp.check_divergence("XYZ", stored_price=100.0)

        assert diverged is True
        assert -10.1 < pct < -9.9

    def test_fetch_fails_returns_not_diverged(self):
        """live_price=None → graceful (not diverged, pct=0)."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=None):
            diverged, pct, live = lp.check_divergence("XYZ", stored_price=100.0)

        assert diverged is False
        assert pct == 0.0
        assert live is None

    def test_zero_stored_price_safe(self):
        """stored=0 또는 음수 → divergence 계산 건너뛰기 (분모 0 방지)."""
        from nuri.core import live_price as lp

        diverged, pct, live = lp.check_divergence("XYZ", stored_price=0)
        assert diverged is False
        assert pct == 0.0
        assert live is None

    def test_custom_threshold(self):
        """threshold=10% 로 높여도 8% divergence 는 flagged 아님."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=108.0):
            diverged, _, _ = lp.check_divergence("XYZ", stored_price=100.0, threshold_pct=10.0)

        assert diverged is False

    def test_exact_threshold_flagged(self):
        """Codex Round 1 LOW: 정확히 threshold(3.0%) 는 spec 상 flagged 이어야 함
        (">=" 연산자 사용)."""
        from nuri.core import live_price as lp

        with patch.object(lp, "fetch_live_price", return_value=103.0):
            diverged, pct, _ = lp.check_divergence("XYZ", stored_price=100.0)

        assert diverged is True
        assert 2.99 < pct < 3.01


pytest.importorskip("pytz")
