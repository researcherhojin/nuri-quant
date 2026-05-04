"""Lock-tests for `nuri/core/db/postmortem_ops.py` (#596 Phase 2).

- Migration #44 applies → market_postmortem table + indices exist
- upsert_postmortem idempotent on (date, session) PK
- Session validation rejects unknown values
- find_similar_days top-k cosine ranking
- exclude_date drops the calling row from candidates
- regime one-hot orthogonalises distinct regimes even with otherwise identical numerics
- Empty corpus returns []
"""

from __future__ import annotations

import pytest

from nuri.core.db import find_similar_days, init_db, query, upsert_postmortem


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "post.db"
    init_db(p)
    return p


class TestMigration44:
    def test_table_exists(self, db_path):
        rows = query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_postmortem'",
            db_path=db_path,
        )
        assert len(rows) == 1

    def test_indices_exist(self, db_path):
        names = {
            r["name"]
            for r in query(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='market_postmortem'",
                db_path=db_path,
            )
        }
        assert "idx_postmortem_regime" in names
        assert "idx_postmortem_vix" in names


class TestUpsertPostmortem:
    def test_basic_insert(self, db_path):
        upsert_postmortem(
            "2026-04-01",
            "us",
            regime="bull",
            vix=15.0,
            fear_greed=70.0,
            macro_summary={"vix": {"value": 15.0}},
            db_path=db_path,
        )
        rows = query("SELECT * FROM market_postmortem", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["regime"] == "bull"
        assert rows[0]["vix"] == 15.0

    def test_pk_idempotent_overwrites(self, db_path):
        upsert_postmortem("2026-04-01", "us", vix=15.0, db_path=db_path)
        upsert_postmortem("2026-04-01", "us", vix=16.5, regime="bear", db_path=db_path)
        rows = query("SELECT vix, regime FROM market_postmortem", db_path=db_path)
        assert len(rows) == 1
        assert rows[0]["vix"] == 16.5
        assert rows[0]["regime"] == "bear"

    def test_distinct_session_coexists(self, db_path):
        upsert_postmortem("2026-04-01", "us", vix=15.0, db_path=db_path)
        upsert_postmortem("2026-04-01", "kr", vix=18.0, db_path=db_path)
        rows = query("SELECT * FROM market_postmortem ORDER BY session", db_path=db_path)
        assert len(rows) == 2
        assert {r["session"] for r in rows} == {"us", "kr"}

    def test_invalid_session_rejected(self, db_path):
        with pytest.raises(ValueError, match="session must be one of"):
            upsert_postmortem("2026-04-01", "asia", vix=15.0, db_path=db_path)

    def test_json_blobs_round_trip(self, db_path):
        upsert_postmortem(
            "2026-04-01",
            "us",
            sector_movers=[{"ticker": "XLK", "delta_pct": 1.5}],
            retro_lessons=["VIX < 16 → bullish bias"],
            db_path=db_path,
        )
        import json

        rows = query("SELECT sector_movers, retro_lessons FROM market_postmortem", db_path=db_path)
        assert json.loads(rows[0]["sector_movers"])[0]["ticker"] == "XLK"
        assert "VIX" in json.loads(rows[0]["retro_lessons"])[0]


class TestFindSimilarDays:
    def _seed(self, db_path):
        upsert_postmortem(
            "2026-04-01",
            "us",
            regime="bull",
            vix=15.0,
            fear_greed=70.0,
            vix_5d_delta=-1.0,
            fg_5d_delta=5.0,
            spy_5d_delta=2.5,
            top_sector_delta_pct=1.5,
            holdings_total_pnl_pct=0.8,
            db_path=db_path,
        )
        upsert_postmortem(
            "2026-04-02",
            "us",
            regime="bull",
            vix=14.5,
            fear_greed=72.0,
            vix_5d_delta=-1.5,
            fg_5d_delta=4.5,
            spy_5d_delta=2.0,
            top_sector_delta_pct=1.2,
            holdings_total_pnl_pct=0.6,
            db_path=db_path,
        )
        upsert_postmortem(
            "2026-04-03",
            "us",
            regime="bear",
            vix=35.0,
            fear_greed=20.0,
            vix_5d_delta=10.0,
            fg_5d_delta=-30.0,
            spy_5d_delta=-3.5,
            top_sector_delta_pct=-2.0,
            holdings_total_pnl_pct=-1.5,
            db_path=db_path,
        )

    def test_empty_corpus_returns_empty(self, db_path):
        assert find_similar_days(session="us", regime="bull", db_path=db_path) == []

    def test_top_k_ranks_by_similarity(self, db_path):
        self._seed(db_path)
        sims = find_similar_days(
            session="us",
            regime="bull",
            vix=15.0,
            fear_greed=71.0,
            vix_5d_delta=-1.0,
            fg_5d_delta=5.0,
            spy_5d_delta=2.4,
            top_sector_delta_pct=1.4,
            holdings_total_pnl_pct=0.7,
            k=2,
            db_path=db_path,
        )
        assert len(sims) == 2
        # bull-similar dates should rank above the bear day
        assert sims[0]["date"] in ("2026-04-01", "2026-04-02")
        assert sims[0]["similarity"] > sims[1]["similarity"]

    def test_session_isolation(self, db_path):
        self._seed(db_path)
        # add KR row with same numerics as one of the bull-US days
        upsert_postmortem("2026-04-02", "kr", regime="bull", vix=14.5, db_path=db_path)
        sims_us = find_similar_days(session="us", regime="bull", vix=15.0, db_path=db_path)
        assert all(s["session"] == "us" for s in sims_us)
        sims_kr = find_similar_days(session="kr", regime="bull", vix=14.5, db_path=db_path)
        assert len(sims_kr) == 1
        assert sims_kr[0]["session"] == "kr"

    def test_exclude_date_drops_self(self, db_path):
        self._seed(db_path)
        sims = find_similar_days(
            session="us",
            regime="bull",
            vix=15.0,
            k=5,
            exclude_date="2026-04-02",
            db_path=db_path,
        )
        assert "2026-04-02" not in {s["date"] for s in sims}

    def test_regime_one_hot_separates_distinct_regimes(self, db_path):
        # Two rows w/ identical numerics but different regimes — distinct regime
        # should drop similarity below 1.0 even with matching scalars
        upsert_postmortem("2026-04-10", "us", regime="bull", vix=20.0, fear_greed=50.0, db_path=db_path)
        upsert_postmortem("2026-04-11", "us", regime="bear", vix=20.0, fear_greed=50.0, db_path=db_path)
        # Query as 'bull' → bull-row must rank strictly higher than bear-row
        sims = find_similar_days(
            session="us",
            regime="bull",
            vix=20.0,
            fear_greed=50.0,
            k=2,
            db_path=db_path,
        )
        bull_sim = next(s["similarity"] for s in sims if s["regime"] == "bull")
        bear_sim = next(s["similarity"] for s in sims if s["regime"] == "bear")
        assert bull_sim > bear_sim

    def test_invalid_session_rejected(self, db_path):
        with pytest.raises(ValueError, match="session must be one of"):
            find_similar_days(session="eu", db_path=db_path)

    def test_k_zero_returns_empty(self, db_path):
        self._seed(db_path)
        assert find_similar_days(session="us", regime="bull", k=0, db_path=db_path) == []
