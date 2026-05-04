"""Branch coverage 보강 — `nuri/trading/agents/consensus/` defensive paths.

대상:
- __init__.py: agent run() exception → fallback verdict (188-189), TimeoutError → 폴백 (192-194),
  streaming agent error (237-238), streaming TimeoutError (242-246), all-canonical 분기 (105-106).
- events.py: tech_v is None → 조기 return (line 34).
- learning_memory.py: invalid schema row → skip (81-82).
- persistence.py: classify_regime non-None → batch_regime 채움 (46-48).
- presentation.py: supporters 비어있으면 continue (71), ticker 외부 data 없으면 continue (118).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "consensus.db"
    init_db(p)
    return p


# ─── learning_memory: invalid schema row → skip ─────────────────────────────


class TestComputeWeightsAllCanonical:
    """`_compute_weights` (lines 105-106): provisional/unsaturating 모두 빈 + canonical 만
    → DEBUG log 분기 진입.

    select_weight_source 가 canonical_30d 만 반환하면 elif canon_agents: 분기 진입.
    """

    def test_all_canonical_logs_debug(self, monkeypatch, db_path, caplog):
        from nuri.trading.agents.consensus import _compute_weights
        from nuri.trading.agents.consensus.models import AgentEligibility

        # canonical 만 채움 — 모든 agent canonical_30d source
        fake_canonical = {
            "technical": AgentEligibility(name="technical", sample_count=30, weight=0.15, eligible=True),
            "fundamental": AgentEligibility(name="fundamental", sample_count=30, weight=0.12, eligible=True),
        }
        # provisional 빈
        fake_provisional = {}

        monkeypatch.setattr(
            "nuri.trading.agents.consensus.compute_canonical_weights",
            lambda db_path=None: fake_canonical,
        )
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.compute_provisional_weights",
            lambda db_path=None: fake_provisional,
        )
        # select_weight_source 가 canonical_30d 만 반환하도록
        monkeypatch.setattr(
            "nuri.trading.agents.consensus.select_weight_source",
            lambda c, p: (
                {"technical": 0.15, "fundamental": 0.12},
                {"technical": "canonical_30d", "fundamental": "canonical_30d"},
            ),
        )

        import logging

        with caplog.at_level(logging.DEBUG, logger="nuri.trading.agents.consensus"):
            _compute_weights(db_path=db_path)
        # all-canonical 분기 진입 → DEBUG log
        assert any("all canonical_30d eligible" in rec.message for rec in caplog.records)


class TestLearningMemoryInvalidSchema:
    def test_invalid_schema_rows_skipped(self, db_path):
        """`agent_verdicts` 가 list 가 아닌 row → skip (lines 81-82).

        `_compute_horizon_eligibility` 의 schema gate 가 invalid JSON dict 를 반려.
        """
        from nuri.core.db.connection import get_db
        from nuri.trading.agents.consensus.learning_memory import _compute_horizon_eligibility

        # 1 invalid (dict, not list) + N valid rows for canonical_30d horizon
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO recommendations
                   (ticker, action, confidence, agent_verdicts, outcome_30d, date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("AAA", "BUY", 70, '{"not": "a list"}', 0.05, "2026-04-01"),
            )
            for i in range(15):
                conn.execute(
                    """INSERT INTO recommendations
                       (ticker, action, confidence, agent_verdicts, outcome_30d, date)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        f"V{i:02d}",
                        "BUY",
                        70,
                        '[{"agent_name": "technical", "action": "BUY", "confidence": 80}]',
                        0.05,
                        "2026-04-01",
                    ),
                )

        # 호출만 정상 통과되면 invalid row 가 skip 된 것 — eligibility map 을 받음.
        elig = _compute_horizon_eligibility(
            outcome_col="outcome_30d",
            adjustment_range=0.30,
            label="canonical_30d",
            db_path=db_path,
        )
        assert isinstance(elig, dict)


# ─── presentation: supporters empty / ticker not in external data ──────────


