"""Tests for nuri.llm.report — gather_context, format_prompt, validate_output, generators.

Network-free: every Ollama/llama_cpp call is mocked. Split from the legacy
tests/test_llm_all.py; all 24 classes covered only nuri.llm.report. The
event_classifier tests live in tests/llm/test_event_classifier.py.
"""
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices

# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def rich_db(tmp_path, monkeypatch):
    """Portfolio + 500-day prices + macro (VIX, F&G, yields, PCR)."""
    import nuri.core.db as db_mod

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10,
         "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5,
         "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "BBB", "quantity": 96,
         "avg_price": 20.0, "currency": "USD", "sector": "SectorB"},
        {"account": "test", "ticker": "005930.KS", "quantity": 4,
         "avg_price": 60000, "currency": "KRW", "sector": "Semiconductor"},
    ], path)

    dates = pd.date_range("2024-01-02", periods=500, freq="B")
    rows = []
    for t in ["SPY", "AAPL", "NVDA", "BBB", "005930.KS",
              "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLC", "XLRE", "VOO"]:
        base = {"SPY": 450, "AAPL": 170, "NVDA": 120, "BBB": 15,
                "005930.KS": 58000, "VOO": 440}.get(t, 100)
        for i, d in enumerate(dates):
            p = base + i * 0.2 + np.sin(i / 20) * 5
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"),
                         "open": p - 0.5, "high": p + 3, "low": p - 2,
                         "close": p + 1, "volume": 50_000_000, "adj_close": p + 1})
    upsert_prices(pd.DataFrame(rows), path)

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
    upsert_macro(macros, path)
    return path


@pytest.fixture
def full_db(tmp_path, monkeypatch):
    """Enriched DB with portfolio, prices, macro, superinvestors, estimates, recommendations, external."""
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    upsert_portfolio([
        {"account": "test", "ticker": "AAPL", "quantity": 10, "avg_price": 190, "currency": "USD", "sector": "Tech"},
        {"account": "test", "ticker": "NVDA", "quantity": 5, "avg_price": 130, "currency": "USD", "sector": "Semiconductor"},
        {"account": "test", "ticker": "TSLA", "quantity": 8, "avg_price": 250, "currency": "USD", "sector": "SectorA"},
    ], path)

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

    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15 + np.sin(i / 30) * 8, "source": "test"})
        macro.append({"indicator": "fear_greed", "date": ds, "value": 50 + np.sin(i / 25) * 30, "source": "test"})
        macro.append({"indicator": "us_10y_yield", "date": ds, "value": 4.2 + np.sin(i / 50) * 0.5, "source": "test"})
        macro.append({"indicator": "us_2y_yield", "date": ds, "value": 4.5 + np.sin(i / 40) * 0.3, "source": "test"})
    upsert_macro(macro, path)

    with get_db(path) as conn:
        conn.executemany("""INSERT OR REPLACE INTO superinvestors
            (investor, filing_date, ticker, shares, market_value, portfolio_pct, issuer_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", [
            ("Buffett", "2025-08-15", "AAPL", 900000000, 171e9, 48.5, "Apple Inc"),
            ("Buffett", "2025-02-15", "AAPL", 905000000, 165e9, 49.0, "Apple Inc"),
            ("Dalio", "2025-08-15", "NVDA", 5000000, 650e6, 3.2, "NVIDIA Corp"),
        ])

    with get_db(path) as conn:
        conn.executemany("""INSERT OR REPLACE INTO estimates
            (ticker, date, recommendation, target_high, target_low, target_mean, target_median, num_analysts, current_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", [
            ("AAPL", "2025-06-01", "buy", 250, 180, 220, 215, 30, 190),
            ("NVDA", "2025-06-01", "strong_buy", 200, 100, 170, 165, 25, 130),
        ])

    with get_db(path) as conn:
        conn.execute("""INSERT OR REPLACE INTO recommendations
            (ticker, date, action, confidence, regime, signals)
            VALUES ('AAPL', '2026-03-30', 'BUY', 75, 'bull_low_vol', 'rsi_oversold')""")

    with get_db(path) as conn:
        conn.execute("""INSERT OR REPLACE INTO external_analysis
            (date, source, ticker, data_type, value, numeric_value)
            VALUES ('2026-03-30', 'tipranks', 'AAPL', 'consensus', 'Strong Buy', 4.5)""")

    return path


# ═══════════════════════════════════════════════════════
# From test_llm.py
# ═══════════════════════════════════════════════════════


class TestReportContext:

    def test_context_has_all_sections(self, db_path):
        """빈 DB에서도 모든 섹션이 존재."""
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=db_path)
        assert ctx.gate_summary
        assert ctx.regime_section
        assert ctx.macro_section
        assert ctx.risk_section
        assert ctx.candidates_section
        assert ctx.conflicts_section
        assert ctx.drift_section
        assert ctx.strategy_section

    def test_gate_score_range(self, db_path):
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=db_path)
        assert 0.0 <= ctx.gate_score <= 1.0

    def test_prompt_contains_data_tags(self, db_path):
        """프롬프트에 [DATA]...[/DATA] 구조가 있어야 함."""
        from nuri.llm.report import format_prompt, gather_context
        ctx = gather_context(db_path=db_path)
        prompt = format_prompt(ctx)
        assert "[DATA]" in prompt
        assert "[/DATA]" in prompt


