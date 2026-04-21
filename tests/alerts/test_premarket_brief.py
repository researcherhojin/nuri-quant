"""Tests for nuri/alerts/premarket_brief.py (PR proactive-daily-brief).

Scope — codex Plan consult 권고 반영:
1. Brief sections are sourced from existing actions.py helpers (single source of truth).
2. Empty-DB graceful — 모든 subsystem 이 None 반환해도 embed/markdown shape 유지.
3. DB-only — external API 호출 없음 (scheduler 적합성).
4. persist file 항상 생성 (Discord 성공 여부 무관, codex Q4 A+B).
5. Scheduler job 등록 확인 (DST-aware tz + 평일 필터).

이 테스트가 fail 하면 brief 가 silent 로 empty field 를 produce 해 사용자가
"오늘 brief 가 왜 없지?" 라고 묻는 regression 발생. 유사 재발 방지.
"""
from unittest.mock import patch

import pytest


@pytest.fixture
def empty_db_ctx():
    """모든 subsystem helper 를 빈 결과로 mock."""
    with (
        patch("nuri.quant.regime.classifier.classify_regime", return_value=None),
        patch("nuri.quant.regime.macro_score.compute_macro_score",
              side_effect=RuntimeError("no macro")),
        patch("nuri.trading.engine.certification.certify",
              side_effect=RuntimeError("no certify")),
        patch("nuri.api.routes.actions._build_actions",
              return_value={"urgent": [], "portfolio": [], "check": [], "hold": []}),
        patch("nuri.api.routes.actions._build_opportunities", return_value=[]),
        patch("nuri.core.db.query", return_value=[]),
    ):
        yield


class TestContextCollection:
    """_collect_context 는 개별 subsystem 실패에도 graceful degrade."""

    def test_all_subsystems_fail_returns_none_values(self, empty_db_ctx):
        from nuri.alerts.premarket_brief import _collect_context
        ctx = _collect_context()
        # 실패한 subsystem 은 None 또는 빈 list, 결코 raise 하지 않음
        assert ctx["regime"] is None
        assert ctx["macro"] is None
        assert ctx["siege"] is None
        # actions/opportunities 는 빈 dict/list 로 폴백
        assert ctx["actions"] == {"urgent": [], "portfolio": [], "check": [], "hold": []}
        assert ctx["opportunities"] == []
        assert ctx["macro_events"] == []

    def test_actions_key_has_all_4_buckets(self):
        """4-bucket shape 보존 — PR #429 가 추가한 portfolio bucket 이 brief 에도 노출."""
        from nuri.alerts.premarket_brief import _collect_context
        with patch("nuri.api.routes.actions._build_actions",
                   return_value={
                       "urgent": [],
                       "portfolio": [{"ticker": "BAC", "action": "HOLD",
                                     "confidence": 62, "pnl_pct": -1.1, "position_pct": 19.8,
                                     "reasons": ["리밸런스 권고"]}],
                       "check": [],
                       "hold": [],
                   }):
            ctx = _collect_context()
        assert "portfolio" in ctx["actions"]
        assert ctx["actions"]["portfolio"][0]["ticker"] == "BAC"


class TestFormatBriefEmbed:
    """format_brief_embed — Discord payload shape + 4-bucket routing."""

    def test_empty_ctx_still_produces_valid_embed(self):
        from nuri.alerts.premarket_brief import format_brief_embed
        ctx = {"regime": None, "macro": None, "vix": None, "usd_krw": None,
               "fear_greed": None, "siege": None, "actions": {}, "opportunities": [],
               "macro_events": [], "portfolio_totals": None}
        embed = format_brief_embed(ctx)
        # Title/color/footer 는 empty 여도 존재해야 Discord 렌더 가능
        assert "title" in embed
        assert "color" in embed
        assert "fields" in embed
        assert isinstance(embed["fields"], list)

    def test_urgent_bucket_triggers_red_color(self):
        from nuri.alerts.premarket_brief import COLOR_RED, format_brief_embed
        ctx = {"actions": {"urgent": [{"ticker": "CRASH", "action": "SELL",
                                        "confidence": 85, "pnl_pct": -30, "position_pct": 5}]}}
        assert format_brief_embed(ctx)["color"] == COLOR_RED

    def test_siege_rejected_triggers_amber_color(self):
        from nuri.alerts.premarket_brief import COLOR_AMBER, format_brief_embed
        ctx = {"actions": {}, "siege": {"certified": False, "score": 58, "passed": 10,
                                         "failed": 1, "warnings": 6, "total": 17,
                                         "failing_errors": []}}
        assert format_brief_embed(ctx)["color"] == COLOR_AMBER

    def test_portfolio_bucket_rendered_distinct_from_urgent(self):
        """PR #429 alpha/portfolio 분리 — brief 도 두 bucket 따로 label."""
        from nuri.alerts.premarket_brief import format_brief_embed
        ctx = {"actions": {
            "urgent": [],
            "portfolio": [{"ticker": "BAC", "action": "HOLD", "confidence": 62,
                          "pnl_pct": -1.1, "position_pct": 19.8, "reasons": []}],
            "check": [], "hold": [],
        }}
        fields = format_brief_embed(ctx)["fields"]
        labels = [f["name"] for f in fields]
        # Portfolio label 포함 + "매도" 어휘 금지 (PR #429 rule)
        assert any("Portfolio" in lbl or "리밸런스" in lbl for lbl in labels)
        portfolio_field = next(f for f in fields if "Portfolio" in f["name"] or "리밸런스" in f["name"])
        assert "매도" not in portfolio_field["value"]


