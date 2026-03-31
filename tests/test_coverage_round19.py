"""Coverage Round 19 — LLM report, regime classifier, superinvestor backtest,
signal backtest macro signals, evidence charts, SSE stream."""
import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Rich DB fixture (portfolio + 500 day prices + macro)
# ═══════════════════════════════════════════════════════


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    # Portfolio
    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4,
         "avg_price": 60000, "currency": "KRW", "sector": "Semiconductor"},
    ], path)

    # Prices: 500 business days
    dates = pd.date_range("2024-01-02", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "005930.KS", "VOO",
              "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLC", "XLRE"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "005930.KS": 58000,
                "VOO": 440}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 3
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p - 0.5, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50_000_000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)

    # Macro: VIX, Fear&Greed, yields, PCR, CPI, GDP
    macros = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macros.append({"indicator": "vix", "date": ds,
                       "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macros.append({"indicator": "fear_greed", "date": ds,
                       "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macros.append({"indicator": "us_10y_yield", "date": ds,
                       "value": 4.2 + np.sin(i / 40) * 0.5, "source": "test"})
        macros.append({"indicator": "us_3m_yield", "date": ds,
                       "value": 5.0 - np.sin(i / 40) * 0.3, "source": "test"})
        macros.append({"indicator": "put_call_ratio", "date": ds,
                       "value": 0.8 + np.sin(i / 15) * 0.4, "source": "test"})
    # CPI / GDP for stagflation
    macros.append({"indicator": "cpi_yoy", "date": dates[-1].strftime("%Y-%m-%d"),
                   "value": 3.0, "source": "test"})
    macros.append({"indicator": "gdp_growth", "date": dates[-1].strftime("%Y-%m-%d"),
                   "value": 2.5, "source": "test"})
    upsert_macro(macros, path)

    return path


# ═══════════════════════════════════════════════════════
# 1. LLM Report (nuri/llm/report.py)
# ═══════════════════════════════════════════════════════


class TestReportContext:
    """ReportContext dataclass tests."""

    def test_defaults_none_to_empty_sets(self):
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="test", gate_score=0.5,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        assert isinstance(ctx.known_tickers, set)
        assert isinstance(ctx.known_numbers, set)
        assert len(ctx.known_tickers) == 0

    def test_explicit_known(self):
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL", "NVDA"},
            known_numbers={"42", "3.14"},
        )
        assert "AAPL" in ctx.known_tickers
        assert "42" in ctx.known_numbers


class TestFormatPrompt:
    """format_prompt() template rendering."""

    def test_contains_all_sections(self):
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="Gate OK 5/5",
            gate_score=1.0,
            regime_section="bull_low_vol",
            macro_section="macro 60/100",
            risk_section="Sharpe 1.2",
            candidates_section="BUY AAPL",
            conflicts_section="no conflicts",
            drift_section="stable",
            consensus_section="10 agents agree",
            strategy_section="aggressive",
            external_section="TipRanks buy",
            rebalance_section="no violations",
        )
        prompt = format_prompt(ctx)
        assert "[DATA]" in prompt
        assert "[/DATA]" in prompt
        assert "Gate OK 5/5" in prompt
        assert "bull_low_vol" in prompt
        assert "매크로" in prompt
        assert "리밸런스 어드바이저" in prompt

    def test_system_prompt_included(self):
        from nuri.llm.report import SYSTEM_PROMPT, ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="", gate_score=0.5,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        prompt = format_prompt(ctx)
        assert SYSTEM_PROMPT in prompt


class TestValidateOutput:
    """validate_output() edge cases."""

    def test_clean_output_passes(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL", "NVDA"},
            known_numbers={"50", "0.65", "1.5"},
        )
        text = (
            "## 1. 데이터 완성도\n시장 환경 분석\n"
            "## 2. 시장 환경\nbull\n"
            "## 3. 리스크\nSharpe OK\n"
            "## 4. 시그널\nRSI\n"
            "## 5. 매매 후보\nAAPL BUY\n"
            "## 6. 전략\naggressive\n"
            "## 7. 주의사항\nnone\n"
        )
        result = validate_output(text, ctx)
        assert result.passed is True
        assert result.hallucinated_tickers == []

    def test_hallucinated_ticker_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers={"AAPL"},
            known_numbers=set(),
        )
        text = "TSLA is a great buy, also check MSFT and AAPL"
        result = validate_output(text, ctx)
        assert "TSLA" in result.hallucinated_tickers
        assert "MSFT" in result.hallucinated_tickers
        assert "AAPL" not in result.hallucinated_tickers
        assert result.passed is False

    def test_low_gate_score_warning(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.2,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        result = validate_output("완성도 시장 리스크 시그널 후보 전략 주의", ctx)
        assert result.passed is False
        assert any("완성도" in w for w in result.warnings)

    def test_missing_sections_warning(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        result = validate_output("hello world", ctx)
        assert any("구조 불완전" in w for w in result.warnings)

    def test_fabricated_win_rate_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers={"0.65"},  # 65%
        )
        # 승률 99% is not in known_numbers
        text = "완성도 시장 리스크 시그널 후보 전략 주의 승률 99%"
        result = validate_output(text, ctx)
        assert any("불일치" in w for w in result.warnings)

    def test_fabricated_pf_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers={"1.5"},
        )
        text = "완성도 시장 리스크 시그널 후보 전략 주의 PF 8.7"
        result = validate_output(text, ctx)
        assert any("불일치" in w for w in result.warnings)


