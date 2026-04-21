"""PR B (codex #2): axis-native read path regression.

재발 방지 lock-in (PR A codex Review caveat 의 결론):
- `/api/actions` — alpha_action=FLAT → urgent/check, alpha_action=None+SELL → back-compat.
- `/api/dashboard` `_get_latest_actions()` — alpha_action=LONG → BUY card, alpha_action=FLAT → SELL card.
  Legacy NULL rows back-compat. Future writer 가 concentration-only SELL 을 emit 해도
  (alpha_action=None + action=HOLD 조합) SELL card 에 surface 되지 않음.

이 테스트가 fail 하면 axis-native read path 가 regressed 됐거나 writer 가
concentration-only SELL 을 emit 하는 경로가 재도입된 것.
"""
from unittest.mock import patch


class TestActionsReadPathAxisNative:
    """`/api/actions` axis-native routing."""

    def _invoke_build_actions(self, *, recommendations, siege=None, portfolio=None):
        from nuri.api.routes import actions as actions_mod

        with (
            patch.object(actions_mod, "_get_recommendations", return_value=recommendations),
            patch.object(actions_mod, "_get_siege_violations", return_value=(siege or [])),
            patch.object(actions_mod, "_get_targets_status", return_value={}),
            patch.object(actions_mod, "_get_portfolio_map", return_value=(portfolio or {})),
            patch.object(actions_mod, "_get_short_interest", return_value=None),
            patch.object(actions_mod, "has_recent_catalyst", return_value=(False, "no data")),
            patch.object(actions_mod, "check_divergence", return_value=(False, 0.0, None)),
        ):
            return actions_mod._build_actions()

    def test_explicit_alpha_flat_enters_sell_path(self):
        """alpha_action=FLAT + stop-loss breach → urgent."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "CRASH", "action": "SELL", "confidence": 85,
                "agreement": 70, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": "FLAT", "portfolio_action": None,
            }],
            portfolio={"CRASH": {
                "current_price": 70.0, "avg_price": 100.0, "quantity": 100,
                "pnl_pct": -30.0, "position_pct": 5.0, "account": "Main",
            }},
        )
        assert len(result["urgent"]) == 1
        assert result["urgent"][0]["ticker"] == "CRASH"
        assert result["urgent"][0]["alpha_action"] == "FLAT"

    def test_legacy_null_axis_sell_backcompat(self):
        """alpha_action=None + action=SELL (pre-migration row) → SELL 경로 허용."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "LEGACY", "action": "SELL", "confidence": 75,
                "agreement": 60, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None, "portfolio_action": None,
            }],
            portfolio={"LEGACY": {
                "current_price": 95.0, "avg_price": 100.0, "quantity": 50,
                "pnl_pct": -5.0, "position_pct": 3.0, "account": "Main",
            }},
        )
        # -5% 는 core stop-loss -7% 넘지 않음 → non-emergency SELL → catalyst 없음 → hold
        # 그러나 이 테스트의 핵심은 "legacy SELL 이 action="SELL" 처리 분기 진입 은 한다"
        # 임을 확인. urgent 에 없지만 hold 로 routed 됨 (기존 actions.py 경로).
        # portfolio bucket 은 비어야 함 (SIEGE violation 없음).
        assert len(result["portfolio"]) == 0
        # Legacy SELL 이 alpha 경로로 진입됐는지 확인 — reason 에 "SELL 근거 없음" prefix 있음
        all_items = result["urgent"] + result["check"] + result["hold"]
        legacy_item = next(i for i in all_items if i["ticker"] == "LEGACY")
        assert legacy_item["action"] == "SELL"
        assert any("SELL" in r for r in legacy_item["reasons"])

    def test_concentration_hold_does_not_enter_sell_path(self):
        """PR B 핵심 assertion — alpha_action=None + action=HOLD + portfolio_action=REBALANCE
        조합 (PR A 이후 risk_agent 가 emit 하는 concentration-only 형태) 은 SELL 경로에
        절대 진입하면 안 된다. SIEGE violation 으로 portfolio bucket 에만 route."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "BAC", "action": "HOLD", "confidence": 62,
                "agreement": 90, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None, "portfolio_action": "REBALANCE",
            }],
            siege=[{
                "ticker": "BAC", "detail": "SIEGE: 종목 비중 한도 — 위반: BAC(19.8%>15%)",
                "condition_id": "position_limit",
            }],
            portfolio={"BAC": {
                "current_price": 40.0, "avg_price": 40.5, "quantity": 100,
                "pnl_pct": -1.2, "position_pct": 19.8, "account": "Main",
            }},
        )
        # 절대 urgent/check 진입 금지 (SELL 경로 차단)
        assert len(result["urgent"]) == 0
        assert all(i["ticker"] != "BAC" for i in result["check"])
        # portfolio bucket 으로만 route
        assert len(result["portfolio"]) == 1
        assert result["portfolio"][0]["ticker"] == "BAC"
        # Per-item axis 필드 노출 확인 (Frontend badge 용)
        assert result["portfolio"][0]["portfolio_action"] == "REBALANCE"
        assert result["portfolio"][0]["alpha_action"] is None

    def test_future_writer_emitting_concentration_sell_blocked_softly(self):
        """가상 future writer — alpha_action=None 에 action=SELL 을 잘못 emit.
        현 back-compat default (strict=False) 에선 legacy SELL 로 받아들임 → SELL 경로.
        이것은 Q1-B 의 의도된 동작 — strict=True 승격은 PR C 이후.

        이 테스트는 `is_alpha_flat_sell` 의 strict=False default semantic 문서화 목적."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "FUTURE", "action": "SELL", "confidence": 80,
                "agreement": 55, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None, "portfolio_action": None,
            }],
            portfolio={"FUTURE": {
                "current_price": 100.0, "avg_price": 100.0, "quantity": 10,
                "pnl_pct": 0.0, "position_pct": 5.0, "account": "Main",
            }},
        )
        # back-compat: alpha=None + action=SELL 이 SELL 경로로 진입됨.
        all_sells = [
            i for i in result["urgent"] + result["check"] + result["hold"]
            if i["ticker"] == "FUTURE"
        ]
        assert len(all_sells) == 1
        assert all_sells[0]["action"] == "SELL"

    def test_known_risk_post_migration_miswriter_concentration_sell_still_surfaces(self):
        """**Known remaining risk lock** (codex Review #434 P1 coverage gap).

        Post-migration-22 miswriter 가 `alpha_action=None, action="SELL",
        portfolio_action="REBALANCE"` 로 emit 하면 (= portfolio rule 을 legacy
        SELL 경로로 실수 라우팅), 현재 reader 는 back-compat 정책상 SELL 경로로
        받아들인다. PR A risk_agent 는 concentration 을 `HOLD + REBALANCE` 로 emit
        하므로 이 조합을 produce 하지 않지만 **구조적 보장은 strict=True 승격 후에만
        성립**. 이 테스트는 그 경계를 문서화 + 승격 전후 behavior change 를 확정.

        strict=True 승격 (PR C) 이 되면 이 테스트는 거꾸로 "SELL 경로 안 들어감" 으로
        update 되어야 함 — 승격 시점의 lock-in point."""
        result = self._invoke_build_actions(
            recommendations=[{
                "ticker": "MISWRITE", "action": "SELL", "confidence": 80,
                "agreement": 55, "scoring_detail": None, "agent_verdicts": None,
                "alpha_action": None,
                "portfolio_action": "REBALANCE",  # 의도적으로 이상한 조합
            }],
            portfolio={"MISWRITE": {
                "current_price": 100.0, "avg_price": 100.0, "quantity": 10,
                "pnl_pct": 0.0, "position_pct": 5.0, "account": "Main",
            }},
        )
        # 현 PR B (strict=False) 에서는 SELL 경로에 들어감 — 의도된 known risk.
        all_buckets_items = {
            t: (bucket, item)
            for bucket in ("urgent", "check", "hold", "portfolio")
            for item in result[bucket]
            if (t := item["ticker"])
        }
        assert "MISWRITE" in all_buckets_items
        bucket, item = all_buckets_items["MISWRITE"]
        # 중요: `portfolio` bucket 이 아님 (SIEGE violation 이 아니어서) — SELL 경로.
        # 실제로 hold (catalyst 없음) or check (catalyst 있음) 중 하나에 도달.
        assert bucket in ("urgent", "check", "hold")
        assert item["action"] == "SELL"
        assert item["alpha_action"] is None
        # portfolio_action=REBALANCE 는 per-item 필드로 여전히 expose — UI 가
        # mismatch 를 감지할 수 있음 (Frontend badge 추가 시 visual warning).
        assert item["portfolio_action"] == "REBALANCE"