class TestMarkdownPersist:
    """persist_brief — scheduler 실패 시 session-handoff artifact 확보 (codex Q4 A+B)."""

    def test_persist_always_writes_file_even_with_empty_content(self, tmp_path, monkeypatch):
        from nuri.alerts import premarket_brief as pb
        monkeypatch.setattr(pb, "__file__",
                            str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        # parents[2] = tmp_path
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)
        path = pb.persist_brief("# test\n\nempty ctx", date="2026-04-21")
        assert path.exists()
        assert "# test" in path.read_text()

    def test_markdown_includes_all_sections_when_populated(self):
        from nuri.alerts.premarket_brief import format_brief_markdown
        ctx = {
            "regime": {"regime": "bull_low_vol", "trend": "bull", "volatility": "low", "confidence": 80},
            "macro": {"score": 65.0, "interpretation": "Good"},
            "vix": {"value": 15.5, "date": "2026-04-20"},
            "fear_greed": {"value": 70, "date": "2026-04-21"},
            "usd_krw": {"value": 1470, "date": "2026-04-20"},
            "siege": {"certified": True, "score": 95, "passed": 16, "failed": 0,
                      "warnings": 1, "total": 17, "failing_errors": []},
            "actions": {
                "urgent": [], "portfolio": [], "check": [],
                "hold": [{"ticker": "NVDA", "action": "BUY", "confidence": 62,
                         "pnl_pct": 11.5, "position_pct": 14.7, "reasons": []}],
            },
            "opportunities": [{"ticker": "AMD", "score": 57, "change_5d": 5,
                              "rsi": 60, "signal": "momentum", "pros": [], "cons": []}],
            "macro_events": [{"category": "demand_growth", "sentiment": 0.85,
                             "confidence": 0.82, "headline": "AI chip demand surges"}],
            "portfolio_totals": {"total_usd": 27000, "by_account": [("kakaopay", 18000)]},
        }
        md = format_brief_markdown(ctx)
        assert "## Regime" in md
        assert "## SIEGE" in md
        assert "## Hold" in md
        assert "## Opportunities" in md
        assert "## 24h Macro Events" in md
        assert "## Portfolio" in md
        assert "$27,000" in md


class TestGenerateBrief:
    """E2E — generate_brief 가 ctx + embed + markdown + persist 경로를 모두 반환."""

    def test_returns_dict_with_expected_keys(self, empty_db_ctx, tmp_path, monkeypatch):
        from nuri.alerts import premarket_brief as pb
        # persist target 을 tmp 로 redirect
        monkeypatch.setattr(pb, "__file__",
                            str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)
        result = pb.generate_brief()
        for k in ("ctx", "embed", "markdown", "path"):
            assert k in result, f"missing key {k}"
        assert "Pre-market Brief" in result["markdown"]

    def test_send_brief_silent_fallback_when_discord_unset(self, monkeypatch):
        """Discord webhook 미설정 시 send_brief 는 False 반환 (scheduler 중단 안 함)."""
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        from nuri.alerts.premarket_brief import send_brief
        assert send_brief({"title": "test"}) is False


class TestSchedulerRegistration:
    """premarket_brief 가 SCHEDULES 에 등록됐는지 + DST-aware tz 확인."""

    def test_premarket_brief_job_registered(self):
        from nuri.scheduler import SCHEDULES
        names = [j["name"] for j in SCHEDULES]
        assert "premarket_brief" in names

    def test_premarket_brief_uses_us_eastern_timezone(self):
        """DST 자동 처리 — cron literal `0 22 * * 1-5` 대신 `0 9 * * 1-5 US/Eastern`.
        EDT 기간 KST 22:00, EST 기간 KST 23:00. codex Plan consult Q1 risk #1."""
        from nuri.scheduler import SCHEDULES
        job = next(j for j in SCHEDULES if j["name"] == "premarket_brief")
        assert job.get("tz") == "US/Eastern", \
            "premarket_brief must use US/Eastern tz for DST auto-handling"
        assert job["cron"] == "0 9 * * 1-5", \
            "premarket_brief must fire at US 09:00 weekdays (pre-market 30min before)"

    def test_create_scheduler_accepts_tz_job(self):
        """create_scheduler 가 tz kwarg 가 있는 job 도 crash 없이 등록 + tz 반영."""
        from nuri.scheduler import create_scheduler
        scheduler = create_scheduler()
        try:
            job = scheduler.get_job("premarket_brief")
            assert job is not None
            # APScheduler CronTrigger.timezone 은 pytz tzinfo — zone 이름으로 직접 확인.
            tz_name = str(getattr(job.trigger, "timezone", ""))
            assert tz_name in ("US/Eastern", "America/New_York"), \
                f"premarket_brief trigger timezone should be US/Eastern, got {tz_name!r}"
        finally:
            # BlockingScheduler 는 start() 전 shutdown() 이 raise. 등록만 검증하고 조용히 종료.
            if getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)