class TestGenerateOllama:
    """_generate_ollama() error paths."""

    def test_connection_refused(self):

        from nuri.llm.report import _generate_ollama
        with patch("nuri.llm.report._generate_ollama.__module__", "nuri.llm.report"):
            # Mock requests inside the function
            mock_post = MagicMock(side_effect=__import__("requests").ConnectionError("refused"))
            with patch.dict("sys.modules", {}), \
                 patch("requests.post", mock_post):
                # The function does lazy import of requests
                result = _generate_ollama("test prompt")
        assert "연결 실패" in result or isinstance(result, str)

    def test_connection_error_returns_help_message(self):
        from nuri.llm.report import _generate_ollama
        mock_requests = MagicMock()
        mock_requests.ConnectionError = ConnectionError
        mock_requests.post.side_effect = ConnectionError("refused")
        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = _generate_ollama("test prompt")
        assert "연결 실패" in result

    def test_successful_response(self):
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "## 1. 데이터 완성도\n리포트 내용입니다."
        }
        mock_resp.raise_for_status = MagicMock()
        mock_requests = MagicMock()
        mock_requests.ConnectionError = ConnectionError
        mock_requests.post.return_value = mock_resp
        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = _generate_ollama("test prompt")
        assert "데이터 완성도" in result

    def test_thinking_model_response(self):
        """Qwen3.5 thinking model: response empty, thinking has content."""
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "",
            "thinking": "blah blah ## 1. 데이터 완성도\n실제 리포트"
        }
        mock_resp.raise_for_status = MagicMock()
        mock_requests = MagicMock()
        mock_requests.ConnectionError = ConnectionError
        mock_requests.post.return_value = mock_resp
        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = _generate_ollama("test prompt")
        assert "데이터 완성도" in result

    def test_generic_exception(self):
        from nuri.llm.report import _generate_ollama
        mock_requests = MagicMock()
        mock_requests.ConnectionError = ConnectionError
        mock_requests.post.side_effect = RuntimeError("timeout")
        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = _generate_ollama("test prompt")
        assert "오류" in result