class TestPresentationContinueBranches:
    def test_no_supporters_continue(self, capsys, db_path):
        """supporters 비어있으면 continue (line 71)."""
        from nuri.trading.agents.consensus import (
            AgentVerdict,
            ConsensusResult,
            print_consensus,
        )

        # final_action=BUY 인데 verdicts 안에 BUY 없음 → supporters=[] → continue
        result = ConsensusResult(
            ticker="AAA",
            final_action="BUY",
            final_confidence=60.0,
            agreement_rate=0.5,
            verdicts=[
                AgentVerdict("a1", "AAA", "HOLD", 50, "neutral"),
                AgentVerdict("a2", "AAA", "HOLD", 60, "neutral"),
            ],
            dissent=[],
            reasoning="",
            divergence_flag=False,
            divergence_reason="",
            penalty_applied=False,
            pre_penalty_action="",
            scoring_detail=None,
        )

        # verbose=True 로 supporters 분기 진입
        print_consensus([result], verbose=True)
        out = capsys.readouterr().out
        # supporters 빈 list 라 "supporters:" 라인 미출력
        assert "supporters:" not in out

    def test_external_data_ticker_filter(self, capsys, monkeypatch):
        """`r.ticker not in tickers_with_data: continue` (line 118).

        `get_external` 은 `from nuri.collectors.external import get_external` 형태 →
        함수 내부 import. nuri.collectors.external 에 직접 patch 하면 import 시 mock pickup.
        """
        from nuri.trading.agents.consensus import (
            AgentVerdict,
            ConsensusResult,
            print_consensus,
        )

        results = [
            ConsensusResult(
                ticker=t,
                final_action="HOLD",
                final_confidence=50.0,
                agreement_rate=0.5,
                verdicts=[],
                dissent=[],
                reasoning="",
                divergence_flag=False,
                divergence_reason="",
                penalty_applied=False,
                pre_penalty_action="",
                scoring_detail=None,
            )
            for t in ("AAA", "BBB")
        ]

        # AAA 는 external data 있음, BBB 는 빈 list → BBB 는 tickers_with_data 미포함
        # → for-loop iteration 시 continue (line 118)
        def fake_get_external(ticker):
            if ticker == "AAA":
                return [
                    {"data_type": "consensus", "value": "Strong Buy", "source": "tipranks"},
                ]
            return []

        monkeypatch.setattr("nuri.collectors.external.get_external", fake_get_external)

        print_consensus(results, verbose=False)
        out = capsys.readouterr().out
        # External Data 섹션 출력 확인 + AAA row 만 details 출력 (BBB skip via continue)
        assert "External Data" in out
        assert "AAA" in out
        assert "TipRanks" in out


# ─── persistence: classify_regime success populates batch_regime ────────────


class TestPersistenceClassifyRegimeException:
    def test_classify_raises_keeps_batch_regime_null(self, monkeypatch, db_path):
        """classify_regime raise → except 분기 → batch_regime = None (lines 47-48)."""
        from nuri.trading.agents.consensus import (
            AgentVerdict,
            ConsensusResult,
            save_to_recommendations,
        )

        def _boom(**kw):
            raise RuntimeError("regime down")

        monkeypatch.setattr("nuri.quant.regime.classifier.classify_regime", _boom)

        result = ConsensusResult(
            ticker="AAA",
            final_action="BUY",
            final_confidence=60.0,
            agreement_rate=0.5,
            verdicts=[AgentVerdict("a1", "AAA", "BUY", 60, "ok")],
            dissent=[],
            reasoning="",
            divergence_flag=False,
            divergence_reason="",
            penalty_applied=False,
            pre_penalty_action="",
            scoring_detail=None,
        )

        # raise 안 함 — except swallowed
        saved = save_to_recommendations([result], db_path=db_path)
        assert saved >= 1

        from nuri.core.db import query

        rows = query("SELECT regime FROM recommendations WHERE ticker = 'AAA'", db_path=db_path)
        assert len(rows) >= 1
        # except 후 batch_regime = None → DB 에 NULL 저장
        assert rows[0]["regime"] is None