class TestDashboardAxisNativeSELL:
    """`/api/dashboard` `_get_latest_actions()` axis-native filtering."""

    def test_concentration_only_hold_not_surfaced_as_sell(self, tmp_path, monkeypatch):
        """PR B dashboard 마무리. BAC/TSLA 같은 concentration-only row
        (alpha_action=None, action=HOLD, portfolio_action=REBALANCE) 가 dashboard
        SELL 카드에 들어가면 안 됨."""
        from nuri.core.db import get_db, init_db
        from nuri.core.timezone import today_kst

        db = tmp_path / "test.db"
        init_db(db)
        monkeypatch.setenv("NURI_DB_PATH", str(db))

        today = today_kst()
        with get_db(db) as conn:
            # Concentration-only row — PR A 이후 risk_agent 가 emit 하는 형태
            conn.execute(
                """INSERT INTO recommendations
                (date, ticker, action, alpha_action, portfolio_action, confidence, regime)
                VALUES (?, 'BAC', 'HOLD', NULL, 'REBALANCE', 62, 'sideways_high_vol')""",
                (today,),
            )
            # 실제 alpha SELL row — confidence 70 이상이라 SELL 카드 진입해야
            conn.execute(
                """INSERT INTO recommendations
                (date, ticker, action, alpha_action, portfolio_action, confidence, regime)
                VALUES (?, 'CRASH', 'SELL', 'FLAT', NULL, 85, 'bear_high_vol')""",
                (today,),
            )

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        from nuri.api.routes.dashboard import _get_latest_actions
        latest = _get_latest_actions()
        # BAC 는 alpha_action=None + action=HOLD → `is_alpha_flat_sell` False → SELL 카드 제외
        assert all(a["ticker"] != "BAC" for a in latest), \
            f"BAC (concentration-only) must NOT appear as dashboard action, got {latest}"
        # CRASH 는 alpha_action=FLAT → SELL 카드 진입
        crash = [a for a in latest if a["ticker"] == "CRASH"]
        assert len(crash) == 1
        assert crash[0]["action"] == "SELL"
        assert crash[0]["alpha_action"] == "FLAT"

    def test_legacy_null_sell_backcompat_on_dashboard(self, tmp_path, monkeypatch):
        """Pre-migration row (alpha_action=NULL + action='SELL' + conf≥70) 은
        dashboard SELL 카드에 여전히 surface (Q1-B back-compat)."""
        from nuri.core.db import get_db, init_db
        from nuri.core.timezone import today_kst

        db = tmp_path / "test.db"
        init_db(db)
        monkeypatch.setenv("NURI_DB_PATH", str(db))

        today = today_kst()
        with get_db(db) as conn:
            conn.execute(
                """INSERT INTO recommendations
                (date, ticker, action, alpha_action, portfolio_action, confidence, regime)
                VALUES (?, 'LEGACY', 'SELL', NULL, NULL, 80, 'neutral')""",
                (today,),
            )

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        from nuri.api.routes.dashboard import _get_latest_actions
        latest = _get_latest_actions()
        # back-compat: legacy SELL 은 dashboard SELL 카드에 surface
        legacy = [a for a in latest if a["ticker"] == "LEGACY"]
        assert len(legacy) == 1
        assert legacy[0]["action"] == "SELL"

    def test_alpha_long_buy_with_legacy_buy_both_surface(self, tmp_path, monkeypatch):
        """BUY card filtering 도 axis-aware — alpha_action=LONG 은 당연히, legacy
        BUY 도 back-compat."""
        from nuri.core.db import get_db, init_db
        from nuri.core.timezone import today_kst

        db = tmp_path / "test.db"
        init_db(db)
        monkeypatch.setenv("NURI_DB_PATH", str(db))

        today = today_kst()
        with get_db(db) as conn:
            conn.execute(
                """INSERT INTO recommendations
                (date, ticker, action, alpha_action, portfolio_action, confidence, regime)
                VALUES (?, 'NEW', 'BUY', 'LONG', NULL, 65, 'bull_low_vol')""",
                (today,),
            )
            conn.execute(
                """INSERT INTO recommendations
                (date, ticker, action, alpha_action, portfolio_action, confidence, regime)
                VALUES (?, 'LEGACYBUY', 'BUY', NULL, NULL, 70, 'neutral')""",
                (today,),
            )

        import nuri.core.db as db_mod
        monkeypatch.setattr(db_mod, "DB_PATH", db)

        from nuri.api.routes.dashboard import _get_latest_actions
        latest = _get_latest_actions()
        tickers = {a["ticker"]: a for a in latest}
        assert "NEW" in tickers and tickers["NEW"]["alpha_action"] == "LONG"
        assert "LEGACYBUY" in tickers and tickers["LEGACYBUY"]["alpha_action"] is None


