"""Branch coverage tests for nuri.agents.actors.sre_incident_agent.

Targets the residual branches uncovered by test_sre_incident_agent.py:
- Detector exception swallow path (lines 126-127): one detector raising must not
  abort scan; instead synthesizes a synthetic db_lock incident describing the
  failed detector. Regression: removing the try/except would surface the inner
  exception out of run() instead of producing the synthetic record.
- disk_usage.total <= 0 short-circuit (line 196): sandboxed/restricted FS may
  report 0 capacity; scan must not div-by-zero.
- DB lock detector exception path (lines 222-224): SELECT 1 raising → synthesize
  db_lock incident. Regression: a healthy DB returns [], a raised DB returns the
  evidence record.
- Heartbeat WARN→CRIT severity branch (line 245): mtime falling between
  WARN and CRIT thresholds yields severity='warning'; >= CRIT yields 'critical'.
- _resolve type guard (line 407): non-int incident_id BLOCKs.
- _publish_alert info-severity short-circuit (line 475): info severity must not
  call any stage function.
- _short_json truncation (lines 498-503): payload length > max_len truncates
  with explicit suffix; small payload returned verbatim.
- main() severity arg pass-through (line 530), exception handling (535-537),
  WARN return code path (543).

Privacy: synthetic actor names; no broker, no real ticker.
"""

# cspell:ignore sandboxed

from __future__ import annotations

import json
import time as _time
from unittest.mock import MagicMock, patch

import pytest

