"""`verify.py` 는 게이트다 — 실패를 찾으면 실패로 끝난다 (#1115).

이전엔 `main()` 이 아무것도 반환하지 않아, 요약에 `[FAIL]` 을 찍어놓고도 종료코드가 0 이었다.
`make verify`(213s, pre-release) · `make verify-fast`(127s, pre-deploy) 두 타깃이 배포 전
게이트로 쓰라고 만든 건데 실은 리포트 생성기였다. 그리고 walk-forward 판정은 아예
`[OK] … gate FAIL` 이라는 문장으로 나가서, 접두어를 세는 쪽에는 통과로 읽혔다.

실패할 수 없는 게이트는 게이트가 아니다 (#910/#911 · #953/#954 와 같은 계열).
"""

from __future__ import annotations

import sys

import pytest

#: `main()` 이 도는 단계 함수들. 하나라도 빠뜨리면 실제 구현이 돌아 네트워크를 탄다.
STEP_FUNCS = (
    "verify_gate",
    "verify_portfolio",
    "verify_risk",
    "verify_sector",
    "verify_correlation",
    "verify_rebalance",
    "verify_factors",
    "verify_performance",
    "verify_signal_backtest",
    "verify_superinvestor_backtest",
    "verify_validation_scorecard",
    "verify_regime",
    "verify_candidates",
    "verify_backtest",
)


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """모든 단계를 대체한 뒤 `main()` 의 종료코드를 돌려준다."""

    def _run(lines_by_step=None, raising_step=None):
        from scripts.verify import verify as vmod

        lines_by_step = lines_by_step or {}
        monkeypatch.setattr(vmod, "create_report_dir", lambda: tmp_path)
        monkeypatch.setattr(sys, "argv", ["verify.py", "--skip-backtest"])

        for name in STEP_FUNCS:
            if name == raising_step:

                def _boom(report_dir, summary):
                    raise RuntimeError("boom")

                monkeypatch.setattr(vmod, name, _boom)
            else:
                line = lines_by_step.get(name, f"[OK] {name}")

                def _ok(report_dir, summary, _line=line):
                    summary.append(_line)

                monkeypatch.setattr(vmod, name, _ok)

        return vmod.main()

    return _run


class TestTheExitCodeReflectsTheFindings:
    def test_a_clean_run_exits_zero(self, run_main):
        assert run_main() == 0

    def test_a_failed_step_exits_nonzero(self, run_main):
        """단계가 예외를 던지면 `main()` 이 `[FAIL]` 을 남긴다 — 그게 종료코드에 반영된다.

        Mutation lock: `return 1` 을 지우면 0 이 되어 이 단언이 깨진다.
        """
        assert run_main(raising_step="verify_regime") == 1

    def test_a_fail_line_alone_is_enough(self, run_main):
        """예외 없이 단계가 스스로 `[FAIL]` 을 적어도 실패다 — `verify_factors` 의 분산
        게이트(#1102)와 `verify_backtest` 의 walk-forward 게이트가 그 형태다."""
        assert run_main(lines_by_step={"verify_factors": "[FAIL] 팩터: 변별력이 없다"}) == 1

    def test_a_skip_is_not_a_failure(self, run_main):
        """데이터가 없어 검사를 못 한 것과 검사가 떨어진 것은 다르다.

        둘을 같이 취급하면 신선한 설치가 영구 빨강이 되고, 영구 빨강은 아무도 안 본다.

        ⚠️ `verify_backtest` 를 쓰면 안 된다 (Codex P2): 이 픽스처는 `--skip-backtest` 를
        넘기므로 그 단계가 `steps` 에 아예 안 들어가고, 넣은 `[SKIP]` 줄은 종료코드 계산에
        참여하지 못한다. 그러면 `main()` 이 `[SKIP]` 을 실패로 취급하기 시작해도 초록으로
        남는 형태만 잠그는 테스트가 된다 — 형태만 보고 동작을 안 보는 그 패턴이다.
        """
        assert run_main(lines_by_step={"verify_regime": "[SKIP] 레짐: 데이터 부족"}) == 0


class TestTheWalkForwardVerdictIsThePrefix:
    def _run(self, monkeypatch, tmp_path, passed: bool):
        import nuri.quant.validation.strategy_walkforward as wf
        from scripts.verify import verify as vmod

        monkeypatch.setattr(
            wf,
            "run_strategy_validation",
            lambda **_: {
                "oos_sharpe_pooled": 0.51,
                "gate": {"passed": passed, "p_value": 0.79},
            },
        )
        summary: list[str] = []
        vmod.verify_backtest(tmp_path, summary)
        return summary[0]

    def test_a_failed_gate_is_reported_as_a_failure(self, monkeypatch, tmp_path):
        """`[OK] … gate FAIL` 이 아니라 `[FAIL] …` 이다.

        판정을 문장 안에 문자열로 넣으면 접두어를 세는 쪽에는 통과로 읽힌다.
        """
        line = self._run(monkeypatch, tmp_path, passed=False)

        assert line.startswith("[FAIL]"), line
        assert "gate FAIL" not in line, "판정이 아직 문장 안에 문자열로 들어 있다"

    def test_a_passing_gate_is_still_ok(self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, tmp_path, passed=True).startswith("[OK]")
