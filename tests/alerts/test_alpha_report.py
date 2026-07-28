"""§3.11 월간 alpha 진행 리포트 → #brief (`nuri/alerts/alpha_report.py`, #856).

`adjudicate()` 는 #842 에서 이미 테스트되므로 여기서는 **표출 계약**만 잠근다:
조기 승격 금지, INFO 고정, 원장 단일 가드, 월 1회 dedupe, cron 표현식.

합성 리포트 dict 로 검증 — 실 DB 표본에 의존하면 시간이 지나며 flaky 해진다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.alerts import alpha_report


def _report(**over):
    """판정일 이전(pre_evaluation) 기본 리포트 — adjudicate() 반환 형태."""
    base = {
        "as_of": "2026-08-01",
        "window_days": 30,
        "benchmark": "SPY",
        "n": 42,
        "min_n_required": 200,
        "missing_rate_pct": 3.5,
        "missing_max_pct": 15,
        "pre_evaluation": True,
        "evaluation_date": "2027-06-30",
        "mean_alpha": 0.0123,
        "p_value": 0.031,
        "p_max": 0.05,
        "halves": {"h1_mean": 0.010, "h2_mean": 0.015},
        "conditions": {
            "mean_alpha_positive": True,
            "permutation_significant": True,
            "both_halves_positive": True,
        },
        "verdict": "PROGRESS_REPORT",
        "criteria_verdict_if_final": "INSUFFICIENT_N",
    }
    base.update(over)
    return base


class TestProductionGuard:
    """§3.11 원장 단일 — stage 는 production 에서만."""

    def test_is_production_requires_explicit_role(self, monkeypatch):
        monkeypatch.delenv("NURI_ROLE", raising=False)
        assert alpha_report.is_production() is False
        monkeypatch.setenv("NURI_ROLE", "dev")
        assert alpha_report.is_production() is False
        monkeypatch.setenv("NURI_ROLE", "production")
        assert alpha_report.is_production() is True

    def test_role_match_is_case_and_space_insensitive(self, monkeypatch):
        monkeypatch.setenv("NURI_ROLE", "  Production  ")
        assert alpha_report.is_production() is True

    def test_stage_skipped_off_production(self, monkeypatch):
        """dev 에서는 stage_brief 를 아예 호출하지 않는다 (replica 숫자 유출 방지)."""
        monkeypatch.delenv("NURI_ROLE", raising=False)
        with patch("nuri.agents.discord.outbox.stage_brief") as staged:
            assert alpha_report.stage_alpha_progress_brief() is None
        staged.assert_not_called()

    def test_stage_runs_on_production(self, monkeypatch, tmp_path):
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)  # tests/CLAUDE.md: 실 data/portfolio.db 를 절대 건드리지 않는다
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "build_progress_report", return_value=_report()),
            patch("nuri.agents.discord.outbox.stage_brief", return_value=7) as staged,
        ):
            assert alpha_report.stage_alpha_progress_brief(db_path=db) == 7
        staged.assert_called_once()


class TestNoEarlyPromotion:
    """조기 승격 금지 (§3.11 원안 4번) — 판정일 이전 결과는 결론이 될 수 없다."""

    def test_payload_keeps_progress_report_verdict(self):
        payload = alpha_report._build_payload(_report())
        assert payload["verdict"] == "PROGRESS_REPORT"

    def test_hypothetical_verdict_is_marked_as_not_a_ruling(self):
        """3조건을 다 충족해도 note 가 '조기 판정 아님'을 명시해야 한다."""
        payload = alpha_report._build_payload(_report(criteria_verdict_if_final="CRITERIA_MET"))
        assert "CRITERIA_MET" in payload["note"]
        assert "조기 판정 아님" in payload["note"]
        # 승격 어휘가 verdict 필드로 새면 안 된다.
        assert payload["verdict"] == "PROGRESS_REPORT"

    def test_post_evaluation_passes_verdict_through(self):
        """판정일 이후에는 adjudicate() 가 준 verdict 를 그대로 (가정법 문구 없음)."""
        payload = alpha_report._build_payload(
            _report(pre_evaluation=False, verdict="CRITERIA_NOT_MET", as_of="2027-07-01")
        )
        assert payload["verdict"] == "CRITERIA_NOT_MET"
        assert "오늘 기준이라면" not in payload["note"]


class TestBriefContract:
    """#brief payload 계약 — 측정 상태지 액션이 아니다."""

    def test_kind_is_info_not_an_action(self):
        payload = alpha_report._build_payload(_report())
        assert payload["kind"] == "INFO"
        assert payload["kind"] not in ("BUY", "SELL", "REBALANCE")

    def test_no_price_levels(self):
        """price_levels 가 있으면 렌더러가 매매 지시처럼 표시한다."""
        assert "price_levels" not in alpha_report._build_payload(_report())

    def test_reason_shows_all_three_criteria_plus_missing_and_dday(self):
        """#856 acceptance: 판정 3조건 + 결측률이 한 화면에."""
        line = alpha_report.format_progress_reason(_report())
        assert "n=42/200" in line
        assert "mean +1.23%p" in line
        assert "p=0.031/0.05" in line
        assert "halves +1.00/+1.50%p" in line
        assert "조건 3/3 충족" in line
        assert "결측 3.5%/15%" in line
        assert "D-" in line

    def test_reason_survives_empty_sample(self):
        """NO_SAMPLE 은 conditions 키가 없다 — 예외 없이 축약 표기."""
        line = alpha_report.format_progress_reason(
            {
                "as_of": "2026-08-01",
                "n": 0,
                "min_n_required": 200,
                "missing_rate_pct": 0.0,
                "missing_max_pct": 15,
                "evaluation_date": "2027-06-30",
                "reason": "표본 0건",
                "verdict": "NO_SAMPLE",
            }
        )
        assert "n=0/200" in line
        assert "표본 0건" in line

    def test_dday_flips_after_evaluation_date(self):
        line = alpha_report.format_progress_reason(_report(as_of="2027-07-10", pre_evaluation=False))
        assert "판정일 경과 +10d" in line

    def test_bad_evaluation_date_omits_dday_instead_of_raising(self):
        line = alpha_report.format_progress_reason(_report(evaluation_date="not-a-date"))
        assert "D-" not in line and "경과" not in line


