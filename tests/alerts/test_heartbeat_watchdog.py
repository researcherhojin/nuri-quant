"""heartbeat_watchdog 테스트 — DB·scheduler 무의존 staleness 알림.

Gotcha-Test Pair (2026-06-09 6일 silent outage 재발 방지): watchdog 이 stale
heartbeat 에 alert 를 보내고, fresh/missing 에는 안 보내는 계약을 고정.
회귀(임계 비교/스킵 로직 변경) 시 silent outage 탐지 불능.
"""

import os
import time
from unittest.mock import patch

import pytest

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
        assert age is not None  # float | None 타입 좁히기 (파일 존재 → non-None)
        assert 39.0 < age < 41.0


class TestWebhookResolution:
    def test_prefers_incidents_channel(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_INCIDENTS", "https://x/incidents")
        monkeypatch.setenv("DISCORD_WEBHOOK_OPS", "https://x/ops")
        assert hw._resolve_webhook_url() == "https://x/incidents"

    def test_falls_back_past_empty_url(self, monkeypatch):
        # generic URL 빈 값 + OPS 만 설정 → OPS 선택 (실제 mini 배포 형태).
        monkeypatch.setenv("DISCORD_WEBHOOK_INCIDENTS", "")
        monkeypatch.setenv("DISCORD_WEBHOOK_OPS", "https://x/ops")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
        assert hw._resolve_webhook_url() == "https://x/ops"

    def test_none_when_all_empty(self, monkeypatch):
        for k in ("DISCORD_WEBHOOK_INCIDENTS", "DISCORD_WEBHOOK_OPS", "DISCORD_WEBHOOK_URL"):
            monkeypatch.setenv(k, "")
        assert hw._resolve_webhook_url() is None


class TestBackupAge:
    """원장 백업 나이 (#835) — scheduler 와 독립적으로 파일 mtime 만 본다."""

    def test_none_when_dir_missing(self, tmp_path):
        assert hw.backup_age_hours(backup_dir=tmp_path / "nope") is None

    def test_none_when_dir_has_no_snapshot(self, tmp_path):
        (tmp_path / "README.txt").write_text("no snapshots here")
        assert hw.backup_age_hours(backup_dir=tmp_path) is None

    def test_uses_the_newest_snapshot(self, tmp_path):
        """오래된 백업이 남아 있어도 '최신' 기준이어야 한다."""
        now = time.time()
        for name, age_h in (("portfolio_old.db", 200.0), ("portfolio_new.db", 3.0)):
            p = tmp_path / name
            p.write_bytes(b"x")
            os.utime(p, (now - age_h * 3600, now - age_h * 3600))
        age = hw.backup_age_hours(backup_dir=tmp_path, now_epoch=now)
        assert age == pytest.approx(3.0, abs=0.1)

    def test_ignores_checksum_sidecars(self, tmp_path):
        """`.sha256` 는 스냅샷이 아니다 — 그것만 있으면 백업 없음으로 봐야 한다."""
        (tmp_path / "portfolio_20260101_000000.db.sha256").write_text("deadbeef")
        assert hw.backup_age_hours(backup_dir=tmp_path) is None


class TestMain:
    @pytest.fixture(autouse=True)
    def _no_services(self, monkeypatch):
        """heartbeat 계약만 격리 검증 — 포트 감시는 TestServiceCheck 에서 별도."""
        monkeypatch.setattr(hw, "SERVICE_PORTS", {})

    @pytest.fixture(autouse=True)
    def _isolated_backup_dir(self, tmp_path, monkeypatch):
        """실 `data/backups/` 를 보지 않게 격리.

        이게 없으면 개발 머신의 백업 유무에 따라 결과가 갈린다 (tests/CLAUDE.md
        의 DB 격리와 같은 취지 — 테스트가 머신 상태에 의존하면 안 된다).
        기본은 '백업 없음' → skip 이라 기존 heartbeat 테스트에 영향 없음.
        """
        monkeypatch.setattr(hw, "BACKUP_DIR", tmp_path / "no-backups")

    def _seed_backup(self, tmp_path, age_hours):
        d = tmp_path / "backups"
        d.mkdir(exist_ok=True)
        p = d / "portfolio_20260101_000000.db"
        p.write_bytes(b"x")
        t = time.time() - age_hours * 3600
        os.utime(p, (t, t))
        return d

    def test_fresh_backup_no_alert(self, tmp_path, monkeypatch):
        hb = tmp_path / "hb"
        _write_heartbeat(hb, age_minutes=1.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", hb)
        monkeypatch.setattr(hw, "BACKUP_DIR", self._seed_backup(tmp_path, 5.0))
        with patch("nuri.alerts.heartbeat_watchdog.send_webhook_text") as send:
            rc = hw.main()
        assert rc == 0
        send.assert_not_called()

    def test_stale_backup_alerts_even_when_heartbeat_is_fresh(self, tmp_path, monkeypatch):
        """#835 acceptance — 백업만 멈춘 상태를 heartbeat 가 못 잡는다.

        Gotcha-Test Pair: 백업 job 은 scheduler 안에서 돈다. scheduler 가 살아
        heartbeat 는 갱신되는데 백업 job 만 조용히 실패하면(#557 경로 drift 로
        2026-04-30~07-08 두 달 넘게 실제로 그랬다) 아무도 모른다.
        """
        hb = tmp_path / "hb"
        _write_heartbeat(hb, age_minutes=1.0)  # heartbeat 는 정상
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", hb)
        monkeypatch.setattr(hw, "BACKUP_DIR", self._seed_backup(tmp_path, hw.BACKUP_STALE_THRESHOLD_H + 10))
        with patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send:
            rc = hw.main()
        assert rc == 2
        msg = send.call_args.args[0]
        assert "백업 STALE" in msg
        assert "heartbeat STALE" not in msg, "heartbeat 는 정상인데 그것까지 경고하면 오탐"

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
        with (
            patch("nuri.alerts.heartbeat_watchdog._kickstart_scheduler", return_value=True),
            patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send,
        ):
            rc = hw.main()
        assert rc == 2
        send.assert_called_once()
        msg = send.call_args.args[0]
        assert "STALE" in msg

    def test_stale_but_webhook_failure_still_returns_2(self, tmp_path, monkeypatch):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=hw.STALE_THRESHOLD_MIN + 15.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with (
            patch("nuri.alerts.heartbeat_watchdog._kickstart_scheduler", return_value=False),
            patch(
                "nuri.alerts.heartbeat_watchdog.send_webhook_text",
                side_effect=RuntimeError("network down"),
            ),
        ):
            rc = hw.main()
        assert rc == 2  # webhook 실패도 stale 신호로 surface (exit 2)

    def test_stale_triggers_auto_restart_and_reports_success(self, tmp_path, monkeypatch):
        # stale → 데몬 자동 재시작 시도 + 성공 문구 알림 (#734 silent-outage 후속).
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=hw.STALE_THRESHOLD_MIN + 15.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with (
            patch("nuri.alerts.heartbeat_watchdog._kickstart_scheduler", return_value=True) as restart,
            patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send,
        ):
            rc = hw.main()
        assert rc == 2
        restart.assert_called_once()
        assert "자동 재시작 완료" in send.call_args.args[0]

    def test_auto_restart_failure_reports_manual_step(self, tmp_path, monkeypatch):
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=hw.STALE_THRESHOLD_MIN + 15.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with (
            patch("nuri.alerts.heartbeat_watchdog._kickstart_scheduler", return_value=False),
            patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send,
        ):
            rc = hw.main()
        assert rc == 2
        assert "자동 재시작 실패" in send.call_args.args[0]


class TestServiceCheck:
    """#826/#857 표출 계층 포트 감시 — 재확인 후에도 닫히면 알림만 (kickstart X).

    Gotcha-Test Pair: 2026-07-08 02:39 오탐 — launchd api 최초 설치 직후 부팅 중
    포트 미개방을 DOWN 오판하고 KeepAlive 서비스에 kickstart -k → 부팅 중 정상
    프로세스 kill + 30s timeout. 계약 고정: (1) 재확인으로 부팅/일시 미바인딩 흡수
    (2) KeepAlive 서비스는 kickstart 미호출 (launchd 가 크래시 복구 담당).
    """

    def test_transient_down_recovers_on_recheck_no_alert(self, monkeypatch):
        # 첫 체크 down → 재확인 시 open = 부팅 중이었음 → 알림 없음 (오탐 방지 핵심).
        monkeypatch.setattr(hw, "SERVICE_PORTS", {"com.nuri-quant.api": 18001})
        calls = iter([False, True])  # 1차 closed, 재확인 open
        with (
            patch.object(hw, "_label_loaded", return_value=True),
            patch.object(hw, "_port_open", side_effect=lambda *a, **k: next(calls)),
            patch.object(hw, "_kickstart") as kick,
        ):
            problems = hw.check_services(recheck_delay_s=0)
        assert problems == []
        kick.assert_not_called()  # KeepAlive 서비스는 절대 kickstart 안 함

    def test_persistent_down_alerts_without_kickstart(self, monkeypatch):
        # 재확인에도 down → 알림 (kickstart 미호출, 수동 안내).
        monkeypatch.setattr(hw, "SERVICE_PORTS", {"com.nuri-quant.api": 18001})
        with (
            patch.object(hw, "_label_loaded", return_value=True),
            patch.object(hw, "_port_open", return_value=False),
            patch.object(hw, "_kickstart") as kick,
        ):
            problems = hw.check_services(recheck_delay_s=0)
        assert len(problems) == 1
        assert "api DOWN" in problems[0]
        assert "KeepAlive 자동복구 실패" in problems[0]
        assert "launchctl kickstart" in problems[0]  # 수동 안내
        kick.assert_not_called()

    def test_recheck_delay_sleeps_when_positive(self, monkeypatch):
        # recheck_delay_s > 0 이면 재확인 전 sleep (부팅 흡수). 기본 15s 경로 커버.
        monkeypatch.setattr(hw, "SERVICE_PORTS", {"com.nuri-quant.api": 18001})
        with (
            patch.object(hw, "_label_loaded", return_value=True),
            patch.object(hw, "_port_open", return_value=False),
            patch.object(hw.time, "sleep") as slept,
        ):
            hw.check_services(recheck_delay_s=15.0)
        slept.assert_called_once_with(15.0)

    def test_not_loaded_skips_silently(self, monkeypatch):
        # dev 머신 (launchd 미설치) — 검사·재시작 모두 없음.
        monkeypatch.setattr(hw, "SERVICE_PORTS", {"com.nuri-quant.api": 18001})
        with (
            patch.object(hw, "_label_loaded", return_value=False),
            patch.object(hw, "_kickstart") as kick,
        ):
            problems = hw.check_services(recheck_delay_s=0)
        kick.assert_not_called()
        assert problems == []

    def test_loaded_and_port_open_is_healthy(self, monkeypatch):
        monkeypatch.setattr(hw, "SERVICE_PORTS", {"com.nuri-quant.dashboard": 13000})
        with (
            patch.object(hw, "_label_loaded", return_value=True),
            patch.object(hw, "_port_open", return_value=True),
            patch.object(hw, "_kickstart") as kick,
        ):
            problems = hw.check_services(recheck_delay_s=0)
        kick.assert_not_called()
        assert problems == []

    def test_main_combines_service_alert_with_fresh_heartbeat(self, tmp_path, monkeypatch):
        # heartbeat 정상이어도 서비스 down 이면 rc=2 + 알림 발송.
        p = tmp_path / "hb"
        _write_heartbeat(p, age_minutes=1.0)
        monkeypatch.setattr(hw, "HEARTBEAT_PATH", p)
        with (
            patch.object(hw, "check_services", return_value=["🔴 **api DOWN** — test"]),
            patch("nuri.alerts.heartbeat_watchdog.send_webhook_text", return_value=True) as send,
        ):
            rc = hw.main()
        assert rc == 2
        send.assert_called_once()
        assert "api DOWN" in send.call_args.args[0]

    def test_label_loaded_true_on_zero_rc(self, monkeypatch):
        class _Proc:
            returncode = 0

        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: _Proc())
        assert hw._label_loaded("com.nuri-quant.api") is True

    def test_label_loaded_false_on_nonzero_rc(self, monkeypatch):
        class _Proc:
            returncode = 113  # launchctl list: 미로드 label

        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: _Proc())
        assert hw._label_loaded("com.nuri-quant.api") is False

    def test_label_loaded_false_when_launchctl_missing(self, monkeypatch):
        # CI/linux — launchctl 부재는 미배포 취급 (skip)
        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        assert hw._label_loaded("com.nuri-quant.api") is False

    def test_port_open_real_socket(self):
        # 실소켓 왕복 1회 — mock 없는 실측 (loopback listener).
        import socket

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            assert hw._port_open(port) is True
        finally:
            srv.close()
        assert hw._port_open(port) is False  # 닫힌 뒤엔 False


class TestKickstart:
    def test_returns_false_when_launchctl_missing(self, monkeypatch):
        # 비배포 환경(launchctl 부재) — 예외 삼키고 False, 알림 흐름은 계속.
        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        assert hw._kickstart_scheduler() is False

    def test_returns_true_on_zero_returncode(self, monkeypatch):
        class _Proc:
            returncode = 0
            stderr = ""

        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: _Proc())
        assert hw._kickstart_scheduler() is True

    def test_returns_false_on_nonzero_returncode(self, monkeypatch):
        # launchctl 실행은 됐으나 실패 반환 — False + stderr surface.
        class _Proc:
            returncode = 1
            stderr = "Could not find service"

        monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: _Proc())
        assert hw._kickstart_scheduler() is False
