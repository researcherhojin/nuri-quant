"""thesis 파일럿의 스케줄 배선 (#1964 · #1998) — 등록 시각을 실제 trigger 로 계산해 확인한다.

함수 단위 테스트만으로는 등록 시각의 결함을 못 본다 — US 브리프가 8개월간 한 번도 안 돈 것도 함수는 옳았는데
cron 이 창 밖에 있었기 때문이다(`tests/alerts/test_postmarket_brief.py`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from nuri import scheduler
from nuri.core.timezone import KST
from nuri.llm import thesis_pilot as tp
from nuri.llm import thesis_pilot_ops as ops

REPO = Path(__file__).resolve().parents[2]


def job(name):
    entries = [j for j in scheduler.SCHEDULES if j["name"] == name]
    assert len(entries) == 1, f"{name} 가 SCHEDULES 에 한 번 등록돼 있어야 한다"
    return entries[0]


# tz 없는 job 은 프로세스의 지역 시간대로 돈다 — 운영 기기(mini)는 KST 다(2026-10-27 `date` 확인). 테스트가
# 어느 기기에서 돌든 운영과 같게 계산한다(CI 러너는 UTC).
PRODUCTION_TZ = "Asia/Seoul"


def fires(name, start, days=7):
    """실제 등록 trigger 의 발화 시각들 — `_make_trigger` 의 요일 변환까지 포함한다."""
    trigger = scheduler._make_trigger(job(name)["cron"], job(name).get("tz") or PRODUCTION_TZ)
    out, prev, now = [], None, start
    while True:
        nxt = trigger.get_next_fire_time(prev, now)
        if nxt is None or nxt >= start + timedelta(days=days):
            return out
        out.append(nxt.astimezone(KST))
        prev, now = nxt, nxt + timedelta(seconds=1)


class TestRegistration:
    def test_the_night_fires_tuesday_to_saturday_at_09_10_kst(self):
        week = fires("thesis_pilot", datetime(2026, 11, 2, 0, 0, tzinfo=KST))  # 월요일 00:00 부터 한 주
        assert [(f.strftime("%a"), f.hour, f.minute) for f in week] == [
            (d, 9, 10) for d in ("Tue", "Wed", "Thu", "Fri", "Sat")
        ]

    @pytest.mark.parametrize("name", ["thesis_pilot", "thesis_pilot_check"])
    def test_the_times_are_kst_on_any_host(self, name):
        """tz 가 없으면 프로세스의 지역 시간대로 해석된다 — CI(UTC)에서 09:10 이 18:10 KST 로 계산됐다."""
        assert job(name).get("tz") == "Asia/Seoul", "tz 를 등록에 명시해야 한다 — 기기 시간대에 기대지 않게"
        assert str(scheduler._make_trigger(job(name)["cron"], job(name)["tz"]).timezone) == "Asia/Seoul"

    def test_the_check_fires_daily_at_noon(self):
        assert [(f.hour, f.minute) for f in fires("thesis_pilot_check", datetime(2026, 11, 2, 0, 0, tzinfo=KST))] == [
            (12, 0)
        ] * 7

    @pytest.mark.parametrize("start", [datetime(2026, 7, 6, tzinfo=KST), datetime(2026, 1, 5, tzinfo=KST)])
    def test_the_night_never_starts_inside_the_brief_ollama_window_in_either_dst_regime(self, start):
        """EDT · EST 둘 다 — 러너가 `ollama_busy` 로 스스로 거절하는 시각에 등록돼 있으면 파일럿이 매일 빈다."""
        quiet = yaml.safe_load((REPO / tp.PILOT_PATH).read_text())["brief_quiet_minutes"]
        for fire in fires("thesis_pilot", start):
            assert not tp.brief_busy(fire, quiet), fire

    def test_the_night_starts_after_the_daily_self_restart(self):
        """재기동이 배치 도중에 오지 않게 — 분리 실행이 지켜 주지만, 굳이 겹칠 이유가 없다."""
        restart = fires("self_restart", datetime(2026, 11, 3, 0, 0, tzinfo=KST), days=1)[0]
        night = fires("thesis_pilot", datetime(2026, 11, 3, 0, 0, tzinfo=KST), days=1)[0]
        assert night > restart

    def test_the_check_runs_after_the_night(self):
        night = fires("thesis_pilot", datetime(2026, 11, 3, 0, 0, tzinfo=KST), days=1)[0]
        check = fires("thesis_pilot_check", datetime(2026, 11, 3, 0, 0, tzinfo=KST), days=1)[0]
        assert check - night >= timedelta(hours=2)


class TestWrappers:
    def test_a_disabled_config_launches_nothing(self, monkeypatch, tmp_path):
        """experiment: null — 스케줄러가 불러도 아무 프로세스도 뜨지 않는다."""
        (tmp_path / "config").mkdir()
        (tmp_path / tp.PILOT_PATH).write_text("experiment: null\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(tp, "launch", lambda *a, **k: pytest.fail("disabled pilot launched a process"))
        scheduler._run_thesis_pilot()

    def test_a_launched_night_is_logged(self, monkeypatch, caplog):
        monkeypatch.setattr(tp, "launch_night", lambda: 4242)
        with caplog.at_level(logging.INFO):
            scheduler._run_thesis_pilot()
        assert "4242" in caplog.text

    def test_a_failure_is_logged_not_raised(self, monkeypatch, caplog):
        """스케줄러 job 하나의 예외가 다른 job 을 멈추지 않게 — 다른 래퍼와 같은 규약."""

        def boom():
            raise RuntimeError("bad config")

        monkeypatch.setattr(tp, "launch_night", boom)
        monkeypatch.setattr(ops, "main", lambda argv: boom())
        with caplog.at_level(logging.ERROR):
            scheduler._run_thesis_pilot()
            scheduler._run_thesis_pilot_check()
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 2 and all("bad config" in m for m in errors)

    def test_the_check_runs_the_ops_check_command(self, monkeypatch):
        seen = []
        monkeypatch.setattr(ops, "main", lambda argv: seen.append(argv) or 0)
        scheduler._run_thesis_pilot_check()
        assert seen == [["check"]]