class TestTrackerAxisPersist:
    """Writer discipline — tracker.save_recommendations 가 axis persist."""

    def test_e1_candidate_buy_persists_alpha_long(self, db_path):
        from dataclasses import dataclass

        from nuri.core.db import query
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class _Candidate:
            ticker: str
            direction: str
            confidence: float
            signal_id: str
            price: float
            regime_fit: bool = True
            tier: str = TIER_ACTIONABLE
            scoring_detail: dict | None = None

        c = _Candidate(ticker="AAA", direction="BUY", confidence=70.0,
                       signal_id="momentum", price=50.0)
        n = save_recommendations(candidates=[c], db_path=db_path)
        assert n == 1
        row = query(
            "SELECT action, alpha_action, portfolio_action FROM recommendations WHERE ticker='AAA'",
            db_path=db_path,
        )[0]
        assert row["action"] == "BUY"
        assert row["alpha_action"] == "LONG"
        assert row["portfolio_action"] is None

    def test_e1_candidate_sell_persists_alpha_flat(self, db_path):
        from dataclasses import dataclass

        from nuri.core.db import query
        from nuri.trading.recommend.candidates import TIER_ACTIONABLE
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class _Candidate:
            ticker: str
            direction: str
            confidence: float
            signal_id: str
            price: float
            regime_fit: bool = True
            tier: str = TIER_ACTIONABLE
            scoring_detail: dict | None = None

        c = _Candidate(ticker="ZZZ", direction="SELL", confidence=65.0,
                       signal_id="bb_reversal", price=100.0)
        save_recommendations(candidates=[c], db_path=db_path)
        row = query(
            "SELECT action, alpha_action FROM recommendations WHERE ticker='ZZZ'",
            db_path=db_path,
        )[0]
        assert row["action"] == "SELL"
        assert row["alpha_action"] == "FLAT"

    def test_e2_action_persists_axis_too(self, db_path):
        """E-2 rebalance action 도 alpha_action 채움."""
        from dataclasses import dataclass

        from nuri.core.db import query
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class _Action:
            ticker: str
            action: str
            signals: list
            regime_note: str = ""

        a = _Action(ticker="REBAL", action="BUY", signals=["rebalance"])
        save_recommendations(actions=[a], db_path=db_path)
        row = query(
            "SELECT action, alpha_action FROM recommendations WHERE ticker='REBAL'",
            db_path=db_path,
        )[0]
        assert row["action"] == "BUY"
        assert row["alpha_action"] == "LONG"
