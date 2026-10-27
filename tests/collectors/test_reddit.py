"""#1979: 은퇴한 Reddit 수집 경로는 다시 활성화하지 않는다."""

import importlib.util
from pathlib import Path

from nuri import scheduler


def test_reddit_collector_is_not_importable():
    assert importlib.util.find_spec("nuri.collectors.reddit") is None


def test_reddit_has_no_scheduled_or_manual_collection_route():
    assert "reddit" not in scheduler._STAGE_OF_JOB
    assert "reddit" not in {job["name"] for job in scheduler.SCHEDULES}
    root = Path(__file__).resolve().parents[2]
    assert "-m nuri.collectors.reddit" not in (root / "Makefile").read_text()
