"""LLM 리포트 생성기 테스트 — 컨텍스트 완성도 + 환각 검증."""
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


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