class TestMonthlyOnce:
    """월 1회 보장은 cron 이 아니라 already_emitted() 가 한다."""

    def test_dedupe_key_is_year_month(self, monkeypatch):
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "already_emitted", return_value=False),
            patch.object(alpha_report, "build_progress_report", return_value=_report(as_of="2026-08-01")),
            patch("nuri.agents.discord.outbox.stage_brief", return_value=1) as staged,
        ):
            alpha_report.stage_alpha_progress_brief(as_of="2026-08-01")
        assert staged.call_args.kwargs["dedupe_key"] == "alpha-progress:2026-08"

    def test_skips_before_running_the_expensive_permutation(self, monkeypatch):
        """이미 발화한 달이면 adjudicate() 를 아예 호출하지 않는다.

        Gotcha-Test Pair: cron 이 매일이라 이 short-circuit 이 없으면 순열
        1,000회를 매일 태우고 #brief 도 매일 중복 발화한다.
        """
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "already_emitted", return_value=True),
            patch.object(alpha_report, "build_progress_report") as built,
            patch("nuri.agents.discord.outbox.stage_brief") as staged,
        ):
            assert alpha_report.stage_alpha_progress_brief(as_of="2026-08-05") is None
        built.assert_not_called()
        staged.assert_not_called()

    def test_already_emitted_counts_sent_rows_not_just_pending(self, tmp_path):
        """stage_outbox 의 dedupe 는 pending 만 본다 — sent 까지 세야 진짜 월 1회.

        이 assert 가 없으면 발송 직후부터 매일 재발화한다.
        """
        from nuri.core.db import get_db, init_db

        db = tmp_path / "t.db"
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO discord_outbox (channel, payload_json, dedupe_key, status) VALUES (?,?,?,?)",
                ("brief", "{}", "alpha-progress:2026-08", "sent"),
            )
        assert alpha_report.already_emitted("2026-08", db_path=db) is True
        assert alpha_report.already_emitted("2026-09", db_path=db) is False

    def test_failed_row_allows_retry(self, tmp_path):
        """못 나간 달은 재시도 — failed/dropped 는 '발화함' 으로 치지 않는다."""
        from nuri.core.db import get_db, init_db

        db = tmp_path / "t.db"
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO discord_outbox (channel, payload_json, dedupe_key, status) VALUES (?,?,?,?)",
                ("brief", "{}", "alpha-progress:2026-08", "failed"),
            )
        assert alpha_report.already_emitted("2026-08", db_path=db) is False


