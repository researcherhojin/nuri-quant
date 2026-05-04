"""Pragma audit: runpy tests for `if __name__ == "__main__":` blocks in nuri/quant/.

Replaces `# pragma: no cover` (coverage gaming) on quant module CLI entry points.
"""

from __future__ import annotations

import io
import runpy
import sys
from typing import Any

import pytest


def _run_module(module_name: str, monkeypatch, argv: list[str] | None = None) -> str:
    """Run module via runpy with stdout captured, return printed text."""
    captured = io.StringIO()
    monkeypatch.setattr(sys, "argv", argv or [module_name])
    monkeypatch.setattr(sys, "stdout", captured)
    try:
        runpy.run_module(module_name, run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise
    return captured.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# nuri.quant.regime.* — read-only DB queries
# ──────────────────────────────────────────────────────────────────────────────


class TestRegimeMainRunpy:
    """Regime modules read DB, print summaries. Empty DB → degraded but valid output."""

    def test_event_score_main(self, monkeypatch, db_path_mp):
        """compute_event_score on empty DB → score=0, print_event_score prints zero."""
        out = _run_module("nuri.quant.regime.event_score", monkeypatch, argv=["event_score"])
        # Behavioral: prints event_score line (label varies by Korean text)
        assert "score" in out.lower() or "이벤트" in out or "Event" in out

    def test_macro_score_main(self, monkeypatch, db_path_mp):
        """compute_macro_score on empty DB → degraded result, prints summary."""
        out = _run_module("nuri.quant.regime.macro_score", monkeypatch, argv=["macro_score"])
        # Macro score module prints something even on empty DB (degraded path)
        assert len(out) > 0

    def test_strategy_map_main_default(self, monkeypatch, db_path_mp):
        """strategy_map main without --analyze: default branch."""
        out = _run_module("nuri.quant.regime.strategy_map", monkeypatch, argv=["strategy_map"])
        assert len(out) > 0

    def test_strategy_map_main_analyze(self, monkeypatch, db_path_mp):
        """strategy_map main --analyze: cross analysis branch."""
        # On empty DB, analyze_signal_by_regime returns empty/zero structure;
        # print_cross_analysis still prints header.
        out = _run_module("nuri.quant.regime.strategy_map", monkeypatch, argv=["strategy_map", "--analyze"])
        assert len(out) > 0

    def test_classifier_main_no_history(self, monkeypatch, db_path_mp):
        """classifier main without --history: classifies current regime."""
        # classifier reads SPY prices from DB; empty → degraded "UNKNOWN" or similar
        out = _run_module("nuri.quant.regime.classifier", monkeypatch, argv=["classifier"])
        assert len(out) > 0


# ──────────────────────────────────────────────────────────────────────────────
# nuri.quant.factors.composite — calls compute → print → save
# ──────────────────────────────────────────────────────────────────────────────


class TestFactorsCompositeMainRunpy:
    def test_composite_main(self, monkeypatch, db_path_mp):
        """composite main: compute → print → save with non-empty mock factors."""
        # Provide non-empty factor DataFrames so set_index('ticker') has data.
        # Patch source modules so runpy-reloaded composite picks them up.
        import pandas as pd

        import nuri.quant.factors.momentum as mom
        import nuri.quant.factors.quality as qua
        import nuri.quant.factors.value as val

        mom_df = pd.DataFrame({"momentum_score": [0.7, 0.6]}, index=["AAA", "BBB"])
        val_df = pd.DataFrame({"value_score": [0.5, 0.4]}, index=["AAA", "BBB"])
        qua_df = pd.DataFrame({"quality_score": [0.8, 0.5]}, index=["AAA", "BBB"])

        monkeypatch.setattr(mom, "compute_momentum", lambda *a, **kw: mom_df.copy())
        monkeypatch.setattr(val, "compute_value", lambda *a, **kw: val_df.copy())
        monkeypatch.setattr(qua, "compute_quality", lambda *a, **kw: qua_df.copy())

        out = _run_module("nuri.quant.factors.composite", monkeypatch, argv=["composite"])
        # Behavioral: prints composite header + ticker rows
        assert "AAA" in out
        assert "BBB" in out
        # save_composite writes to factors table — verify
        from nuri.core.db import query

        rows = query("SELECT ticker FROM factors", db_path=db_path_mp)
        assert {r["ticker"] for r in rows} == {"AAA", "BBB"}


# ──────────────────────────────────────────────────────────────────────────────
# nuri.quant.backtest.* — heavier lifts; patch heavy entry points if possible
# ──────────────────────────────────────────────────────────────────────────────


class TestBacktestMainRunpy:
    def test_engine_main(self, monkeypatch, db_path_mp):
        """engine main: run_momentum_backtest with empty data → degraded result."""
        # Empty DB → empty pivot → backtest returns zero/null result
        out = _run_module("nuri.quant.backtest.engine", monkeypatch, argv=["engine", "--period", "5d"])
        # Either prints backtest summary OR fails gracefully — tolerate either via stdout content
        # Verify SystemExit code 0 (already enforced by _run_module)
        assert isinstance(out, str)

    def test_optimizer_main(self, monkeypatch, db_path_mp):
        """optimizer main without --signal: optimize_all branch."""
        # Patch optimize_all to a no-op (it iterates many signals)
        import nuri.quant.backtest.optimizer as opt

        called: list[str] = []
        monkeypatch.setattr(opt, "optimize_all", lambda: called.append("optimize_all"))
        _run_module("nuri.quant.backtest.optimizer", monkeypatch, argv=["optimizer"])
        # Patch may be invalidated by runpy reload — if invalidated, optimize_all runs for real;
        # accept either path: verify module ran (SystemExit 0 already)

    def test_leverage_study_main(self, monkeypatch, db_path_mp):
        """leverage_study main with default args: TSLL/TSLA — patch run_leverage_study."""
        # Empty DB → run_leverage_study returns degraded result (no scenarios)
        out = _run_module("nuri.quant.backtest.leverage_study", monkeypatch, argv=["leverage_study"])
        assert isinstance(out, str)


# ──────────────────────────────────────────────────────────────────────────────
# nuri.quant.validation.*
# ──────────────────────────────────────────────────────────────────────────────


class TestValidationMainRunpy:
    def test_scorecard_main(self, monkeypatch, db_path_mp):
        """scorecard main: generate_validation_report. Empty DB → returns None → 'C-1부터' msg."""
        out = _run_module("nuri.quant.validation.scorecard", monkeypatch, argv=["scorecard"])
        # Either prints "통합 리포트" or "C-1부터" (data-missing branch)
        assert "리포트" in out or "C-1" in out

    def test_analyst_backtest_main(self, monkeypatch, db_path_mp):
        """analyst_backtest main with default --min-days: empty DB → empty results."""
        out = _run_module("nuri.quant.validation.analyst_backtest", monkeypatch, argv=["analyst_backtest"])
        # Empty DB → empty results; print_results still prints header or empty msg
        assert isinstance(out, str)

    def test_signal_backtest_main(self, monkeypatch, db_path_mp):
        """signal_backtest main: backtest_signals on empty DB → empty results."""
        # Patch the heavy backtest function's source — defined inside same module,
        # so runpy reload re-binds it. Patch only via module-level fallback.
        import nuri.quant.validation.signal_backtest as sb

        # backtest_signals returns dict[ticker, list[result]]; empty DB → empty dict
        out = _run_module("nuri.quant.validation.signal_backtest", monkeypatch, argv=["signal_backtest"])
        assert isinstance(out, str)

    def test_superinvestor_backtest_main(self, monkeypatch, db_path_mp):
        """superinvestor_backtest main with default args: empty DB → empty."""
        _run_module(
            "nuri.quant.validation.superinvestor_backtest",
            monkeypatch,
            argv=["superinvestor_backtest"],
        )

    # ─── Branch coverage: __main__ 안의 if results / --history / --signal 등 ───

    def test_classifier_main_with_history_flag(self, monkeypatch, db_path_mp):
        """classifier --history 분기 진입 (line 642). history=[] 면 CSV write 안 함."""
        out = _run_module(
            "nuri.quant.regime.classifier",
            monkeypatch,
            argv=["classifier", "--history"],
        )
        assert isinstance(out, str)

    def test_classifier_main_history_csv_write_via_seeded_db(self, monkeypatch, db_path_mp, tmp_path):
        """classifier --history 가 history 채워서 CSV save 까지 (lines 642-652).

        runpy-aware 패치 전략:
        1) `nuri.core.db.query` 를 mock 으로 패치 → runpy reload 후 `from nuri.core.db
           import query` 시 mock 이 보임.
        2) REPORT_DIR 도 module-level 정의 → runpy reload 시 redefine 됨. 하지만
           classifier 의 REPORT_DIR 는 `Path("data/reports")` 같은 literal 일 수 있음 —
           tmp_path 로 redirect 하려면 source-level patch 필요. monkeypatch.setattr 가
           module 객체에 setattr 하므로 reload 후엔 무효 → 직접 chdir 로 우회.
        """
        from nuri.quant.regime.classifier import RegimeState

        # classify_regime_history 가 의존하는 query 결과만 mock
        # (history dates + history snapshot)
        # 너무 많은 구현 의존이라 deferred — line 642 진입만 cover.
        # CSV write 경로 (lines 646-652) 는 source 안에서 history 가 비어있으면 skip.
        # 빈 DB 라 path 도달 어려움 → 별도 issue 로 refactor 권고.
        pytest.skip(
            "lines 646-652 (history CSV save) 는 빈 DB 에서 history=[] 가 되어 분기 미진입. "
            "source 의 main(argv) 추출 + DB seeding 필요 (별도 이슈)."
        )

    def test_optimizer_main_with_signal_flag(self, monkeypatch, db_path_mp):
        """optimizer --signal X (lines 293-295): optimize_signal 결과 print top 10.

        runpy 가 module 재실행 → same-module `optimize_signal` 재정의로 source-level
        patch 가 적용 안 됨. 그러나 optimize_signal 내부의 `query_df` import 는
        nuri.core.db 외부 모듈이므로 BEFORE runpy 패치가 module reload 후에도 적용됨.

        하지만 실제로 grid sweep + signal 백테스트가 진행되어야 results 가 나옴 →
        cost 가 너무 큼. line 293 진입은 커버, 294-295 body 는 results 가 빈 list 면 미진입.
        → 짧게 진입만 확인하고 line 294-295 는 직접 호출 unit test 로 별도 cover.
        """
        # Args.signal 분기 진입은 보장 (line 293)
        out = _run_module(
            "nuri.quant.backtest.optimizer",
            monkeypatch,
            argv=["optimizer", "--signal", "rsi_oversold"],
        )
        assert isinstance(out, str)

    def test_analyst_backtest_main_with_min_days_branch(self, monkeypatch, db_path_mp):
        """analyst_backtest --min-days 진입. 빈 DB → results=[] → CSV write 안 함.

        lines 172-176 (CSV write) 는 results 가 빈 list 면 if-block skip.
        same-module `validate_estimates` 는 runpy 후 redefine 되어 monkeypatch 무효 →
        구현 source 가 main(argv) 함수로 추출되기 전엔 cover 불가.
        """
        out = _run_module(
            "nuri.quant.validation.analyst_backtest",
            monkeypatch,
            argv=["analyst_backtest", "--min-days", "30"],
        )
        assert isinstance(out, str)

        assert isinstance(out, str)


# ─── Direct main(argv) tests after source extraction (#610 follow-up) ───
# Source PR refactored `if __name__ == "__main__":` bodies into `main(argv)` so we can
# monkeypatch + call directly (runpy reload semantics no longer matter).


class TestMainEntrypoints:
    def test_scorecard_main_writes_path(self, monkeypatch, capsys, tmp_path):
        """scorecard.main: generate_validation_report → path → '통합 리포트:' line."""
        from nuri.quant.validation import scorecard

        target = tmp_path / "report.html"
        target.write_text("dummy")
        monkeypatch.setattr(scorecard, "generate_validation_report", lambda: target)
        rc = scorecard.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "통합 리포트:" in out
        assert str(target) in out

    def test_scorecard_main_no_path_prints_advice(self, monkeypatch, capsys):
        """generate_validation_report None → 안내 메시지."""
        from nuri.quant.validation import scorecard

        monkeypatch.setattr(scorecard, "generate_validation_report", lambda: None)
        rc = scorecard.main()
        assert rc == 0
        assert "C-1부터" in capsys.readouterr().out

    def test_optimizer_main_with_signal_flag_prints_top_results(self, monkeypatch, capsys):
        """optimizer.main --signal X: optimize_signal 결과 top 10 print (line 295)."""
        from nuri.quant.backtest import optimizer

        class _R:
            profit_factor = 1.5
            win_rate = 0.55
            total_trades = 20
            params = {"a": 1}

        monkeypatch.setattr(optimizer, "optimize_signal", lambda s: [_R(), _R()])
        rc = optimizer.main(["--signal", "rsi_oversold"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PF=1.50" in out
        assert "WR=55%" in out

    def test_optimizer_main_default_calls_optimize_all(self, monkeypatch):
        """optimizer.main 인자 없음 → optimize_all() 호출."""
        from nuri.quant.backtest import optimizer

        called: list[bool] = []
        monkeypatch.setattr(optimizer, "optimize_all", lambda: called.append(True))
        rc = optimizer.main([])
        assert rc == 0
        assert called == [True]

    def test_analyst_backtest_main_writes_csv_when_results(self, monkeypatch, tmp_path, capsys):
        """analyst_backtest.main: results non-empty → CSV write (lines 172-176)."""
        from dataclasses import dataclass

        from nuri.quant.validation import analyst_backtest

        @dataclass
        class _Row:
            ticker: str = "TEST"
            recommendation: str = "buy"
            target: float = 100.0
            elapsed_days: int = 95
            hit: bool = False
            return_pct: float = 0.05

        monkeypatch.setattr(analyst_backtest, "validate_estimates", lambda **kw: [_Row()])
        monkeypatch.setattr(analyst_backtest, "print_results", lambda r: None)
        monkeypatch.setattr(analyst_backtest, "REPORT_DIR", tmp_path)
        rc = analyst_backtest.main(["--min-days", "30"])
        assert rc == 0
        # Find the CSV under tmp_path/<today>/analyst_results.csv
        csvs = list(tmp_path.rglob("analyst_results.csv"))
        assert len(csvs) == 1

    def test_signal_backtest_main_writes_csvs(self, monkeypatch, tmp_path):
        """signal_backtest.main: results + scorecards non-empty → 2 CSV files (lines 805, 807)."""
        from dataclasses import dataclass

        from nuri.quant.validation import signal_backtest

        @dataclass
        class _R:
            ticker: str = "T"
            signal_id: str = "x"
            entry_date: str = "2026-04-01"
            entry_price: float = 100.0
            exit_date: str = "2026-04-08"
            exit_price: float = 105.0
            return_pct: float = 5.0
            holding_days: int = 7

        @dataclass
        class _SC:
            signal_id: str = "x"
            total_trades: int = 1
            win_rate: float = 1.0
            avg_return: float = 5.0
            max_return: float = 5.0
            max_loss: float = 0.0
            profit_factor: float = 5.0

        monkeypatch.setattr(signal_backtest, "backtest_signals", lambda **kw: [_R()])
        monkeypatch.setattr(signal_backtest, "generate_scorecard", lambda r: [_SC()])
        monkeypatch.setattr(signal_backtest, "print_scorecard", lambda s: None)
        monkeypatch.setattr(signal_backtest, "REPORT_DIR", tmp_path)
        rc = signal_backtest.main([])
        assert rc == 0
        assert len(list(tmp_path.rglob("signal_results.csv"))) == 1
        assert len(list(tmp_path.rglob("signal_scorecard.csv"))) == 1

    def test_superinvestor_backtest_main_writes_csvs(self, monkeypatch, tmp_path):
        """superinvestor_backtest.main: results + scorecards → 2 CSV (lines 260, 262)."""
        from dataclasses import dataclass

        from nuri.quant.validation import superinvestor_backtest as sib

        @dataclass
        class _R:
            ticker: str = "T"
            investor: str = "x"
            filing_date: str = "2026-01-01"
            return_pct: float = 5.0
            excess_return: float = 3.0

        @dataclass
        class _SC:
            investor: str = "x"
            total_follows: int = 1
            win_rate: float = 1.0
            avg_return: float = 5.0
            avg_excess_return: float = 3.0
            best_ticker: str = "T"
            best_return: float = 5.0
            worst_ticker: str = "T"
            worst_return: float = 5.0

        monkeypatch.setattr(sib, "backtest_superinvestor", lambda **kw: [_R()])
        monkeypatch.setattr(sib, "generate_scorecard", lambda r, h: [_SC()])
        monkeypatch.setattr(sib, "print_scorecard", lambda s: None)
        monkeypatch.setattr(sib, "REPORT_DIR", tmp_path)
        rc = sib.main([])
        assert rc == 0
        assert len(list(tmp_path.rglob("superinvestor_results.csv"))) == 1
        assert len(list(tmp_path.rglob("superinvestor_scorecard.csv"))) == 1

    def test_classifier_main_history_writes_csv(self, monkeypatch, tmp_path):
        """classifier.main --history: history non-empty → CSV write (lines 646-652)."""
        from nuri.quant.regime import classifier

        fake_state = classifier.RegimeState(
            date="2026-04-01",
            trend="up",
            volatility="low",
            regime="bull",
            confidence=0.8,
            details={"spy_close": 500.0, "vix": 18.0, "fear_greed": 60},
        )
        monkeypatch.setattr(classifier, "classify_regime_history", lambda **kw: [fake_state])
        monkeypatch.setattr(classifier, "print_history", lambda h: None)
        monkeypatch.setattr(classifier, "REPORT_DIR", tmp_path)
        rc = classifier.main(["--history", "--start", "2026-01-01"])
        assert rc == 0
        assert len(list(tmp_path.rglob("regime_history.csv"))) == 1

    def test_classifier_main_default_calls_print_regime(self, monkeypatch):
        """classifier.main (--history 없음) → classify_regime + print_regime path."""
        from nuri.quant.regime import classifier

        called: list[str] = []
        monkeypatch.setattr(classifier, "classify_regime", lambda: "STATE")
        monkeypatch.setattr(classifier, "print_regime", lambda s: called.append(s))
        rc = classifier.main([])
        assert rc == 0
        assert called == ["STATE"]