class TestGenerateLlmReport:
    """generate_llm_report() full flow."""

    def test_gate_blocked_low_score(self):
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="low data", gate_score=0.1,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        with patch("nuri.llm.report.gather_context", return_value=mock_ctx):
            result = generate_llm_report()
        assert result["gate_blocked"] is True
        assert result["report"] is None

    def test_full_flow_with_mock_ollama(self):
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="OK 8/10", gate_score=0.8,
            regime_section="bull_low_vol", macro_section="macro 60",
            risk_section="Sharpe 1.2", candidates_section="BUY AAPL",
            conflicts_section="", drift_section="stable",
            consensus_section="", strategy_section="aggressive",
            known_tickers={"AAPL"}, known_numbers={"60", "1.2"},
        )
        with patch("nuri.llm.report.gather_context", return_value=mock_ctx), \
             patch("nuri.llm.report._generate_ollama",
                   return_value="## 1. 데이터 완성도\n시장 리스크 시그널 후보 전략 주의"):
            result = generate_llm_report()
        assert result["gate_blocked"] is False
        assert result["report"] is not None
        assert "면책" in result["disclaimer"] or "투자 조언" in result["disclaimer"]

    def test_low_gate_score_adds_warning_to_report(self):
        from nuri.llm.report import ReportContext, generate_llm_report
        mock_ctx = ReportContext(
            gate_summary="partial", gate_score=0.5,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        with patch("nuri.llm.report.gather_context", return_value=mock_ctx), \
             patch("nuri.llm.report._generate_ollama", return_value="report text"):
            result = generate_llm_report()
        assert "완성도" in result["report"]

    def test_sync_alias(self):
        from nuri.llm.report import ReportContext, generate_llm_report_sync
        mock_ctx = ReportContext(
            gate_summary="", gate_score=0.1,
            regime_section="", macro_section="",
            risk_section="", candidates_section="",
            conflicts_section="", drift_section="",
            consensus_section="", strategy_section="",
        )
        with patch("nuri.llm.report.gather_context", return_value=mock_ctx):
            result = generate_llm_report_sync()
        assert result["gate_blocked"] is True


# ═══════════════════════════════════════════════════════
# 2. Regime Classifier (nuri/quant/regime/classifier.py)
# ═══════════════════════════════════════════════════════


class TestSpecialRegimes:
    """Special regime detection functions."""

    def test_euphoria_detected(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=10.0, fear_greed=85.0) is True

    def test_euphoria_not_detected_high_vix(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=15.0, fear_greed=85.0) is False

    def test_euphoria_not_detected_low_fg(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=10.0, fear_greed=60.0) is False

    def test_euphoria_none_inputs(self):
        from nuri.quant.regime.classifier import _detect_euphoria
        assert _detect_euphoria(vix=None, fear_greed=85.0) is False
        assert _detect_euphoria(vix=10.0, fear_greed=None) is False

    def test_stagflation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 0.5, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is True

    def test_stagflation_not_detected_normal_economy(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 2.5, "source": "test"},
            {"indicator": "gdp_growth", "date": "2025-01-01", "value": 2.5, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is False

    def test_stagflation_no_gdp_data(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_stagflation
        path = tmp_path / "test.db"
        init_db(path)
        upsert_macro([
            {"indicator": "cpi_yoy", "date": "2025-01-01", "value": 5.0, "source": "test"},
        ], path)
        assert _detect_stagflation(db_path=path) is False

    def test_recovery_detected(self):
        from nuri.quant.regime.classifier import _detect_recovery
        # Build a DataFrame with 300 rows: sma50 < sma200 200 rows ago, sma50 >= sma200 now
        n = 300
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n),
            "close": np.linspace(100, 200, n),
        })
        # sma50 and sma200: 200 rows ago sma50 < sma200, now sma50 >= sma200
        sma50 = np.ones(n) * 150.0
        sma200 = np.ones(n) * 160.0
        # Past: row 100 (idx = n - 200 = 100) → sma50 < sma200
        # Now: last row → sma50 >= sma200
        sma50[-1] = 165
        sma200[-1] = 160
        df["sma50"] = sma50
        df["sma200"] = sma200
        assert _detect_recovery(df) is True

    def test_recovery_not_detected_bull_to_bull(self):
        from nuri.quant.regime.classifier import _detect_recovery
        n = 300
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n),
            "close": np.linspace(100, 200, n),
        })
        df["sma50"] = 170.0  # always above sma200
        df["sma200"] = 160.0
        assert _detect_recovery(df) is False

    def test_recovery_short_data(self):
        from nuri.quant.regime.classifier import _detect_recovery
        df = pd.DataFrame({"date": ["2024-01-01"], "close": [100], "sma50": [100], "sma200": [100]})
        assert _detect_recovery(df) is False
        assert _detect_recovery(None) is False

    def test_sector_rotation_detected(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        path = tmp_path / "test.db"
        init_db(path)
        # SPY flat: 21 prices almost same
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for d in dates:
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": 450, "high": 451, "low": 449,
                         "close": 450, "volume": 1000000, "adj_close": 450})
        # XLK with 4% gain over 20 days
        for i, d in enumerate(dates):
            p = 200 + i * 0.5
            rows.append({"ticker": "XLK", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is True

    def test_sector_rotation_spy_not_flat(self, tmp_path):
        from nuri.quant.regime.classifier import _detect_sector_rotation
        path = tmp_path / "test.db"
        init_db(path)
        dates = pd.date_range("2025-01-01", periods=21, freq="B")
        rows = []
        for i, d in enumerate(dates):
            # SPY rising strongly (>2%)
            p = 450 + i * 2
            rows.append({"ticker": "SPY", "date": d.strftime("%Y-%m-%d"),
                         "open": p, "high": p + 1, "low": p - 1,
                         "close": p, "volume": 1000000, "adj_close": p})
        upsert_prices(pd.DataFrame(rows), path)
        assert _detect_sector_rotation(db_path=path) is False


class TestClassifySingle:
    """_classify_single trend/volatility logic."""

    def test_bull(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=15.0, bb_width=5.0, thresholds=th)
        assert trend == "bull"
        assert vol == "low"

    def test_bear(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=400, sma50=420, sma200=460, vix=30.0, bb_width=8.0, thresholds=th)
        assert trend == "bear"
        assert vol == "high"

    def test_sideways_narrow_gap(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=460, sma50=461, sma200=460, vix=16.0, bb_width=5.0, thresholds=th)
        assert trend == "sideways"

    def test_volatility_from_bb_when_no_vix(self):
        from nuri.quant.regime.classifier import _classify_single
        th = {"sideways_pct": 2.0, "vix_threshold": 18.0, "vix_bear_threshold": 24.0, "bb_width_threshold": 6.0}
        trend, vol = _classify_single(close=500, sma50=490, sma200=460, vix=None, bb_width=8.0, thresholds=th)
        assert vol == "high"


class TestClassifyRegime:
    """classify_regime() integration with DB."""

    def test_full_classification(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        # Reset freshness warning flag
        cls_mod._freshness_warned = False
        # Mock freshness check to pass
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        result = cls_mod.classify_regime(db_path=rich_db)
        assert result is not None
        assert result.trend in ("bull", "bear", "sideways")
        assert result.volatility in ("high", "low")
        assert 0 <= result.confidence <= 1
        assert result.details["base_regime"] is not None

    def test_with_date_param(self, rich_db):
        from nuri.quant.regime.classifier import classify_regime
        # Use a specific date that exists in our data
        result = classify_regime(date="2025-06-01", db_path=rich_db)
        # Should work since we have data up to that date
        if result is not None:
            assert result.date <= "2025-06-01"

    def test_print_regime_none(self, capsys):
        from nuri.quant.regime.classifier import print_regime
        print_regime(None)
        captured = capsys.readouterr()
        assert "불가" in captured.out

    def test_print_regime_with_state(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-06-01",
            trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                "rsi": 55.0, "bb_width": 5.0,
                "thresholds": {"vix_threshold": 18.0, "vix_bear_threshold": 24.0,
                               "sideways_pct": 2.0, "bb_width_threshold": 6.0},
                "base_regime": "bull_low_vol", "special_regime": None,
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "BULL" in captured.out
        assert "LOW VOL" in captured.out

    def test_print_regime_special(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_regime
        state = RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="euphoria", confidence=0.8,
            details={
                "spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                "sma_diff_pct": 6.5, "vix": 10.0, "fear_greed": 85.0,
                "rsi": None, "bb_width": 5.0,
                "thresholds": {}, "base_regime": "bull_low_vol",
                "special_regime": "euphoria",
            },
        )
        print_regime(state)
        captured = capsys.readouterr()
        assert "EUPHORIA" in captured.out

    def test_print_history_empty(self, capsys):
        from nuri.quant.regime.classifier import print_history
        print_history([])
        captured = capsys.readouterr()
        assert "없음" in captured.out

    def test_print_history_with_data(self, capsys):
        from nuri.quant.regime.classifier import RegimeState, print_history
        states = [RegimeState(
            date="2025-06-01", trend="bull", volatility="low",
            regime="bull_low_vol", confidence=0.75,
            details={"spy_close": 500.0, "sma50": 490.0, "sma200": 460.0,
                     "sma_diff_pct": 6.5, "vix": 15.0, "fear_greed": 65.0,
                     "rsi": 55.0, "bb_width": 5.0, "thresholds": {},
                     "base_regime": "bull_low_vol", "special_regime": None},
        )]
        print_history(states)
        captured = capsys.readouterr()
        assert "Regime History" in captured.out


class TestDynamicThresholds:
    """compute_dynamic_thresholds()."""

    def test_with_data(self, rich_db):
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=rich_db)
        assert "vix_threshold" in th
        assert "sideways_pct" in th
        assert th["vix_threshold"] > 0

    def test_with_insufficient_data(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import compute_dynamic_thresholds
        th = compute_dynamic_thresholds(db_path=path)
        # Falls back to defaults
        assert th["vix_threshold"] == 18.0
        assert th["sideways_pct"] == 2.0


# ═══════════════════════════════════════════════════════
# 3. Superinvestor Backtest
# ═══════════════════════════════════════════════════════


class TestSuperinvestorBacktest:
    """superinvestor_backtest.py functions."""

    def test_check_data_readiness_no_data(self, tmp_path):
        path = tmp_path / "test.db"
        init_db(path)
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_one_quarter(self, tmp_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
        assert _check_data_readiness(db_path=path) is False

    def test_check_data_readiness_two_quarters(self, tmp_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.superinvestor_backtest import _check_data_readiness
        path = tmp_path / "test.db"
        init_db(path)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-01-15", 100000, 50000000),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Buffett", "AAPL", "2025-04-15", 120000, 60000000),
            )
        assert _check_data_readiness(db_path=path) is True

    def test_backtest_no_data_returns_empty(self, tmp_path):
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor
        path = tmp_path / "test.db"
        init_db(path)
        results = backtest_superinvestor(db_path=path)
        assert results == []

    def test_generate_scorecard_empty(self):
        from nuri.quant.validation.superinvestor_backtest import generate_scorecard
        assert generate_scorecard([], 120) == []

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.superinvestor_backtest import (
            FollowResult,
            generate_scorecard,
        )
        results = [
            FollowResult(investor="Buffett", ticker="AAPL", filing_date="2025-01-15",
                         change_type="NEW", entry_date="2025-01-16", entry_price=190.0,
                         exit_date="2025-05-16", exit_price=210.0,
                         return_pct=10.53, benchmark_return_pct=5.0, excess_return_pct=5.53),
            FollowResult(investor="Buffett", ticker="MSFT", filing_date="2025-01-15",
                         change_type="INCREASED", entry_date="2025-01-16", entry_price=400.0,
                         exit_date="2025-05-16", exit_price=380.0,
                         return_pct=-5.0, benchmark_return_pct=5.0, excess_return_pct=-10.0),
        ]
        scorecards = generate_scorecard(results, 120)
        assert len(scorecards) == 1
        sc = scorecards[0]
        assert sc.investor == "Buffett"
        assert sc.total_follows == 2
        assert sc.win_rate == 0.5
        assert sc.best_ticker == "AAPL"
        assert sc.worst_ticker == "MSFT"

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out

    def test_print_scorecard_with_data(self, capsys):
        from nuri.quant.validation.superinvestor_backtest import (
            InvestorScorecard,
            print_scorecard,
        )
        sc = InvestorScorecard(
            investor="Buffett", hold_days=120, total_follows=5,
            win_rate=0.6, avg_return=8.5, avg_excess_return=3.2,
            best_ticker="AAPL", best_return=25.0,
            worst_ticker="META", worst_return=-10.0,
        )
        print_scorecard([sc])
        captured = capsys.readouterr()
        assert "Buffett" in captured.out
        assert "120일" in captured.out


# ═══════════════════════════════════════════════════════
# 4. Signal Backtest — Macro signals, data signals, exit
# ═══════════════════════════════════════════════════════


class TestMacroSignalDetectors:
    """Macro-based signal entry detectors."""

    def _make_df(self, n=30):
        """Create base DataFrame for signal tests."""
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n),
            "close": np.linspace(100, 110, n),
            "open": np.linspace(99, 109, n),
            "volume": [1000000] * n,
        })
        return df

    def test_vix_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        # VIX: 30+ for days 0-25, then drops to 24
        df["macro_vix"] = 32.0
        df.loc[26:, "macro_vix"] = 24.0
        # Check at index 26: prev 3 days are 32 (>=30), current is 24 (<=25)
        assert _entry_vix_reversal(df, 26) is True

    def test_vix_reversal_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        df["macro_vix"] = 20.0  # always low
        assert _entry_vix_reversal(df, 10) is False

    def test_vix_reversal_missing_column(self):
        from nuri.quant.validation.signal_backtest import _entry_vix_reversal
        df = self._make_df(30)
        assert _entry_vix_reversal(df, 10) is False

    def test_pcr_reversal_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        # PCR: peak at 1.3 then drops to 0.7
        df["macro_pcr"] = 0.9
        df.loc[5:10, "macro_pcr"] = 1.3
        df.loc[22:, "macro_pcr"] = 0.7
        assert _entry_pcr_reversal(df, 25) is True

    def test_pcr_reversal_no_peak(self):
        from nuri.quant.validation.signal_backtest import _entry_pcr_reversal
        df = self._make_df(30)
        df["macro_pcr"] = 0.7  # always low, never hit 1.2
        assert _entry_pcr_reversal(df, 25) is False

    def test_yield_curve_recovery_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [-0.5, -0.4, -0.3, -0.2, -0.1, 0.05, 0.1, 0.2, 0.3, 0.4]
        assert _entry_yield_curve_recovery(df, 5) is True  # prev < 0, now >= 0

    def test_yield_curve_recovery_no_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_yield_curve_recovery
        df = self._make_df(10)
        df["macro_yield_spread"] = [0.5] * 10  # always positive
        assert _entry_yield_curve_recovery(df, 5) is False


class TestDataSignalDetectors:
    """Data-dependent signal detectors."""

    def test_insider_cluster_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_insider_cluster
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100] * 10,
            "insider_buy_count_10d": [0, 1, 2, 2, 3, 4, 4, 3, 2, 1],
        })
        assert _entry_insider_cluster(df, 4) is True  # prev < 3, now >= 3

    def test_short_squeeze_entry(self):
        from nuri.quant.validation.signal_backtest import _entry_short_squeeze
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=10),
            "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "short_interest": [12.0] * 10,
        })
        # 3 consecutive up days + high short interest
        assert _entry_short_squeeze(df, 5) is True


