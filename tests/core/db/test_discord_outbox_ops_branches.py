"""Branch coverage for `nuri.core.db.discord_outbox_ops` (#610).

Targets validation + edge-case branches that aren't reached by the existing
single-writer outbox tests:
- channel/priority/dedupe_strategy validation errors
- scheduled_for path (vs default datetime('now'))
- claim_pending invalid channel guard
- JSON decode fallback in claim_pending
- mark_outbox_sent / mark_outbox_failed empty-ids early return
"""

from __future__ import annotations

import pytest

from nuri.core.db import init_db
from nuri.core.db.discord_outbox_ops import (
    claim_pending_outbox,
    mark_outbox_failed,
    mark_outbox_sent,
    stage_outbox,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "outbox.db"
    init_db(path)
    return path


class TestStageOutboxValidation:
    def test_invalid_channel_raises(self, db_path):
        with pytest.raises(ValueError, match="channel must be"):
            stage_outbox("nonexistent", {"x": 1}, db_path=db_path)

    def test_invalid_priority_raises(self, db_path):
        with pytest.raises(ValueError, match="priority must be"):
            stage_outbox("ops", {"x": 1}, priority="urgent", db_path=db_path)

    def test_invalid_dedupe_strategy_raises(self, db_path):
        with pytest.raises(ValueError, match="dedupe_strategy must be"):
            stage_outbox("ops", {"x": 1}, dedupe_strategy="merge", db_path=db_path)


class TestStageOutboxScheduled:
    def test_scheduled_for_path_inserts_with_explicit_timestamp(self, db_path):
        rid = stage_outbox(
            "ops",
            {"text": "future"},
            scheduled_for="2030-01-01 00:00:00",
            db_path=db_path,
        )
        assert rid is not None and rid > 0


class TestClaimValidation:
    def test_invalid_channel_raises(self, db_path):
        with pytest.raises(ValueError, match="channel must be"):
            claim_pending_outbox("totally-fake", db_path=db_path)


class TestClaimJSONFallback:
    def test_corrupt_payload_decodes_to_empty_dict(self, db_path):
        # Stage a row, then corrupt its payload_json directly via raw write helper
        from nuri.core.db.connection import get_db

        rid = stage_outbox("ops", {"original": True}, db_path=db_path)
        assert rid is not None
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE discord_outbox SET payload_json = ? WHERE id = ?",
                ("{not-json", rid),
            )

        token, claimed = claim_pending_outbox("ops", limit=10, db_path=db_path)
        assert claimed and claimed[0]["payload"] == {}


class TestMarkEmptyIds:
    def test_mark_sent_empty_returns_zero(self, db_path):
        assert mark_outbox_sent([], "tok", db_path=db_path) == 0

    def test_mark_failed_empty_returns_zero(self, db_path):
        assert mark_outbox_failed([], "tok", "err", db_path=db_path) == 0