class TestSchedulerWiring:
    def test_monthly_cron_registered(self):
        """매월 1일 발화 (#856 acceptance). cron 표현식을 lock."""
        from nuri import scheduler

        jobs = {j["name"]: j for j in scheduler.SCHEDULES}
        assert "alpha_report" in jobs, "SCHEDULES 에 alpha_report 미등록"
        # 매일 확인 — 월 1회 보장은 already_emitted() 담당 (misfire self-heal)
        assert jobs["alpha_report"]["cron"] == "0 9 * * *"
        assert jobs["alpha_report"]["func"] is scheduler._run_alpha_report

    def test_production_role_lives_in_the_scheduler_plist(self):
        """`NURI_ROLE=production` 은 plist 에 있어야 한다 — `.env` 는 덮어써진다.

        Gotcha-Test Pair: deploy_to_mini.sh 3단계가 MBP `.env` 를 mini 로 SCP
        하므로 `.env` 에 두면 다음 배포에 조용히 지워지고, 리포트는 아무 에러
        없이 영영 안 나간다(가드가 stage 를 skip 할 뿐이라 실패로 안 보임).
        plist 는 동기화 대상이 아니라 안전하다.
        """
        import plistlib
        from pathlib import Path

        p = Path(__file__).resolve().parents[2] / "scripts/launchd/com.nuri-quant.scheduler.plist"
        env = plistlib.loads(p.read_bytes()).get("EnvironmentVariables", {})
        assert env.get("NURI_ROLE") == "production", "scheduler plist 에 NURI_ROLE=production 필요"

    def test_role_not_declared_in_env_example(self):
        """`.env.example` 에 활성 NURI_ROLE 라인이 있으면 안 된다 (주석 안내만)."""
        import re
        from pathlib import Path

        body = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*NURI_ROLE\s*=", body), ".env 는 배포로 덮어써진다 — plist 를 쓸 것"

    def test_wrapper_actually_calls_the_stager(self):
        """래퍼가 실제로 stage 함수를 부르는지.

        이전 버전은 예외를 넣고 `"alpha_report" in caplog.text` 만 봤는데,
        래퍼가 무엇을 하든 except 절이 같은 문자열을 찍으므로 **호출 자체가
        사라져도 통과**했다. 호출을 직접 assert 한다.
        """
        from nuri import scheduler

        with patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=11) as staged:
            scheduler._run_alpha_report()
        staged.assert_called_once_with()

    def test_heartbeat_written_on_every_path(self, caplog):
        """발화/미발화/예외 **모두** `alpha_report_run` heartbeat 1행을 남긴다 (#894).

        Gotcha-Test Pair: heartbeat 가 없으면 '이번 달 이미 발화(정상)' 와
        'NURI_ROLE 누락(고장, 판정일까지 영영 안 나감)' 이 관측상 동일해진다.
        `emit_event` 호출을 지우면 세 케이스 모두 FAIL.
        """
        from nuri import scheduler

        cases = {
            "staged": (11, None),
            "skipped": (None, None),
            "raised": (None, RuntimeError("boom")),
        }
        for label, (ret, exc) in cases.items():
            kw = {"side_effect": exc} if exc else {"return_value": ret}
            with (
                patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", **kw),
                patch("nuri.alerts.alpha_report.already_emitted", return_value=False),
                patch("nuri.core.events.emit_event") as emitted,
            ):
                scheduler._run_alpha_report()
            assert emitted.call_count == 1, f"{label}: heartbeat 누락"
            assert emitted.call_args.args[0] == "alpha_report_run"
            payload = emitted.call_args.kwargs["payload"]
            assert payload["staged"] is (ret is not None), label
            assert (payload["error"] is not None) is (exc is not None), label

    def test_heartbeat_records_role_state_for_the_detector(self):
        """`role_ok` 가 payload 에 들어가야 detector 가 설정 오류를 지목할 수 있다."""
        from nuri import scheduler

        with (
            patch("nuri.alerts.alpha_report.is_production", return_value=False),
            patch("nuri.alerts.alpha_report.stage_alpha_progress_brief", return_value=None),
            patch("nuri.alerts.alpha_report.already_emitted", return_value=False),
            patch("nuri.core.events.emit_event") as emitted,
        ):
            scheduler._run_alpha_report()
        payload = emitted.call_args.kwargs["payload"]
        assert payload["role_ok"] is False
        assert payload["staged"] is False

    def test_wrapper_absorbs_failure(self, caplog):
        """한 job 실패가 스케줄러를 죽이면 안 된다 (다른 _run_* 와 동일 계약)."""
        import logging

        from nuri import scheduler

        with (
            caplog.at_level(logging.ERROR),
            patch(
                "nuri.alerts.alpha_report.stage_alpha_progress_brief",
                side_effect=RuntimeError("boom"),
            ),
        ):
            scheduler._run_alpha_report()  # 예외가 새어나오면 실패
        # 삼키되 **흔적은 남겨야** 한다 — 조용한 실패 방지.
        assert "alpha_report" in caplog.text
        assert "boom" in caplog.text, "원인 예외가 로그에 없으면 디버깅 불가"