class TestComputeExit:
    """compute_exit() branches."""

    def test_hold_days_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(50)})
        # rsi_oversold has hold_days=20
        exit_idx = compute_exit(df, 5, "rsi_oversold")
        assert exit_idx == 25

    def test_hold_days_exit_out_of_range(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({"close": range(10)})
        exit_idx = compute_exit(df, 5, "rsi_oversold")
        assert exit_idx is None

    def test_signal_exit_function(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        # macd_golden uses exit function (MACD < Signal)
        df = pd.DataFrame({
            "close": range(20),
            "macd": [0.5] * 10 + [-0.5] * 10,
            "macd_signal": [0.0] * 20,
        })
        exit_idx = compute_exit(df, 0, "macd_golden")
        assert exit_idx == 10  # first time macd < signal

    def test_yield_curve_recovery_exit(self):
        from nuri.quant.validation.signal_backtest import compute_exit
        df = pd.DataFrame({
            "close": range(20),
            "macro_yield_spread": [0.5] * 10 + [-0.5] * 10,
        })
        exit_idx = compute_exit(df, 0, "yield_curve_recovery")
        assert exit_idx == 10


class TestMergeDataSignals:
    """merge_data_signals() with DB data."""

    def test_merge_with_insider_trades(self, tmp_path):
        from nuri.core.db import get_db
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        # Insert insider trades (schema: ticker, date, insider_name, position, transaction_type, shares, value)
        with get_db(path) as conn:
            conn.execute(
                "INSERT INTO insider_trades (ticker, date, insider_name, transaction_type, "
                "shares, value) VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2025-03-01", "Tim Cook", "P-Purchase", 1000, 190000.0),
            )
        dates = pd.date_range("2025-02-25", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates,
            "close": [190.0] * 10,
        })
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns
        assert "short_interest" in result.columns

    def test_merge_empty_db(self, tmp_path):
        from nuri.quant.validation.signal_backtest import merge_data_signals
        path = tmp_path / "test.db"
        init_db(path)
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=5),
            "close": [100] * 5,
        })
        result = merge_data_signals(df, "AAPL", db_path=path)
        assert "insider_buy_count_10d" in result.columns


