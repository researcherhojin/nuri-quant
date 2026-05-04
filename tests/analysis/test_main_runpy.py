"""Behavioral tests for `main()` entrypoints in nuri/analysis/.

Refactored from runpy pattern (PR #593/#595) to direct main() invocation.
Each test patches DB-dependent leaf functions to keep main() fast + deterministic.
"""

from __future__ import annotations

import pytest


class TestChartsMain:
    def test_charts_main_help_when_no_flags(self, db_path, capsys):
        """charts.main(): --ticker 또는 --all 없으면 help + return 1."""
        from nuri.analysis import charts

        rc = charts.main([])
        assert rc == 1
        out = capsys.readouterr().out
        assert "ticker" in out or "--all" in out
        assert "지정하세요" in out

    def test_charts_main_with_ticker_returns_zero(self, db_path, monkeypatch, capsys):
        """charts.main(['--ticker', 'AAPL']): generate_charts → 파일 목록 출력 + return 0."""
        from nuri.analysis import charts

        monkeypatch.setattr(charts, "generate_charts", lambda **kw: ["chart1.html", "chart2.html"])
        rc = charts.main(["--ticker", "AAPL"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "생성: 2개 차트" in out
        assert "chart1.html" in out
        assert "chart2.html" in out


class TestEvidenceChartsMain:
    def test_evidence_charts_main_empty_db(self, db_path, monkeypatch):
        """evidence_charts main exists; with empty DB → no-op no raise."""
        # evidence_charts.py 는 다른 패치에서 다룸 — 본 모듈의 __main__ 은
        # 본 task 범주(scope) 외 (charts.py만 refactor 했으므로).
        # 이 placeholder 는 future-proofing 용으로만 유지.
        pytest.skip("evidence_charts not refactored in this PR scope")


class TestRebalanceAdvisorMain:
    def test_main_no_violations_branch(self, db_path, monkeypatch, capsys):
        """rebalance_advisor.main(): actions 빈 → '준수 상태입니다' 분기."""
        from nuri.analysis import rebalance_advisor

        monkeypatch.setattr(
            rebalance_advisor,
            "generate_advisor_report",
            lambda *a, **kw: {
                "actions": [],
                "total_violations": 0,
                "violations_by_type": {},
                "violations_by_severity": {},
                "has_critical": False,
            },
        )
        rc = rebalance_advisor.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "준수 상태" in out

    def test_main_with_critical_violations_branch(self, db_path, monkeypatch, capsys):
        """rebalance_advisor.main(): actions + has_critical=True → CRITICAL 경고 분기."""
        from nuri.analysis import rebalance_advisor

        fake_report = {
            "actions": [
                {"ticker": "AAA", "reason": "concentration", "sell_value_usd": 5000.0,
                 "severity": "critical", "violation_type": "single_position_cap",
                 "sell_shares": 10, "action": "SELL_ALL", "current_price": 500.0,
                 "current_weight_pct": 30.0, "target_weight_pct": 15.0},
            ],
            "total_violations": 2,
            "violations_by_type": {"single_position_cap": 2},
            "violations_by_severity": {"critical": 2},
            "has_critical": True,
        }
        # print_rebalance_advisor 는 본 테스트의 검증 대상 아님 — stub 으로 우회.
        monkeypatch.setattr(rebalance_advisor, "print_rebalance_advisor", lambda a: None)
        monkeypatch.setattr(rebalance_advisor, "generate_advisor_report", lambda *a, **kw: fake_report)
        rc = rebalance_advisor.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "위반 건수: 2" in out
        assert "CRITICAL 위반 존재" in out


class TestCorrelationMain:
    def test_main_runs_through(self, db_path, monkeypatch, capsys):
        """correlation.main(): analyze_correlation + print_correlation + save_heatmap 호출."""
        import pandas as pd

        from nuri.analysis import correlation

        df = pd.DataFrame({"AAA": [1.0, 0.5], "BBB": [0.5, 1.0]}, index=["AAA", "BBB"])
        monkeypatch.setattr(correlation, "analyze_correlation", lambda: (df, []))
        save_called = {"flag": False}

        def _fake_save(corr):
            save_called["flag"] = True

        monkeypatch.setattr(correlation, "save_heatmap", _fake_save)
        rc = correlation.main()
        assert rc == 0
        # corr 비어있지 않으므로 save_heatmap 호출
        assert save_called["flag"] is True

    def test_main_skips_save_when_corr_empty(self, db_path, monkeypatch):
        """correlation.main(): analyze_correlation 빈 df → save_heatmap 스킵."""
        import pandas as pd

        from nuri.analysis import correlation

        empty = pd.DataFrame()
        monkeypatch.setattr(correlation, "analyze_correlation", lambda: (empty, []))
        save_called = {"flag": False}
        monkeypatch.setattr(correlation, "save_heatmap", lambda c: save_called.update({"flag": True}))
        rc = correlation.main()
        assert rc == 0
        assert save_called["flag"] is False


class TestPerformanceMain:
    def test_main_no_html_branch(self, db_path, monkeypatch, capsys):
        """performance.main([]): --html 없으면 generate_html_report 호출 안 됨."""
        import pandas as pd

        from nuri.analysis import performance

        port = pd.Series([0.01, 0.02, -0.01], name="r")
        bench = pd.Series([0.005, 0.01, 0.0], name="b")
        monkeypatch.setattr(performance, "get_portfolio_returns", lambda: port)
        monkeypatch.setattr(performance, "get_benchmark_returns", lambda: bench)
        called = {"html": False}
        monkeypatch.setattr(
            performance,
            "generate_html_report",
            lambda p, b: called.update({"html": True}) or "/tmp/r.html",
        )
        monkeypatch.setattr(performance, "print_performance", lambda p, b: print("PERF_OK"))
        rc = performance.main([])
        assert rc == 0
        assert called["html"] is False
        assert "PERF_OK" in capsys.readouterr().out

    def test_main_html_branch(self, db_path, monkeypatch, capsys):
        """performance.main(['--html']): generate_html_report 호출 + 경로 출력."""
        import pandas as pd

        from nuri.analysis import performance

        port = pd.Series([0.01, 0.02], name="r")
        bench = pd.Series([0.005, 0.01], name="b")
        monkeypatch.setattr(performance, "get_portfolio_returns", lambda: port)
        monkeypatch.setattr(performance, "get_benchmark_returns", lambda: bench)
        monkeypatch.setattr(performance, "print_performance", lambda p, b: None)
        monkeypatch.setattr(performance, "generate_html_report", lambda p, b: "/tmp/report.html")
        rc = performance.main(["--html"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "/tmp/report.html" in out


class TestPortfolioMain:
    def test_main_runs(self, db_path, monkeypatch, capsys):
        """portfolio.main(): analyze_portfolio + print_summary."""
        import pandas as pd

        from nuri.analysis import portfolio

        df = pd.DataFrame([{"ticker": "AAA", "weight": 0.5}])
        monkeypatch.setattr(portfolio, "analyze_portfolio", lambda: df)
        monkeypatch.setattr(portfolio, "print_summary", lambda d: print("PORT_OK"))
        rc = portfolio.main()
        assert rc == 0
        assert "PORT_OK" in capsys.readouterr().out


class TestRebalanceMain:
    def test_main_default_method_mvo(self, db_path, monkeypatch, capsys):
        """rebalance.main([]): default method=mvo, analyze_rebalance + print_rebalance 호출."""
        import pandas as pd

        from nuri.analysis import rebalance

        captured_method = {}

        def _fake_analyze(method="mvo"):
            captured_method["method"] = method
            return pd.DataFrame()

        monkeypatch.setattr(rebalance, "analyze_rebalance", _fake_analyze)
        monkeypatch.setattr(rebalance, "print_rebalance", lambda d: print("REB_OK"))
        rc = rebalance.main([])
        assert rc == 0
        assert captured_method["method"] == "mvo"
        assert "REB_OK" in capsys.readouterr().out

    def test_main_method_rp(self, db_path, monkeypatch):
        """rebalance.main(['--method', 'rp']): method=rp 전달."""
        import pandas as pd

        from nuri.analysis import rebalance

        captured = {}
        monkeypatch.setattr(rebalance, "analyze_rebalance", lambda method="mvo": captured.update({"m": method}) or pd.DataFrame())
        monkeypatch.setattr(rebalance, "print_rebalance", lambda d: None)
        rc = rebalance.main(["--method", "rp"])
        assert rc == 0
        assert captured["m"] == "rp"


class TestRiskMain:
    def test_main_runs(self, db_path, monkeypatch, capsys):
        """risk.main(): analyze_risk + print_risk 호출."""
        from nuri.analysis import risk

        monkeypatch.setattr(risk, "analyze_risk", lambda: {"sharpe_ratio": 1.0})
        monkeypatch.setattr(risk, "print_risk", lambda m: print("RISK_OK"))
        rc = risk.main()
        assert rc == 0
        assert "RISK_OK" in capsys.readouterr().out


class TestSectorMain:
    def test_main_runs(self, db_path, monkeypatch, capsys):
        """sector.main(): analyze_sector + print_sector 호출."""
        import pandas as pd

        from nuri.analysis import sector

        monkeypatch.setattr(sector, "analyze_sector", lambda: (pd.DataFrame(), pd.DataFrame(), []))
        monkeypatch.setattr(sector, "print_sector", lambda s, r, w: print("SEC_OK"))
        rc = sector.main()
        assert rc == 0
        assert "SEC_OK" in capsys.readouterr().out


class TestSentimentMain:
    def test_main_runs(self, db_path, monkeypatch, capsys):
        """sentiment.main(): analyze_sentiment + print_sentiment 호출."""
        from nuri.analysis import sentiment

        monkeypatch.setattr(sentiment, "analyze_sentiment", lambda: {"foo": "bar"})
        monkeypatch.setattr(sentiment, "print_sentiment", lambda s: print("SENT_OK"))
        rc = sentiment.main()
        assert rc == 0
        assert "SENT_OK" in capsys.readouterr().out