class TestConfigDriven:
    def test_criteria_track_config_rather_than_a_local_default(self, tmp_path, monkeypatch):
        """#856 acceptance: 기준값은 rules.yaml measurement_mode 에서만 온다.

        소스에서 리터럴을 grep 하던 이전 버전은 무의미했다 — 오늘의 config 값
        문자열을 찾을 뿐이라, `report.get("p_max", 0.10)` 같은 진짜 하드코딩은
        통과시키고 정상 산문은 오탐했다. 대신 **config 를 바꾸면 출력이 따라
        움직이는지** 를 본다.
        """
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)
        real = alpha_report.build_progress_report(db_path=db, as_of="2026-08-01", n_perm=5)
        # 표본이 없어도 기준값(min_n / missing_max / evaluation_date)은 config 에서 온다.
        for key in ("min_n_required", "missing_max_pct", "evaluation_date"):
            assert key in real, f"{key} 가 리포트에 없음 — config 로드 경로 확인"

        import yaml

        mm = yaml.safe_load(open("config/rules.yaml", encoding="utf-8"))["measurement_mode"]
        assert real["min_n_required"] == int(mm["min_n_us_buy_decisions"])
        assert real["missing_max_pct"] == int(mm["missing_outcome_max_pct"])
        assert str(real["evaluation_date"]) == str(mm["evaluation_date"])

    def test_reason_renders_config_values_not_constants(self):
        """config 가 바뀌면 표시 문자열도 바뀐다 (상수 박아넣기 방지)."""
        line = alpha_report.format_progress_reason(_report(min_n_required=999, missing_max_pct=42))
        assert "n=42/999" in line
        assert "결측 3.5%/42%" in line


class TestRendererPath:
    """payload 가 실제 #brief 렌더러를 통과했을 때 무엇이 보이는가.

    Gotcha-Test Pair: 렌더러 `_format_event_line` 은 화이트리스트
    ("regime","causal","horizon","position","reason","note") 만 출력한다.
    verdict 를 payload 키로만 두면 **화면에 안 나온다** — §3.11 이 만들려는
    단 하나의 산출물이 사용자에게 도달하지 못한다.
    """

    def _render(self, report):
        from nuri.agents.discord.outbox import _format_event_line

        return _format_event_line(alpha_report._build_payload(report))

    def test_verdict_is_visible_in_rendered_line(self):
        assert "PROGRESS_REPORT" in self._render(_report())

    def test_final_verdict_visible_after_evaluation_date(self):
        line = self._render(_report(pre_evaluation=False, verdict="CRITERIA_MET", as_of="2027-07-01"))
        assert "CRITERIA_MET" in line
        assert "측정 진행 중" not in line, "판정일 이후에 '진행 중' 은 사실과 다르다"

    def test_rendered_line_never_reads_as_a_trade_instruction(self):
        line = self._render(_report())
        assert "INFO" in line
        assert "ALPHA-MEASUREMENT" in line, "티커 라벨이 실종목처럼 보이면 #429 축 혼동"
        for banned in ("BUY", "SELL", "REBALANCE", "entry", "stop"):
            assert banned not in line, f"{banned!r} 가 렌더링됨 — 액션으로 읽힌다"

    def test_payload_ticker_is_the_measurement_label(self):
        """실종목 티커로 새면 보유 종목에 대한 콜처럼 읽힌다 (#429)."""
        assert alpha_report._build_payload(_report())["ticker"] == "ALPHA-MEASUREMENT"

    def test_payload_horizon_states_window_and_benchmark(self):
        assert alpha_report._build_payload(_report())["horizon"] == "30d vs SPY"


