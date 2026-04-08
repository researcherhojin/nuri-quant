"""Global test fixtures — yfinance mock + CI tmpfs SQLite 호환성."""
import pytest


@pytest.fixture(autouse=True)
def _force_no_wal(monkeypatch):
    """모든 테스트에서 SQLite를 MEMORY journal mode로 강제.

    배경: CI Linux tmpfs(/tmp)에서 다음 두 문제 발생:
    1. WAL 파일이 다른 연결에 보이지 않음 (mmap 비호환)
    2. journal_mode=OFF + 별도 connection 간 INSERT visibility 손실
       (synchronous도 같이 OFF 되어 fsync 안 됨 → tmpfs 캐시 비일관성)

    해결: journal_mode=MEMORY
    - 롤백 journal을 RAM에 유지 (빠름, 디스크 I/O 없음)
    - 트랜잭션 의미는 보존 → INSERT 후 다른 connection에서 즉시 보임
    - tmpfs/일반 fs 모두 호환

    영향: TestGate / TestGate_R23 / TestStockCollectorCoverage 등
    별도 connection 간 visibility 의존 테스트가 안정화됨.
    """
    import sqlite3

    import nuri.core.db as db_mod

    def _test_connect(dp=None):
        path = dp or db_mod.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        # MEMORY: rollback journal in RAM, preserves transaction semantics
        # (NORMAL synchronous → fsync on commit → cross-connection visibility)
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    monkeypatch.setattr(db_mod, "get_connection", _test_connect)


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
