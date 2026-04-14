"""Integration tests for universe_sync — hits REAL Wikipedia + FDR.

이 파일은 mock 없이 실제 외부 서비스를 호출한다. Mock 테스트가 놓치는
실제 breakage (API 변경, 네트워크 실패, 라이브러리 버전 drift)를 잡는다.

실행 방법:
    make test-integration                        # 이 파일만
    pytest -m integration tests/integration/     # marker 기준

CI에서는 별도 job으로 격리 실행 (네트워크 실패가 일반 PR 차단하지 않도록).

왜 필요한가 (#272 세션 교훈):
    PR #276 개발 중 mock-only 테스트로 ship했다가 사용자가 실제 실행 시
    FDR의 SnapDataReader 깨짐 + BaseCollector retry 증폭 발견. 이런 real-world
    breakage는 mock으로 절대 감지 불가 — 실제 호출만 잡을 수 있다.
"""

from __future__ import annotations

import pytest

from nuri.collectors.universe_sync import (
    UniverseSyncCollector,
    _fetch_kospi200,
    _fetch_sp500_from_wikipedia,
)

pytestmark = pytest.mark.integration


class TestRealWikipedia:
    def test_sp500_fetches_503_tickers(self):
        """Wikipedia S&P 500 페이지가 500종목 범위 반환 (503±10 허용)."""
        tickers = _fetch_sp500_from_wikipedia()
        assert 490 <= len(tickers) <= 520, f"Expected ~500 tickers, got {len(tickers)}"

    def test_sp500_contains_known_mega_caps(self):
        """S&P 500에 반드시 있어야 할 mega cap 확인."""
        tickers = set(_fetch_sp500_from_wikipedia())
        # These MUST be in S&P 500 for the foreseeable future
        for expected in ["AAPL", "MSFT", "GOOGL", "NVDA", "JPM", "BRK-B"]:
            assert expected in tickers, f"Expected {expected} in S&P 500"

    def test_sp500_tickers_are_uppercase_alnum(self):
        """모든 ticker가 정상 format (대문자 + 숫자 + 하이픈)."""
        import re

        tickers = _fetch_sp500_from_wikipedia()
        pattern = re.compile(r"^[A-Z][A-Z0-9-]*$")
        for t in tickers:
            assert pattern.match(t), f"Invalid ticker format: {t}"


class TestRealFinanceDataReader:
    def test_fdr_installed(self):
        """FDR 설치 확인 — CI 에서는 dep으로 설치되어야."""
        try:
            import FinanceDataReader  # noqa: F401
        except ImportError:
            pytest.skip("finance-datareader not installed — run: uv pip install finance-datareader")

    def test_kospi200_fetches_200_tickers(self):
        """FDR StockListing('KOSPI') → Marcap top 200 정상 fetch."""
        try:
            import FinanceDataReader  # noqa: F401
        except ImportError:
            pytest.skip("finance-datareader not installed")

        tickers = _fetch_kospi200()
        assert len(tickers) == 200, f"Expected exactly 200 top-by-Marcap, got {len(tickers)}"

    def test_kospi200_contains_known_mega_caps(self):
        """KOSPI 시총 top-200에 반드시 있어야 할 종목."""
        try:
            import FinanceDataReader  # noqa: F401
        except ImportError:
            pytest.skip("finance-datareader not installed")

        tickers = set(_fetch_kospi200())
        # Samsung Electronics, SK Hynix — KOSPI 시총 영구 top-5
        assert "005930.KS" in tickers, "Samsung Electronics (005930) must be in KOSPI top-200"
        assert "000660.KS" in tickers, "SK Hynix (000660) must be in KOSPI top-200"

    def test_kospi200_suffix_format(self):
        """모든 ticker가 .KS suffix + 6자리 KRX code (ETN/신주 등 일부 알파벳 포함 허용)."""
        try:
            import FinanceDataReader  # noqa: F401
        except ImportError:
            pytest.skip("finance-datareader not installed")

        import re

        tickers = _fetch_kospi200()
        # KRX code: 주로 숫자 6자리, 드물게 ETN/신주인수권 같은 경우 알파벳 1자 포함
        # 예: 00680K (우리금융지주 신주)
        pattern = re.compile(r"^[0-9A-Z]{6}\.KS$")
        for t in tickers:
            assert pattern.match(t), f"Invalid KR ticker format: {t}"


class TestRealCollectorEndToEnd:
    """Full UniverseSyncCollector.run() E2E with real external deps."""

    def test_dry_run_us_only_no_retry_no_crash(self, capsys, caplog):
        """make universe-sync-us 실제 동작 시뮬레이션 — clean output, no retry."""
        import logging

        c = UniverseSyncCollector()
        with caplog.at_level(logging.INFO):
            count = c.run(market="us", dry_run=True)

        # Basic sanity
        assert count >= 0
        # No retry warnings (override of run() verified)
        retry_warnings = [r for r in caplog.records if "재시도" in r.message]
        assert retry_warnings == [], f"Unexpected retry: {[r.message for r in retry_warnings]}"
        # No exception class names in stderr
        out = capsys.readouterr()
        assert "Traceback" not in out.out, "Traceback leaked to stdout"
        assert "Traceback" not in out.err, "Traceback leaked to stderr"

    def test_dry_run_full_sync_both_markets(self, caplog):
        """make universe-sync — US + KR 모두 수집 성공 (또는 clean skip)."""
        import logging

        c = UniverseSyncCollector()
        with caplog.at_level(logging.INFO):
            c.run(dry_run=True)

        # Check: US fetched successfully (Wikipedia stable)
        us_fetched = any("S&P 500:" in r.message for r in caplog.records)
        assert us_fetched, "US S&P 500 fetch should succeed against live Wikipedia"