class TestAdjudicateIntegration:
    """유일한 통합 지점 — 나머지 테스트가 전부 build_progress_report 를 패치한다."""

    def test_real_adjudicate_shape_matches_what_the_formatter_reads(self, tmp_path):
        """fixture 가 adjudicate() 실제 반환 형태에서 드리프트하면 잡는다.

        이게 없으면 decision_alpha 가 키를 rename 해도 테스트는 다 통과하고
        프로덕션 #brief 만 'n=42/None' 을 찍는다.
        """
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)
        real = alpha_report.build_progress_report(db_path=db, as_of="2026-08-01", n_perm=5)
        # formatter 가 읽는 키가 실제 리포트에 존재해야 한다.
        for key in ("n", "min_n_required", "missing_rate_pct", "missing_max_pct", "evaluation_date", "verdict"):
            assert key in real, f"adjudicate() 가 {key} 를 더 이상 주지 않는다 — formatter 수정 필요"
        line = alpha_report.format_progress_reason(real)
        assert "None" not in line, f"실제 리포트로 렌더링 시 None 누출: {line}"
        payload = alpha_report._build_payload(real)
        assert payload["kind"] == "INFO"


class TestCli:
    def test_dry_run_never_stages(self, monkeypatch, capsys):
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "build_progress_report", return_value=_report()),
            patch("nuri.agents.discord.outbox.stage_brief") as staged,
        ):
            assert alpha_report.main(["--dry-run"]) == 0
        staged.assert_not_called()
        assert "dry-run" in capsys.readouterr().out

    def test_cli_off_production_reports_and_exits_clean(self, monkeypatch, capsys):
        monkeypatch.delenv("NURI_ROLE", raising=False)
        with (
            patch.object(alpha_report, "build_progress_report", return_value=_report()),
            patch("nuri.agents.discord.outbox.stage_brief") as staged,
        ):
            assert alpha_report.main([]) == 0
        staged.assert_not_called()
        assert "production" in capsys.readouterr().out

    def test_cli_stages_on_production(self, monkeypatch, capsys, tmp_path):
        """production 에서 --dry-run 없이 부르면 실제로 stage 하고 결과를 보고한다."""
        from nuri.core.db import init_db

        db = tmp_path / "t.db"
        init_db(db)
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "build_progress_report", return_value=_report()),
            patch("nuri.agents.discord.outbox.stage_brief", return_value=5) as staged,
        ):
            assert alpha_report.main(["--db", str(db), "--as-of", "2026-08-01"]) == 0
        staged.assert_called_once()
        assert "staged" in capsys.readouterr().out

    def test_cli_reports_when_month_already_emitted(self, monkeypatch, capsys, tmp_path):
        """중복 달은 조용히 0 을 반환하지 말고 이유를 말한다."""
        from nuri.core.db import get_db, init_db

        db = tmp_path / "t.db"
        init_db(db)
        with get_db(db) as conn:
            conn.execute(
                "INSERT INTO discord_outbox (channel, payload_json, dedupe_key, status) VALUES (?,?,?,?)",
                ("brief", "{}", "alpha-progress:2026-08", "sent"),
            )
        monkeypatch.setenv("NURI_ROLE", "production")
        with (
            patch.object(alpha_report, "build_progress_report", return_value=_report()),
            patch("nuri.agents.discord.outbox.stage_brief") as staged,
        ):
            assert alpha_report.main(["--db", str(db), "--as-of", "2026-08-01"]) == 0
        staged.assert_not_called()
        assert "이미 이번 달" in capsys.readouterr().out

    def test_json_mode_emits_parseable_report(self, monkeypatch, capsys):
        import json as _json

        monkeypatch.delenv("NURI_ROLE", raising=False)
        with patch.object(alpha_report, "build_progress_report", return_value=_report()):
            alpha_report.main(["--json"])
        out = capsys.readouterr().out
        parsed = _json.loads(out[out.index("{") : out.rindex("}") + 1])
        assert parsed["verdict"] == "PROGRESS_REPORT"


@pytest.mark.parametrize("role", ["production", "PRODUCTION"])
def test_role_accepted_forms(monkeypatch, role):
    monkeypatch.setenv("NURI_ROLE", role)
    assert alpha_report.is_production() is True
