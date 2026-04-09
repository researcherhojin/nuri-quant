"""Tests for scripts/check_privacy_leak.py — #138 regression guard.

Network-free. Tests use temporary fixture files with intentional leak content
that the scanner must catch — these fixtures live outside `tests/` to avoid
the scanner flagging the test file itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ═══════════════════════════════════════════════════════
# Fixture content — intentional leaks (must NOT live in tests/ paths)
# ═══════════════════════════════════════════════════════

LEAK_BROKER_KO = """\
# Test fixture
account = {
    "name": "Brokerage Alpha Cash Account",
    "broker": "Brokerage Alpha Securities",
}
"""

LEAK_BROKER_EN = """\
account_id = "kakaopay_main"
backup = "mirae_secondary"
"""

LEAK_SUSPECT_NUMERIC = """\
account = {
    "total_invested": 1000000,
    "cash_balance": 1000000,
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
    "name": "Brokerage Alpha Cash Account",
    "broker": "Brokerage Alpha Securities",
    "total_invested": 1000000,
}
"""

NUMERIC_WITHOUT_MONEY_KEY = """\
ROW_COUNT_THRESHOLD = 99999999
SAMPLE_SIZE = 1000000
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
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_BROKER_KO))
        broker_findings = [f for f in findings if f.category == "broker_name"]
        assert len(broker_findings) >= 1
        patterns = {f.pattern for f in broker_findings}
        assert "Brokerage Alpha" in patterns

    def test_detects_romanized_broker_name(self, tmp_file):
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_BROKER_EN))
        patterns = {f.pattern for f in findings}
        assert "kakaopay" in patterns
        assert "mirae" in patterns

    def test_detects_suspect_numeric(self, tmp_file):
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_SUSPECT_NUMERIC))
        numeric_findings = [f for f in findings if f.category == "suspect_numeric"]
        assert len(numeric_findings) == 2
        values = {f.pattern for f in numeric_findings}
        assert "1000000" in values
        assert "1000000" in values

    def test_round_million_placeholder_is_allowed(self, tmp_file):
        """1_000_000 / 5_000_000 등 round 값은 placeholder로 간주."""
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(LEAK_NUMERIC_NEAR_KEY_BUT_ROUND))
        assert findings == []

    def test_clean_fixture_yields_no_findings(self, tmp_file):
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(CLEAN_FIXTURE))
        assert findings == []

    def test_large_numeric_far_from_money_key_is_ignored(self, tmp_file):
        """ROW_COUNT, SAMPLE_SIZE 등은 금융 데이터 아님."""
        from scripts.check_privacy_leak import scan_path

        findings = scan_path(tmp_file(NUMERIC_WITHOUT_MONEY_KEY))
        numeric_findings = [f for f in findings if f.category == "suspect_numeric"]
        assert numeric_findings == []


class TestKisExclusion_R138:
    """`한국투자증권` (KIS) 은 Open API 통합 대상으로 의도적 제외.

    Regression: 처음 패턴 리스트에 KIS를 넣었더니 `nuri/collectors/kis_*`,
    `docs/KIS_INTEGRATION.md`, `.env.example`에서 false positive 4건 발생.
    이 테스트는 KIS가 빠진 상태를 보장한다.
    """

    def test_kis_not_in_blocked_list(self):
        from scripts.check_privacy_leak import BROKER_NAMES_KO

        assert "한국투자증권" not in BROKER_NAMES_KO

    def test_kis_documentation_does_not_trigger(self, tmp_file):
        from scripts.check_privacy_leak import scan_path

        kis_doc = tmp_file(
            '"""KIS (한국투자증권) Open API 실시간 시세 수집기."""\n'
        )
        findings = scan_path(kis_doc)
        # Brokerage Alpha 등 다른 broker는 없고, 한국투자증권은 블록 안 됨
        assert findings == []


class TestAllowlist:
    def test_self_allowlisted(self):
        from scripts.check_privacy_leak import is_allowlisted

        # check_privacy_leak.py 자체는 패턴을 documentation하므로 allowlist
        path = Path("scripts/check_privacy_leak.py")
        assert is_allowlisted(path) is True

    def test_external_path_not_allowlisted(self, tmp_path):
        """Repo 밖 경로는 allowlist 체크에서 ValueError 발생 안 해야."""
        from scripts.check_privacy_leak import is_allowlisted

        external = tmp_path / "outside.py"
        external.write_text("noop")
        # 외부 경로 → False (not allowlisted) — ValueError 안 나야
        assert is_allowlisted(external) is False


class TestExitCodes:
    def test_main_returns_one_on_leak(self, monkeypatch, tmp_file, capsys):
        from scripts import check_privacy_leak as mod

        leak_file = tmp_file(LEAK_BROKER_KO)
        monkeypatch.setattr("sys.argv", ["check_privacy_leak.py", str(leak_file)])
        assert mod.main() == 1

    def test_main_returns_zero_on_clean(self, monkeypatch, tmp_file, capsys):
        from scripts import check_privacy_leak as mod

        clean_file = tmp_file(CLEAN_FIXTURE)
        monkeypatch.setattr("sys.argv", ["check_privacy_leak.py", str(clean_file)])
        assert mod.main() == 0

    def test_quiet_suppresses_output_on_clean(self, monkeypatch, tmp_file, capsys):
        from scripts import check_privacy_leak as mod

        clean_file = tmp_file(CLEAN_FIXTURE)
        monkeypatch.setattr(
            "sys.argv",
            ["check_privacy_leak.py", "--quiet", str(clean_file)],
        )
        rc = mod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert out == ""  # quiet on success
