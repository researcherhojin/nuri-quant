"""Global test fixtures — yfinance mock으로 네트워크 호출 제거."""
import pytest


@pytest.fixture(autouse=True)
def mock_yfinance(monkeypatch):
    """모든 테스트에서 yfinance.download와 Ticker를 mock."""
    import pandas as pd
    import numpy as np

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