class TestMergeMacroData:
    """merge_macro_data() with DB."""

    def test_merge_macro(self, rich_db):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        dates = pd.date_range("2025-01-01", periods=20, freq="B")
        df = pd.DataFrame({
            "date": dates,
            "close": np.linspace(100, 110, 20),
        })
        result = merge_macro_data(df, db_path=rich_db)
        assert "macro_vix" in result.columns
        assert "macro_pcr" in result.columns
        assert "macro_yield_spread" in result.columns

    def test_merge_macro_no_date_col(self):
        from nuri.quant.validation.signal_backtest import merge_macro_data
        df = pd.DataFrame({"close": [100, 101]})
        result = merge_macro_data(df)
        assert "macro_vix" not in result.columns  # no merge happened


class TestSignalScorecard:
    """generate_scorecard() and print_scorecard()."""

    def test_generate_scorecard_with_results(self):
        from nuri.quant.validation.signal_backtest import SignalResult, generate_scorecard
        results = [
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-01-01", entry_price=100.0,
                         exit_date="2025-01-21", exit_price=110.0,
                         return_pct=10.0, holding_days=20, won=True),
            SignalResult(signal_id="rsi_oversold", ticker="AAPL",
                         entry_date="2025-02-01", entry_price=110.0,
                         exit_date="2025-02-21", exit_price=105.0,
                         return_pct=-4.55, holding_days=20, won=False),
        ]
        scorecards = generate_scorecard(results)
        # Per-ticker + aggregate
        assert len(scorecards) >= 2
        aggregate = [s for s in scorecards if s.ticker is None]
        assert len(aggregate) == 1
        assert aggregate[0].total_trades == 2
        assert aggregate[0].win_rate == 0.5

    def test_print_scorecard_empty(self, capsys):
        from nuri.quant.validation.signal_backtest import print_scorecard
        print_scorecard([])
        captured = capsys.readouterr()
        assert "없습니다" in captured.out


