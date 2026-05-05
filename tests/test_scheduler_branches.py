"""Branch coverage tests for nuri.scheduler — fills gaps not covered by test_scheduler.py.

Targets:
- _configure_logging OSError on mkdir (lines 56-58, read-only FS)
- _run_collector branches: macro_news (111-113), kis_analyst_opinion (119-121),
  holdings_monitor (165-169)
- _run_premarket_brief success+error (182-187)
- _run_brief_audit success+error (227-237)
- _run_channel_dispatcher success/skipped/error (245-258)
- _run_held_add_shadow success+error (287-329)
- _run_outbox_watchdog healthy/breach/error (319-329)
- _write_heartbeat exception swallow (455-456)
- main shutdown handler (545-547)
- __main__ guard (558)
"""

# cspell:ignore sandboxed

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# _configure_logging branches
# ─────────────────────────────────────────────


class TestConfigureLoggingReadOnlyFS:
    """Lines 54-58: OSError on mkdir (read-only FS) keeps console-only logging."""

    def test_oserror_on_mkdir_returns_without_handler(self, tmp_path, monkeypatch):
        """When `log_dir.mkdir(...)` raises OSError, _configure_logging must return
        early — no RotatingFileHandler attached. Covers lines 55-58 (the try/except
        OSError -> return branch).
        """
        import importlib
        import logging
        import logging.handlers

        # Set env var so we hit the file-handler path, but force mkdir to raise.
        monkeypatch.setenv("NURI_SCHEDULER_LOG_DIR", str(tmp_path / "ro"))
        monkeypatch.delenv("NURI_SCHEDULER_LOG_DISABLE_FILE", raising=False)

        # Patch Path.mkdir at the class level so the call inside _configure_logging
        # raises OSError (simulates read-only filesystem / sandboxed CI).
        from pathlib import Path as _Path

        original_mkdir = _Path.mkdir

        def boom(self, *a, **kw):
            if str(self).startswith(str(tmp_path / "ro")):
                raise OSError("read-only fs")
            return original_mkdir(self, *a, **kw)

        monkeypatch.setattr(_Path, "mkdir", boom)

        # Snapshot existing handlers BEFORE reload to avoid false positives from
        # earlier tests' RotatingFileHandlers.
        root = logging.getLogger()
        before = {id(h) for h in root.handlers}

        import nuri.scheduler

        importlib.reload(nuri.scheduler)
        try:
            new_rotating = [
                h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler) and id(h) not in before
            ]
            # The early return on OSError means no NEW rotating handler was attached.
            assert new_rotating == [], (
                f"OSError on mkdir must short-circuit before RotatingFileHandler "
                f"attach (got {len(new_rotating)} new handler(s))"
            )
        finally:
            for h in list(root.handlers):
                if isinstance(h, logging.handlers.RotatingFileHandler) and id(h) not in before:
                    h.close()
                    root.removeHandler(h)


# ─────────────────────────────────────────────
# _run_collector — uncovered name branches
# ─────────────────────────────────────────────


