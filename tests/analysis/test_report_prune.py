"""`data/reports` 날짜 디렉터리 보존 정리 (#1654).

지워도 되는 것(보존 기간 지난 날짜 디렉터리)과 절대 지우면 안 되는 것(비-날짜 원장 디렉터리 ·
최신 날짜 디렉터리 · 미래 디렉터리)을 임시 트리에서 잠근다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nuri.analysis.report_prune import (
    REPORT_RETENTION_DAYS,
    main,
    prunable_report_dirs,
    prune_report_dirs,
)

TODAY = "2026-10-06"


def _tree(root: Path, names: list[str]) -> None:
    for n in names:
        (root / n).mkdir(parents=True)
        (root / n / "marker.txt").write_text(n)


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    _tree(root, ["2026-01-01", "2026-09-01", "2026-09-07", "2026-10-05", "2027-09-14", "briefs", "buy_tracking"])
    (root / "stray.md").write_text("not a dir")
    return root


class TestPrunableReportDirs:
    def test_only_date_dirs_older_than_the_cutoff(self, reports: Path):
        # cutoff = today − 30d = 2026-09-06: 09-01 is older, 09-07 is not
        got = [d.name for d in prunable_report_dirs(reports, 30, TODAY)]
        assert got == ["2026-01-01", "2026-09-01"]

    def test_never_the_non_date_or_future_dirs(self, reports: Path):
        got = {d.name for d in prunable_report_dirs(reports, 0, TODAY)}
        assert "briefs" not in got
        assert "buy_tracking" not in got
        assert "2027-09-14" not in got

    def test_keeps_the_newest_past_dir_even_when_everything_is_old(self, tmp_path: Path):
        root = tmp_path / "reports"
        _tree(root, ["2026-01-01", "2026-02-01"])
        got = [d.name for d in prunable_report_dirs(root, 30, TODAY)]
        assert got == ["2026-01-01"]

    def test_keeps_the_newest_holder_of_each_consumed_artifact(self, tmp_path: Path):
        # Codex #1654 P1: scorecard/results 는 수동 `make validate` 때만 생긴다 — 8월 디렉터리에만
        # 있고 그 뒤는 evidence 만 쌓인 트리에서 "최신 디렉터리" 만 남기면 소비자가 빈손이 된다.
        root = tmp_path / "reports"
        _tree(root, ["2026-08-17", "2026-08-30", "2026-09-20", "2026-10-05"])
        (root / "2026-08-17" / "signal_scorecard.csv").write_text("old")
        (root / "2026-08-30" / "signal_scorecard.csv").write_text("latest scorecard")
        (root / "2026-08-30" / "signal_results.csv").write_text("latest results")
        (root / "2026-09-20" / "evidence").mkdir()
        got = [d.name for d in prunable_report_dirs(root, 7, TODAY)]
        # 08-17 은 더 최신 보유자가 있어 지워진다; 08-30(scorecard·results), 09-20(evidence), 10-05(최신) 는 남는다
        assert got == ["2026-08-17"]

    def test_missing_report_dir_is_empty(self, tmp_path: Path):
        assert prunable_report_dirs(tmp_path / "nope", 30, TODAY) == []

    def test_default_retention_is_thirty_days(self):
        assert REPORT_RETENTION_DAYS == 30


class TestPruneReportDirs:
    def test_removes_the_targets_and_nothing_else(self, reports: Path):
        removed = prune_report_dirs(reports, 30, TODAY)
        assert [d.name for d in removed] == ["2026-01-01", "2026-09-01"]
        left = sorted(p.name for p in reports.iterdir())
        assert left == ["2026-09-07", "2026-10-05", "2027-09-14", "briefs", "buy_tracking", "stray.md"]

    def test_dry_run_lists_without_removing(self, reports: Path):
        before = sorted(p.name for p in reports.iterdir())
        targets = prune_report_dirs(reports, 30, TODAY, dry_run=True)
        assert [d.name for d in targets] == ["2026-01-01", "2026-09-01"]
        assert sorted(p.name for p in reports.iterdir()) == before


class TestMain:
    def test_cli_dry_run_reports_targets(
        self, reports: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr("nuri.analysis.report_prune.REPORT_DIR", reports)
        monkeypatch.setattr("nuri.analysis.report_prune.today_kst", lambda: TODAY)
        assert main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "would remove 2 report directories older than 30 days" in out
        assert (reports / "2026-01-01").exists()

    def test_cli_days_override(
        self, reports: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr("nuri.analysis.report_prune.REPORT_DIR", reports)
        monkeypatch.setattr("nuri.analysis.report_prune.today_kst", lambda: TODAY)
        assert main(["--days", "0"]) == 0
        assert "removed 3 report directories older than 0 days" in capsys.readouterr().out
        assert (reports / "2026-10-05").exists()  # newest past dir survives
        assert not (reports / "2026-09-07").exists()