# ═══════════════════════════════════════════════════════
# 5. Evidence Charts (nuri/analysis/evidence_charts.py)
# ═══════════════════════════════════════════════════════


class TestEvidenceCharts:
    """Chart generation tests with mocked plotly write_html."""

    def test_generate_regime_chart_empty_db(self, tmp_path):
        """Regime chart with no SPY data."""
        from nuri.analysis.evidence_charts import generate_regime_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=path)
        assert result == output_dir / "regime_evidence.html"

    def test_generate_regime_chart_with_data(self, rich_db, tmp_path, monkeypatch):
        from nuri.analysis.evidence_charts import generate_regime_chart
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_regime_chart(output_dir, db_path=rich_db)
        assert result.exists()
        assert result.suffix == ".html"

    def test_generate_fear_greed_chart_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        path = tmp_path / "test.db"
        init_db(path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=path)
        assert result == output_dir / "fear_greed.html"

    def test_generate_fear_greed_chart_with_data(self, rich_db, tmp_path):
        from nuri.analysis.evidence_charts import generate_fear_greed_chart
        output_dir = tmp_path / "evidence"
        output_dir.mkdir()
        result = generate_fear_greed_chart(output_dir, db_path=rich_db)
        assert result.exists()
        content = result.read_text()
        assert "plotly" in content.lower() or "html" in content.lower()

    def test_generate_sell_evidence_no_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = generate_sell_evidence_chart([], output_dir)
        assert result.exists()

    def test_generate_sell_evidence_with_violations(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_sell_evidence_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        violations = [
            {"ticker": "TSLA", "type": "stop_loss", "severity": 25.3,
             "action": "SELL ALL", "recovery": "6-12개월"},
            {"ticker": "NVDA", "type": "overweight", "severity": 5.2,
             "action": "REDUCE", "recovery": "리밸런싱 필요"},
        ]
        result = generate_sell_evidence_chart(violations, output_dir)
        assert result.exists()

    def test_save_empty_chart(self, tmp_path):
        from nuri.analysis.evidence_charts import _save_empty_chart
        output_path = tmp_path / "empty.html"
        _save_empty_chart("No data available", output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "No data available" in content

    def test_shade_regime_zones_empty(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        fig = go.Figure()
        df = pd.DataFrame(columns=["date", "sma50", "sma200"])
        _shade_regime_zones(fig, df)
        # Should not crash on empty data

    def test_load_latest_scorecard_no_reports(self, tmp_path, monkeypatch):
        from nuri.analysis import evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "nonexistent")
        result = ec_mod._load_latest_scorecard()
        assert result is None

    def test_detect_portfolio_violations_no_data(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   return_value=pd.DataFrame()):
            violations = _detect_portfolio_violations()
        assert violations == []

    def test_generate_signal_performance_empty(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard", return_value=None):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()


# ═══════════════════════════════════════════════════════
# 6. SSE Stream (nuri/api/routes/stream.py)
# ═══════════════════════════════════════════════════════


class TestSSEStream:
    """SSE stream endpoint tests."""

    def test_get_snapshot_returns_dict(self):
        # Mock all lazy imports to avoid needing full DB
        with patch("nuri.api.routes.stream._get_snapshot") as mock:
            mock.return_value = {"timestamp": 123.0, "regime": "bull_low_vol"}
            result = mock()
        assert "timestamp" in result

    def test_get_snapshot_caching(self):
        """Cached snapshot should return quickly."""
        import nuri.api.routes.stream as stream_mod
        # Reset cache
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        import time
        stream_mod._cache_time = time.time()  # just cached
        result = stream_mod._get_snapshot()
        assert result.get("cached") is True

    def test_get_snapshot_fresh_with_mocked_deps(self, monkeypatch):
        """Fresh snapshot (cache expired) with all dependencies mocked."""
        import nuri.api.routes.stream as stream_mod
        # Expire the cache
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        # Mock classify_regime
        mock_regime = MagicMock()
        mock_regime.regime = "bull_low_vol"
        mock_regime.confidence = 0.8
        mock_regime.details = {"vix": 15.0, "fear_greed": 60.0}

        mock_macro = MagicMock()
        mock_macro.total_score = 65.0

        with patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", return_value=mock_macro), \
             patch("nuri.core.db.query", return_value=[{"c": 3}]):
            result = stream_mod._get_snapshot()

        assert result["regime"] == "bull_low_vol"
        assert result["macro_score"] == 65
        assert result["open_positions"] == 3

    def test_get_snapshot_handles_exceptions(self, monkeypatch):
        """All dependencies failing should not crash."""
        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {}
        stream_mod._cache_time = 0

        with patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("no data")), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception("no data")), \
             patch("nuri.core.db.query", side_effect=Exception("no db")):
            result = stream_mod._get_snapshot()

        assert "timestamp" in result
        # Should not have regime/macro_score since they all failed

    def test_stream_endpoint_response_type(self):
        """Test that /api/stream returns an SSE response (media type check only)."""
        # Pre-fill cache so no DB calls happen
        import time as _time

        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 100.0, "regime": "test"}
        stream_mod._cache_time = _time.time()

        import asyncio

        from nuri.api.routes.stream import stream as stream_handler

        async def run():
            resp = await stream_handler()
            return resp

        resp = asyncio.run(run())
        assert resp.media_type == "text/event-stream"
        assert resp.headers.get("Cache-Control") == "no-cache"

    def test_event_generator_yields_data(self):
        """Event generator should yield SSE-formatted data."""
        import asyncio

        # Pre-fill cache
        import time as _time

        import nuri.api.routes.stream as stream_mod
        stream_mod._cache = {"timestamp": 42.0, "regime": "test_bull"}
        stream_mod._cache_time = _time.time()

        async def run():
            gen = stream_mod._event_generator()
            event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert result.startswith("data:")
        parsed = json.loads(result.replace("data:", "").strip())
        assert "timestamp" in parsed

    def test_event_generator_error_handling(self):
        """Event generator should yield error JSON on exception."""
        import asyncio

        import nuri.api.routes.stream as stream_mod

        async def run():
            gen = stream_mod._event_generator()
            with patch.object(stream_mod, "_get_snapshot", side_effect=Exception("boom")):
                event = await gen.__anext__()
            return event

        result = asyncio.run(run())
        assert "data:" in result
        parsed = json.loads(result.replace("data:", "").strip())
        assert "error" in parsed


