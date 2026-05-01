"""Tests for scripts/validate_portfolio.py — #131 regression guard.

Privacy: per project memory, no real tickers/quantities/prices/accounts in
fixtures. All fixtures use TEST_* placeholders.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

# Note: conftest.py auto-mocks yfinance.download to empty DataFrame.
# Tests below override that mock per-test as needed.


FIXTURE_YAML = """\
accounts:
  test_alpha:
    name: "Test Alpha Account"
    broker: "Mock Broker"
    currency: USD
    holdings:
      - { ticker: TEST_VALID,   qty: 1, avg: 100.00, sector: Test }
      - { ticker: TEST_DELISTED, qty: 1, avg: 100.00, sector: Test }
  test_beta:
    name: "Test Beta Account"
    broker: "Mock Broker"
    currency: KRW
    holdings:
      - { ticker: "TEST_KR",    qty: 1, avg: 1000.00, sector: Test }
"""


@pytest.fixture()
def fixture_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "portfolio.yaml"
    path.write_text(FIXTURE_YAML)
    return path


@pytest.fixture()
def mock_yfinance_per_ticker(monkeypatch):
    """yfinance.download이 ticker별로 다른 결과를 내도록 패치."""

    def fake_download(ticker, *args, **kwargs):
        if ticker == "TEST_VALID":
            return pd.DataFrame(
                {"Open": [100, 101], "Close": [101, 102], "Volume": [1000, 1100]},
                index=pd.to_datetime(["2026-04-08", "2026-04-09"]),
            )
        if ticker == "TEST_KR":
            return pd.DataFrame(
                {"Open": [1000], "Close": [1010], "Volume": [500]},
                index=pd.to_datetime(["2026-04-09"]),
            )
        # TEST_DELISTED + 그 외 → 빈 DataFrame
        return pd.DataFrame()

    import yfinance as yf

    monkeypatch.setattr(yf, "download", fake_download)


class TestCheckTicker:
    def test_valid_ticker_returns_truthy(self, mock_yfinance_per_ticker):
        from scripts.doc.validate_portfolio import check_ticker

        is_valid, rows, error = check_ticker("TEST_VALID")
        assert is_valid is True
        assert rows == 2
        assert error is None

    def test_empty_dataframe_returns_invalid(self, mock_yfinance_per_ticker):
        from scripts.doc.validate_portfolio import check_ticker

        is_valid, rows, error = check_ticker("TEST_DELISTED")
        assert is_valid is False
        assert rows == 0
        assert error is None  # 빈 결과는 에러 아님 — "데이터 없음"

    def test_exception_returns_invalid_with_error(self, monkeypatch):
        import yfinance as yf

        def boom(*args, **kwargs):
            raise ConnectionError("network down")

        monkeypatch.setattr(yf, "download", boom)
        from scripts.doc.validate_portfolio import check_ticker

        is_valid, rows, error = check_ticker("TEST_NETWORK_FAIL")
        assert is_valid is False
        assert rows == 0
        assert error is not None
        assert "ConnectionError" in error
        assert "network down" in error


class TestValidatePortfolio:
    def test_returns_one_result_per_ticker(self, fixture_yaml, mock_yfinance_per_ticker):
        from scripts.doc.validate_portfolio import validate_portfolio

        results = validate_portfolio(fixture_yaml)
        assert len(results) == 3

        by_ticker = {r.ticker: r for r in results}
        assert by_ticker["TEST_VALID"].is_valid is True
        assert by_ticker["TEST_VALID"].account == "test_alpha"
        assert by_ticker["TEST_DELISTED"].is_valid is False
        assert by_ticker["TEST_KR"].is_valid is True
        assert by_ticker["TEST_KR"].account == "test_beta"


class TestPrintReport:
    def test_lists_valid_and_invalid(self, capsys, mock_yfinance_per_ticker, fixture_yaml):
        from scripts.doc.validate_portfolio import print_report, validate_portfolio

        results = validate_portfolio(fixture_yaml)
        print_report(results)

        out = capsys.readouterr().out
        assert "TEST_VALID" in out
        assert "TEST_KR" in out
        assert "TEST_DELISTED" in out
        assert "Invalid" in out or "invalid" in out
        assert "Action:" in out

    def test_quiet_skips_valid_section(self, capsys, mock_yfinance_per_ticker, fixture_yaml):
        from scripts.doc.validate_portfolio import print_report, validate_portfolio

        results = validate_portfolio(fixture_yaml)
        print_report(results, quiet=True)

        out = capsys.readouterr().out
        # quiet에서도 invalid 섹션은 보여야 함
        assert "TEST_DELISTED" in out
        # 정상 ticker는 quiet에서 안 보임
        assert "TEST_VALID" not in out
        assert "All tickers valid" not in out

    def test_all_valid_shows_success_message(self, capsys, monkeypatch, tmp_path):
        # 모든 ticker가 valid한 fixture
        yaml_path = tmp_path / "all_valid.yaml"
        yaml_path.write_text(
            "accounts:\n"
            "  test:\n"
            "    name: Test\n"
            "    broker: Mock\n"
            "    currency: USD\n"
            "    holdings:\n"
            "      - { ticker: TEST_VALID, qty: 1, avg: 100, sector: Test }\n"
        )

        import yfinance as yf

        monkeypatch.setattr(
            yf,
            "download",
            lambda *a, **kw: pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-04-09"])),
        )

        from scripts.doc.validate_portfolio import print_report, validate_portfolio

        results = validate_portfolio(yaml_path)
        print_report(results)

        out = capsys.readouterr().out
        assert "All tickers valid" in out


class TestMainExitCodes:
    def test_returns_zero_when_all_valid(self, monkeypatch, tmp_path):
        yaml_path = tmp_path / "ok.yaml"
        yaml_path.write_text(
            "accounts:\n  test:\n    name: T\n    broker: M\n    currency: USD\n"
            "    holdings:\n      - { ticker: TEST_OK, qty: 1, avg: 100, sector: T }\n"
        )

        import yfinance as yf

        monkeypatch.setattr(
            yf,
            "download",
            lambda *a, **kw: pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-04-09"])),
        )

        from scripts.doc import validate_portfolio as mod

        monkeypatch.setattr("sys.argv", ["validate_portfolio.py", "--config", str(yaml_path)])
        assert mod.main() == 0

    def test_returns_one_when_any_invalid(self, monkeypatch, fixture_yaml, mock_yfinance_per_ticker):
        from scripts.doc import validate_portfolio as mod

        monkeypatch.setattr("sys.argv", ["validate_portfolio.py", "--config", str(fixture_yaml)])
        assert mod.main() == 1

    def test_returns_two_when_config_missing(self, monkeypatch, tmp_path):
        from scripts.doc import validate_portfolio as mod

        missing = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr("sys.argv", ["validate_portfolio.py", "--config", str(missing)])
        assert mod.main() == 2
