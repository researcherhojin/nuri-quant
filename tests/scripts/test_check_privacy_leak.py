"""Tests for scripts/check_privacy_leak.py — #138 regression guard.

Network-free. Tests use temporary fixture files with intentional leak content
that the scanner must catch — these fixtures live outside `tests/` paths to avoid
the scanner flagging the test file itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ═══════════════════════════════════════════════════════
# Fixture content — intentional leaks (must NOT live in tests/ paths)
# ═══════════════════════════════════════════════════════

LEAK_BROKER_KO = (
    "# Test fixture\n"
    "account = {\n"
    '    "name": "\uce74\uce74\uc624\ud398\uc774 \uc885\ud569\uacc4\uc88c",\n'
    '    "broker": "\uce74\uce74\uc624\ud398\uc774\uc99d\uad8c",\n'
    "}\n"
)

LEAK_BROKER_EN = """\
account_id = "kakaopay_main"
backup = "mirae_secondary"
"""

LEAK_SUSPECT_NUMERIC = """\
account = {
    "total_invested": 48323344,
    "cash_balance": 12345678,
}
"""

LEAK_NUMERIC_NEAR_KEY_BUT_ROUND = """\
account = {
    "total_invested": 1000000,
    "cash_balance": 5000000,
}
"""

CLEAN_FIXTURE = """\
account = {
    "name": "Test Account Alpha",
    "broker": "Test Securities Inc",
    "total_invested": 1000000,
}
"""

NUMERIC_WITHOUT_MONEY_KEY = """\
ROW_COUNT_THRESHOLD = 99999999
SAMPLE_SIZE = 12345678
"""


@pytest.fixture()
def tmp_file(tmp_path):
    def _make(content: str, name: str = "fixture.py") -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _make


class TestScanFile:
    def test_detects_korean_broker_name(self, tmp_file):
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_BROKER_KO))
        broker_findings = [f for f in findings if f.category == "broker_name"]
        assert len(broker_findings) >= 1
        # The pattern detected should be one of the Korean broker names
        categories = {f.category for f in broker_findings}
        assert "broker_name" in categories

    def test_detects_romanized_broker_name(self, tmp_file):
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_BROKER_EN))
        patterns = {f.pattern for f in findings}
        assert "kakaopay" in patterns
        assert "mirae" in patterns

    def test_detects_suspect_numeric(self, tmp_file):
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_SUSPECT_NUMERIC))
        numeric_findings = [f for f in findings if f.category == "suspect_numeric"]
        assert len(numeric_findings) == 2
        values = {f.pattern for f in numeric_findings}
        assert "48323344" in values
        assert "12345678" in values

    def test_round_million_placeholder_is_allowed(self, tmp_file):
        """1_000_000 / 5_000_000 etc. round values treated as placeholders."""
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_NUMERIC_NEAR_KEY_BUT_ROUND))
        assert findings == []

    def test_clean_fixture_yields_no_findings(self, tmp_file):
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(CLEAN_FIXTURE))
        assert findings == []

    def test_large_numeric_far_from_money_key_is_ignored(self, tmp_file):
        """ROW_COUNT, SAMPLE_SIZE etc. are not financial data."""
        from scripts.verify.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(NUMERIC_WITHOUT_MONEY_KEY))
        numeric_findings = [f for f in findings if f.category == "suspect_numeric"]
        assert numeric_findings == []


class TestTickerPnlPattern:
    """PR #202 leak signature — ticker + PnL co-occurrence."""

    def test_detects_signed_pct_with_ticker_in_parens(self):
        from scripts.verify.check_privacy_leak import scan_text_for_ticker_pnl

        text = "Losses: -34% (TEM), -22% (RKLB), -15% (TSLA) before trigger"
        findings = scan_text_for_ticker_pnl(text)
        tickers = {f.pattern for f in findings}
        assert "%(TEM)" in tickers
        assert "%(RKLB)" in tickers
        assert "%(TSLA)" in tickers
        assert all(f.category == "ticker_pnl" for f in findings)

    def test_detects_ticker_adjacent_signed_pct(self):
        from scripts.verify.check_privacy_leak import scan_text_for_ticker_pnl

        text = "trailing_stop_arm (PL +43% → +38%)"
        findings = scan_text_for_ticker_pnl(text)
        patterns = {f.pattern for f in findings}
        assert "PL +43%" in patterns

    def test_strategy_rule_text_is_not_flagged(self):
        """Rule thresholds like '손절 -7%' should NOT trigger — no ticker context."""
        from scripts.verify.check_privacy_leak import scan_text_for_ticker_pnl

        text = "O'Neil CAN SLIM: 손절 -7%, 익절 +20%/+40%, 트레일링 -15%"
        findings = scan_text_for_ticker_pnl(text)
        assert findings == []

    def test_abbreviations_not_treated_as_tickers(self):
        """HWM, SL, MDD, CPI, VIX should NOT trigger ticker+PnL."""
        from scripts.verify.check_privacy_leak import scan_text_for_ticker_pnl

        texts = [
            "Growth | +20% (sell 50%) | -15% from HWM",
            "(-7% SL, 15% pos)",
            "PnL -15% → MDD 한도(-10%) 초과",
            "Sharpe 1.5, MDD -5%",
            "CPI +0.3% MoM",
        ]
        for text in texts:
            findings = scan_text_for_ticker_pnl(text)
            assert findings == [], f"false positive on: {text!r}"

    def test_kospi_ticker_with_pnl_is_detected(self):
        """.KS suffix tickers should still match."""
        from scripts.verify.check_privacy_leak import scan_text_for_ticker_pnl

        text = "-8% (SMCI) and 005930.KS +12% disclosure"
        findings = scan_text_for_ticker_pnl(text)
        patterns = {f.pattern for f in findings}
        assert "%(SMCI)" in patterns

    def test_message_cli_mode_scans_stdin(self, monkeypatch, capsys):
        """--message reads stdin and scans as text."""
        import io

        from scripts.verify import check_privacy_leak as mod

        monkeypatch.setattr("sys.argv", ["check_privacy_leak.py", "--message"])
        monkeypatch.setattr("sys.stdin", io.StringIO("Losses: -34% (TEM)"))
        rc = mod.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "ticker+PnL" in out

    def test_message_cli_mode_exits_zero_on_clean(self, monkeypatch):
        import io

        from scripts.verify import check_privacy_leak as mod

        monkeypatch.setattr("sys.argv", ["check_privacy_leak.py", "--message", "--quiet"])
        monkeypatch.setattr("sys.stdin", io.StringIO("Standard rule: 손절 -7%"))
        assert mod.main() == 0