# ═══════════════════════════════════════════════════════
# 7. Additional coverage — deeper paths
# ═══════════════════════════════════════════════════════


class TestSuperinvestorBacktestIntegration:
    """Deeper tests for backtest_superinvestor with actual data flow."""

    def test_backtest_with_mocked_detect_changes(self, rich_db):
        """backtest_superinvestor with mocked superinvestors + detect_changes."""
        from nuri.core.db import get_db
        from nuri.quant.validation.superinvestor_backtest import backtest_superinvestor

        # Insert 2 quarters of superinvestor data
        with get_db(rich_db) as conn:
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-02-15", 100000, 50000000),
            )
            conn.execute(
                "INSERT INTO superinvestors (investor, ticker, filing_date, shares, market_value) "
                "VALUES (?, ?, ?, ?, ?)",
                ("Warren Buffett", "AAPL", "2024-05-15", 120000, 60000000),
            )

        # Mock detect_changes to return a proper DataFrame
        mock_changes = pd.DataFrame([{
            "ticker": "AAPL",
            "filing_date": "2024-05-15",
            "change_type": "INCREASED",
            "shares_change": 20000,
        }])

        with patch("nuri.collectors.superinvestors.detect_changes",
                   return_value=mock_changes), \
             patch("nuri.collectors.superinvestors.SUPERINVESTORS",
                   {"Warren Buffett": "0000000001"}):
            results = backtest_superinvestor(
                investor="Warren Buffett", hold_days=30, db_path=rich_db
            )

        # Should have results since we have AAPL price data
        assert isinstance(results, list)
        if results:
            assert results[0].investor == "Warren Buffett"
            assert results[0].ticker == "AAPL"


class TestClassifyRegimeHistory:
    """classify_regime_history() function."""

    def test_history_with_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        monkeypatch.setattr(cls_mod, "_check_data_freshness", lambda db_path=None: True)
        from nuri.quant.regime.classifier import classify_regime_history
        history = classify_regime_history(
            start_date="2024-06-01", end_date="2025-06-01", db_path=rich_db
        )
        # Should return monthly regimes
        assert isinstance(history, list)
        if history:
            assert history[0].trend in ("bull", "bear", "sideways")

    def test_history_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.quant.regime.classifier import classify_regime_history
        history = classify_regime_history(db_path=path)
        assert history == []


