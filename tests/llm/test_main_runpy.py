"""Behavioral tests for nuri/llm/report.py `main()` entrypoint.

Refactored from runpy pattern (mocks invalidated by source re-execution) to direct
`main()` invocation following PR #593/#595 pattern.
"""

from __future__ import annotations

import io
import sys

import pytest

from nuri.llm import report as report_mod


class TestLLMReportMain:
    def test_main_gate_blocked_branch(self, monkeypatch, capsys):
        """gate_blocked=True 분기: '❌ Gate 차단' 메시지 + context 출력 + 파일 저장 X."""
        # 데모용 결과 — gate-blocked path
        fake_result = {
            "gate_blocked": True,
            "context": "데이터 완성도 25% — 모듈 X/Y 미수집",
            "report": None,
            "validation": {"passed": False, "warnings": ["데이터 부족"]},
            "disclaimer": "(disclaimer)",
        }
        monkeypatch.setattr(report_mod, "generate_llm_report_sync", lambda: fake_result)

        rc = report_mod.main()
        assert rc == 0

        out = capsys.readouterr().out
        assert "❌ Gate 차단" in out
        assert "데이터 완성도 25%" in out
        # 검증 경고 섹션도 함께 출력
        assert "=== 검증 결과 ===" in out
        assert "데이터 부족" in out

    def test_main_success_branch_writes_file(self, monkeypatch, tmp_path, capsys):
        """gate_blocked=False 성공 경로: 리포트 출력 + data/reports/{today}/llm_report.md 저장."""
        monkeypatch.chdir(tmp_path)

        report_text = "## 1. 시장 진단\n오늘은 위험-온 국면입니다."
        fake_result = {
            "gate_blocked": False,
            "context": "(unused on success)",
            "report": report_text,
            "validation": {"passed": True, "warnings": []},
            "disclaimer": "(disclaimer)",
        }
        monkeypatch.setattr(report_mod, "generate_llm_report_sync", lambda: fake_result)

        rc = report_mod.main()
        assert rc == 0

        out = capsys.readouterr().out
        assert "=== LLM 리포트 ===" in out
        assert "오늘은 위험-온 국면입니다" in out
        assert "📄 리포트 저장:" in out

        # 파일 실제 저장 확인
        from datetime import date

        saved = tmp_path / "data" / "reports" / str(date.today()) / "llm_report.md"
        assert saved.exists()
        assert saved.read_text(encoding="utf-8") == report_text

    def test_main_argv_unused_does_not_raise(self, monkeypatch, tmp_path):
        """argv 인자 받아도 무시 (현재 인자 없음). main(["--anything"]) → SystemExit 없음."""
        monkeypatch.chdir(tmp_path)
        fake_result = {
            "gate_blocked": True,
            "context": "x",
            "report": None,
            "validation": {"passed": False, "warnings": []},
            "disclaimer": "d",
        }
        monkeypatch.setattr(report_mod, "generate_llm_report_sync", lambda: fake_result)
        # 인자가 무시되는지 검증 — SystemExit 없이 0 반환
        assert report_mod.main(["--anything"]) == 0

    @pytest.mark.skip(reason="Removed legacy runpy test — main() refactor (PR #593/#595 pattern)")
    def test_main_gate_blocked_path(self):
        """Legacy runpy test placeholder."""
        # Kept as named slot to detect anyone trying to revive runpy pattern.
        pass


class TestLLMReportMainStdoutCapture:
    """capsys is the standard fixture; this guards against direct sys.stdout swap regressions."""

    def test_main_uses_print_not_logger(self, monkeypatch):
        """main()의 출력 경로는 print() — capsys로 캡처되어야 함."""
        captured = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured
        try:
            fake_result = {
                "gate_blocked": True,
                "context": "ctx-marker-XYZ",
                "report": None,
                "validation": {"passed": False, "warnings": []},
                "disclaimer": "d",
            }
            monkeypatch.setattr(report_mod, "generate_llm_report_sync", lambda: fake_result)
            report_mod.main()
        finally:
            sys.stdout = original_stdout

        assert "ctx-marker-XYZ" in captured.getvalue()