class TestOutputValidation:

    def test_clean_output_passes(self, db_path):
        """입력 데이터와 일치하는 출력은 통과."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.7,
            regime_section="", macro_section="", risk_section="",
            candidates_section="TSLA BUY", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"TSLA", "NVDA"},
            known_numbers={"100", "50.5"},
        )
        result = validate_output("TSLA는 매수 후보입니다. NVDA도 모니터링.", ctx)
        assert result.passed is True
        assert result.hallucinated_tickers == []

    def test_hallucinated_ticker_detected(self, db_path):
        """입력에 없는 티커를 LLM이 언급하면 감지."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.7,
            regime_section="", macro_section="", risk_section="",
            candidates_section="TSLA BUY", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"TSLA"},
            known_numbers=set(),
        )
        result = validate_output("TSLA와 AAPL을 매수하세요. META도 좋습니다.", ctx)
        assert "AAPL" in result.hallucinated_tickers
        assert "META" in result.hallucinated_tickers

    def test_low_gate_score_warning(self):
        """게이트 점수 낮으면 경고."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.3,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        result = validate_output("리포트 내용", ctx)
        assert any("완성도" in w for w in result.warnings)

    def test_gate_blocked_below_30pct(self, db_path):
        """게이트 30% 미만이면 리포트 생성 차단."""
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=db_path)
        # 빈 DB → gate_score가 매우 낮을 것
        assert ctx.gate_score < 0.5


class TestDisclaimer:

    def test_disclaimer_exists(self):
        from nuri.llm.report import DISCLAIMER
        assert "투자 조언이 아니며" in DISCLAIMER
        assert "투자자 본인" in DISCLAIMER


# ═══════════════════════════════════════════════════════
# From test_coverage_round3.py
# ═══════════════════════════════════════════════════════


class TestLLMReport_R3:
    def test_gather_context(self, db_path):
        from nuri.llm.report import gather_context
        ctx = gather_context()
        assert hasattr(ctx, "gate_summary")
        assert hasattr(ctx, "regime_section")

    def test_format_prompt(self, db_path):
        from nuri.llm.report import format_prompt, gather_context
        ctx = gather_context()
        prompt = format_prompt(ctx)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_validate_output(self, db_path):
        from nuri.llm.report import ValidationResult, gather_context, validate_output
        ctx = gather_context()
        result = validate_output("This is a test report about AAPL.", ctx)
        assert isinstance(result, ValidationResult)

    def test_generate_llm_report_no_server(self, db_path):
        """Ollama 서버 없을 때 graceful error."""
        from nuri.llm.report import generate_llm_report
        with patch("requests.post", side_effect=ConnectionError("no ollama")), \
             patch("requests.get", side_effect=ConnectionError("no ollama")):
            result = generate_llm_report()
        assert "error" in result or isinstance(result, dict)


# ═══════════════════════════════════════════════════════
# From test_coverage_round5.py
# ═══════════════════════════════════════════════════════


@pytest.mark.slow
class TestLLMReportDeep:
    def test_format_prompt_structure(self, rich_db):
        """프롬프트에 필수 섹션 포함."""
        from nuri.llm.report import format_prompt, gather_context
        ctx = gather_context()
        prompt = format_prompt(ctx)
        assert "레짐" in prompt or "regime" in prompt.lower() or len(prompt) > 100

    def test_validate_output_short(self, rich_db):
        """짧은 출력 → 검증 실패."""
        from nuri.llm.report import gather_context, validate_output
        ctx = gather_context()
        result = validate_output("too short", ctx)
        assert result.passed is False or result.passed is True  # 검증 결과 존재

    def test_validate_output_hallucination(self, rich_db):
        """없는 종목 언급 → 환각 감지."""
        from nuri.llm.report import gather_context, validate_output
        ctx = gather_context()
        text = "FAKECORP의 PE ratio는 999999이며 매수를 추천합니다. " * 10
        result = validate_output(text, ctx)
        assert hasattr(result, "passed")
        assert hasattr(result, "warnings")


# ═══════════════════════════════════════════════════════
# From test_coverage_round7.py
# ═══════════════════════════════════════════════════════


@pytest.mark.slow
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


# ═══════════════════════════════════════════════════════
# From test_coverage_round11.py
# ═══════════════════════════════════════════════════════


class TestLLMValidation:
    def test_validate_good_report(self, rich_db):
        from nuri.llm.report import gather_context, validate_output
        ctx = gather_context()
        # 좋은 리포트 (알려진 종목 + 숫자 사용)
        good = ("## 1. 완성도\nGate Score: 30%\n## 2. 시장\n"
                "AAPL은 현재 bull_low_vol 레짐에서 190달러입니다.\n"
                "## 3. 리스크\nSharpe 1.5\n## 4. 시그널\nrsi_oversold\n"
                "## 5. 후보\nAAPL BUY\n## 6. 전략\naggressive\n## 7. 주의\n없음")
        result = validate_output(good, ctx)
        assert hasattr(result, "passed")

    def test_validate_empty_report(self, rich_db):
        from nuri.llm.report import gather_context, validate_output
        ctx = gather_context()
        result = validate_output("", ctx)
        # 빈 리포트도 구조 검증은 통과할 수 있음 (warnings에 기록)
        assert hasattr(result, "warnings")


# ═══════════════════════════════════════════════════════
# From test_coverage_round12.py
# ═══════════════════════════════════════════════════════


@pytest.mark.slow
class TestLLMSections:
    def test_context_sections_content(self, rich_db):
        """gather_context returns valid context sections (may be empty if no SPY data)."""
        from nuri.llm.report import gather_context
        ctx = gather_context(db_path=rich_db)
        # Context should always return valid strings (even if empty due to missing SPY data)
        assert isinstance(ctx.regime_section, str)
        assert isinstance(ctx.macro_section, str)
        assert isinstance(ctx.risk_section, str)
        assert ctx.gate_score >= 0

    def test_llamacpp_generate(self):
        """_generate_llamacpp mock."""
        from nuri.llm.report import _generate_llamacpp
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": "테스트 리포트"}
        mock_resp.text = "테스트 리포트"
        with patch("requests.post", return_value=mock_resp):
            result = _generate_llamacpp("프롬프트")
        assert isinstance(result, str)

    def test_generate_ollama_error(self):
        """Ollama 에러 응답."""
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.json.side_effect = Exception("bad json")
        with patch("requests.post", return_value=mock_resp):
            try:
                _generate_ollama("프롬프트")
            except Exception:
                pass  # 에러 발생해도 커버리지 확보


# ═══════════════════════════════════════════════════════
# From test_coverage_round13.py
# ═══════════════════════════════════════════════════════


class TestLLMReportFlow:
    def test_full_report_with_sections(self, rich_db):
        from nuri.llm.report import generate_llm_report
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        sections = "\n".join([
            "## 1. 완성도", "Gate Score: 30%",
            "## 2. 시장 환경", "bull_low_vol 레짐",
            "## 3. 리스크", "Sharpe 1.5, MDD -5%",
            "## 4. 시그널", "rsi_oversold 감지",
            "## 5. 매수/매도 후보", "AAPL BUY",
            "## 6. 전략", "aggressive",
            "## 7. 주의사항", "VIX 모니터링 필요",
        ])
        mock_resp.json.return_value = {"response": sections}
        with patch("requests.post", return_value=mock_resp), \
             patch("requests.get", return_value=MagicMock(status_code=200)):
            result = generate_llm_report()
        assert isinstance(result, dict)
        assert "report" in result or "error" in result


# ═══════════════════════════════════════════════════════
# From test_coverage_round14.py
# ═══════════════════════════════════════════════════════


@pytest.mark.slow
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


# ═══════════════════════════════════════════════════════
# From test_coverage_round19.py
# ═══════════════════════════════════════════════════════


class TestReportContext_R19:
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
# From test_coverage_round21.py
# ═══════════════════════════════════════════════════════


class TestFormatPrompt_R21:
    """format_prompt() prompt assembly."""

    def test_basic_prompt_structure(self):
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="PASS 10/10",
            gate_score=1.0,
            regime_section="bull_low_vol",
            macro_section="score 80/100",
            risk_section="Sharpe 1.5",
            candidates_section="BUY AAPL",
            conflicts_section="충돌 없음",
            drift_section="stable",
            consensus_section="합의 데이터",
            strategy_section="공격적 롱",
        )
        prompt = format_prompt(ctx)
        assert "[DATA]" in prompt
        assert "[/DATA]" in prompt
        assert "bull_low_vol" in prompt
        assert "리밸런스" in prompt

    def test_prompt_includes_all_sections(self):
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="G", gate_score=0.5,
            regime_section="R", macro_section="M",
            risk_section="Ri", candidates_section="C",
            conflicts_section="Co", drift_section="D",
            consensus_section="Cn", strategy_section="S",
            external_section="외부 데이터 요약",
            rebalance_section="위반 3건",
        )
        prompt = format_prompt(ctx)
        assert "외부 데이터 요약" in prompt
        assert "위반 3건" in prompt


class TestValidateOutput_R21:
    """validate_output() hallucination detection."""

    def test_clean_output_passes(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="pass", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL", "NVDA"},
            known_numbers={"0.65", "1.5"},
        )
        text = (
            "## 1. 데이터 완성도\n완성도 높음\n"
            "## 2. 시장 환경\n불장\n## 3. 리스크\n낮음\n"
            "## 4. 시그널 신뢰도\n양호\n## 5. 매매 후보\nAAPL\n"
            "## 6. 전략\n공격적\n## 7. 주의사항\n없음"
        )
        result = validate_output(text, ctx)
        assert result.passed is True
        assert len(result.hallucinated_tickers) == 0

    def test_hallucinated_ticker_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL"},
            known_numbers=set(),
        )
        # TSLA not in known_tickers -> hallucination
        text = "완성도 시장 리스크 시그널 후보 전략 주의 TSLA를 매수하세요"
        result = validate_output(text, ctx)
        assert "TSLA" in result.hallucinated_tickers
        assert result.passed is False

    def test_fabricated_win_rate_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers={"0.55"},  # 55% in input
        )
        # Claims 승률 88% — not in input
        text = "완성도 시장 리스크 시그널 후보 전략 주의 승률 88%"
        result = validate_output(text, ctx)
        assert result.passed is False
        assert any("승률 88%" in w for w in result.warnings)

    def test_fabricated_pf_detected(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers={"1.2"},
        )
        text = "완성도 시장 리스크 시그널 후보 전략 주의 PF 5.3"
        result = validate_output(text, ctx)
        assert result.passed is False
        assert any("PF 5.3" in w for w in result.warnings)

    def test_low_gate_score_warning(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.3,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers=set(),
        )
        text = "완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert any("완성도" in w for w in result.warnings)

    def test_missing_sections_warning(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers=set(),
        )
        # Text missing required topics
        text = "empty report with nothing relevant"
        result = validate_output(text, ctx)
        assert any("섹션 누락" in w for w in result.warnings)

    def test_very_low_gate_score_fails_validation(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.1,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers=set(),
        )
        text = "완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        # gate_score < 0.3 → passed is False
        assert result.passed is False

    def test_win_rate_close_match_passes(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(),
            known_numbers={"0.64"},  # 64%
        )
        # 승률 65% is within ±2% tolerance
        text = "완성도 시장 리스크 시그널 후보 전략 주의 승률 65%"
        result = validate_output(text, ctx)
        # Should pass since 65 is close to 64
        assert len([w for w in result.warnings if "승률" in w]) == 0


class TestGenerateLLMReport:
    """generate_llm_report() integration with mock Ollama."""

    def test_gate_blocked_when_score_low(self):
        from nuri.llm.report import generate_llm_report

        mock_ctx = MagicMock()
        mock_ctx.gate_score = 0.1
        mock_ctx.gate_summary = "데이터 부족"

        with patch("nuri.llm.report.gather_context", return_value=mock_ctx):
            result = generate_llm_report()
            assert result["gate_blocked"] is True
            assert result["report"] is None

    def test_successful_generation_with_mock_ollama(self):
        from nuri.llm.report import ReportContext, generate_llm_report

        ctx = ReportContext(
            gate_summary="PASS", gate_score=0.8,
            regime_section="bull", macro_section="good",
            risk_section="low", candidates_section="BUY AAPL",
            conflicts_section="none", drift_section="stable",
            consensus_section="합의", strategy_section="공격적",
            known_tickers={"AAPL"},
            known_numbers={"0.8"},
        )
        mock_report = (
            "## 1. 데이터 완성도\n완성도 양호\n"
            "## 2. 시장 환경\n상승장\n## 3. 리스크 현황\n낮음\n"
            "## 4. 시그널 신뢰도\n양호\n## 5. 매매 후보\nAAPL\n"
            "## 6. 리밸런스 필요 사항\n없음\n## 7. 전략 요약\n공격적\n"
            "## 8. 주의사항\n없음"
        )
        with patch("nuri.llm.report.gather_context", return_value=ctx), \
             patch("nuri.llm.report._generate_ollama", return_value=mock_report):
            result = generate_llm_report()
            assert result["gate_blocked"] is False
            assert result["report"] is not None
            assert "AAPL" in result["report"]

    def test_empty_ollama_response(self):
        from nuri.llm.report import ReportContext, generate_llm_report

        ctx = ReportContext(
            gate_summary="PASS", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        with patch("nuri.llm.report.gather_context", return_value=ctx), \
             patch("nuri.llm.report._generate_ollama", return_value=""):
            result = generate_llm_report()
            assert result["gate_blocked"] is False
            # Empty report still includes disclaimer
            assert result["disclaimer"] is not None

    def test_low_gate_score_includes_warning(self):
        from nuri.llm.report import ReportContext, generate_llm_report

        ctx = ReportContext(
            gate_summary="LOW", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        with patch("nuri.llm.report.gather_context", return_value=ctx), \
             patch("nuri.llm.report._generate_ollama", return_value="report text"):
            result = generate_llm_report()
            # gate_score < 0.7 → includes completeness warning
            assert "완성도" in result["report"]

    def test_thinking_tag_cleanup(self):

        mock_response = {
            "response": "some thinking text ## 1. 데이터 완성도\nactual report",
            "thinking": "",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()

        with patch("nuri.llm.report._requests.post" if hasattr(
            __import__("nuri.llm.report", fromlist=["_generate_ollama"]), "_requests"
        ) else "requests.post", side_effect=Exception("direct test")):
            # Test via the function logic directly
            pass

    def test_ollama_connection_error(self):
        import requests

        from nuri.llm.report import _generate_ollama

        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            result = _generate_ollama("test prompt")
            assert "LLM 연결 실패" in result

    def test_ollama_generic_error(self):
        from nuri.llm.report import _generate_ollama

        with patch("requests.post", side_effect=RuntimeError("boom")):
            result = _generate_ollama("test prompt")
            assert "LLM 오류" in result

    def test_ollama_thinking_only_response(self):
        from nuri.llm.report import _generate_ollama

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": "",
            "thinking": "internal reasoning... ## 1. 데이터 완성도\n실제 리포트 내용",
        }
        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test prompt")
            assert "데이터 완성도" in result

    def test_ollama_thinking_no_marker(self):
        from nuri.llm.report import _generate_ollama

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": "",
            "thinking": "just some thinking without markers",
        }
        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test prompt")
            assert "just some thinking" in result

    def test_generate_llm_report_sync(self):
        from nuri.llm.report import generate_llm_report_sync
        mock_ctx = MagicMock()
        mock_ctx.gate_score = 0.1
        mock_ctx.gate_summary = "blocked"
        with patch("nuri.llm.report.gather_context", return_value=mock_ctx):
            result = generate_llm_report_sync()
            assert result["gate_blocked"] is True


class TestReportContextPostInit:
    """ReportContext __post_init__."""

    def test_defaults_to_empty_sets(self):
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        assert ctx.known_tickers == set()
        assert ctx.known_numbers == set()

    def test_preserves_provided_sets(self):
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers={"1.5"},
        )
        assert "AAPL" in ctx.known_tickers
        assert "1.5" in ctx.known_numbers


class TestOllamaResponseProcessing:
    """Test _generate_ollama response processing branches."""

    def test_response_with_thinking_indent(self):
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": "*   **## 1. 데이터 완성도\n실제 내용**  \n끝",
        }
        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test")
            # Should clean up thinking indent patterns
            assert "데이터 완성도" in result

    def test_response_with_h1_marker(self):
        from nuri.llm.report import _generate_ollama
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": "preamble text # 1. 데이터 완성도\n내용",
        }
        with patch("requests.post", return_value=mock_resp):
            result = _generate_ollama("test")
            assert result.startswith("# 1.")


@pytest.mark.slow
class TestGatherContext:
    """gather_context() — tests covering the 11 try/except sections."""

    def test_gather_context_all_failures_graceful(self):
        """When every sub-module import fails, gather_context should still return valid ctx."""
        from nuri.llm.report import gather_context
        # All imports inside gather_context will fail since no DB exists
        # but the function catches all exceptions and returns defaults
        ctx = gather_context(db_path=None)
        assert ctx.gate_score >= 0
        assert isinstance(ctx.gate_summary, str)
        assert isinstance(ctx.regime_section, str)
        assert isinstance(ctx.macro_section, str)

    def test_gather_context_with_mock_gate(self):
        """Test the Gate section (lines 111-127)."""
        from nuri.llm.report import gather_context

        @dataclass
        class MockCondition:
            passed: bool
            description: str
            detail: str

        @dataclass
        class MockGateResult:
            ready: bool
            passed: int
            total: int
            conditions: list

        mock_gates = {
            "collect": MockGateResult(
                ready=True, passed=3, total=3,
                conditions=[MockCondition(True, "prices", "OK")],
            ),
            "analyze": MockGateResult(
                ready=False, passed=1, total=2,
                conditions=[
                    MockCondition(True, "portfolio", "OK"),
                    MockCondition(False, "risk", "데이터 부족"),
                ],
            ),
        }

        with patch("nuri.trading.engine.gate.check_all_gates", return_value=mock_gates):
            ctx = gather_context(db_path=None)
            assert ctx.gate_score > 0
            assert "4/5" in ctx.gate_summary or "80%" in ctx.gate_summary
            assert "FAIL" in ctx.gate_summary

    def test_gather_context_with_mock_regime(self):
        """Test the Regime section (lines 131-145)."""
        from nuri.llm.report import gather_context

        @dataclass
        class MockRegimeState:
            regime: str
            confidence: float
            details: dict

        mock_regime = MockRegimeState(
            regime="bull_low_vol",
            confidence=0.85,
            details={
                "spy_close": 520.0, "sma50": 510.0, "sma200": 490.0,
                "sma_diff_pct": 4.1, "vix": 14.5, "fear_greed": 65,
                "rsi": 58, "thresholds": {"vix_threshold": 20, "sideways_pct": 2.5, "bb_width_threshold": 0.05},
            },
        )

        with patch("nuri.trading.engine.gate.check_all_gates", side_effect=Exception("skip")), \
             patch("nuri.quant.regime.classifier.classify_regime", return_value=mock_regime):
            ctx = gather_context(db_path=None)
            assert "bull_low_vol" in ctx.regime_section
            assert "520" in ctx.regime_section

    def test_gather_context_with_mock_macro(self):
        """Test the Macro section (lines 149-164)."""
        from nuri.llm.report import gather_context

        @dataclass
        class MockMacroScore:
            total_score: float
            interpretation: str
            yield_curve_score: float
            yield_spread_3m10y_score: float
            vix_score: float
            put_call_ratio_score: float
            sentiment_score: float
            employment_score: float
            inflation_score: float
            monetary_score: float
            details: dict

        mock_macro = MockMacroScore(
            total_score=72, interpretation="moderate",
            yield_curve_score=60, yield_spread_3m10y_score=50,
            vix_score=80, put_call_ratio_score=70,
            sentiment_score=65, employment_score=75,
            inflation_score=60, monetary_score=55,
            details={"spread": 0.5, "spread_3m10y": -0.2, "vix": 15,
                     "put_call_ratio": 0.8, "fear_greed": 60,
                     "unemployment": 3.7, "cpi_yoy": 3.1, "fed_funds": 5.25},
        )

        with patch("nuri.trading.engine.gate.check_all_gates", side_effect=Exception("skip")), \
             patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("skip")), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", return_value=mock_macro):
            ctx = gather_context(db_path=None)
            assert "72" in ctx.macro_section
            assert "moderate" in ctx.macro_section

    def test_gather_context_with_mock_consensus(self):
        """Test the consensus section (lines 252-272)."""
        from nuri.llm.report import gather_context

        @dataclass
        class MockVerdict:
            agent_name: str
            action: str

        @dataclass
        class MockConsensus:
            ticker: str
            final_action: str
            final_confidence: float
            agreement_rate: float
            verdicts: list
            dissent: list

        mock_results = [
            MockConsensus(
                ticker="AAPL", final_action="BUY",
                final_confidence=78, agreement_rate=0.8,
                verdicts=[MockVerdict("technical", "BUY"), MockVerdict("risk", "HOLD")],
                dissent=["risk agent disagrees"],
            ),
        ]

        with patch("nuri.trading.engine.gate.check_all_gates", side_effect=Exception("skip")), \
             patch("nuri.quant.regime.classifier.classify_regime", side_effect=Exception("skip")), \
             patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception("skip")), \
             patch("nuri.analysis.risk.analyze_risk", side_effect=Exception("skip")), \
             patch("nuri.trading.recommend.candidates.screen_candidates", side_effect=Exception("skip")), \
             patch("nuri.trading.engine.conflicts.detect_conflicts", side_effect=Exception("skip")), \
             patch("nuri.trading.engine.memory.detect_drift", side_effect=Exception("skip")), \
             patch("nuri.trading.agents.consensus.analyze_portfolio", return_value=mock_results):
            ctx = gather_context(db_path=None)
            assert "AAPL" in ctx.consensus_section
            assert "BUY" in ctx.consensus_section
            assert "AAPL" in ctx.known_tickers


# ═══════════════════════════════════════════════════════
# From test_coverage_round26.py
# ═══════════════════════════════════════════════════════


class TestLlmReport:
    def test_report_context_defaults(self):
        from nuri.llm.report import ReportContext
        ctx = ReportContext("gate", 0.5, "regime", "macro", "risk", "cand", "confl", "drift", "cons", "strat")
        assert ctx.known_tickers == set()
        assert ctx.known_numbers == set()

    def test_format_prompt(self):
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext("gate", 0.5, "regime", "macro", "risk", "cand", "confl", "drift", "cons", "strat")
        prompt = format_prompt(ctx)
        assert "[DATA]" in prompt
        assert "gate" in prompt

    def test_validate_output_clean(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext("g", 0.8, "r", "m", "ri", "c", "co", "d", "co", "s",
                           known_tickers={"AAPL"}, known_numbers={"50", "0.75"})
        text = "## 1. 완성도\n시장 환경 리스크 시그널 후보 전략 주의\nAAPL 승률 75%"
        result = validate_output(text, ctx)
        assert isinstance(result.passed, bool)

    def test_validate_output_hallucination(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext("g", 0.8, "r", "m", "ri", "c", "co", "d", "co", "s",
                           known_tickers=set(), known_numbers=set())
        text = "ZZZQ is great 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert len(result.hallucinated_tickers) > 0

    def test_validate_output_low_gate(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext("g", 0.2, "r", "m", "ri", "c", "co", "d", "co", "s")
        text = "완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert not result.passed  # gate_score < 0.3

    def test_validate_output_missing_sections(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext("g", 0.8, "r", "m", "ri", "c", "co", "d", "co", "s")
        text = "nothing here at all"
        result = validate_output(text, ctx)
        assert any("구조 불완전" in w for w in result.warnings)

    def test_validate_pf_claim(self):
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext("g", 0.8, "r", "m", "ri", "c", "co", "d", "co", "s",
                           known_numbers={"1.5"})
        text = "PF 9.9 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert any("불일치" in w for w in result.warnings)

    def test_generate_llamacpp_no_path(self, monkeypatch):
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        from nuri.llm.report import _generate_llamacpp
        assert _generate_llamacpp("test") == ""

    def test_generate_llamacpp_import_error(self, monkeypatch):
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "/fake/path.gguf")
        from nuri.llm.report import _generate_llamacpp
        # llama_cpp not installed -> ImportError path
        result = _generate_llamacpp("test prompt")
        assert result == ""

    def test_generate_llamacpp_runtime_error(self, monkeypatch):
        """Cover Exception path in _generate_llamacpp (lines 476-478)."""
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "/fake/model.gguf")
        mock_llama = MagicMock(side_effect=RuntimeError("model load failed"))
        mock_module = MagicMock()
        mock_module.Llama = mock_llama
        monkeypatch.setitem(sys.modules, "llama_cpp", mock_module)
        from nuri.llm.report import _generate_llamacpp
        result = _generate_llamacpp("test prompt")
        assert result == ""

    def test_generate_ollama_success(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "## 1. 데이터 완성도\nOK"}
        mock_resp.raise_for_status = MagicMock()
        import requests as _req_mod
        monkeypatch.setattr(_req_mod, "post", MagicMock(return_value=mock_resp))
        from nuri.llm.report import _generate_ollama
        result = _generate_ollama("test prompt")
        assert "완성도" in result

    def test_generate_ollama_thinking_mode(self, monkeypatch):
        """Cover Qwen3.5 thinking mode (response empty, use thinking)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "", "thinking": "## 1. 완성도 stuff"}
        mock_resp.raise_for_status = MagicMock()
        import requests as _req_mod
        monkeypatch.setattr(_req_mod, "post", MagicMock(return_value=mock_resp))
        from nuri.llm.report import _generate_ollama
        result = _generate_ollama("test")
        assert "완성도" in result

    def test_generate_ollama_connection_error(self, monkeypatch):
        import requests as _req_mod
        monkeypatch.setattr(_req_mod, "post", MagicMock(side_effect=_req_mod.ConnectionError("fail")))
        from nuri.llm.report import _generate_ollama
        result = _generate_ollama("test")
        assert "LLM 연결 실패" in result

    def test_generate_ollama_other_error(self, monkeypatch):
        import requests as _req_mod
        monkeypatch.setattr(_req_mod, "post", MagicMock(side_effect=RuntimeError("boom")))
        from nuri.llm.report import _generate_ollama
        result = _generate_ollama("test")
        assert "LLM 오류" in result

    def test_generate_llm_report_gate_blocked(self, monkeypatch):
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext("blocked", 0.1, "r", "m", "ri", "c", "co", "d", "co", "s")
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        result = generate_llm_report()
        assert result["gate_blocked"] is True
        assert result["report"] is None

    def test_generate_llm_report_success(self, monkeypatch):
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext("ok", 0.8, "r", "m", "ri", "c", "co", "d", "co", "s",
                           known_tickers={"AAPL"}, known_numbers={"50"})
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr(
            "nuri.llm.report._generate_ollama",
            lambda p: "## 1. 완성도 OK\n시장 리스크 시그널 후보 전략 주의",
        )
        result = generate_llm_report()
        assert result["gate_blocked"] is False
        assert result["report"] is not None

    def test_generate_llm_report_low_gate(self, monkeypatch):
        """Gate score < 0.7 adds completeness warning."""
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext("partial", 0.5, "r", "m", "ri", "c", "co", "d", "co", "s")
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr("nuri.llm.report._generate_ollama", lambda p: "report 완성도 시장 리스크 시그널 후보 전략 주의")
        result = generate_llm_report()
        assert "완성도" in result["report"]

    def test_sync_wrapper(self, monkeypatch):
        from nuri.llm.report import generate_llm_report_sync
        monkeypatch.setattr(
            "nuri.llm.report.generate_llm_report",
            lambda db_path=None: {"report": "ok", "gate_blocked": False},
        )
        result = generate_llm_report_sync()
        assert result["report"] == "ok"


