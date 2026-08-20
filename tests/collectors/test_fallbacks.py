"""CBOE 외부 소스 fallback 단위 테스트.

검증 범위:
    - CBOE 모든 소스 실패 → yfinance SPY 옵션 PCR
    - CBOE PCR DB stale fallback
    - consensus print verbose 모드

ARK 폴백 테스트는 여기 있었는데, 그 폴백이 제거되면서 같이 나갔다 (#1143 — top-10
보유 스냅샷을 매매 자리에 쓰던 코드다). ARK 는 `tests/collectors/test_ark.py` 로.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.cboe import CBOECollector

# ═══════════════════════════════════════════════════════
# CBOE yfinance SPY PCR fallback
# ═══════════════════════════════════════════════════════


class TestCBOEYFinancePCR:
    def test_spy_pcr_calculation(self):
        """SPY 옵션 체인에서 PCR 계산."""
        mock_calls = pd.DataFrame({"volume": [100.0, 200.0, 300.0]})
        mock_puts = pd.DataFrame({"volume": [400.0, 300.0, 200.0]})
        mock_chain = MagicMock()
        mock_chain.calls = mock_calls
        mock_chain.puts = mock_puts

        mock_ticker = MagicMock()
        mock_ticker.options = ["2026-04-15", "2026-05-20"]
        mock_ticker.option_chain.return_value = mock_chain

        collector = CBOECollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance_spy_pcr()

        assert len(records) == 1
        # PCR = 900 / 600 = 1.5
        assert abs(records[0]["value"] - 1.5) < 0.001
        assert records[0]["source"] == "yfinance_SPY"
        assert records[0]["indicator"] == "put_call_ratio"

    def test_no_options_returns_empty(self):
        mock_ticker = MagicMock()
        mock_ticker.options = []
        collector = CBOECollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance_spy_pcr()
        assert records == []

    def test_zero_call_volume_returns_empty(self):
        """0으로 나누기 방지."""
        mock_calls = pd.DataFrame({"volume": [0.0, 0.0]})
        mock_puts = pd.DataFrame({"volume": [100.0, 200.0]})
        mock_chain = MagicMock()
        mock_chain.calls = mock_calls
        mock_chain.puts = mock_puts

        mock_ticker = MagicMock()
        mock_ticker.options = ["2026-04-15"]
        mock_ticker.option_chain.return_value = mock_chain

        collector = CBOECollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance_spy_pcr()
        assert records == []

    def test_nan_volumes_handled(self):
        """NaN 거래량은 fillna(0)로 처리."""
        mock_calls = pd.DataFrame({"volume": [100.0, float("nan"), 200.0]})
        mock_puts = pd.DataFrame({"volume": [float("nan"), 300.0, 100.0]})
        mock_chain = MagicMock()
        mock_chain.calls = mock_calls
        mock_chain.puts = mock_puts

        mock_ticker = MagicMock()
        mock_ticker.options = ["2026-04-15"]
        mock_ticker.option_chain.return_value = mock_chain

        collector = CBOECollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance_spy_pcr()
        assert len(records) == 1
        # PCR = 400 / 300 ≈ 1.333
        assert abs(records[0]["value"] - 1.3333) < 0.001


# ═══════════════════════════════════════════════════════
# CBOE DB stale fallback
# ═══════════════════════════════════════════════════════


class TestCBOEDBStaleFallback:
    def test_stale_fallback_returns_old_value(self):
        """이전 PCR 값이 DB에 있으면 stale로 반환."""
        collector = CBOECollector()
        # 가짜 query 결과
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: {"date": "2026-04-01", "value": 0.85}[k]
        with patch("nuri.core.db.query", return_value=[mock_row]):
            with patch("nuri.collectors.cboe.today_str", return_value="2026-04-08"):
                records = collector._collect_db_stale()
        assert len(records) == 1
        assert records[0]["source"] == "DB_STALE"
        assert records[0]["date"] == "2026-04-01"  # 원래 날짜 유지
        assert records[0]["value"] == 0.85

    def test_stale_skipped_if_today_already_present(self):
        """오늘 데이터가 이미 있으면 stale fallback 안 함."""
        collector = CBOECollector()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: {"date": "2026-04-08", "value": 0.85}[k]
        with patch("nuri.core.db.query", return_value=[mock_row]):
            with patch("nuri.collectors.cboe.today_str", return_value="2026-04-08"):
                records = collector._collect_db_stale()
        assert records == []

    def test_stale_empty_db(self):
        collector = CBOECollector()
        with patch("nuri.core.db.query", return_value=[]):
            records = collector._collect_db_stale()
        assert records == []