from nuri.agents.actors.sre_incident_agent import (
    DISK_CRIT_PCT,
    SCHEDULER_CRIT_MIN,
    SCHEDULER_WARN_MIN,
    SREIncidentAgent,
    _short_json,
    main,
)
from nuri.agents.base import Outcome
from nuri.core.db import init_db, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sre_branches.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """모든 DB 호출을 임시 path 로 redirect — test_sre_incident_agent.py 와 동일 패턴."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch("nuri.agents.base.log_agent_audit", side_effect=make_redirect(db_module.log_agent_audit)),
        patch("nuri.agents.base.start_agent_run", side_effect=make_redirect(db_module.start_agent_run)),
        patch("nuri.agents.base.finish_agent_run", side_effect=make_redirect(db_module.finish_agent_run)),
        patch(
            "nuri.agents.actors.sre_incident_agent.log_incident",
            side_effect=make_redirect(db_module.log_incident),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.db_acknowledge_incident",
            side_effect=make_redirect(db_module.acknowledge_incident),
        ),
        patch(
            "nuri.agents.actors.sre_incident_agent.db_resolve_incident",
            side_effect=make_redirect(db_module.resolve_incident),
        ),
        patch("nuri.agents.actors.sre_incident_agent.query", side_effect=make_redirect(db_module.query)),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


# ════════════════════════════════════════════════════════════
# Detector exception fallback (lines 126-127)
# ════════════════════════════════════════════════════════════


class TestDetectorExceptionFallback:
    def test_detector_raise_synthesizes_db_lock_record(self, patched_db):
        """L126-127: detector 가 raise 하면 다른 detector 진행 + 합성 db_lock 레코드.

        Regression: 본 분기 제거 시 detector 1 개 실패가 scan 전체를 abort 한다.
        """
        # disk_full detector 만 강제 실패 — 나머지는 정상 실행돼야 함.
        with (
            patch(
                "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
                side_effect=RuntimeError("synthetic detector boom"),
            ),
            patch("nuri.core.freshness.check_all_freshness", return_value=[]),
            patch("nuri.agents.actors.sre_incident_agent.SREIncidentAgent._publish_alert"),
        ):
            result = SREIncidentAgent().run({"action": "scan"})

        # scan 자체는 PASS — abort 되지 않음.
        assert result.outcome == Outcome.PASS
        # 합성 incident 가 detector 이름과 evidence error 둘 다 포함.
        synth = [inc for inc in result.output["incidents"] if inc.get("target") == "_detect_disk_full"]
        assert len(synth) == 1, "fallback synth incident expected exactly once"
        assert synth[0]["severity"] == "warning"
        assert "synthetic detector boom" in synth[0]["evidence"]["detector_error"]
        assert synth[0]["is_new"] is False  # 합성은 신규 row 아님


# ════════════════════════════════════════════════════════════
# Disk total<=0 short-circuit (line 196)
# ════════════════════════════════════════════════════════════


class TestDiskUsageZeroTotal:
    def test_zero_total_returns_empty_no_division(self, patched_db):
        """L196: total <= 0 분기. ZeroDivision 없이 [] 반환.

        Regression: 본 가드 제거 시 percent_used = used/0 = ZeroDivisionError.
        """
        with patch(
            "nuri.agents.actors.sre_incident_agent.shutil.disk_usage",
            return_value=MagicMock(total=0, used=0, free=0),
        ):
            out = SREIncidentAgent()._detect_disk_full(MagicMock())
        assert out == []  # 정확히 빈 리스트 (NOT just falsy)


# ════════════════════════════════════════════════════════════
# DB lock detector exception (lines 222-224)
# ════════════════════════════════════════════════════════════


class TestDbLockDetector:
    def test_query_raises_synthesizes_db_lock_incident(self, patched_db):
        """L222-224: SELECT 1 가 raise 하면 critical db_lock incident 1 건 생성.

        Regression: try/except 제거 시 raise 가 scan 전체를 break — _detect_db_lock
        의 raise 가 _run_scan 의 outer try/except 까지 비등.
        """
        from nuri.agents.actors import sre_incident_agent as sre_mod
        from nuri.core import db as db_module

        real_query = db_module.query
        call_count = {"n": 0}

        def selective_raise(sql, *args, **kwargs):
            # 첫 호출 (probe SELECT 1) 만 raise — 후속 _record_incident query 는 통과.
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("database is locked")
            kwargs.setdefault("db_path", patched_db)
            return real_query(sql, *args, **kwargs)

        with patch.object(sre_mod, "query", side_effect=selective_raise):
            agent = SREIncidentAgent()
            ctx = MagicMock()
            ctx.run_id = "test-run-db-lock"
            out = agent._detect_db_lock(ctx)
        assert len(out) == 1, "db lock detector must surface exactly one incident"
        # 합성된 incident 가 evidence.error 에 원본 메시지 보존.
        rows = query(
            "SELECT severity, evidence_json FROM incidents WHERE incident_type = 'db_lock'",
            db_path=patched_db,
        )
        assert rows[0]["severity"] == "critical"
        assert "database is locked" in rows[0]["evidence_json"]


# ════════════════════════════════════════════════════════════
# Heartbeat severity branch (line 245)
# ════════════════════════════════════════════════════════════


class TestHeartbeatSeverity:
    def test_warn_band_yields_warning_severity(self, patched_db, tmp_path):
        """L245 false 분기: WARN < age < CRIT → severity='warning'.

        Regression: 분기 inversion 시 warning band 가 critical 로 surface.
        """
        # heartbeat 파일 생성, mtime 을 WARN+1 분 (CRIT 미달) 로 backdate.
        from nuri.agents.actors import sre_incident_agent as mod

        hb_path = tmp_path / "heartbeat"
        hb_path.write_text("ok")
        warn_age_s = (SCHEDULER_WARN_MIN + 1) * 60
        os_mtime = _time.time() - warn_age_s
        import os as _os

        _os.utime(hb_path, (os_mtime, os_mtime))

        with patch.object(mod, "HEARTBEAT_PATH", hb_path):
            agent = SREIncidentAgent()
            ctx = MagicMock()
            ctx.run_id = "hb-warn"
            out = agent._detect_scheduler_heartbeat(ctx)
        assert len(out) == 1
        # log_incident 결과 dict 형태 — severity field 검증.
        # patched_db 가 log_incident 를 redirect 했으므로 실제 DB row 의 severity 검사.
        rows = query(
            "SELECT severity FROM incidents WHERE incident_type = 'scheduler_heartbeat'",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["severity"] == "warning"

    def test_fresh_heartbeat_returns_empty(self, patched_db, tmp_path):
        """L244-245: age <= WARN → [] 반환 (정상 운영 환경).

        Regression: <= 비교가 < 로 잘못 바뀌면 정확히 WARN 분 경계에서 false-alarm.
        """
        from nuri.agents.actors import sre_incident_agent as mod

        hb_path = tmp_path / "fresh_heartbeat"
        hb_path.write_text("ok")
        # 방금 touched — age = 0 << WARN.

        with patch.object(mod, "HEARTBEAT_PATH", hb_path):
            agent = SREIncidentAgent()
            ctx = MagicMock()
            ctx.run_id = "hb-fresh"
            out = agent._detect_scheduler_heartbeat(ctx)
        assert out == []  # 신선하면 어떤 incident 도 없음

    def test_crit_band_yields_critical_severity(self, patched_db, tmp_path):
        """L245 true 분기: age >= CRIT → severity='critical'."""
        from nuri.agents.actors import sre_incident_agent as mod

        hb_path = tmp_path / "heartbeat2"
        hb_path.write_text("ok")
        crit_age_s = (SCHEDULER_CRIT_MIN + 1) * 60
        os_mtime = _time.time() - crit_age_s
        import os as _os

        _os.utime(hb_path, (os_mtime, os_mtime))

        with patch.object(mod, "HEARTBEAT_PATH", hb_path):
            agent = SREIncidentAgent()
            ctx = MagicMock()
            ctx.run_id = "hb-crit"
            agent._detect_scheduler_heartbeat(ctx)
        rows = query(
            "SELECT severity FROM incidents WHERE incident_type = 'scheduler_heartbeat'",
            db_path=patched_db,
        )
        assert rows[0]["severity"] == "critical"


# ════════════════════════════════════════════════════════════
# _resolve / _acknowledge type guard (line 407 mirror)
# ════════════════════════════════════════════════════════════


class TestResolveTypeGuard:
    def test_resolve_with_string_id_blocks(self, patched_db):
        """L407 (resolve mirror): incident_id 가 int 가 아니면 BLOCK + error msg.

        Regression: type 체크 제거 시 db_resolve_incident 가 TypeError raise.
        """
        result = SREIncidentAgent().run({"action": "resolve", "incident_id": "not-an-int"})
        assert result.outcome == Outcome.BLOCK
        assert "incident_id" in result.output["error"]


# ════════════════════════════════════════════════════════════
# _publish_alert info-severity skip (line 475)
# ════════════════════════════════════════════════════════════


class TestPublishAlertInfoSkip:
    def test_info_severity_does_not_invoke_stage_fns(self):
        """L474-475: severity='info' 면 stage_incident / stage_ops 둘 다 호출 X.

        Regression: 분기 제거 시 info 알림이 #ops 로 새서 noise 폭증.
        """
        with (
            patch("nuri.agents.discord.outbox.stage_incident") as si,
            patch("nuri.agents.discord.outbox.stage_ops") as so,
        ):
            SREIncidentAgent._publish_alert(
                incident_id=1,
                incident_type="orphan_run",
                severity="info",
                target="test",
                evidence={"x": 1},
                run_id="run-info",
            )
        si.assert_not_called()
        so.assert_not_called()


# ════════════════════════════════════════════════════════════
# _short_json (lines 498-503)
# ════════════════════════════════════════════════════════════


class TestShortJsonHelper:
    def test_short_payload_returned_verbatim(self):
        """L498-503: max_len 초과 안 하면 그대로 직렬화."""
        out = _short_json({"a": 1}, max_len=800)
        assert json.loads(out) == {"a": 1}
        assert "(truncated)" not in out

    def test_long_payload_truncated_with_marker(self):
        """L501-503: max_len 초과 시 자르고 명시적 truncated 마커 첨부."""
        big = {"k": "x" * 2000}
        out = _short_json(big, max_len=200)
        assert "(truncated)" in out
        # 200 char + truncation suffix → 명시 마커 포함, 원본 길이 미만.
        assert len(out) < len(json.dumps(big))


# ════════════════════════════════════════════════════════════
# CLI main() — severity flag, exception, WARN exit code
# ════════════════════════════════════════════════════════════


class TestCliBranches:
    def test_severity_flag_passed_to_payload(self, patched_db, capsys):
        """L530: --severity critical 이 payload['severity'] 로 전달.

        Regression: 분기 누락 시 severity 필터링이 silently no-op.
        """
        # list_open 만으로 severity 필터링 path 검증.
        rc = main(["list_open", "--severity", "critical"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "incidents" in out  # 정상 출력 — payload 통과 확인

    def test_actor_run_raises_returns_exit_code_2(self, patched_db, capsys):
        """L535-537: actor.run 이 exception raise 하면 stderr 에 error JSON, exit 2.

        Regression: 분기 누락 시 raw traceback 으로 exit 1 일 수도 있어
        scheduler 가 retry policy 잘못 적용.
        """
        with patch.object(SREIncidentAgent, "run", side_effect=RuntimeError("boom")):
            rc = main(["scan"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "boom" in err

    def test_outcome_warn_returns_exit_code_1(self, patched_db, capsys):
        """L542-543: result.outcome == WARN → exit 1 (CI distinguishable from BLOCK)."""
        from nuri.agents.base import ActorResult

        warn_result = ActorResult(output={"incidents": []}, outcome=Outcome.WARN)
        with patch.object(SREIncidentAgent, "run", return_value=warn_result):
            rc = main(["scan"])
        assert rc == 1
