"""PR A (2026-04-21, codex bubble-bear #1) — alpha_action / portfolio_action 분리 regression.

재발 차단 lock-in:
- concentration > 15% 단독 발동 시 `alpha_action=None`, `portfolio_action="REBALANCE"`,
  legacy `action != "SELL"`, score 영향 0 → consensus risk veto 미발동.
- stop-loss breach → `alpha_action="FLAT"`, `action=="SELL"` 유지 (alpha-driven).
- concentration + stop-loss 병렬 → 둘 다 emit (alpha=FLAT, portfolio=REBALANCE, action=SELL).

이 테스트가 fail 하면 SIEGE REJECT → SELL 경로가 다시 조성된 것 — 사용자 -₩7M 손실
재발 가능. 절대 skip 금지.
"""
from unittest.mock import patch

import pandas as pd
import yaml

from nuri.core.db import get_db


def _seed_concentrated_portfolio(
    db_path,
    ticker: str,
    current_price: float,
    avg_price: float,
    account: str = "Main",
    qty: int = 100,
):
    """Seed a portfolio whose total value is just this one ticker — weight = 100% > 15%."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM portfolio")
        conn.execute("DELETE FROM prices")
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            (account, ticker, qty, avg_price, "USD"),
        )
    # 30 rows 가격 (변동성 계산 가능하도록). 마지막 row = current_price.
    dates = pd.bdate_range("2025-01-01", periods=30).strftime("%Y-%m-%d").tolist()
    with get_db(db_path) as conn:
        for i, d in enumerate(dates):
            price = avg_price + (current_price - avg_price) * (i / 29)
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, d, price * 0.99, price * 1.01, price * 0.98, price, 100000),
            )


def _portfolio_yaml_opener(tmp_path, strategy: str = "core"):
    """builtins.open patch factory — portfolio.yaml 만 redirect."""
    portfolio_yaml = tmp_path / "portfolio.yaml"
    portfolio_yaml.write_text(yaml.dump({"accounts": {"Main": {"strategy": strategy}}}))
    real_open = open

    def _opener(path, *args, **kwargs):
        if str(path).endswith("portfolio.yaml"):
            return real_open(portfolio_yaml, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    return _opener


class TestConcentrationOnlyDoesNotTriggerSellVeto:
    """Concentration > 15% 단독 발동은 `alpha_action=None` 을 유지해 consensus risk
    veto 경로에 들어가면 안 된다. 이 regression 이 PR A 의 핵심 목적 — 사용자 BAC/TSLA
    SIEGE REJECT 를 "매도" 로 surface 하려던 경로 구조 차단."""

    def test_concentration_alone_emits_portfolio_action_not_sell(self, db_path, tmp_path):
        from nuri.trading.agents.risk_agent import RiskAgent

        # current_price == avg_price → pnl 0% (stop-loss 미발동), 비중 100% (concentration)
        _seed_concentrated_portfolio(
            db_path, "CONC", current_price=100.0, avg_price=100.0
        )

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            v = RiskAgent().analyze("CONC", db_path=db_path)

        # legacy action 은 SELL 이 아니어야 함 — concentration 만으로는 score 에 기여
        # 안 하므로 score=0 → HOLD bucket. (이 테스트가 fail 하면 risk_agent 의
        # concentration `-1` score 가 돌아온 것이고, 그것이 곧 사용자 -₩7M 재발 트리거.)
        assert v.action != "SELL", f"concentration-only should not produce SELL, got {v.action}"

        # alpha_action=None (HOLD → alpha 중립), portfolio_action=REBALANCE.
        assert v.alpha_action is None, f"expected alpha=None, got {v.alpha_action}"
        assert v.portfolio_action == "REBALANCE", f"expected REBALANCE, got {v.portfolio_action}"

        # data_points 에 concentration_breach 기록 (audit 용)
        assert v.data_points.get("concentration_breach") is True
        # score 는 concentration 에 의해 깎이지 않음 (0 이거나 변동성 기여만)
        assert v.data_points.get("score", 0) >= -1, (
            f"concentration must not reduce score, got score={v.data_points.get('score')}"
        )

        # reasoning 에 "리밸런스 권고" 문구 포함 (사용자 surface 언어)
        assert "리밸런스" in v.reasoning


class TestStopLossBreachStillEmitsAlphaFlat:
    """Stop-loss breach (alpha-driven) 는 기존과 동일하게 SELL + alpha=FLAT 유지.
    Regression lock: PR A 가 concentration 만 분리하고 stop-loss 는 그대로 veto 경로."""

    def test_stop_loss_breach_sets_alpha_flat(self, db_path, tmp_path):
        from nuri.trading.agents.risk_agent import RiskAgent

        # avg 100, current 70 → pnl -30% < core -7%
        _seed_concentrated_portfolio(
            db_path, "CRASH", current_price=70.0, avg_price=100.0
        )

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            v = RiskAgent().analyze("CRASH", db_path=db_path)

        assert v.action == "SELL"
        assert v.alpha_action == "FLAT"
        # 이 시나리오는 concentration 도 100% 라 portfolio_action 병렬 emit
        assert v.portfolio_action == "REBALANCE"
        assert "손절선" in v.reasoning


class TestHybridStopLossAndConcentrationParallel:
    """Stop-loss + concentration 동시 발동 → 두 axis 모두 emit. Legacy action 은
    stop-loss 가 dominant (SELL). UI 가 portfolio_action=REBALANCE 를 surface 할 수
    있어야 사용자가 "손절 말고 리밸런스" 로 선택 가능."""

    def test_hybrid_axes_parallel(self, db_path, tmp_path):
        from nuri.trading.agents.risk_agent import RiskAgent

        _seed_concentrated_portfolio(
            db_path, "HYBRID", current_price=75.0, avg_price=100.0
        )

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            v = RiskAgent().analyze("HYBRID", db_path=db_path)

        # stop-loss dominant (SELL, alpha=FLAT)
        assert v.action == "SELL"
        assert v.alpha_action == "FLAT"
        # portfolio axis 도 병렬 emit
        assert v.portfolio_action == "REBALANCE"


class TestConcentrationHighConfidenceCannotVeto:
    """Consensus risk veto 는 alpha_action=='FLAT' 만 발동. concentration 단독으로
    confidence 가 veto_threshold 이상이어도 veto 안 걸려야 함."""

    def test_consensus_does_not_veto_on_concentration_only(self, db_path, tmp_path):
        # concentration 단독 high-conf verdict 를 직접 주입해 _build_consensus 검증
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _build_consensus

        verdicts = [
            # risk agent: concentration 만, alpha=None
            AgentVerdict(
                agent_name="risk", ticker="BAC", action="HOLD", confidence=90.0,
                reasoning="비중 초과 (19.8% > 15%) — 리밸런스 권고",
                alpha_action=None,
                portfolio_action="REBALANCE",
            ),
            # 나머지 9 agents BUY (다수결) — 기존 합의 로직 확인
            *[
                AgentVerdict(agent_name=name, ticker="BAC", action="BUY", confidence=60.0,
                             reasoning=f"{name} BUY")
                for name in (
                    "technical", "fundamental", "macro", "smart_money", "wallstreet",
                    "korean_market", "options", "crypto", "retail",
                )
            ],
        ]

        result = _build_consensus("BAC", verdicts, DEFAULT_WEIGHTS)

        # risk veto 발동 안 함 — concentration 은 portfolio signal 이므로
        assert result.final_action != "SELL", f"veto should not fire on concentration, got {result.final_action}"
        assert result.scoring_detail is not None
        assert result.scoring_detail.get("risk_veto_fired") is False

    def test_consensus_veto_still_fires_on_stop_loss(self):
        """Back-compat: alpha_action=FLAT (stop-loss) 은 여전히 veto."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _build_consensus

        verdicts = [
            AgentVerdict(
                agent_name="risk", ticker="CRASH", action="SELL", confidence=90.0,
                reasoning="손절선 돌파 (-30.0% < -7%)",
                alpha_action="FLAT",
                portfolio_action=None,
            ),
            *[
                AgentVerdict(agent_name=name, ticker="CRASH", action="BUY", confidence=60.0,
                             reasoning=f"{name} BUY")
                for name in (
                    "technical", "fundamental", "macro", "smart_money", "wallstreet",
                    "korean_market", "options", "crypto", "retail",
                )
            ],
        ]

        result = _build_consensus("CRASH", verdicts, DEFAULT_WEIGHTS)

        assert result.final_action == "SELL"
        assert result.scoring_detail is not None
        assert result.scoring_detail.get("risk_veto_fired") is True

    def test_consensus_veto_back_compat_legacy_sell_no_alpha(self):
        """alpha_action=None + action=SELL (legacy agent, PR A axis 미설정) 는 여전히
        veto. Back-compat: 다른 에이전트가 axis 를 채우지 않아도 기존 behavior 유지."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import DEFAULT_WEIGHTS, _build_consensus

        verdicts = [
            AgentVerdict(
                agent_name="risk", ticker="LEGACY", action="SELL", confidence=85.0,
                reasoning="legacy sell (no axis set)",
                alpha_action=None,
                portfolio_action=None,
            ),
            *[
                AgentVerdict(agent_name=name, ticker="LEGACY", action="BUY", confidence=60.0,
                             reasoning=f"{name} BUY")
                for name in (
                    "technical", "fundamental", "macro", "smart_money", "wallstreet",
                    "korean_market", "options", "crypto", "retail",
                )
            ],
        ]

        result = _build_consensus("LEGACY", verdicts, DEFAULT_WEIGHTS)
        assert result.final_action == "SELL"


class TestMigration22:
    """Migration 22 idempotency + legacy row NULL safety."""

    def test_fresh_db_has_new_columns(self, tmp_path):
        from nuri.core.db import init_db, query

        p = tmp_path / "fresh.db"
        init_db(p)
        cols = query("PRAGMA table_info(recommendations)", db_path=p)
        names = {c["name"] for c in cols}
        assert "alpha_action" in names
        assert "portfolio_action" in names

    def test_migration_is_idempotent(self, tmp_path):
        from nuri.core.db import init_db, query

        p = tmp_path / "idem.db"
        init_db(p)
        init_db(p)  # 두 번째 호출도 안전해야 함
        cols = query("PRAGMA table_info(recommendations)", db_path=p)
        names = [c["name"] for c in cols]
        # alpha_action 은 정확히 1개 (중복 ALTER 없음)
        assert names.count("alpha_action") == 1
        assert names.count("portfolio_action") == 1
        # schema_version 도 1개 row
        rows = query("SELECT * FROM schema_version WHERE version = 22", db_path=p)
        assert len(rows) == 1

    def test_legacy_row_null_safe(self, tmp_path):
        """migration 22 전에 작성된 row 처럼 alpha/portfolio 를 skip 해 insert 시도 —
        NULL 폴백해야 함 (forward-only NULL 정책)."""
        from nuri.core.db import get_db, init_db, query

        p = tmp_path / "legacy.db"
        init_db(p)
        with get_db(p) as conn:
            conn.execute(
                """INSERT INTO recommendations (date, ticker, action, confidence)
                   VALUES ('2026-04-21', 'LEGACY', 'BUY', 75.0)"""
            )
        row = query(
            "SELECT alpha_action, portfolio_action FROM recommendations WHERE ticker='LEGACY'",
            db_path=p,
        )[0]
        assert row["alpha_action"] is None
        assert row["portfolio_action"] is None


class TestSaveToRecommendationsAlphaPortfolioPersist:
    """save_to_recommendations 가 alpha_action/portfolio_action 을 올바르게 채우고,
    same-day UPSERT 시 두 axis 모두 update 되는지 검증."""

    def test_buy_persists_as_alpha_long(self, db_path, tmp_path):
        from nuri.core.db import query
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, save_to_recommendations

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            r = ConsensusResult(
                ticker="BUYME",
                final_action="BUY",
                final_confidence=75.0,
                agreement_rate=0.7,
                verdicts=[
                    AgentVerdict("risk", "BUYME", "BUY", 60.0, "ok",
                                 alpha_action="LONG", portfolio_action=None),
                ],
                dissent=[],
                reasoning="BUY consensus",
            )
            n = save_to_recommendations([r], db_path=db_path)
        assert n == 1
        row = query(
            "SELECT action, alpha_action, portfolio_action, regime FROM recommendations "
            "WHERE ticker='BUYME'", db_path=db_path,
        )[0]
        assert row["action"] == "BUY"
        assert row["alpha_action"] == "LONG"
        assert row["portfolio_action"] is None

    def test_sell_persists_as_alpha_flat(self, db_path, tmp_path):
        from nuri.core.db import query
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, save_to_recommendations

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            r = ConsensusResult(
                ticker="SELLME", final_action="SELL", final_confidence=85.0,
                agreement_rate=0.8, verdicts=[
                    AgentVerdict("risk", "SELLME", "SELL", 85.0, "stop",
                                 alpha_action="FLAT", portfolio_action=None),
                ], dissent=[], reasoning="SELL",
            )
            save_to_recommendations([r], db_path=db_path)
        row = query(
            "SELECT alpha_action, portfolio_action FROM recommendations WHERE ticker='SELLME'",
            db_path=db_path,
        )[0]
        assert row["alpha_action"] == "FLAT"

    def test_hold_with_portfolio_rebalance(self, db_path, tmp_path):
        """핵심 regression: consensus HOLD + risk.portfolio_action=REBALANCE →
        DB 에 alpha_action=None, portfolio_action='REBALANCE' persist."""
        from nuri.core.db import query
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, save_to_recommendations

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            r = ConsensusResult(
                ticker="BAC", final_action="HOLD", final_confidence=62.0,
                agreement_rate=0.9, verdicts=[
                    AgentVerdict("risk", "BAC", "HOLD", 85.0,
                                 "비중 초과 (19.8% > 15%) — 리밸런스 권고",
                                 alpha_action=None, portfolio_action="REBALANCE"),
                ], dissent=[], reasoning="hold + portfolio rebalance",
            )
            save_to_recommendations([r], db_path=db_path)
        row = query(
            "SELECT action, alpha_action, portfolio_action FROM recommendations WHERE ticker='BAC'",
            db_path=db_path,
        )[0]
        assert row["action"] == "HOLD"
        assert row["alpha_action"] is None
        assert row["portfolio_action"] == "REBALANCE"

    def test_same_day_upsert_updates_both_axes(self, db_path, tmp_path):
        """same-day 재실행 시 alpha/portfolio axis 도 ON CONFLICT DO UPDATE 로 갱신."""
        from nuri.core.db import query
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult, save_to_recommendations

        with patch("builtins.open", side_effect=_portfolio_yaml_opener(tmp_path, "core")):
            # 1차: BUY
            r1 = ConsensusResult(
                ticker="FLIP", final_action="BUY", final_confidence=70.0,
                agreement_rate=0.6, verdicts=[
                    AgentVerdict("risk", "FLIP", "BUY", 60.0, "",
                                 alpha_action="LONG", portfolio_action=None),
                ], dissent=[], reasoning="",
            )
            save_to_recommendations([r1], db_path=db_path)

            # 2차: HOLD + REBALANCE (같은 날 — UPSERT 경로)
            r2 = ConsensusResult(
                ticker="FLIP", final_action="HOLD", final_confidence=55.0,
                agreement_rate=0.9, verdicts=[
                    AgentVerdict("risk", "FLIP", "HOLD", 85.0, "concentration",
                                 alpha_action=None, portfolio_action="REBALANCE"),
                ], dissent=[], reasoning="flip",
            )
            save_to_recommendations([r2], db_path=db_path)

        rows = query(
            "SELECT action, alpha_action, portfolio_action FROM recommendations WHERE ticker='FLIP'",
            db_path=db_path,
        )
        # same date+ticker UNIQUE → 1 row
        assert len(rows) == 1
        # update 됐는지 (BUY/LONG → HOLD/None/REBALANCE)
        assert rows[0]["action"] == "HOLD"
        assert rows[0]["alpha_action"] is None
        assert rows[0]["portfolio_action"] == "REBALANCE"


class TestTrackerWriterStillWorksAfterMigration:
    """PR A: tracker.save_recommendations insert 가 새 컬럼 존재하에 fail 안함.
    PR B: tracker 도 axis 채움 — `derive_alpha_action` 로 direction→alpha_action.
    두 의도 (PR A insert safety + PR B writer discipline) 는 양립 가능."""

    def test_e1_candidate_save_derives_alpha_action(self, db_path):
        """PR B 전환 — tracker 는 이제 alpha_action 을 자동 derive. direction=BUY
        → alpha_action=LONG, direction=SELL → alpha_action=FLAT. portfolio_action
        은 E-1 signal-driven 이라 NULL 유지 (portfolio rule 아님)."""
        from dataclasses import dataclass

        from nuri.core.db import query
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class _FakeCandidate:
            ticker: str
            direction: str
            confidence: float
            signal_id: str
            price: float
            regime_fit: bool = True
            tier: str = TIER_ACTIONABLE
            scoring_detail: dict | None = None

        c = _FakeCandidate(
            ticker="TKR", direction="BUY", confidence=70.0,
            signal_id="momentum", price=50.0,
        )
        n = save_recommendations(candidates=[c], db_path=db_path)
        assert n == 1
        row = query(
            "SELECT alpha_action, portfolio_action FROM recommendations WHERE ticker='TKR'",
            db_path=db_path,
        )[0]
        # PR B: tracker 가 direction=BUY → alpha_action=LONG derive
        assert row["alpha_action"] == "LONG"
        # portfolio_action 은 E-1 scope 아니므로 NULL 유지
        assert row["portfolio_action"] is None
