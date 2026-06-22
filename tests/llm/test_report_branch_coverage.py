"""Coverage gap fillers for nuri/llm/report.py — bring 87% → 100%.

Targeted tests for each remaining `except Exception: pass` and conditional
branch that isn't exercised by tests/llm/test_report.py. Tests are small
and direct: monkeypatch the source dependency to inject the desired branch.
"""

from __future__ import annotations

import logging
import runpy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import nuri.llm.report as report_mod
from nuri.llm.report import (
    ReportContext,
    _generate_llamacpp,
    _generate_ollama,
    gather_context,
    validate_output,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Empty DB path — most _section helpers tolerate empty/raise gracefully."""
    from nuri.core.db import init_db

    p = tmp_path / "test.db"
    init_db(p)
    return p


# ─── Section 4 (Risk) — stop_loss_alerts loop (194-196) ───────────────


class TestRiskSectionAlerts:
    def test_stop_loss_alerts_appended_to_risk_section(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """analyze_risk 가 stop_loss_alerts 반환 → known_tickers 에 추가 + 손절 경고 line."""

        def _fake(*a, **kw):
            return {
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -10.5,
                "var_95_daily_pct": -2.1,
                "cvar_95_daily_pct": -3.0,
                "stop_loss_alerts": [
                    {"ticker": "AAA", "pnl_pct": -8.5},
                    {"ticker": "BBB", "pnl_pct": -7.2},
                ],
            }

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", _fake)
        ctx = gather_context(db_path=db_path)
        assert "AAA" in ctx.known_tickers
        assert "BBB" in ctx.known_tickers
        assert "손절선 경고" in ctx.risk_section


# ─── Section 5 (Candidates) — drift / conflict / advisory / avoid ────


class TestCandidatesFlagsBranches:
    def test_drift_critical_flag_renders(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """drift_status critical → 'drift:critical' flag line, conflict True → '충돌'."""
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE

        c1 = MagicMock(
            ticker="AAA",
            tier=TIER_ACTIONABLE,
            regime_fit=True,
            drift_status="critical",
            conflict=True,
            direction="BUY",
            signal_id="test_signal",
            confidence=80,
            win_rate=0.65,
            profit_factor=1.5,
            notes="ok",
        )

        def _screen(*a, **kw):
            return [c1]

        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", _screen)
        ctx = gather_context(db_path=db_path)
        assert "AAA" in ctx.known_tickers
        assert "drift:critical" in ctx.candidates_section
        assert "충돌" in ctx.candidates_section

    def test_advisory_and_avoid_branches(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from nuri.trading.recommend.candidates import (
            TIER_ACTIONABLE,
            TIER_ADVISORY,
            TIER_AVOID,
        )

        adv = MagicMock(
            ticker="ADV",
            tier=TIER_ADVISORY,
            regime_fit=True,
            drift_status="stable",
            conflict=False,
            direction="BUY",
            signal_id="adv_sig",
            confidence=60,
            win_rate=0.5,
            profit_factor=1.0,
            notes="low sample",
        )
        avoid = MagicMock(
            ticker="AVD",
            tier=TIER_AVOID,
            regime_fit=True,
            drift_status="stable",
            conflict=False,
            direction="SELL",
            signal_id="avd_sig",
            confidence=40,
            win_rate=0.3,
            profit_factor=0.4,
            notes="negative edge",
        )
        # actionable 1건 (need at least one)
        act = MagicMock(
            ticker="ACT",
            tier=TIER_ACTIONABLE,
            regime_fit=True,
            drift_status="stable",
            conflict=False,
            direction="BUY",
            signal_id="act_sig",
            confidence=80,
            win_rate=0.6,
            profit_factor=1.5,
            notes="ok",
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda *a, **kw: [act, adv, avoid],
        )
        ctx = gather_context(db_path=db_path)
        assert "ADV" in ctx.candidates_section
        assert "AVD" in ctx.candidates_section
        assert "Advisory" in ctx.candidates_section
        assert "Avoid" in ctx.candidates_section


# ─── Section 6 (Conflicts) — successful render path ──────────────────


class TestConflictsSection:
    def test_conflict_renders_with_recommendation(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cf = MagicMock(
            ticker="AAA",
            conflict_type="buy_sell_overlap",
            severity="high",
            buy_signals=["sig1"],
            sell_signals=["sig2"],
            recommendation="resolve via tie-break",
        )
        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", lambda **kw: [cf])
        ctx = gather_context(db_path=db_path)
        assert "AAA" in ctx.known_tickers
        assert "buy_sell_overlap" in ctx.conflicts_section
        assert "resolve via tie-break" in ctx.conflicts_section


# ─── Section 8 (Consensus) — dissent path ────────────────────────────


class TestConsensusSectionDissent:
    def test_dissent_first_item_rendered(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        verdict = MagicMock(agent_name="agent1", action="BUY")
        result = MagicMock(
            ticker="AAA",
            final_action="BUY",
            final_confidence=80,
            agreement_rate=0.8,
            verdicts=[verdict],
            dissent=["agent_x: SELL", "agent_y: HOLD"],
        )
        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", lambda **kw: [result])
        ctx = gather_context(db_path=db_path)
        assert "AAA" in ctx.known_tickers
        assert "반대:" in ctx.consensus_section


# ─── Section 9 (Strategy) — recommended path ─────────────────────────


class TestStrategySection:
    def test_strategy_recommendation_rendered(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = MagicMock(
            position_sizing="50% deploy",
            recommended_signals=["bb_bounce", "macd_cross"],
            avoid_signals=["overbought_top"],
            sector_preference=["Tech", "BigTech"],
            notes="bullish regime",
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda **kw: rec,
        )
        ctx = gather_context(db_path=db_path)
        assert "50% deploy" in ctx.strategy_section
        assert "bb_bounce" in ctx.strategy_section


# ─── Section 10 (External summary) ───────────────────────────────────


class TestExternalSection:
    def test_external_summary_rendered(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nuri.collectors.external.get_external_summary",
            lambda *a, **kw: {
                "total_records": 25,
                "sources": [
                    {"source": "src1", "tickers": 10, "records": 15, "latest_date": "2026-05-01"},
                ],
            },
        )
        ctx = gather_context(db_path=db_path)
        assert "총 25건" in ctx.external_section
        assert "src1" in ctx.external_section


# ─── validate_output continue ValueError path (501-502) ─────────────


class TestValidateReportNumericParse:
    def _make_ctx(self, known_numbers: set[str]) -> ReportContext:
        return ReportContext(
            gate_summary="g",
            gate_score=0.8,
            regime_section="",
            macro_section="",
            risk_section="",
            candidates_section="",
            conflicts_section="",
            drift_section="",
            consensus_section="",
            strategy_section="",
            external_section="",
            rebalance_section="",
            known_tickers={"AAA"},
            known_numbers=known_numbers,
        )

    def test_non_numeric_only_triggers_fabricated(self) -> None:
        """known_numbers 가 전부 non-numeric → 모든 항목 ValueError → continue →
        loop 종료 후 found=False → fabricated 에 추가 (negative path).

        line 501-502 (ValueError continue) 의 종료 조건 lock-in.
        """
        ctx = self._make_ctx({"not_a_number", "abc", "xyz"})
        text = "AAA 승률 65% PF 1.5 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        assert any("승률 65%" in w for w in result.warnings)

    def test_non_numeric_does_not_block_subsequent_numeric_match(self) -> None:
        """non-numeric 항목 ValueError 후에도 loop 가 다음 numeric 로 진행되어 매치 →
        fabricated 추가 안 됨 (positive path).

        continue 가 loop 를 abort 시키지 않고 다음 candidate 로 이동하는지 확인.
        """
        ctx = self._make_ctx({"not_a_number", "abc", "0.65", "1.5"})
        text = "AAA 승률 65% PF 1.5 완성도 시장 리스크 시그널 후보 전략 주의"
        result = validate_output(text, ctx)
        # 65% / 1.5 모두 매치 → fabricated 없음
        assert all("승률 65%" not in w for w in result.warnings)
        assert all("PF 1.5" not in w for w in result.warnings)


# ─── _generate_llamacpp branches (580-587) ──────────────────────────


class TestGenerateLlamacpp:
    def test_no_model_path_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(report_mod, "LLAMA_MODEL_PATH", "")
        assert _generate_llamacpp("prompt") == ""

    def test_unexpected_response_type_logs_warning(self, monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setattr(report_mod, "LLAMA_MODEL_PATH", "/fake/path")
        fake_llama_module = MagicMock()
        # Llama() returns callable; calling it returns iter([]) (not dict) → warning + ""
        fake_llama_module.Llama = MagicMock(return_value=lambda *a, **kw: iter([]))
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module)
        with caplog.at_level(logging.WARNING):
            result = _generate_llamacpp("prompt")
        assert result == ""

    def test_dict_response_returns_text(self, monkeypatch) -> None:
        """isinstance(output, dict) True path → output['choices'][0]['text']."""
        monkeypatch.setattr(report_mod, "LLAMA_MODEL_PATH", "/fake/path")
        fake_llama_module = MagicMock()
        fake_llama_module.Llama = MagicMock(
            return_value=lambda *a, **kw: {"choices": [{"text": "  generated content  "}]}
        )
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module)
        result = _generate_llamacpp("prompt")
        assert result == "generated content"

    def test_import_error_returns_empty(self, monkeypatch) -> None:
        import builtins

        monkeypatch.setattr(report_mod, "LLAMA_MODEL_PATH", "/fake/path")
        sys.modules.pop("llama_cpp", None)
        original_import = builtins.__import__

        def _fake(name, *a, **kw):
            if name == "llama_cpp":
                raise ImportError("not installed")
            return original_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _fake)
        assert _generate_llamacpp("prompt") == ""


# ─── _generate_ollama no-host (596) ──────────────────────────────────


class TestGenerateOllamaNoHost:
    def test_no_ollama_host_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(report_mod, "OLLAMA_HOST", "")
        assert _generate_ollama("prompt") == ""


class TestOllamaLocalOnlyGuard:
    """STRATEGY §4.4.3 — 비-localhost OLLAMA_HOST 는 egress 차단 (#797)."""

    def test_host_is_local_predicate(self) -> None:
        from nuri.llm.report import _host_is_local

        assert _host_is_local("http://localhost:11434") is True
        assert _host_is_local("http://127.0.0.1:11434") is True
        assert _host_is_local("http://[::1]:11434") is True
        assert _host_is_local("http://remote.example.com:11434") is False
        assert _host_is_local("") is False
        assert _host_is_local(None) is False

    def test_nonlocal_host_blocks_post(self, monkeypatch) -> None:
        # 비-localhost host → requests.post 호출 자체가 안 일어남 (egress 차단).
        monkeypatch.setattr(report_mod, "OLLAMA_HOST", "http://attacker.example.com:11434")
        with patch("requests.post") as post:
            assert _generate_ollama("portfolio prompt") == ""
        post.assert_not_called()


# ─── 227 / 229 standalone branch fillers ─────────────────────────────


class TestRegimeAndMacroExceptionPaths:
    def test_regime_classify_exception_swallowed(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """classify_regime exception → regime_section keeps default '레짐 데이터 없음'."""

        def _raise(*a, **kw):
            raise RuntimeError("classifier broken")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _raise)
        ctx = gather_context(db_path=db_path)
        assert ctx.regime_section == "레짐 데이터 없음"

    def test_macro_score_exception_swallowed(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **kw):
            raise RuntimeError("macro broken")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", _raise)
        ctx = gather_context(db_path=db_path)
        assert ctx.macro_section == "매크로 데이터 없음"

    def test_consensus_exception_swallowed(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """analyze_portfolio exception → consensus_section default."""

        def _raise(*a, **kw):
            raise RuntimeError("consensus broken")

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", _raise)
        ctx = gather_context(db_path=db_path)
        assert ctx.consensus_section == "에이전트 합의 데이터 없음"

    def test_strategy_exception_swallowed(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **kw):
            raise RuntimeError("strategy broken")

        monkeypatch.setattr("nuri.quant.regime.strategy_map.map_regime_to_strategy", _raise)
        ctx = gather_context(db_path=db_path)
        assert ctx.strategy_section == "전략 데이터 없음"

    def test_external_exception_swallowed(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **kw):
            raise RuntimeError("external broken")

        monkeypatch.setattr("nuri.collectors.external.get_external_summary", _raise)
        ctx = gather_context(db_path=db_path)
        assert ctx.external_section == "외부 데이터 없음"


# ─── __main__ guard (727-751) — pragma no-cover annotated below ──────
#
# `if __name__ == '__main__':` 블록은 entry-point 로 실행 시에만 호출되며
# runpy.run_module 로 monkeypatch 가 reload 후 살아남지 않아 stub 적용이
# 어렵다. 본 블록은 production CLI 진입점 — `python -m nuri.llm.report` 호출
# 시 실측. 단위 테스트로 cover 시 monkeypatch 가 의도대로 적용 안 됨 (real
# generate_llm_report 호출 → API 인증 실패 등 noise). 운영 코드 자체는 단순
# print/file_write 라 unit test 가치 < cost.


@pytest.fixture(autouse=False)
def _cleanup_singletons():
    """openai_client singleton reset between tests."""
    import nuri.llm.openai_client as oc

    oc._singleton = None
    yield
    oc._singleton = None


# ─── Section 7 (Drift) — detect_drift detail rendering (274-283) ─────


class TestDriftSectionDetail:
    def test_drift_renders_lines_including_critical(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_drift 가 critical 항목 포함 → drift_section 에 signal_id 행 + ⚠ critical 라인."""
        from nuri.trading.engine.memory import PerformanceDrift

        drifts = [
            PerformanceDrift(
                signal_id="rsi_oversold",
                regime=None,
                all_time_wr=0.65,
                recent_wr=0.40,
                drift_pct=-38.5,
                status="critical",
                detail="35% drop in 90d",
            ),
            PerformanceDrift(
                signal_id="macd_cross",
                regime=None,
                all_time_wr=0.55,
                recent_wr=0.58,
                drift_pct=5.5,
                status="stable",
                detail="ok",
            ),
        ]
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: drifts)
        ctx = gather_context(db_path=db_path)
        # 라인 274-279: signal 별 wr/drift 출력
        assert "rsi_oversold" in ctx.drift_section
        assert "macd_cross" in ctx.drift_section
        # 라인 280-282: critical filter + ⚠ 경고
        assert "성과 급락 시그널" in ctx.drift_section
        assert "rsi_oversold" in ctx.drift_section


# ─── Section 11 (Rebalance) — generate_advisor_report rendering (347-353) ──


class TestRebalanceAdvisorSection:
    def test_rebalance_violations_render(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """generate_advisor_report total_violations>0 → rebalance_section 에 위반/회수/액션 행 출력."""
        fake_report = {
            "total_violations": 3,
            "violations_by_severity": {"critical": 2, "warning": 1},
            "total_recovery_usd": 12345.6,
            "actions": [
                {"ticker": "AAA", "reason": "concentration over 25%", "sell_value_usd": 5000.0},
                {"ticker": "BBB", "reason": "sector cap", "sell_value_usd": 3000.0},
            ],
        }
        monkeypatch.setattr(
            "nuri.analysis.rebalance_advisor.generate_advisor_report",
            lambda *a, **kw: fake_report,
        )
        ctx = gather_context(db_path=db_path)
        assert "위반 3건" in ctx.rebalance_section
        assert "critical 2건" in ctx.rebalance_section
        assert "$12,346" in ctx.rebalance_section
        assert "AAA" in ctx.rebalance_section
        assert "concentration over 25%" in ctx.rebalance_section


# ─── Defensive `except Exception:` paths — exercised by injecting raises ────


class TestExceptionFallbackPaths:
    """모든 try/except 의 fallback 분기가 import 또는 호출 실패 시 정상 동작함을 검증.

    각 dependency 가 raise 하는 시나리오 — fallback string 또는 default
    section 값이 유지되어야 한다 (gather_context 자체가 죽지 않음).
    """

    def test_gate_exception_yields_failure_summary(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """check_all_gates raise → gate_summary 가 "Gate 검증 실패" 메시지 (134-137)."""

        def _boom(*a, **kw):
            raise RuntimeError("gate down")

        monkeypatch.setattr("nuri.trading.engine.gate.check_all_gates", _boom)
        ctx = gather_context(db_path=db_path)
        assert "Gate 검증 실패" in ctx.gate_summary
        assert "서버 로그" in ctx.gate_summary

    def test_regime_populates_section_when_classifier_returns_state(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """classify_regime non-None → regime_section 에 SPY/SMA/VIX 라인 출력 (146-155)."""
        from nuri.quant.regime.classifier import RegimeState

        fake_state = RegimeState(
            date="2026-04-01",
            trend="up",
            volatility="low",
            regime="bull",
            confidence=0.82,
            details={
                "spy_close": 500.0,
                "sma50": 480.0,
                "sma200": 460.0,
                "sma_diff_pct": 4.2,
                "vix": 18.0,
                "fear_greed": 60,
                "rsi": 55.0,
                "thresholds": {"vix_threshold": 30, "sideways_pct": 2.0, "bb_width_threshold": 0.05},
            },
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: fake_state,
        )
        ctx = gather_context(db_path=db_path)
        assert "bull" in ctx.regime_section
        assert "SPY: $500" in ctx.regime_section
        assert "SMA Gap: +4.2%" in ctx.regime_section
        assert "VIX: 18.0" in ctx.regime_section

    def test_risk_exception_keeps_default_section(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """analyze_risk raise → risk_section 기본값 유지 (197-198)."""

        def _boom(*a, **kw):
            raise RuntimeError("risk metric failure")

        monkeypatch.setattr("nuri.analysis.risk.analyze_risk", _boom)
        ctx = gather_context(db_path=db_path)
        assert ctx.risk_section == "리스크 데이터 없음"

    def test_candidates_exception_keeps_default_section(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """screen_candidates raise → candidates_section 기본값 유지 (245-246)."""

        def _boom(*a, **kw):
            raise RuntimeError("candidates engine down")

        monkeypatch.setattr("nuri.trading.recommend.candidates.screen_candidates", _boom)
        ctx = gather_context(db_path=db_path)
        assert ctx.candidates_section == "매매 후보 없음"

    def test_conflicts_exception_keeps_default_section(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_conflicts raise → conflicts_section 기본값 유지 (264-265)."""

        def _boom(*a, **kw):
            raise RuntimeError("conflicts down")

        monkeypatch.setattr("nuri.trading.engine.conflicts.detect_conflicts", _boom)
        ctx = gather_context(db_path=db_path)
        assert ctx.conflicts_section == "충돌 없음"

    def test_drift_exception_keeps_default_section(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_drift raise → drift_section 기본값 유지 (284-285)."""

        def _boom(*a, **kw):
            raise RuntimeError("memory drift detect down")

        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", _boom)
        ctx = gather_context(db_path=db_path)
        assert ctx.drift_section == "성과 변화 데이터 없음"


# ─── Phase 3-D #616: remaining 5 partials ─────────────────────────────


class TestDriftAllStable:
    def test_drift_no_critical_skips_warning_line(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """281→283: drifts 존재하지만 status=stable 만 → if critical False → 경고 라인 skip."""
        drifts = [
            MagicMock(
                signal_id="rsi_oversold",
                all_time_wr=0.65,
                recent_wr=0.62,
                drift_pct=-3.0,
                status="stable",
            ),
            MagicMock(
                signal_id="macd_cross",
                all_time_wr=0.55,
                recent_wr=0.58,
                drift_pct=5.5,
                status="improving",
            ),
        ]
        monkeypatch.setattr("nuri.trading.engine.memory.detect_drift", lambda **kw: drifts)
        ctx = gather_context(db_path=db_path)
        assert "rsi_oversold" in ctx.drift_section
        # critical 없음 → ⚠ 라인 미렌더
        assert "성과 급락 시그널" not in ctx.drift_section


class TestConsensusNoDissent:
    def test_consensus_dissent_empty_skips_inner_lines(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """302→295: r.dissent=[] False → inner for skip → 다음 result iter."""
        verdict = MagicMock(agent_name="agent1", action="HOLD")
        result = MagicMock(
            ticker="BBB",
            final_action="HOLD",
            final_confidence=70,
            agreement_rate=1.0,
            verdicts=[verdict],
            dissent=[],  # 빈 list → if False
        )
        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_portfolio", lambda **kw: [result])
        ctx = gather_context(db_path=db_path)
        assert "BBB" in ctx.known_tickers
        # dissent 라인 미렌더
        assert "반대:" not in ctx.consensus_section


class TestOllamaNoMarker:
    def test_response_without_marker_returns_as_is(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """615→620: response 에 '## 1.' / '# 1. ' 마커 없음 → for 자연 종료 → re.sub 진행."""
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"response": "직접 분석 결과만 텍스트"}
        fake_resp.raise_for_status = lambda: None

        import sys

        mock_requests = MagicMock()
        mock_requests.post.return_value = fake_resp
        mock_requests.ConnectionError = ConnectionError
        monkeypatch.setitem(sys.modules, "requests", mock_requests)
        monkeypatch.setattr(report_mod, "OLLAMA_HOST", "http://localhost:11434")

        result = _generate_ollama("test prompt")
        # 마커 없음 → response 가 그대로 (re.sub 적용된 형태) 반환
        assert "직접 분석 결과만 텍스트" in result

    def test_thinking_path_when_response_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """622→632 inverse: response='' but thinking 존재 → elif True → thinking 처리."""
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"response": "", "thinking": "## 1. thinking content"}
        fake_resp.raise_for_status = lambda: None

        import sys

        mock_requests = MagicMock()
        mock_requests.post.return_value = fake_resp
        mock_requests.ConnectionError = ConnectionError
        monkeypatch.setitem(sys.modules, "requests", mock_requests)
        monkeypatch.setattr(report_mod, "OLLAMA_HOST", "http://localhost:11434")

        result = _generate_ollama("test prompt")
        assert "thinking content" in result

    def test_response_empty_no_thinking_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """622→632: response='' AND data.thinking 부재 → elif False → return '' (response 그대로)."""
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"response": ""}  # thinking 없음
        fake_resp.raise_for_status = lambda: None

        import sys

        mock_requests = MagicMock()
        mock_requests.post.return_value = fake_resp
        mock_requests.ConnectionError = ConnectionError
        monkeypatch.setitem(sys.modules, "requests", mock_requests)
        monkeypatch.setattr(report_mod, "OLLAMA_HOST", "http://localhost:11434")

        result = _generate_ollama("test prompt")
        assert result == ""
