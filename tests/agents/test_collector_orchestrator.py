"""CollectorOrchestrator tests (#529 Phase 2 — actor #1, canonical, Layer B).

검증:
- Layer B (deterministic, ZERO LLM)
- 3 actions: orchestrate / scan_health / list_recent
- orchestrate happy path / under-fetch WARN / final-fail BLOCK
- Retry classification (rate_limited / timeout / failed) + exponential backoff
- scan_health PASS / WARN / BLOCK + per-collector aggregation
- list_recent ordering + filtering
- Discord publish (mock) routing (OPS / INCIDENTS)
- HelperLockTests (status enum 위반 시 ValueError)
- audit_ledger 자동 기록
- CLI

Anti-leak Lock-Test (Gotcha-Test Pair §5.3.1):
- log_collector_run status enum 위반 시 ValueError 가 떠야 함 — 위 contract 가
  무력화되면 sqlite CHECK 만 남고 helper-level guard 사라짐.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuri.agents.actors.collector_orchestrator import (
    CollectorOrchestrator,
    _classify_error,
    main,
    make_collector_fn,
)
from nuri.agents.base import Layer, Outcome
from nuri.core.db import init_db, log_collector_run, query


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "collector.db"
    init_db(path)
    return path


@pytest.fixture
def patched_db(db_path):
    """base + actor 의 db 호출을 임시 path 로 redirect."""
    from nuri.core import db as db_module

    def make_redirect(fn):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("db_path", db_path)
            return fn(*args, **kwargs)

        return wrapped

    patches = [
        patch(
            "nuri.agents.base.log_agent_audit",
            side_effect=make_redirect(db_module.log_agent_audit),
        ),
        patch(
            "nuri.agents.base.start_agent_run",
            side_effect=make_redirect(db_module.start_agent_run),
        ),
        patch(
            "nuri.agents.base.finish_agent_run",
            side_effect=make_redirect(db_module.finish_agent_run),
        ),
        patch(
            "nuri.agents.actors.collector_orchestrator.log_collector_run",
            side_effect=make_redirect(db_module.log_collector_run),
        ),
        patch(
            "nuri.agents.actors.collector_orchestrator.query",
            side_effect=make_redirect(db_module.query),
        ),
    ]
    for p in patches:
        p.start()
    yield db_path
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def _patch_sleep():
    """exponential backoff sleep mock — 테스트 시간 단축."""
    with patch("nuri.agents.actors.collector_orchestrator.time.sleep") as m:
        yield m


# ═══════════════════════════════════════════════════════
# Layer B invariants
# ═══════════════════════════════════════════════════════


class TestActorRegistration:
    def test_layer_is_b(self):
        assert CollectorOrchestrator.layer == Layer.B

    def test_no_llm_dependency(self):
        assert getattr(CollectorOrchestrator, "_uses_llm", False) is False

    def test_registered_in_canonical_15(self):
        from nuri.agents.base import REGISTRY

        assert REGISTRY.get("collector-orchestrator") is CollectorOrchestrator

    def test_valid_actions(self):
        assert CollectorOrchestrator.VALID_ACTIONS == (
            "orchestrate",
            "scan_health",
            "list_recent",
        )


# ═══════════════════════════════════════════════════════
# _classify_error helper
# ═══════════════════════════════════════════════════════


class TestClassifyError:
    def test_timeout_error(self):
        assert _classify_error(TimeoutError("timed out")) == "timeout"

    def test_timeout_message(self):
        assert _classify_error(RuntimeError("operation timeout")) == "timeout"

    def test_rate_limit_429(self):
        assert _classify_error(RuntimeError("HTTP 429 too many")) == "rate_limited"

    def test_rate_limit_keyword(self):
        assert _classify_error(RuntimeError("rate limit exceeded")) == "rate_limited"

    def test_throttle_keyword(self):
        assert _classify_error(RuntimeError("throttle hit")) == "rate_limited"

    def test_generic_failed(self):
        assert _classify_error(ValueError("bad payload")) == "failed"


# ═══════════════════════════════════════════════════════
# Helper Lock-Test — log_collector_run enum guard
# ═══════════════════════════════════════════════════════


class TestHelperLockTest:
    """LOCK-TEST (§5.3.1): log_collector_run 의 enum 검증이 무력화되면 fail."""

    def test_invalid_status_raises(self, db_path):
        with pytest.raises(ValueError, match="status must be one of"):
            log_collector_run(
                collector_name="x",
                status="bogus",
                db_path=db_path,
            )

    def test_valid_statuses_accepted(self, db_path):
        for status in ("started", "finished", "failed", "timeout", "rate_limited"):
            run_id = log_collector_run(
                collector_name="x",
                status=status,
                db_path=db_path,
            )
            assert run_id > 0


# ═══════════════════════════════════════════════════════
# Action: orchestrate — happy path
# ═══════════════════════════════════════════════════════


class TestOrchestrateHappyPath:
    def test_pass_when_rows_meet_expected(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": lambda: list(range(100)),
                "expected_rows": 100,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["rows_collected"] == 100
        assert len(result.output["attempts"]) == 1
        assert result.output["attempts"][0]["status"] == "finished"

    def test_pass_with_no_expected_rows(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "yfinance",
                "collector_fn": lambda: 5,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["rows_collected"] == 5

    def test_persisted_to_collector_runs(self, patched_db):
        actor = CollectorOrchestrator()
        actor.run(
            {
                "action": "orchestrate",
                "collector_name": "fred",
                "collector_fn": lambda: [1, 2, 3],
            }
        )
        rows = query(
            "SELECT collector_name, status, rows_collected FROM collector_runs WHERE collector_name = 'fred'",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "finished"
        assert rows[0]["rows_collected"] == 3


# ═══════════════════════════════════════════════════════
# Action: orchestrate — under-fetch WARN
# ═══════════════════════════════════════════════════════


class TestOrchestrateWarn:
    def test_warn_when_rows_under_threshold(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "pykrx",
                "collector_fn": lambda: list(range(50)),  # 50 / 100 = 50% < 90%
                "expected_rows": 100,
            }
        )
        assert result.outcome == Outcome.WARN
        assert result.output["rows_collected"] == 50

    def test_pass_at_90_percent_margin(self, patched_db):
        actor = CollectorOrchestrator()
        # 92 / 100 = 92% >= 90% → PASS
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "pykrx",
                "collector_fn": lambda: list(range(92)),
                "expected_rows": 100,
            }
        )
        assert result.outcome == Outcome.PASS


# ═══════════════════════════════════════════════════════
# Action: orchestrate — retry / final-fail
# ═══════════════════════════════════════════════════════


class TestOrchestrateRetry:
    def test_rate_limited_then_finished_is_warn_not_pass(self, patched_db):
        """재시도로 살아났어도 rate limit 을 맞았으면 **WARN** 이다.

        PASS 로 적으면 IP ban 직전까지 아무 신호가 없다 — 재시도가 벌어준 시간이
        그대로 사라진다. `rate_limit_hits` 는 예전에도 세어서 DB 에 넣고 있었고,
        빠져 있던 건 그걸 Outcome 에 드러내는 것뿐이었다 (carry-over audit N4).
        """
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("HTTP 429 rate limit")
            return [1, 2, 3]

        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "yfinance",
                "collector_fn": flaky,
                "max_retries": 3,
            }
        )
        assert result.outcome == Outcome.WARN, "rate limit 을 맞은 런이 PASS 로 기록되면 안 된다"
        assert call_count["n"] == 3
        assert result.output["rate_limit_hits"] == 2
        # 2 rate_limited attempts + 1 finished
        statuses = [a["status"] for a in result.output["attempts"]]
        assert statuses == ["rate_limited", "rate_limited", "finished"]

    def test_timeout_then_block(self, patched_db):
        def always_timeout():
            raise TimeoutError("operation timed out")

        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": always_timeout,
                "max_retries": 2,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert len(result.output["attempts"]) == 3  # 1 + 2 retries
        assert all(a["status"] == "timeout" for a in result.output["attempts"])

    def test_generic_failure_then_block(self, patched_db):
        def always_fail():
            raise ValueError("bad payload")

        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "finviz",
                "collector_fn": always_fail,
                "max_retries": 1,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert len(result.output["attempts"]) == 2
        assert all(a["status"] == "failed" for a in result.output["attempts"])

    def test_zero_retries_immediate_block(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "finviz",
                "collector_fn": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                "max_retries": 0,
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert len(result.output["attempts"]) == 1

    def test_backoff_progression(self, patched_db, _patch_sleep):
        def always_fail():
            raise ValueError("boom")

        actor = CollectorOrchestrator()
        actor.run(
            {
                "action": "orchestrate",
                "collector_name": "finviz",
                "collector_fn": always_fail,
                "max_retries": 3,
            }
        )
        # 3 retries → 3 sleep calls (after attempt 0/1/2; not after final attempt 3).
        sleep_args = [c.args[0] for c in _patch_sleep.call_args_list]
        assert sleep_args == [1.0, 2.0, 4.0]


# ═══════════════════════════════════════════════════════
# Action: orchestrate — input validation
# ═══════════════════════════════════════════════════════


class TestOrchestrateInputValidation:
    def test_invalid_action_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run({"action": "weird"})
        assert result.outcome == Outcome.BLOCK

    def test_missing_collector_name_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_fn": lambda: [],
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "collector_name" in result.output["error"]

    def test_missing_collector_fn_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
            }
        )
        assert result.outcome == Outcome.BLOCK
        assert "collector_fn" in result.output["error"]

    def test_negative_max_retries_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": lambda: [],
                "max_retries": -1,
            }
        )
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Action: scan_health
# ═══════════════════════════════════════════════════════


class TestScanHealth:
    def _seed(self, db_path, name, statuses):
        for s in statuses:
            log_collector_run(collector_name=name, status=s, db_path=db_path)

    def test_no_data_returns_pass(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 24})
        assert result.outcome == Outcome.PASS
        assert result.output["collector_count"] == 0

    def test_all_healthy_pass(self, patched_db):
        self._seed(patched_db, "kis_prices", ["finished"] * 10)
        self._seed(patched_db, "yfinance", ["finished"] * 5 + ["failed"])
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 24})
        assert result.outcome == Outcome.PASS
        assert result.output["unhealthy_count"] == 0
        assert result.output["collector_count"] == 2

    def test_one_unhealthy_warn(self, patched_db):
        self._seed(patched_db, "kis_prices", ["finished"] * 10)
        # 4 fail / 5 total = 80% failure → unhealthy
        self._seed(patched_db, "yfinance", ["failed"] * 4 + ["finished"])
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 24})
        assert result.outcome == Outcome.WARN
        assert result.output["unhealthy_count"] == 1
        unhealthy = [s for s in result.output["summaries"] if s["health_status"] == "unhealthy"]
        assert unhealthy[0]["collector_name"] == "yfinance"

    def test_all_unhealthy_block(self, patched_db):
        self._seed(patched_db, "kis_prices", ["failed"] * 5)
        self._seed(patched_db, "yfinance", ["timeout"] * 5)
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 24})
        assert result.outcome == Outcome.BLOCK
        assert result.output["unhealthy_count"] == 2

    def test_invalid_hours_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 0})
        assert result.outcome == Outcome.BLOCK

    def test_pass_rate_computation(self, patched_db):
        self._seed(patched_db, "kis_prices", ["finished"] * 7 + ["failed"] * 3)
        actor = CollectorOrchestrator()
        result = actor.run({"action": "scan_health", "hours": 24})
        summary = result.output["summaries"][0]
        assert summary["total_runs"] == 10
        assert summary["pass_rate"] == 0.7


# ═══════════════════════════════════════════════════════
# Action: list_recent
# ═══════════════════════════════════════════════════════


class TestListRecent:
    def test_lists_all_when_no_filter(self, patched_db):
        for name in ("kis_prices", "yfinance", "fred"):
            log_collector_run(collector_name=name, status="finished", db_path=patched_db)
        actor = CollectorOrchestrator()
        result = actor.run({"action": "list_recent", "limit": 10})
        assert result.outcome == Outcome.PASS
        assert result.output["count"] == 3

    def test_filters_by_collector_name(self, patched_db):
        log_collector_run(collector_name="kis_prices", status="finished", db_path=patched_db)
        log_collector_run(collector_name="yfinance", status="finished", db_path=patched_db)
        actor = CollectorOrchestrator()
        result = actor.run({"action": "list_recent", "collector_name": "yfinance", "limit": 10})
        assert result.output["count"] == 1
        assert result.output["runs"][0]["collector_name"] == "yfinance"

    def test_limit_enforced(self, patched_db):
        for _ in range(5):
            log_collector_run(
                collector_name="kis_prices",
                status="finished",
                db_path=patched_db,
            )
        actor = CollectorOrchestrator()
        result = actor.run({"action": "list_recent", "limit": 3})
        assert result.output["count"] == 3

    def test_invalid_limit_blocks(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run({"action": "list_recent", "limit": 0})
        assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Discord publish (mocked)
# ═══════════════════════════════════════════════════════


class TestDiscordPublish:
    def test_orchestrate_failure_stages_to_ops(self, patched_db):
        """orchestrate failure → outbox stage_ops (PR3 Codex Round 6)."""
        with patch("nuri.agents.discord.outbox.stage_ops") as mock_stage:
            actor = CollectorOrchestrator()
            actor.run(
                {
                    "action": "orchestrate",
                    "collector_name": "kis_prices",
                    "collector_fn": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                    "max_retries": 0,
                }
            )
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "collector_failure"

    def test_scan_health_block_stages_to_incidents(self, patched_db):
        for name in ("kis_prices", "yfinance"):
            for _ in range(5):
                log_collector_run(collector_name=name, status="failed", db_path=patched_db)
        with patch("nuri.agents.discord.outbox.stage_incident") as mock_stage:
            actor = CollectorOrchestrator()
            actor.run({"action": "scan_health", "hours": 24})
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "collector_health_catastrophic"

    def test_scan_health_warn_stages_to_ops(self, patched_db):
        log_collector_run(collector_name="kis_prices", status="finished", db_path=patched_db)
        for _ in range(5):
            log_collector_run(collector_name="yfinance", status="failed", db_path=patched_db)
        with patch("nuri.agents.discord.outbox.stage_ops") as mock_stage:
            actor = CollectorOrchestrator()
            actor.run({"action": "scan_health", "hours": 24})
            mock_stage.assert_called_once()
            assert mock_stage.call_args.kwargs["payload"]["kind"] == "collector_health_warn"

    def test_publish_failure_does_not_break_actor(self, patched_db):
        """Discord 가 raise 해도 actor outcome 영향 없음 — best-effort 보장."""
        with patch("nuri.agents.discord.publisher.DiscordPublisher") as MockPub:
            MockPub.return_value.publish_embed.side_effect = RuntimeError("discord down")
            actor = CollectorOrchestrator()
            result = actor.run(
                {
                    "action": "orchestrate",
                    "collector_name": "kis_prices",
                    "collector_fn": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                    "max_retries": 0,
                }
            )
            assert result.outcome == Outcome.BLOCK


# ═══════════════════════════════════════════════════════
# Audit trail integration
# ═══════════════════════════════════════════════════════


class TestAuditTrail:
    def test_orchestrate_logged_to_audit_ledger(self, patched_db):
        actor = CollectorOrchestrator()
        actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": lambda: [1, 2, 3],
            }
        )
        rows = query(
            "SELECT actor_name, layer, outcome FROM agent_audit_ledger WHERE actor_name = 'collector-orchestrator'",
            db_path=patched_db,
        )
        assert len(rows) >= 1
        assert rows[0]["layer"] == "B"
        assert rows[0]["outcome"] == "pass"

    def test_actor_run_id_propagated_to_collector_runs(self, patched_db):
        actor = CollectorOrchestrator()
        actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": lambda: [1, 2, 3],
            }
        )
        rows = query(
            "SELECT actor_run_id FROM collector_runs WHERE collector_name = 'kis_prices'",
            db_path=patched_db,
        )
        assert len(rows) == 1
        assert rows[0]["actor_run_id"] is not None


# ═══════════════════════════════════════════════════════
# make_collector_fn helper
# ═══════════════════════════════════════════════════════


class TestMakeCollectorFn:
    def test_wraps_args(self, patched_db):
        def src(a, b):
            return [a, b]

        wrapped = make_collector_fn(src, 1, b=2)
        assert wrapped() == [1, 2]

    def test_orchestrate_with_wrapped_fn(self, patched_db):
        def src(n):
            return list(range(n))

        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "kis_prices",
                "collector_fn": make_collector_fn(src, 7),
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["rows_collected"] == 7


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


class TestCli:
    def test_cli_scan_health_no_data(self, patched_db, capsys):
        rc = main(["scan_health", "--hours", "24"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "collector_count" in out

    def test_cli_list_recent(self, patched_db, capsys):
        log_collector_run(
            collector_name="kis_prices",
            status="finished",
            db_path=patched_db,
        )
        rc = main(["list_recent", "--limit", "5"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "kis_prices" in out

    def test_cli_warn_returns_1(self, patched_db, capsys):
        # 1 healthy + 1 unhealthy → WARN → rc=1
        log_collector_run(collector_name="kis_prices", status="finished", db_path=patched_db)
        for _ in range(5):
            log_collector_run(collector_name="yfinance", status="failed", db_path=patched_db)
        rc = main(["scan_health", "--hours", "24"])
        assert rc == 1

    def test_cli_block_returns_2(self, patched_db, capsys):
        # 모두 unhealthy → BLOCK → rc=2
        for _ in range(5):
            log_collector_run(collector_name="kis_prices", status="failed", db_path=patched_db)
        rc = main(["scan_health", "--hours", "24"])
        assert rc == 2


# ═══════════════════════════════════════════════════════
# _extract_row_count edge cases
# ═══════════════════════════════════════════════════════


class TestExtractRowCount:
    def test_none_returns_zero(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "fred",
                "collector_fn": lambda: None,
            }
        )
        assert result.outcome == Outcome.PASS
        assert result.output["rows_collected"] == 0

    def test_negative_int_clamps_to_zero(self, patched_db):
        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "fred",
                "collector_fn": lambda: -3,
            }
        )
        assert result.output["rows_collected"] == 0

    def test_unsized_object_returns_zero(self, patched_db):
        class Bare:
            pass

        actor = CollectorOrchestrator()
        result = actor.run(
            {
                "action": "orchestrate",
                "collector_name": "fred",
                "collector_fn": lambda: Bare(),
            }
        )
        assert result.output["rows_collected"] == 0


class TestRateLimitIsSurfacedNotSwallowed:
    """rate limit 신호가 Outcome 까지 올라오는지 (carry-over audit N4).

    DB 에는 예전부터 `rate_limit_hits` 가 들어가고 있었다. 빠져 있던 건 그걸
    **읽는 쪽**이다 — Outcome 이 PASS 면 아무도 안 본다.
    """

    def test_clean_run_stays_pass(self, patched_db):
        """rate limit 이 없으면 WARN 으로 올리지 않는다 — 경보 피로 방지."""
        actor = CollectorOrchestrator()
        result = actor.run({"action": "orchestrate", "collector_name": "yfinance", "collector_fn": lambda: [1, 2, 3]})
        assert result.outcome == Outcome.PASS
        assert result.output["rate_limit_hits"] == 0

    def test_single_rate_limit_hit_is_enough_to_warn(self, patched_db):
        """한 번만 맞아도 신호다. 임계값을 두면 그 값이 또 하나의 매직넘버가 된다."""
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("HTTP 429")
            return [1]

        result = CollectorOrchestrator().run(
            {"action": "orchestrate", "collector_name": "yfinance", "collector_fn": flaky, "max_retries": 3}
        )
        assert result.outcome == Outcome.WARN
        assert result.output["rate_limit_hits"] == 1

    def test_non_rate_limit_retry_stays_pass(self, patched_db):
        """일시적 timeout 은 rate limit 이 아니다 — 여기까지 WARN 으로 올리면 노이즈다."""
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return [1]

        result = CollectorOrchestrator().run(
            {"action": "orchestrate", "collector_name": "yfinance", "collector_fn": flaky, "max_retries": 3}
        )
        assert result.outcome == Outcome.PASS
        assert result.output["rate_limit_hits"] == 0
