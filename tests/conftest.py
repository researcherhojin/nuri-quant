"""Global test fixtures — yfinance mock + CI tmpfs WAL 호환성."""
import pytest


@pytest.fixture(autouse=True)
def _force_no_wal(monkeypatch):
    """모든 테스트에서 SQLite WAL 모드를 비활성화.

    CI tmpfs에서 WAL 파일이 다른 연결에 보이지 않는 문제를 방지.
    원본 get_connection을 우회하여 WAL 설정 자체를 건너뜀.
    """
    import sqlite3

    import nuri.core.db as db_mod

    def _no_wal(dp=None):
        path = dp or db_mod.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", _no_wal)


@pytest.fixture(autouse=True)
def mock_yfinance(monkeypatch):
    """모든 테스트에서 yfinance.download와 Ticker를 mock."""
    import pandas as pd

    class MockTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.upgrades_downgrades = None
            self.earnings_history = None
            self.insider_transactions = None
            self.recommendations = None

    def mock_download(*args, **kwargs):
        return pd.DataFrame()

    try:
        import yfinance
        monkeypatch.setattr(yfinance, "download", mock_download)
        monkeypatch.setattr(yfinance, "Ticker", MockTicker)
    except ImportError:
        pass
