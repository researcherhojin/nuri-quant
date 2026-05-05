"""audit_ledger.py branch coverage — Issue #616 Phase 3-C3.

| line | branch / stmt | trigger |
|---|---|---|
| 170→165 | `elif key in totals:` False | DB row 의 outcome key 가 4종 외 (defensive) |
| 204-205 | `since_iso` clauses append | summarize_by_actor 호출 시 since_iso 인자 |
| 217→219 | `if outcome_key in slot:` False | DB row 의 outcome key 가 4종 외 |
"""

from __future__ import annotations

from unittest.mock import patch


class TestSummarizeByOutcomeUnknownKey:
    def test_unknown_outcome_key_skips_totals_update(self):
        """170→165: row 에 totals 4종(pass/block/warn/error) 도 None 도 아닌 outcome
        → 두 elif 모두 False → 다음 iter 로 fall through.
        """
        from nuri.agents.actors.audit_ledger import AuditLedger
        from nuri.agents.base import Outcome

        # mock query → 'foo' 라는 unknown outcome row 1개 + valid 'pass' row 1개
        fake_rows = [
            {"outcome": "foo", "cnt": 5},  # 170 elif False → skip
            {"outcome": "pass", "cnt": 3},
        ]
        with patch("nuri.agents.actors.audit_ledger.query", return_value=fake_rows):
            actor = AuditLedger()
            result = actor._summarize_by_outcome({"action": "summarize_by_outcome"})

        assert result.outcome == Outcome.PASS
        assert result.output["totals"]["pass"] == 3
        # foo 는 어디에도 누적 안 됨 (None 도 아니라 unset 에도 안 들어감 — 누락 OK)
        assert "foo" not in result.output["totals"]


class TestSummarizeByActorSinceIso:
    def test_since_iso_appends_clause(self):
        """204-205: since_iso 인자 → WHERE timestamp 절 추가."""
        from nuri.agents.actors.audit_ledger import AuditLedger

        captured_sql = []

        def _spy_query(sql, params=()):
            captured_sql.append((sql, params))
            return []

        with patch("nuri.agents.actors.audit_ledger.query", side_effect=_spy_query):
            actor = AuditLedger()
            actor._summarize_by_actor(
                {"action": "summarize_by_actor", "since_iso": "2026-01-01T00:00:00"},
            )

        sql, params = captured_sql[0]
        assert "timestamp >= ?" in sql
        assert "2026-01-01T00:00:00" in params

    def test_unknown_outcome_in_actor_only_total_increments(self):
        """217→219: row outcome 이 4종 외 → slot 키 update skip → total 만 증가."""
        from nuri.agents.actors.audit_ledger import AuditLedger

        fake_rows = [
            {"actor_name": "actor_x", "outcome": "weird", "cnt": 7},  # 217 False
            {"actor_name": "actor_x", "outcome": "pass", "cnt": 2},
        ]
        with patch("nuri.agents.actors.audit_ledger.query", return_value=fake_rows):
            actor = AuditLedger()
            result = actor._summarize_by_actor({"action": "summarize_by_actor"})

        actor_x = result.output["actors"]["actor_x"]
        assert actor_x["pass"] == 2
        assert actor_x["total"] == 9  # 7 + 2 (weird 도 total 에 반영)
        assert actor_x["block"] == 0  # weird 는 어떤 slot 키에도 안 더해짐