class TestPersistenceClassifyRegimeSuccess:
    def test_classify_returns_state_populates_batch_regime(self, monkeypatch, db_path):
        """classify_regime 가 non-None RegimeState 반환 → batch_regime 변수 채움 (lines 45-46).

        save_to_recommendations 가 records 에 regime 컬럼을 write 하는지 검증.
        """
        from nuri.quant.regime.classifier import RegimeState
        from nuri.trading.agents.consensus import (
            AgentVerdict,
            ConsensusResult,
            save_to_recommendations,
        )

        fake_state = RegimeState(
            date="2026-04-01",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.8,
            details={},
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: fake_state,
        )

        result = ConsensusResult(
            ticker="AAA",
            final_action="BUY",
            final_confidence=60.0,
            agreement_rate=0.5,
            verdicts=[AgentVerdict("a1", "AAA", "BUY", 60, "ok")],
            dissent=[],
            reasoning="",
            divergence_flag=False,
            divergence_reason="",
            penalty_applied=False,
            pre_penalty_action="",
            scoring_detail=None,
        )

        # save persists → DB row 의 regime 컬럼 = bull_low_vol
        saved = save_to_recommendations([result], db_path=db_path)
        assert saved >= 1

        from nuri.core.db import query

        rows = query("SELECT regime FROM recommendations WHERE ticker = 'AAA'", db_path=db_path)
        assert len(rows) >= 1
        assert rows[0]["regime"] == "bull_low_vol"


# ─── events: tech_v is None → early return ─────────────────────────────────


class TestConsensusEventsTechMissing:
    def test_no_technical_verdict_returns_early(self, monkeypatch):
        """penalty_applied=True 인데 verdicts 안에 'technical' 없음 → early return (line 34)."""
        from nuri.trading.agents.consensus import AgentVerdict, ConsensusResult
        from nuri.trading.agents.consensus.events import _emit_penalty_event_if_fired

        result = ConsensusResult(
            ticker="AAA",
            final_action="HOLD",
            final_confidence=50.0,
            agreement_rate=0.5,
            verdicts=[AgentVerdict("a1", "AAA", "HOLD", 50, "neutral")],
            dissent=[],
            reasoning="",
            divergence_flag=False,
            divergence_reason="",
            penalty_applied=True,  # penalty applied
            pre_penalty_action="BUY",
            scoring_detail=None,
        )

        emit_calls = []
        monkeypatch.setattr(
            "nuri.core.events.emit_event",
            lambda *a, **kw: emit_calls.append((a, kw)),
        )

        # technical agent 없음 → tech_v is None → early return → emit_event 호출 안 됨
        _emit_penalty_event_if_fired(result, [AgentVerdict("a1", "AAA", "HOLD", 50, "neutral")])
        assert emit_calls == []


# ─── consensus.__init__ exception/timeout fallback verdicts ─────────────────


class TestConsensusBatchTimeoutFallback:
    """analyze_ticker 의 batch TimeoutError 분기 (lines 192-194).

    `as_completed(timeout=)` 가 timeout → 미완료 future 들을 fallback HOLD/0/'타임아웃'.
    """

    def test_timeout_yields_fallback_verdicts(self, monkeypatch, db_path):
        import threading

        from nuri.trading.agents.consensus import analyze_ticker

        evt = threading.Event()

        # agent.analyze 가 evt.wait → 강제 hang
        slow_agent = MagicMock()
        slow_agent.name = "slow_agent"

        def slow_analyze(*a, **kw):
            evt.wait(timeout=2.0)
            return None

        slow_agent.analyze = slow_analyze

        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [slow_agent])
        # agent_timeout 매우 짧게
        from nuri.core.agent_config import AGENT_CONFIG

        original = AGENT_CONFIG.get("consensus", {}).copy()
        AGENT_CONFIG["consensus"]["agent_timeout_sec"] = 0.05
        try:
            result = analyze_ticker("AAA", db_path=db_path)
            # batch timeout → 폴백 verdict 생성
            assert len(result.verdicts) == 1
            assert result.verdicts[0].action == "HOLD"
            assert "타임아웃" in result.verdicts[0].reasoning
        finally:
            AGENT_CONFIG["consensus"] = original
            evt.set()


