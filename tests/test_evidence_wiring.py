"""evidence 차트 생성이 스케줄러에 배선돼 있는지 잠근다 (#1128).

automation parity gap (#897/#899/#900) 계열: `make evidence` 만 있고 스케줄러
job 이 없어 프로덕션 차트가 4개월(2026-04-14 이후) 멈췄는데 모든 헬스가
초록이었다. 래퍼 함수를 직접 부르는 테스트는 SCHEDULES 등록이 빠져도
초록이므로(#wiring-axis, 2026-08-21 하루 3회 재발한 축), **SCHEDULES 엔트리를
찾아 그 func 를 실행**하는 방식으로 잠근다.
"""

from __future__ import annotations

from unittest.mock import patch


def _evidence_entry():
    from nuri.scheduler import SCHEDULES

    matches = [j for j in SCHEDULES if j["name"] == "evidence_charts"]
    assert len(matches) == 1, "SCHEDULES 에 evidence_charts job 이 정확히 1개 있어야 한다"
    return matches[0]


class TestEvidenceChartsWiring:
    def test_schedule_entry_invokes_the_cli_entrypoint(self):
        """job func 실행 → `make evidence` 와 같은 generate_all_evidence 호출.

        스케줄러가 CLI 경로를 재구현하면(부분 write 집합) 이 계열 사고가
        재발한다 — 같은 진입점을 부르는지 동작으로 잠근다.
        """
        entry = _evidence_entry()
        with patch("nuri.analysis.evidence_charts.generate_all_evidence", return_value=[]) as gen:
            entry["func"](*entry["args"])
        gen.assert_called_once()

    def test_runs_daily_after_morning_collectors(self):
        """cron 은 매일이어야 한다 — 주중 한정이면 주말 공백이 stale 로 보인다.
        시각은 아침 수집(fear_greed 08:00 · factors 08:10) 이후여야 한다."""
        cron = _evidence_entry()["cron"]
        minute, hour, dom, month, dow = cron.split()
        assert dow == "*" and dom == "*" and month == "*", f"매일 실행이어야 한다: {cron}"
        assert (int(hour), int(minute)) > (8, 10), f"아침 수집 뒤여야 한다: {cron}"

    def test_generator_failure_does_not_escape_the_job(self):
        """차트 실패가 스케줄러 job 밖으로 새면 안 된다 (#894 관측 비게이트)."""
        entry = _evidence_entry()
        with patch(
            "nuri.analysis.evidence_charts.generate_all_evidence",
            side_effect=RuntimeError("boom"),
        ):
            entry["func"](*entry["args"])  # raise 하면 테스트가 실패한다
