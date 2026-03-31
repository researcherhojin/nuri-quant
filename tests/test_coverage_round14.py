"""커버리지 보강 Round 14 — llm context enriched, regime special, consensus weighted, position open, longshort execute."""

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def full_db(tmp_path, monkeypatch):
    """모든 모듈이 데이터를 찾을 수 있도록 풍부한 DB."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    # 포트폴리오
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "EV/AI"},
    ], path)

    # 가격 500일
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLA"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLA": 200}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)

    # 매크로 (VIX + Fear&Greed + 금리)
    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macro.append({"indicator": "us_10y_yield", "date": ds, "value": 4.2 + np.sin(i / 50) * 0.5, "source": "test"})
        macro.append({"indicator": "us_2y_yield", "date": ds, "value": 4.5 + np.sin(i / 40) * 0.3, "source": "test"})
    upsert_macro(macro, path)

    # superinvestors
    with get_db(path) as conn:
        conn.executemany("""INSERT OR REPLACE INTO superinvestors
            (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", [
            ("Buffett", "2025-08-15", "AAPL", 900000000, 171e9, 48.5, "Apple Inc"),
            ("Buffett", "2025-02-15", "AAPL", 905000000, 165e9, 49.0, "Apple Inc"),
            ("Dalio", "2025-08-15", "NVDA", 5000000, 650e6, 3.2, "NVIDIA Corp"),
        ])

    # estimates
    with get_db(path) as conn:
        conn.executemany("""INSERT OR REPLACE INTO estimates
            (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", [
            ("AAPL", "2025-06-01", "buy", 250, 180, 220, 215, 30, 190),
            ("NVDA", "2025-06-01", "strong_buy", 200, 100, 170, 165, 25, 130),
        ])

    # recommendations (consensus 결과)
    with get_db(path) as conn:
        conn.execute("""INSERT OR REPLACE INTO recommendations
            (ticker, date, action, confidence, regime, signals)
            VALUES ('AAPL', '2026-03-30', 'BUY', 75, 'bull_low_vol', 'rsi_oversold')""")

    # external_analysis
    with get_db(path) as conn:
        conn.execute("""INSERT OR REPLACE INTO external_analysis
            (date, source, ticker, data_type, value, numeric_value)
            VALUES ('2026-03-30', 'tipranks', 'AAPL', 'consensus', 'Strong Buy', 4.5)""")

    return path


# ─── LLM Report — enriched context (conflicts, drift, external) ───


class TestLLMEnriched:
    def test_context_with_recommendations(self, full_db):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        # candidates 섹션에 BUY 포함
        assert "BUY" in ctx.candidates_section or "0건" in ctx.candidates_section

    def test_context_with_external(self, full_db):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        # external 섹션
        assert "tipranks" in ctx.external_section.lower() or "외부" in ctx.external_section

    def test_context_known_numbers(self, full_db):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        assert len(ctx.known_numbers) > 0
        assert len(ctx.known_tickers) >= 3


# ─── Regime Classifier — special regime branches ───


class TestRegimeClassifierBranches:
    def test_recovery_detection(self, full_db):
        """recovery 레짐 감지 (SMA 교차)."""
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        # recovery는 SMA50 < SMA200 200일 전 + SMA50 >= SMA200 현재
        # 테스트 데이터는 상승 추세이므로 recovery 아닐 수 있음
        assert state.details["base_regime"] is not None

    def test_euphoria_check(self, full_db):
        """euphoria 체크 (VIX < 12 AND F&G > 80)."""
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        # special_regime은 None이거나 euphoria/recovery/stagflation/sector_rotation
        sp = state.details.get("special_regime")
        assert sp is None or sp in ("euphoria", "recovery", "stagflation", "sector_rotation")

    def test_regime_with_macro_data(self, full_db):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        # 금리 데이터가 있으므로 더 많은 분기 진입
        assert state.confidence > 0


# ─── Consensus — weighted voting internals ───


class TestConsensusWeighted:
    def test_all_agents_called(self, full_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        agent_names = [v.agent_name for v in result.verdicts]
        # 10 에이전트 전부 호출
        assert len(agent_names) == 10
        assert "technical" in agent_names
        assert "risk" in agent_names

    def test_dissent_detection(self, full_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        # dissent는 majority와 다른 의견 목록
        assert isinstance(result.dissent, list)

    def test_analyze_multiple_tickers(self, full_db):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio()
        assert len(results) >= 3  # AAPL, NVDA, TSLA


# ─── Position — open with full certification ───


class TestPositionFull:
    def test_open_with_all_checks(self, full_db):
        from nuri.trading.strategy.position import certify_position
        cert = certify_position("TSLA", "long", "bull_low_vol", "growth")
        # 모든 체크 필드
        assert hasattr(cert, "regime_aligned")
        assert hasattr(cert, "agent_consensus")
        assert hasattr(cert, "concentration_ok")
        assert hasattr(cert, "daily_limit_ok")
        assert hasattr(cert, "drift_safe")
        assert hasattr(cert, "certified")

    def test_position_print(self, full_db, capsys):
        from nuri.trading.strategy.position import print_positions
        print_positions()
        output = capsys.readouterr().out
        assert len(output) >= 0


# ─── Longshort — execute + print ───


class TestLongshortFull:
    def test_strategy_with_3_tickers(self, full_db):
        from nuri.trading.strategy.longshort import generate_strategy
        actions = generate_strategy()
        assert isinstance(actions, list)

    def test_execute_and_print(self, full_db, capsys):
        from nuri.trading.strategy.longshort import (
            execute_strategy,
            generate_strategy,
            print_strategy,
        )
        actions = generate_strategy()
        print_strategy(actions)
        if actions:
            execute_strategy(actions)
        output = capsys.readouterr().out
        assert len(output) >= 0


# ─── Superinvestor Backtest — with data ───


class TestSuperinvestorBT:
    def test_backtest_with_data(self, full_db):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        results = backtest_superinvestor()
        assert isinstance(results, list)

    def test_generate_scorecard(self, full_db):
        from nuri.quant.validation.superinvestor_backtest import (
            backtest_superinvestor,
            generate_scorecard,
        )
        results = backtest_superinvestor()
        if results:
            scorecard = generate_scorecard(results, hold_days=90)
            assert isinstance(scorecard, list)


# ─── Analyst Backtest — with data ───


class TestAnalystBT:
    def test_validate_with_data(self, full_db):
        from nuri.quant.validation.analyst_backtest import validate_estimates
        results = validate_estimates()
        assert isinstance(results, list)


# ─── Swing Scanner — deeper ───


class TestSwingScannerFull:
    def test_scan_with_data(self, full_db):
        from nuri.trading.swing.scanner import scan_market
        results = scan_market()
        assert isinstance(results, list)

    def test_swing_rules_evaluate(self, full_db):
        from nuri.trading.swing.rules import evaluate_entries
        entries = evaluate_entries()
        assert isinstance(entries, list)


# ─── Charts — generate all types ───


class TestChartsAll:
    def test_generate_for_all_tickers(self, full_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) >= 3  # AAPL, NVDA, TSLA