class TestKisExclusion_R138:
    """KIS (Korea Investment Securities) is intentionally excluded from the
    broker name list because it's an Open API integration target."""

    def test_kis_not_in_blocked_list(self):
        from scripts.verify.check_privacy_leak import BROKER_NAMES_KO

        assert "\ud55c\uad6d\ud22c\uc790\uc99d\uad8c" not in BROKER_NAMES_KO

    def test_kis_documentation_does_not_trigger(self, tmp_file):
        from scripts.verify.check_privacy_leak import scan_path

        kis_doc = tmp_file('"""KIS Open API collector."""\n')
        findings = scan_path(kis_doc)
        assert findings == []


class TestAllowlist:
    def test_self_allowlisted(self):
        from scripts.verify.check_privacy_leak import is_allowlisted

        path = Path("scripts/check_privacy_leak.py")
        assert is_allowlisted(path) is True

    def test_external_path_not_allowlisted(self, tmp_path):
        """Repo-external paths should not be allowlisted."""
        from scripts.verify.check_privacy_leak import is_allowlisted

        external = tmp_path / "outside.py"
        external.write_text("noop")
        assert is_allowlisted(external) is False


class TestExitCodes:
    def test_main_returns_one_on_leak(self, monkeypatch, tmp_file, capsys):
        from scripts.verify import check_privacy_leak as mod

        leak_file = tmp_file(LEAK_BROKER_KO)
        monkeypatch.setattr("sys.argv", ["check_privacy_leak.py", str(leak_file)])
        assert mod.main() == 1

    def test_main_returns_zero_on_clean(self, monkeypatch, tmp_file, capsys):
        from scripts.verify import check_privacy_leak as mod

        clean_file = tmp_file(CLEAN_FIXTURE)
        monkeypatch.setattr(
            "sys.argv",
            ["check_privacy_leak.py", str(clean_file)],
        )
        assert mod.main() == 0

    def test_quiet_suppresses_output_on_clean(self, monkeypatch, tmp_file, capsys):
        from scripts.verify import check_privacy_leak as mod

        clean_file = tmp_file(CLEAN_FIXTURE)
        monkeypatch.setattr(
            "sys.argv",
            ["check_privacy_leak.py", "--quiet", str(clean_file)],
        )
        rc = mod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert out == ""  # quiet on success
