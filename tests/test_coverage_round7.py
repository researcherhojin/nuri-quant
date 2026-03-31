"""커버리지 보강 Round 7 — llm deep, charts deep, position deep, consensus deep, rebalance, regime."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLL", "quantity": 96,
         "avg_price": 16.93, "currency": "USD", "sector": "Leveraged_ETF"},
    ], path)
    dates = pd.date_range("2024-06-01", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "TSLL"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "TSLL": 15}[t]
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 3
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50000000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)
    vix = [{"indicator": "vix", "date": d.strftime("%Y-%m-%d"),
            "value": 15 + np.sin(i / 30) * 8, "source": "test"}
           for i, d in enumerate(dates)]
    fg = [{"indicator": "fear_greed", "date": d.strftime("%Y-%m-%d"),
           "value": 50 + np.sin(i / 25) * 30, "source": "test"}
          for i, d in enumerate(dates)]
    upsert_macro(vix + fg, path)
    return path


# ─── LLM Report — deeper sections ───


class TestLLMDeep:
    def test_report_context_all_sections(self, rich_db):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        sections = ["gate_summary", "regime_section", "macro_section",
                     "risk_section", "candidates_section", "conflicts_section",
                     "drift_section", "consensus_section", "strategy_section",
                     "external_section", "rebalance_section"]
        for s in sections:
            assert hasattr(ctx, s), f"missing section: {s}"
            assert isinstance(getattr(ctx, s), str)

    def test_known_tickers_set(self, rich_db):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        assert "AAPL" in ctx.known_tickers
        assert "NVDA" in ctx.known_tickers

    def test_generate_ollama_mock(self, rich_db):
        """Ollama API mock으로 LLM 생성."""
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "## 시장 분석\n테스트 리포트입니다."}
        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("테스트 프롬프트")
        assert "시장 분석" in result or "테스트" in result

    def test_generate_llm_report_full(self, rich_db):
        """전체 리포트 생성 (Ollama mock)."""
        from nuri.llm.report import generate_llm_report
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "## 1. 완성도\nGate Score: 30%\n## 2. 시장\nbull\n## 3. 리스크\nlow\n"
                        "## 4. 시그널\nnone\n## 5. 후보\nnone\n## 6. 전략\nhold\n## 7. 주의\nnone",
        }
        with patch("requests.post", return_value=mock_resp), \
             patch("requests.get", return_value=MagicMock(status_code=200)):
            result = generate_llm_report()
        assert isinstance(result, dict)


# ─── Charts — deeper (generate_png, info panel) ───


class TestChartsDeep:
    def test_detect_signals_with_data(self, rich_db):
        from nuri.analysis.charts import _detect_signals, _load_chart_data
        df = _load_chart_data("AAPL")
        if df is not None and len(df) > 50:
            result = _detect_signals(df)
            assert "signal" in result.columns or len(result) > 0

    def test_get_info_panel(self, rich_db):
        from nuri.analysis.charts import _get_info_panel
        info = _get_info_panel("AAPL")
        assert "ticker" in info

    def test_generate_charts_with_output(self, rich_db, tmp_path):
        from nuri.analysis.charts import generate_charts
        results = generate_charts(output_dir=tmp_path, tickers=["AAPL"])
        assert isinstance(results, list)


# ─── Position — deeper (open/close flow) ───


class TestPositionRound7:
    def test_open_close_full_flow(self, rich_db):
        """open → certify → close 전체 흐름."""
        from nuri.trading.strategy.position import (
            certify_position,
            close_position,
            get_positions_summary,
            open_position,
        )
        # 인증
        certify_position("AAPL", "long", "bull_low_vol", "growth")

        # consensus mock으로 open
        with patch("nuri.trading.agents.consensus.analyze_ticker") as mock_at, \
             patch("nuri.trading.engine.memory.detect_drift", return_value=[]):
            mock_at.return_value = MagicMock(
                final_action="BUY", final_confidence=85, agreement_rate=0.8,
            )
            opened = open_position("AAPL", "long", 190.0, 10, "growth", "bull_low_vol")

        if opened:
            from nuri.core.db import query
            pos = query("SELECT id FROM positions WHERE ticker='AAPL' AND exit_date IS NULL")
            if pos:
                close_position(pos[0]["id"], 210.0, "take_profit")

        summary = get_positions_summary()
        assert isinstance(summary, dict)

    def test_update_prices(self, rich_db):
        from nuri.trading.strategy.position import update_prices
        update_prices()  # 에러 없이 실행


# ─── Consensus — deeper (agent verdicts) ───


class TestConsensusRound7:
    def test_analyze_ticker_result_fields(self, rich_db):
        from nuri.trading.agents.consensus import analyze_ticker
        result = analyze_ticker("AAPL")
        assert hasattr(result, "final_action")
        assert result.final_action in ("BUY", "SELL", "HOLD")
        assert 0 <= result.final_confidence <= 100
        assert 0 <= result.agreement_rate <= 1

    def test_analyze_portfolio_multiple(self, rich_db):
        from nuri.trading.agents.consensus import analyze_portfolio
        results = analyze_portfolio()
        assert len(results) >= 2  # AAPL + NVDA


# ─── Rebalance — deeper ───


class TestRebalanceDeep:
    def test_regime_aware_rebalance(self, rich_db):
        from nuri.trading.recommend.rebalance import regime_aware_rebalance
        result = regime_aware_rebalance()
        assert isinstance(result, list)

    def test_detect_violations_leveraged(self, rich_db):
        """TSLL 레버리지 ETF 위반 감지."""
        from nuri.analysis.rebalance_advisor import detect_violations
        with patch("nuri.analysis.rebalance_advisor.analyze_portfolio") as mock_ap:
            mock_df = pd.DataFrame([
                {"ticker": "TSLL", "account": "test", "quantity": 96,
                 "avg_price": 16.93, "current_price": 12.0,
                 "current_value_usd": 1152, "pnl_pct": -29.1,
                 "weight_pct": 5.0, "sector": "Leveraged_ETF", "currency": "USD"},
            ])
            mock_df.attrs["total_value_usd"] = 23000
            mock_ap.return_value = mock_df
            violations = detect_violations()
        # TSLL은 레버리지 ETF이므로 위반 감지
        lev = [v for v in violations if v.get("violation_type") == "leverage_etf"]
        assert len(lev) > 0


# ─── Regime — deeper (special regimes) ───


class TestRegimeDeep:
    def test_classify_with_fear_greed(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        state = classify_regime()
        assert state.details is not None
        assert "base_regime" in state.details

    def test_macro_score(self, rich_db):
        from nuri.quant.regime.macro_score import compute_macro_score
        score = compute_macro_score()
        assert hasattr(score, "total_score")
        assert 0 <= score.total_score <= 100

    def test_strategy_map(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        state = classify_regime()
        result = map_regime_to_strategy(state)
        assert hasattr(result, "regime")
        assert hasattr(result, "position_sizing")