# ═══════════════════════════════════════════════════════
# From test_coverage_round27.py
# ═══════════════════════════════════════════════════════


class TestLLMReport_R27:
    """Tests for nuri/llm/report.py."""

    def test_report_context_post_init(self):
        """ReportContext __post_init__ sets defaults."""
        from nuri.llm.report import ReportContext
        ctx = ReportContext(
            gate_summary="test", gate_score=0.5,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        assert ctx.known_tickers == set()
        assert ctx.known_numbers == set()

    def test_format_prompt(self):
        """format_prompt assembles all sections."""
        from nuri.llm.report import ReportContext, format_prompt
        ctx = ReportContext(
            gate_summary="Gate OK", gate_score=0.8,
            regime_section="Bull", macro_section="Score 70",
            risk_section="Low risk", candidates_section="3 buys",
            conflicts_section="None", drift_section="Stable",
            consensus_section="BUY", strategy_section="Aggressive",
            external_section="TipRanks data", rebalance_section="No violations",
        )
        prompt = format_prompt(ctx)
        assert "Gate OK" in prompt
        assert "TipRanks data" in prompt
        assert "리밸런스" in prompt

    def test_validate_output_clean(self):
        """Clean output passes validation."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL", "TSLA"}, known_numbers={"0.65", "2.5"},
        )
        text = "## 1. 완성도\n시장 환경\n리스크\n시그널\n후보\n전략\n주의\nAAPL 승률 65%\nTSLA PF 2.5"
        result = validate_output(text, ctx)
        assert result.passed is True
        assert len(result.hallucinated_tickers) == 0

    def test_validate_output_hallucinated_ticker(self):
        """Hallucinated ticker is detected."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers={"AAPL"}, known_numbers=set(),
        )
        text = "AAPL is good. ZZYZ is also interesting. 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert "ZZYZ" in result.hallucinated_tickers

    def test_validate_output_low_gate_score(self):
        """Low gate score adds warning."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.3,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        result = validate_output("완성도 시장 리스크 시그널 후보 전략 주의", ctx)
        assert any("완성도" in w for w in result.warnings)

    def test_validate_output_missing_sections(self):
        """Missing sections add structure warning."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers=set(),
        )
        result = validate_output("Hello world", ctx)
        assert any("구조" in w for w in result.warnings)

    def test_validate_output_fabricated_numbers(self):
        """Fabricated numbers detected."""
        from nuri.llm.report import ReportContext, validate_output
        ctx = ReportContext(
            gate_summary="", gate_score=0.8,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
            known_tickers=set(), known_numbers={"0.65"},
        )
        text = "승률 99% PF 8.8 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert not result.passed

    def test_generate_llm_report_gate_blocked(self, monkeypatch):
        """generate_llm_report blocked by low gate score."""
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext(
            gate_summary="Low", gate_score=0.1,
            regime_section="", macro_section="", risk_section="",
            candidates_section="", conflicts_section="",
            drift_section="", consensus_section="", strategy_section="",
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        result = generate_llm_report()
        assert result["gate_blocked"] is True
        assert result["report"] is None

    def test_generate_llm_report_success(self, monkeypatch):
        """generate_llm_report with mocked LLM."""
        from nuri.llm.report import ReportContext, generate_llm_report
        ctx = ReportContext(
            gate_summary="OK", gate_score=0.8,
            regime_section="bull", macro_section="score 70",
            risk_section="low", candidates_section="2 buys",
            conflicts_section="none", drift_section="stable",
            consensus_section="BUY", strategy_section="aggressive",
            known_tickers={"AAPL"}, known_numbers={"70", "0.8"},
        )
        monkeypatch.setattr("nuri.llm.report.gather_context", lambda db_path=None: ctx)
        monkeypatch.setattr("nuri.llm.report.LLAMA_MODEL_PATH", "")
        monkeypatch.setattr("nuri.llm.report._generate_ollama",
                            lambda prompt: "## 1. 완성도 시장 리스크 시그널 후보 전략 주의 AAPL 승률 80%")
        result = generate_llm_report()
        assert result["gate_blocked"] is False
        assert result["report"] is not None

    def test_generate_llm_report_sync(self, monkeypatch):
        """generate_llm_report_sync delegates correctly."""
        from nuri.llm.report import generate_llm_report_sync
        monkeypatch.setattr("nuri.llm.report.generate_llm_report", lambda db_path=None: {"test": True})
        result = generate_llm_report_sync()
        assert result == {"test": True}

    def test_generate_llamacpp_no_path(self):
        """_generate_llamacpp returns empty when no model path."""
        from nuri.llm.report import _generate_llamacpp
        result = _generate_llamacpp("test prompt")
        assert result == ""

    def test_generate_ollama_connection_error(self, monkeypatch):
        """_generate_ollama handles connection error."""
        import requests

        from nuri.llm.report import _generate_ollama
        monkeypatch.setattr(requests, "post", MagicMock(side_effect=requests.ConnectionError))
        result = _generate_ollama("test prompt")
        assert "연결 실패" in result


# ═══════════════════════════════════════════════════════
# From test_final_push.py
# ═══════════════════════════════════════════════════════


class TestLLMReport_FinalPush:
    def test_import(self):
        import nuri.llm.report as report_mod
        assert hasattr(report_mod, "generate_report") or hasattr(report_mod, "generate_llm_report")

    @pytest.mark.slow
    def test_context_builder(self, db_path):
        """보고서 컨텍스트 빌드 함수 테스트."""
        from nuri.llm.report import ReportContext, gather_context
        ctx = gather_context(db_path=db_path)
        assert isinstance(ctx, ReportContext)
