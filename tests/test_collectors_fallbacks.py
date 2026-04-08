"""ARK / CBOE 외부 소스 fallback 단위 테스트.

검증 범위:
    - ARK CSV 실패 → yfinance ETF holdings fallback
    - ARK weight 단위 변환 (yfinance 0.10 → 10%)
    - CBOE 모든 소스 실패 → yfinance SPY 옵션 PCR
    - CBOE PCR DB stale fallback
    - consensus print verbose 모드
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nuri.collectors.ark import ARK_ETFS, ARKCollector
from nuri.collectors.cboe import CBOECollector

# ═══════════════════════════════════════════════════════
# ARK yfinance fallback
# ═══════════════════════════════════════════════════════


class TestARKYFinanceFallback:
    def test_yfinance_fallback_collects_holdings(self):
        """CSV 실패 → yfinance fallback 호출 → holdings 정상 변환."""
        # 모의 yfinance Ticker.funds_data.top_holdings
        mock_holdings = pd.DataFrame({
            "Name": ["Tesla Inc", "NVIDIA Corp"],
            "Holding Percent": [0.1040, 0.0850],  # 10.4%, 8.5%
        }, index=pd.Index(["TSLA", "NVDA"], name="Symbol"))
        mock_fd = MagicMock()
        mock_fd.top_holdings = mock_holdings
        mock_ticker = MagicMock()
        mock_ticker.funds_data = mock_fd

        held = {"TSLA", "NVDA", "AMD"}  # AMD는 없는 종목
        collector = ARKCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance(held)

        assert len(records) > 0
        # ARK ETF 5개 × 2개 종목 = 10건
        assert len(records) == len(ARK_ETFS) * 2
        # 단위 변환 확인: 0.1040 → 10.40
        tsla_records = [r for r in records if r["ticker"] == "TSLA"]
        assert all(abs(r["weight"] - 10.40) < 0.01 for r in tsla_records)
        nvda_records = [r for r in records if r["ticker"] == "NVDA"]
        assert all(abs(r["weight"] - 8.50) < 0.01 for r in nvda_records)
        # direction은 "Hold" (매매 내역 X)
        assert all(r["direction"] == "Hold" for r in records)
        # held 필터링: AMD는 없어야 함
        assert not any(r["ticker"] == "AMD" for r in records)

    def test_yfinance_fallback_skips_non_held(self):
        mock_holdings = pd.DataFrame({
            "Name": ["Tesla Inc"],
            "Holding Percent": [0.1040],
        }, index=pd.Index(["TSLA"], name="Symbol"))
        mock_fd = MagicMock()
        mock_fd.top_holdings = mock_holdings
        mock_ticker = MagicMock()
        mock_ticker.funds_data = mock_fd

        # 보유 종목에 TSLA 없음
        held = {"AMD"}
        collector = ARKCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance(held)
        assert records == []

    def test_yfinance_fallback_empty_holdings(self):
        mock_fd = MagicMock()
        mock_fd.top_holdings = pd.DataFrame()
        mock_ticker = MagicMock()
        mock_ticker.funds_data = mock_fd

        collector = ARKCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance({"TSLA"})
        assert records == []

    def test_yfinance_fallback_no_funds_data(self):
        """funds_data가 None인 ETF."""
        mock_ticker = MagicMock()
        mock_ticker.funds_data = None

        collector = ARKCollector()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            records = collector._collect_yfinance({"TSLA"})
        assert records == []

    def test_collect_falls_through_to_yfinance(self):
        """CSV 2개 모두 실패 시 yfinance fallback 호출 확인."""
        collector = ARKCollector()
        with patch.object(collector, "_collect_csv",
                          side_effect=Exception("CSV 다운 실패")):
            with patch.object(collector, "_collect_yfinance",
                              return_value=[{"ticker": "TSLA", "weight": 10.4,
                                              "shares": 0.0, "direction": "Hold",
                                              "fund": "ARKK", "date": "2026-04-08"}]):
                with patch("nuri.collectors.ark.get_tickers", return_value=["TSLA"]):
                    result = collector.collect()
        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"


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