class TestConsensusInnerRunAgentExceptionPath:
    """`_run_agent` (inner function) 의 except → fallback verdict 경로 (lines 172-173).

    참고: outer except (lines 188-189) 는 `_run_agent` 가 이미 예외를 흡수하므로
    practically dead code (defensive). future.result() 가 raise 하려면 future cancel
    상태여야 함 — as_completed 는 done future 만 yield 하므로 unreachable.
    """

    def test_agent_analyze_exception_becomes_hold_fallback(self, monkeypatch, db_path):
        """ALL_AGENTS 의 agent 한 개를 raise 하도록 패치 → HOLD 폴백 verdict 생성."""
        from nuri.trading.agents.consensus import analyze_ticker

        # Bad agent: analyze() 에서 raise
        bad_agent = MagicMock()
        bad_agent.name = "bad_agent"
        bad_agent.analyze.side_effect = RuntimeError("simulated")

        # 단일 bad agent 만 들어가도록 ALL_AGENTS 패치
        monkeypatch.setattr("nuri.trading.agents.consensus.ALL_AGENTS", [bad_agent])

        result = analyze_ticker("AAA", db_path=db_path)
        # bad agent 의 verdict 가 fallback HOLD/0 + "에러:" prefix
        assert len(result.verdicts) == 1
        assert result.verdicts[0].action == "HOLD"
        assert result.verdicts[0].confidence == 0
        assert "에러" in result.verdicts[0].reasoning


# ─── future.result() Exception fallback (lines 188-189, 237-238) ───────────


class TestFutureResultExceptionFallback:
    """`analyze_ticker` / `stream_analyze_ticker` 의 `future.result()` 가 raise 하는 경로.

    내부 `_run_agent` 가 Exception 을 잡아 AgentVerdict 반환하므로 future.result() 가
    raise 하려면 _run_agent BEFORE 에서 발생한 BaseException 또는 future.set_exception 을
    직접 주입해야 한다. ThreadPoolExecutor.submit 을 patch 해 set_exception 된 Future 를
    반환하면 outer try/except Exception 분기 (188-189, 237-238) 가 진입한다.
    """

    @staticmethod
    def _broken_executor_class():
        """submit() 이 set_exception 된 Future 를 반환하는 가짜 executor."""
        import concurrent.futures as cf

        class _Broken(cf.ThreadPoolExecutor):
            def submit(self, fn, *a, **kw):
                fut: cf.Future = cf.Future()
                fut.set_exception(RuntimeError("forced future failure"))
                return fut

        return _Broken

    def test_analyze_ticker_future_exception_falls_back_to_hold(self, db_path, monkeypatch):
        """analyze_ticker: future.result() raise → outer except → HOLD 폴백 (188-189)."""
        import concurrent.futures as cf

        from nuri.trading.agents import consensus as cons_mod

        monkeypatch.setattr(cf, "ThreadPoolExecutor", self._broken_executor_class())
        result = cons_mod.analyze_ticker("AAA", db_path=db_path)
        # 모든 verdict 가 폴백: action=HOLD, confidence=0
        assert result.ticker == "AAA"
        assert all(v.action == "HOLD" for v in result.verdicts)
        assert all(v.confidence == 0 for v in result.verdicts)
        assert all("에러:" in v.reasoning for v in result.verdicts)

    def test_stream_analyze_ticker_future_exception_falls_back(self, db_path, monkeypatch):
        """stream_analyze_ticker: future.result() raise → except → HOLD 폴백 (237-238)."""
        import concurrent.futures as cf

        from nuri.trading.agents import consensus as cons_mod

        monkeypatch.setattr(cf, "ThreadPoolExecutor", self._broken_executor_class())
        events = list(cons_mod.stream_analyze_ticker("AAA", db_path=db_path))
        # verdict 이벤트만 골라내기
        verdict_evs = [e for e in events if e[0] == "verdict"]
        assert len(verdict_evs) > 0
        for _, v in verdict_evs:
            assert v.action == "HOLD"
            assert v.confidence == 0
            assert "에러:" in v.reasoning