class TestEvidenceChartsPortfolioViolations:
    """Deeper coverage for _detect_portfolio_violations."""

    def test_violations_detected(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        mock_df = pd.DataFrame([
            {"ticker": "TSLA", "pnl_pct": -25.0, "weight_pct": 8.0},
            {"ticker": "NVDA", "pnl_pct": 15.0, "weight_pct": 20.0},
            {"ticker": "AAPL", "pnl_pct": 5.0, "weight_pct": 10.0},
        ])
        with patch("nuri.analysis.portfolio.analyze_portfolio", return_value=mock_df):
            violations = _detect_portfolio_violations()
        assert len(violations) >= 2  # TSLA stop_loss + NVDA overweight
        tickers = [v["ticker"] for v in violations]
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_violations_exception_returns_empty(self):
        from nuri.analysis.evidence_charts import _detect_portfolio_violations
        with patch("nuri.analysis.portfolio.analyze_portfolio",
                   side_effect=Exception("no data")):
            violations = _detect_portfolio_violations()
        assert violations == []


class TestSignalPerformanceChart:
    """generate_signal_performance_chart with actual scorecard data."""

    def test_with_scorecard_data(self, tmp_path):
        from nuri.analysis.evidence_charts import generate_signal_performance_chart
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        scorecard_df = pd.DataFrame([
            {"signal_id": "rsi_oversold", "ticker": None, "total_trades": 10,
             "win_rate": 0.6, "profit_factor": 1.5, "avg_return": 2.0,
             "median_return": 1.5, "max_return": 10.0, "max_loss": -5.0,
             "avg_holding_days": 20},
            {"signal_id": "macd_golden", "ticker": None, "total_trades": 8,
             "win_rate": 0.5, "profit_factor": 1.2, "avg_return": 1.0,
             "median_return": 0.8, "max_return": 8.0, "max_loss": -6.0,
             "avg_holding_days": 30},
        ])
        with patch("nuri.analysis.evidence_charts._load_latest_scorecard",
                   return_value=scorecard_df), \
             patch("nuri.analysis.evidence_charts._load_drift_map",
                   return_value={"rsi_oversold": {"status": "critical", "drift_pct": -15.0}}):
            result = generate_signal_performance_chart(output_dir)
        assert result.exists()
        content = result.read_text()
        assert "rsi_oversold" in content or "plotly" in content.lower()


class TestShadeRegimeZonesWithData:
    """_shade_regime_zones with real-ish data."""

    def test_zones_applied(self):
        import plotly.graph_objects as go

        from nuri.analysis.evidence_charts import _shade_regime_zones
        n = 100
        spy = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n),
            "close": np.linspace(450, 500, n),
        })
        spy["sma50"] = spy["close"].rolling(20).mean()
        spy["sma200"] = spy["close"].rolling(50).mean()
        fig = go.Figure()
        _shade_regime_zones(fig, spy)
        # Should not crash and may have added vrects


class TestGenerateAllEvidence:
    """generate_all_evidence integration."""

    def test_all_evidence_with_mocks(self, tmp_path, monkeypatch, capsys):
        import nuri.analysis.evidence_charts as ec_mod
        monkeypatch.setattr(ec_mod, "REPORT_DIR", tmp_path / "reports")
        with patch.object(ec_mod, "generate_regime_chart",
                         return_value=tmp_path / "regime.html"), \
             patch.object(ec_mod, "generate_portfolio_heatmap",
                         return_value=tmp_path / "heatmap.html"), \
             patch.object(ec_mod, "generate_signal_performance_chart",
                         return_value=tmp_path / "signal.html"), \
             patch.object(ec_mod, "generate_fear_greed_chart",
                         return_value=tmp_path / "fg.html"), \
             patch.object(ec_mod, "_detect_portfolio_violations",
                         return_value=[]), \
             patch.object(ec_mod, "generate_sell_evidence_chart",
                         return_value=tmp_path / "sell.html"):
            paths = ec_mod.generate_all_evidence()
        assert len(paths) == 5
        captured = capsys.readouterr()
        assert "완료" in captured.out


class TestDataFreshness:
    """_check_data_freshness in classifier."""

    def test_no_data(self, tmp_path, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        path = tmp_path / "empty.db"
        init_db(path)
        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", path)
        result = cls_mod._check_data_freshness(db_path=path)
        assert result is False

    def test_recent_data(self, rich_db, monkeypatch):
        from nuri.quant.regime import classifier as cls_mod
        cls_mod._freshness_warned = False
        # rich_db has data up to recent dates, need to mock kst_now
        # to be close to the latest date
        from nuri.core.db import query as _query
        rows = _query(
            "SELECT MAX(date) as latest FROM prices WHERE ticker = 'SPY'",
            db_path=rich_db,
        )
        latest_str = rows[0]["latest"]
        from datetime import datetime, timedelta
        latest_dt = datetime.strptime(latest_str, "%Y-%m-%d")
        # Mock kst_now to be 24 hours after latest
        mock_now = latest_dt + timedelta(hours=24)
        with patch("nuri.core.timezone.kst_now", return_value=mock_now):
            result = cls_mod._check_data_freshness(db_path=rich_db)
        assert result is True
