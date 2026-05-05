"""Branch coverage 보강 — `nuri/core/db/` defensive guard / 검증 분기.

대상 (실제 source line 매칭):
- audit.audit_log: except Exception → swallow (lines 64-65)
- connection._resolve_db_path: db_path is None → facade.DB_PATH 반환 (33-35)
- agent_runtime.log_agent_message: invalid channel → ValueError (288)
- portfolio.upsert_portfolio: empty records → 0 (18)
- postmortem_ops._cosine: zero norm → 0.0 (132)
- postmortem_ops.find_similar_days: regime not in regime_universe → append (171)
- research_ops.reject_hypothesis: hypothesis_id 없음 → ValueError (239)
- trades.upsert_trade: id-only data → 0 (27)
- market_data.upsert_signals empty → 0 (47), insert_events empty → 0 (78)
- discord_outbox_ops: priority/dedupe_strategy/channel ValueError, scheduled_for INSERT,
  JSONDecodeError fallback, mark_*_empty ids → 0 (66, 68, 104, 130, 180-181, 196, 221)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "branch.db"
    init_db(p)
    return p


# ─── audit.py — except 분기 ─────────────────────────────────────────────


class TestAuditLog:
    def test_audit_log_swallows_db_failure(self, monkeypatch):
        """audit_log 의 INSERT 가 실패해도 raise 없이 swallow (lines 64-65)."""
        from nuri.core.db.audit import audit_log

        # get_db 자체를 raise 하도록 패치 → audit_log try/except 가 swallow 해야 함
        def _boom(*a, **kw):
            raise RuntimeError("simulated DB lock")

        monkeypatch.setattr("nuri.core.db.audit.get_db", _boom)
        # raise 안 됨 → return None
        assert audit_log("test", "trades", "AAA") is None


# ─── connection._resolve_db_path ──────────────────────────────────────


class TestConnectionResolveDbPath:
    def test_default_uses_facade_db_path(self, tmp_path, monkeypatch):
        """db_path=None → facade.DB_PATH 사용 (lines 33-35)."""
        from nuri.core import db as facade
        from nuri.core.db.connection import _resolve_db_path

        target = tmp_path / "default.db"
        monkeypatch.setattr(facade, "DB_PATH", target)
        result = _resolve_db_path(None)
        assert result == target


# ─── agent_runtime — invalid channel ──────────────────────────────────


class TestAgentRuntimeChannelValidation:
    def test_log_agent_message_rejects_unknown_channel(self, db_path):
        """log_agent_message 에 정의 외 channel → ValueError (line 288)."""
        from nuri.core.db.agent_runtime import log_agent_message

        with pytest.raises(ValueError, match="channel must be"):
            log_agent_message(channel="invalid_channel", content_preview="x", db_path=db_path)


# ─── portfolio.upsert_portfolio — empty list ──────────────────────────


class TestPortfolioEmpty:
    def test_upsert_portfolio_empty_returns_zero(self, db_path):
        """빈 records → 0 반환 (line 18)."""
        from nuri.core.db.portfolio import upsert_portfolio

        assert upsert_portfolio([], db_path) == 0


# ─── postmortem_ops ────────────────────────────────────────────────────


class TestPostmortemOpsCosine:
    def test_cosine_zero_vector_returns_zero(self):
        """na==0 또는 nb==0 → 0.0 반환 (line 132 degenerate guard)."""
        from nuri.core.db.postmortem_ops import _cosine

        # 모두 0 인 벡터 → norm 0 → 0.0
        assert _cosine([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
        assert _cosine([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0


class TestFindSimilarDaysRegimeUniverseAppend:
    def test_unknown_regime_appended_to_universe(self, db_path):
        """regime not in regime_universe → append (line 171).

        rows 의 regime 들과 다른 query regime 을 줘서 append 분기 활성화.
        """
        from nuri.core.db import upsert_postmortem
        from nuri.core.db.postmortem_ops import find_similar_days

        # 2 rows with regime='bull'
        for d in ("2026-04-20", "2026-04-21"):
            upsert_postmortem(
                date=d,
                session="us",
                regime="bull",
                vix=18.0,
                fear_greed=50.0,
                vix_5d_delta=0.0,
                fg_5d_delta=0.0,
                spy_5d_delta=1.0,
                top_sector_delta_pct=0.0,
                holdings_total_pnl_pct=0.0,
                db_path=db_path,
            )

        # query regime='bear' → not in {'bull'} → append 분기
        result = find_similar_days(
            session="us",
            regime="bear",
            vix=18.0,
            fear_greed=50.0,
            vix_5d_delta=0.0,
            fg_5d_delta=0.0,
            spy_5d_delta=1.0,
            top_sector_delta_pct=0.0,
            holdings_total_pnl_pct=0.0,
            db_path=db_path,
        )
        # similarity 가 계산되어야 함 (raise 안 함). regime hot-encode 가 universe size 확장됨.
        assert isinstance(result, list)
        assert len(result) <= 2


# ─── research_ops.reject_hypothesis ────────────────────────────────────


class TestRejectHypothesisNotFound:
    def test_unknown_hypothesis_id_raises(self, db_path):
        """hypothesis_id 없음 → ValueError (line 239)."""
        from nuri.core.db.research_ops import reject_hypothesis

        with pytest.raises(ValueError, match="not found"):
            reject_hypothesis("no-such-id", "test rejection reason", db_path=db_path)


# ─── trades.upsert_trade ───────────────────────────────────────────────


class TestUpsertTradeIdOnly:
    def test_upsert_trade_with_id_only_returns_zero(self, db_path):
        """id 만 있고 다른 필드 없음 → 0 (line 27)."""
        from nuri.core.db.trades import upsert_trade

        # id 만 → pop("id") 후 data 가 빈 dict → if not data: return 0
        result = upsert_trade({"id": 1}, db_path=db_path)
        assert result == 0


# ─── market_data ──────────────────────────────────────────────────────


class TestMarketDataEmptyGuards:
    def test_upsert_signals_empty_df(self, db_path):
        """upsert_signals empty DF → 0 (line 47)."""
        from nuri.core.db.market_data import upsert_signals

        assert upsert_signals(pd.DataFrame(), db_path) == 0

    def test_insert_events_empty_list(self, db_path):
        """insert_events empty → 0 (line 78)."""
        from nuri.core.db.market_data import insert_events

        assert insert_events([], db_path) == 0


# ─── discord_outbox_ops 분기 ──────────────────────────────────────────


class TestDiscordOutboxValidations:
    def test_stage_outbox_invalid_priority(self, db_path):
        """priority not in _PRIORITIES → ValueError (line 66)."""
        from nuri.core.db.discord_outbox_ops import stage_outbox

        with pytest.raises(ValueError, match="priority must"):
            stage_outbox("brief", {"x": 1}, priority="urgent", db_path=db_path)

    def test_stage_outbox_invalid_dedupe_strategy(self, db_path):
        """dedupe_strategy invalid → ValueError (line 68)."""
        from nuri.core.db.discord_outbox_ops import stage_outbox

        with pytest.raises(ValueError, match="dedupe_strategy must"):
            stage_outbox(
                "brief",
                {"x": 1},
                dedupe_strategy="merge",  # not skip|replace
                db_path=db_path,
            )

    def test_stage_outbox_with_scheduled_for(self, db_path):
        """scheduled_for 명시 → INSERT scheduled_for branch (line 104)."""
        from nuri.core.db.discord_outbox_ops import stage_outbox

        rid = stage_outbox(
            "brief",
            {"content": "scheduled message"},
            scheduled_for="2026-12-31 23:59:59",
            db_path=db_path,
        )
        assert rid is not None and rid > 0

    def test_claim_pending_invalid_channel(self, db_path):
        """claim 시 channel invalid → ValueError (line 130)."""
        from nuri.core.db.discord_outbox_ops import claim_pending_outbox

        with pytest.raises(ValueError, match="channel must"):
            claim_pending_outbox("not_a_channel", db_path=db_path)

    def test_claim_returns_empty_with_corrupted_payload(self, db_path):
        """payload_json 이 invalid JSON → JSONDecodeError → payload={} (lines 180-181)."""
        from nuri.core.db.connection import get_db
        from nuri.core.db.discord_outbox_ops import claim_pending_outbox

        # 직접 INSERT 로 corrupt payload 행 stage (stage_outbox 거치면 JSON 직렬화)
        with get_db(db_path) as conn:
            conn.execute(
                """INSERT INTO discord_outbox
                       (channel, payload_json, priority, status, scheduled_for)
                   VALUES (?, ?, ?, 'pending', datetime('now', '-1 minute'))""",
                ("brief", "not-valid-json{", "normal"),
            )

        token, rows = claim_pending_outbox("brief", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["payload"] == {}

    def test_mark_sent_empty_ids_returns_zero(self, db_path):
        """ids 빈 list → 0 (line 196)."""
        from nuri.core.db.discord_outbox_ops import mark_outbox_sent

        assert mark_outbox_sent([], "any-token", db_path=db_path) == 0

    def test_mark_failed_empty_ids_returns_zero(self, db_path):
        """ids 빈 list → 0 (line 221)."""
        from nuri.core.db.discord_outbox_ops import mark_outbox_failed

        assert mark_outbox_failed([], "any-token", "err", db_path=db_path) == 0


# ─── Phase 4 #616 statement coverage ──────────────────────────────────


class TestUpsertSignalsNonEmpty:
    """market_data.py L48-59: upsert_signals() non-empty df path."""

    def test_upsert_signals_inserts_rows(self, db_path):
        import pandas as pd

        from nuri.core.db.market_data import upsert_signals

        df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "date": "2026-05-06",
                    "rsi_14": 55.0,
                    "macd": 0.5,
                    "macd_signal": 0.4,
                    "macd_hist": 0.1,
                    "bb_upper": 210,
                    "bb_middle": 200,
                    "bb_lower": 190,
                    "sma_20": 200,
                    "sma_50": 195,
                    "sma_200": 180,
                    "ema_12": 202,
                    "ema_26": 198,
                },
            ]
        )
        result = upsert_signals(df, db_path=db_path)
        assert result == 1

    def test_upsert_signals_empty_df_returns_zero(self, db_path):
        import pandas as pd

        from nuri.core.db.market_data import upsert_signals

        assert upsert_signals(pd.DataFrame(), db_path=db_path) == 0
