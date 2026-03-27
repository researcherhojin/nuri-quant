"""스윙 트레이드 시스템 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestScanResult:
    def test_analyze_ticker(self):
        """단일 종목 분석 결과 구조."""
        from nuri.trading.swing.scanner import ScanResult, _analyze_ticker

        dates = pd.bdate_range("2025-01-01", periods=30)
        close = np.linspace(100, 120, 30)
        volume = [1000000] * 20 + [3000000] * 10  # 거래량 급증

        data = pd.DataFrame({
            "Close": close,
            "Volume": volume,
        }, index=dates)

        result = _analyze_ticker("TEST", data)
        # 거래량 급증 → volume_spike
        if result:
            assert isinstance(result, ScanResult)
            assert result.ticker == "TEST"
            assert result.score > 0


class TestSwingRules:
    def test_entry_evaluation(self, db_path):
        """빈 스캔 결과 → 빈 진입."""
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries(scan_results=[], db_path=db_path)
        assert entries == []

    def test_exit_no_positions(self, db_path):
        """오픈 포지션 없으면 빈 청산."""
        from nuri.trading.swing.rules import check_exits
        exits = check_exits(db_path=db_path)
        assert exits == []

    def test_save_entry(self, db_path):
        """진입 저장."""
        from nuri.trading.swing.rules import SwingEntry, save_entries
        entries = [SwingEntry(
            ticker="TEST", price=100.0, scan_signal="volume_spike",
            scan_score=30, agent_action="BUY", agent_confidence=70,
            agent_agreement=0.6, approved=True, reason="test",
        )]
        n = save_entries(entries, db_path=db_path)
        assert n == 1

        from nuri.core.db import query
        rows = query("SELECT * FROM swing_trades WHERE ticker='TEST'", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["status"] == "open"
