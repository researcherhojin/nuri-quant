"""heartbeat_watchdog 테스트 — DB·scheduler 무의존 staleness 알림.

Gotcha-Test Pair (2026-06-09 6일 silent outage 재발 방지): watchdog 이 stale
heartbeat 에 alert 를 보내고, fresh/missing 에는 안 보내는 계약을 고정.
회귀(임계 비교/스킵 로직 변경) 시 silent outage 탐지 불능.
"""

import os
import time
from unittest.mock import patch

from nuri.alerts import heartbeat_watchdog as hw


def _write_heartbeat(path, age_minutes: float):
    """주어진 age(분) 만큼 과거 mtime 으로 heartbeat 파일 생성."""
    path.write_text("2026-06-15T00:00:00")
    past = time.time() - age_minutes * 60.0
    os.utime(path, (past, past))


class TestHeartbeatAge:
    def test_age_none_when_file_missing(self, tmp_path):
        assert hw.heartbeat_age_minutes(path=tmp_path / "nope") is None

    def test_age_computed_from_mtime(self, tmp_path):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=40.0)
        age = hw.heartbeat_age_minutes(path=p, now_epoch=time.time())
        assert 39.0 < age < 41.0


class TestMain:
    def test_fresh_heartbeat_no_alert(self, tmp_path, monkeypatch):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=1.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with patch("nuri.alerts.heartbeat_watchdog.send_webhook_text") as send:
            rc = hw.main()
        assert rc == 0
        send.assert_not_called()

    def test_missing_heartbeat_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", tmp_path / "nope")
        with patch("nuri.alerts.heartbeat_watchdog.send_webhook_text") as send:
            rc = hw.main()
        assert rc == 0
        send.assert_not_called()

    def test_stale_heartbeat_alerts(self, tmp_path, monkeypatch):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=hw.STALE_THRESHOLD_MIN + 15.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send:
            rc = hw.main()
        assert rc == 2
        send.assert_called_once()
        msg = send.call_args.args[0]
        assert "STALE" in msg

    def test_stale_but_webhook_failure_still_returns_2(self, tmp_path, monkeypatch):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=hw.STALE_THRESHOLD_MIN + 15.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with patch(
            "nuri.alerts.heartbeat_watchdog.send_webhook_text",
            side_effect=RuntimeError("network down"),
        ):
            rc = hw.main()
        assert rc == 2  # webhook 실패도 stale 신호로 surface (exit 2)