class TestRunCollectorRemainingBranches:
    """Cover collector dispatch branches not exercised in test_scheduler.py."""

    def test_macro_news_dispatch(self):
        """Lines 110-113: macro_news → MacroNewsCollector.run()."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch("nuri.collectors.macro_news.MacroNewsCollector", return_value=mock_collector):
            _run_collector("macro_news")
        # The behavior under test: dispatch routes to the run() method exactly once.
        mock_collector.run.assert_called_once_with()

    def test_kis_analyst_opinion_dispatch(self):
        """Lines 118-121: kis_analyst_opinion → KISAnalystOpinionCollector.run()."""
        from nuri.scheduler import _run_collector

        mock_collector = MagicMock()
        with patch(
            "nuri.collectors.kis_analyst_opinion.KISAnalystOpinionCollector",
            return_value=mock_collector,
        ):
            _run_collector("kis_analyst_opinion")
        mock_collector.run.assert_called_once_with()

    def test_holdings_monitor_dispatch_logs_summary(self, caplog):
        """Lines 161-171: holdings_monitor → run_monitor() + send_alerts(summary).

        The branch must:
          1) call run_monitor() once
          2) pass its return into send_alerts() once
          3) emit an INFO log containing the 3 counters (n_holdings, n_alerted, sent)
        Revert (e.g. dropping send_alerts) → counters wrong → log assert fails.
        """
        import logging

        from nuri.scheduler import _run_collector

        summary = SimpleNamespace(n_holdings=7, n_alerted=2)  # arbitrary distinct ints
        mock_run_monitor = MagicMock(return_value=summary)
        mock_send_alerts = MagicMock(return_value=2)  # 2 alerts surfaced

        with (
            patch("nuri.trading.recommend.holdings_monitor.run_monitor", mock_run_monitor),
            patch(
                "nuri.trading.recommend.holdings_monitor.send_alerts",
                mock_send_alerts,
            ),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_collector("holdings_monitor")

        mock_run_monitor.assert_called_once_with()
        mock_send_alerts.assert_called_once_with(summary)
        # Confirm the formatted log line contains all 3 distinct counters
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "7" in msgs and "2" in msgs and "holdings_monitor" in msgs


# ─────────────────────────────────────────────
# _run_premarket_brief
# ─────────────────────────────────────────────


class TestRunPremarketBrief:
    """Lines 176-187."""

    def test_success_calls_brief_main_with_empty_argv(self):
        """Line 185: brief_main([]) — empty list, not None."""
        from nuri.scheduler import _run_premarket_brief

        mock_brief = MagicMock()
        with patch("nuri.alerts.premarket_brief.main", mock_brief):
            _run_premarket_brief()
        mock_brief.assert_called_once_with([])

    def test_exception_swallowed(self, caplog):
        """Lines 186-187: exception inside brief_main must NOT propagate.

        Scheduler must keep running even if pre-market brief fails (DST switch,
        module import failure). Verify the error is logged at ERROR level.
        """
        import logging

        from nuri.scheduler import _run_premarket_brief

        with (
            patch("nuri.alerts.premarket_brief.main", side_effect=RuntimeError("boom")),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            _run_premarket_brief()  # MUST NOT raise

        assert any("premarket_brief" in r.getMessage() for r in caplog.records), (
            "Failure must be logged with the [premarket_brief] tag"
        )


# ─────────────────────────────────────────────
# _run_brief_audit
# ─────────────────────────────────────────────


class TestRunBriefAudit:
    """Lines 220-237."""

    def test_success_logs_three_counters(self, caplog):
        """Lines 227-235: BriefAuditor().run({hours:24}) → log decisions/found/emitted."""
        import logging

        from nuri.scheduler import _run_brief_audit

        result = SimpleNamespace(output={"decisions_audited": 9, "issues_found": 3, "issues_emitted": 1})
        mock_auditor_cls = MagicMock()
        mock_auditor_cls.return_value.run.return_value = result

        with (
            patch(
                "nuri.agents.actors.brief_auditor.BriefAuditor",
                mock_auditor_cls,
            ),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_brief_audit()

        # Verify run() called with the hours=24 contract (locked by docstring)
        mock_auditor_cls.return_value.run.assert_called_once_with({"hours": 24})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "decisions=9" in msgs and "found=3" in msgs and "emitted=1" in msgs

    def test_exception_swallowed(self, caplog):
        """Lines 236-237: exception → ERROR log, no raise."""
        import logging

        from nuri.scheduler import _run_brief_audit

        with (
            patch(
                "nuri.agents.actors.brief_auditor.BriefAuditor",
                side_effect=RuntimeError("brief boom"),
            ),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            _run_brief_audit()  # must not raise

        assert any("brief_audit" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────
# _run_channel_dispatcher
# ─────────────────────────────────────────────


class TestRunChannelDispatcher:
    """Lines 240-258 — 3 paths: skipped / sent / error."""

    def test_skipped_path_logs_skip_reason(self, caplog):
        """Lines 250-251: when output has 'skipped' key — log skipped reason only."""
        import logging

        from nuri.scheduler import _run_channel_dispatcher

        result = SimpleNamespace(output={"skipped": "quiet_period"})
        mock_disp_cls = MagicMock()
        mock_disp_cls.return_value.run.return_value = result

        with (
            patch(
                "nuri.agents.actors.channel_dispatcher.ChannelDispatcher",
                mock_disp_cls,
            ),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_channel_dispatcher("brief")

        mock_disp_cls.return_value.run.assert_called_once_with({"channel": "brief"})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "skipped=quiet_period" in msgs and "dispatcher:brief" in msgs

    def test_sent_path_logs_claimed_sent_http(self, caplog):
        """Lines 252-256: success path logs claimed_n / marked_sent_n / http_status."""
        import logging

        from nuri.scheduler import _run_channel_dispatcher

        result = SimpleNamespace(output={"claimed_n": 4, "marked_sent_n": 4, "http_status": 204})
        mock_disp_cls = MagicMock()
        mock_disp_cls.return_value.run.return_value = result

        with (
            patch(
                "nuri.agents.actors.channel_dispatcher.ChannelDispatcher",
                mock_disp_cls,
            ),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_channel_dispatcher("ops")

        msgs = " ".join(r.getMessage() for r in caplog.records)
        # 204 is the Discord webhook success status — used here as a distinguishing int
        assert "claimed=4" in msgs and "sent=4" in msgs and "http=204" in msgs

    def test_exception_swallowed(self, caplog):
        """Lines 257-258: exception inside dispatcher must not propagate."""
        import logging

        from nuri.scheduler import _run_channel_dispatcher

        with (
            patch(
                "nuri.agents.actors.channel_dispatcher.ChannelDispatcher",
                side_effect=RuntimeError("disp fail"),
            ),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            _run_channel_dispatcher("incidents")

        assert any("dispatcher:incidents" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────
# _run_held_add_shadow
# ─────────────────────────────────────────────


class TestRunHeldAddShadow:
    """Lines 261-314 — provider construction + emit_held_add_shadow + log."""

    def test_success_routes_providers_and_logs_counts(self, caplog):
        """Lines 272-312: providers built from collectors, passed into emit_held_add_shadow,
        n_emit/n_skip/shadow_mode logged.

        The behavioral lock here: the score provider must multiply factor composite
        by 100 (line 288). If a regression drops `* 100.0`, the captured score for
        AAA differs from the expected 42.0.
        """
        import logging

        from nuri.scheduler import _run_held_add_shadow

        # Snapshot returned by buy_candidate_emitter helpers
        factors = {"AAA": {"composite": 0.42}}  # 0.42 → expect score 42.0
        rsi_map = {"AAA": 65.0}
        prices = {"AAA": {"ret_5d": 0.03}}  # 3% 5d return → sector_mom proxy

        # Capture the providers passed into emit_held_add_shadow
        captured: dict = {}

        def fake_emit(*, score_provider, rsi_provider, regime_provider, sector_mom_provider):
            captured["score"] = score_provider("AAA")
            captured["rsi"] = rsi_provider("AAA")
            captured["regime"] = regime_provider()
            captured["sector_mom"] = sector_mom_provider("AAA")
            return SimpleNamespace(
                candidates=["AAA", "BBB"],  # 2 emit
                skipped=["CCC"],  # 1 skip
                shadow_mode=True,
                shadow_mode_until="2026-12-31",
            )

        with (
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_factor_scores",
                return_value=factors,
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_rsi_snapshot",
                return_value=rsi_map,
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_price_signals",
                return_value=prices,
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_regime",
                return_value=("BULL", 18.5),
            ),
            patch(
                "nuri.trading.recommend.held_add.emit_held_add_shadow",
                side_effect=fake_emit,
            ),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_held_add_shadow()

        # Behavioral assertions: providers wired correctly
        assert captured["score"] == pytest.approx(42.0), (
            "score provider must multiply factor composite by 100 (line 288)"
        )
        assert captured["rsi"] == 65.0
        assert captured["regime"] == ("BULL", 18.5)
        # sector_mom proxy = ret_5d (line 299)
        assert captured["sector_mom"] == pytest.approx(0.03)

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "held_add_shadow" in msgs
        assert "2건 emit" in msgs and "1건 skip" in msgs
        assert "shadow=True" in msgs

    def test_score_provider_handles_missing_factor(self):
        """Line 287-288: factors.get(t) returning None → composite default 0.0 → score 0.0.

        The (f or {}).get pattern guards against None. If revert to factors[t]['composite'],
        an unknown ticker raises KeyError.
        """
        from nuri.scheduler import _run_held_add_shadow

        captured: dict = {}

        def fake_emit(*, score_provider, **_):
            captured["unknown"] = score_provider("UNKNOWN")
            return SimpleNamespace(candidates=[], skipped=[], shadow_mode=True, shadow_mode_until=None)

        with (
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_factor_scores",
                return_value={},  # no entry for UNKNOWN
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_rsi_snapshot",
                return_value={},
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_price_signals",
                return_value={},
            ),
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_regime",
                return_value=("FLAT", 22.0),
            ),
            patch(
                "nuri.trading.recommend.held_add.emit_held_add_shadow",
                side_effect=fake_emit,
            ),
        ):
            _run_held_add_shadow()

        # 0.0 = explicit default from `(f or {}).get("composite", 0.0)`
        assert captured["unknown"] == 0.0

    def test_exception_swallowed(self, caplog):
        """Lines 313-314: any exception inside the closure → ERROR log, not raise."""
        import logging

        from nuri.scheduler import _run_held_add_shadow

        with (
            patch(
                "nuri.trading.recommend.buy_candidate_emitter._get_factor_scores",
                side_effect=RuntimeError("factor fail"),
            ),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            _run_held_add_shadow()  # must not raise

        assert any("held_add_shadow" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────
# _run_outbox_watchdog
# ─────────────────────────────────────────────


class TestRunOutboxWatchdog:
    """Lines 317-329."""

    def test_healthy_path_logs_healthy(self, caplog):
        """Lines 322-327: empty breaches → INFO 'healthy'."""
        import logging

        from nuri.scheduler import _run_outbox_watchdog

        result = SimpleNamespace(output={"breaches": []})
        mock_wd = MagicMock()
        mock_wd.return_value.run.return_value = result

        with (
            patch("nuri.agents.actors.outbox_watchdog.OutboxWatchdog", mock_wd),
            caplog.at_level(logging.INFO, logger="nuri.scheduler"),
        ):
            _run_outbox_watchdog()

        mock_wd.return_value.run.assert_called_once_with({})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "healthy" in msgs and "outbox_watchdog" in msgs

    def test_breach_path_warns(self, caplog):
        """Lines 323-325: non-empty breaches → WARNING with count."""
        import logging

        from nuri.scheduler import _run_outbox_watchdog

        result = SimpleNamespace(output={"breaches": ["b1", "b2", "b3"]})
        mock_wd = MagicMock()
        mock_wd.return_value.run.return_value = result

        with (
            patch("nuri.agents.actors.outbox_watchdog.OutboxWatchdog", mock_wd),
            caplog.at_level(logging.WARNING, logger="nuri.scheduler"),
        ):
            _run_outbox_watchdog()

        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warns) == 1
        # 3 breaches → "3 breach"
        assert "3 breach" in warns[0].getMessage()

    def test_exception_swallowed(self, caplog):
        """Lines 328-329: exception → ERROR log, not raise."""
        import logging

        from nuri.scheduler import _run_outbox_watchdog

        with (
            patch(
                "nuri.agents.actors.outbox_watchdog.OutboxWatchdog",
                side_effect=RuntimeError("wd fail"),
            ),
            caplog.at_level(logging.ERROR, logger="nuri.scheduler"),
        ):
            _run_outbox_watchdog()  # must not raise

        assert any("outbox_watchdog" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────
# _write_heartbeat exception path
# ─────────────────────────────────────────────


class TestWriteHeartbeatException:
    """Lines 455-456: exception inside _write_heartbeat must be silently swallowed
    (the API health check should never crash the scheduler loop)."""

    def test_oserror_on_write_swallowed(self, tmp_path, monkeypatch):
        """write_text() raises → bare `pass` covers (no log, no raise)."""
        import nuri.scheduler as sched_mod

        # Point heartbeat to a directory we'll make unwritable via patching write_text
        monkeypatch.setattr(sched_mod, "HEARTBEAT_PATH", tmp_path / ".hb")

        from pathlib import Path as _Path

        original = _Path.write_text

        def boom(self, *a, **kw):
            if self == tmp_path / ".hb":
                raise OSError("disk full")
            return original(self, *a, **kw)

        monkeypatch.setattr(_Path, "write_text", boom)

        # MUST NOT raise. The function returns None on the silent-swallow path.
        result = sched_mod._write_heartbeat()
        assert result is None
        # Heartbeat was NOT created (write failed before content landed)
        assert not (tmp_path / ".hb").exists()


# ─────────────────────────────────────────────
# main shutdown handler
# ─────────────────────────────────────────────


class TestMainShutdownHandler:
    """Lines 544-547: signal handler calls scheduler.shutdown() + sys.exit(0)."""

    def test_shutdown_handler_invokes_shutdown_and_exit(self, monkeypatch):
        """Capture the registered SIGTERM handler, invoke it, verify behavior.

        Lines 544-547 only run when the scheduler receives a signal. We capture
        the handler via signal.signal patching, then invoke it directly.
        Behavior locked: shutdown() called once, sys.exit(0) raises SystemExit(0).
        """
        from nuri import scheduler as sched_mod

        captured_handlers: dict = {}

        def fake_signal(signum, handler):
            captured_handlers[signum] = handler

        mock_scheduler = MagicMock()
        # Make scheduler.start() a no-op so main returns synchronously.
        mock_scheduler.start.return_value = None

        monkeypatch.setattr(sched_mod, "init_db", MagicMock())
        monkeypatch.setattr(sched_mod, "create_scheduler", MagicMock(return_value=mock_scheduler))
        monkeypatch.setattr(sched_mod.signal, "signal", fake_signal)
        monkeypatch.setattr(sys, "argv", ["nuri.scheduler"])

        sched_mod.main()

        import signal as _signal

        assert _signal.SIGINT in captured_handlers
        assert _signal.SIGTERM in captured_handlers
        # The two handlers must be the same closure (same shutdown())
        assert captured_handlers[_signal.SIGINT] is captured_handlers[_signal.SIGTERM]

        # Now invoke the captured handler — should call shutdown() + sys.exit(0)
        handler = captured_handlers[_signal.SIGTERM]
        with pytest.raises(SystemExit) as exc_info:
            handler(_signal.SIGTERM, None)

        assert exc_info.value.code == 0
        mock_scheduler.shutdown.assert_called_once()


# ─────────────────────────────────────────────
# __main__ guard
# ─────────────────────────────────────────────


class TestMainGuard:
    """Line 558: `if __name__ == "__main__": main()`."""

    def test_module_run_invokes_main(self, monkeypatch):
        """Run scheduler as `__main__` via runpy, with main() patched.

        Note: per tests/CLAUDE.md, `runpy.run_module` re-executes the source so
        we must patch at the source level (`nuri.scheduler.main`) using a
        sys.modules pre-injection so the freshly-executed module sees our patch.
        """
        import runpy

        # Pre-import so we can monkeypatch, then runpy will reload — to avoid
        # re-execution invalidating our mock, we instead use a different
        # technique: patch sys.argv to --dry-run so main() exits cleanly,
        # then assert the scheduler module printed its schedule banner.
        monkeypatch.setattr(sys, "argv", ["nuri.scheduler", "--dry-run"])

        # Suppress stdout
        import io

        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)

        # run_module re-executes nuri.scheduler with __name__ == "__main__".
        # The --dry-run flag makes main() return after printing the schedule.
        runpy.run_module("nuri.scheduler", run_name="__main__")

        out = buf.getvalue()
        # Banner emitted by print_schedule (line 517) — confirms main() was invoked.
        assert "Nuri-Quant Scheduler" in out, "__main__ guard must invoke main() which prints the banner"
