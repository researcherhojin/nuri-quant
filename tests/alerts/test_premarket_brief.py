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
    """모든 subsystem helper 를 빈 결과로 mock.

    Pre-import lazy-imported modules BEFORE applying patches — `_collect_context`
    가 함수 안에서 `from nuri.quant.validation.market_signals import detect_all`
    하면, patch 활성 상태에서 market_signals 모듈이 처음 로드되며 그 안의
    `from nuri.core.db import query` 가 MOCK query 를 캡처. patch 종료 후 db.query
    는 복원되지만 market_signals.query 는 mock 으로 stuck → 후속 테스트의
    market_signals 호출이 모두 빈 결과 반환 (#test isolation bug).
    """
    # 강제 사전 import — 모든 lazy-loaded module 의 query 바인딩을 real 로 고정
    import nuri.api.routes.actions  # noqa: F401

    # query rebound 방어 — patch 후 모듈 query 가 mock 으로 stuck 되는 케이스 복원
    import nuri.core.db as _db_mod
    import nuri.quant.regime.classifier  # noqa: F401
    import nuri.quant.regime.macro_score  # noqa: F401
    import nuri.quant.validation.market_signals  # noqa: F401
    import nuri.trading.engine.certification  # noqa: F401

    _real_query = _db_mod.query
    _ms_orig_query = nuri.quant.validation.market_signals.query

    try:
        with (
            patch("nuri.quant.regime.classifier.classify_regime", return_value=None),
            patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=RuntimeError("no macro")),
            patch("nuri.trading.engine.certification.certify", side_effect=RuntimeError("no certify")),
            patch(
                "nuri.api.routes.actions._build_actions",
                return_value={"urgent": [], "portfolio": [], "check": [], "hold": []},
            ),
            patch("nuri.api.routes.actions._build_opportunities", return_value=[]),
            patch("nuri.core.db.query", return_value=[]),
        ):
            yield
    finally:
        # market_signals.query 가 patch 동안 mock 으로 rebound 되었을 수 있음 — 강제 복원
        nuri.quant.validation.market_signals.query = _ms_orig_query
        # db_mod.query 는 patch 가 자체 복원하지만, 방어적 lock
        _db_mod.query = _real_query


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

    def test_regime_populates_ctx_when_classify_returns_state(self):
        """classify_regime non-None → ctx["regime"] dict 채움 (line 119)."""
        from nuri.alerts.premarket_brief import _collect_context
        from nuri.quant.regime.classifier import RegimeState

        fake = RegimeState(
            date="2026-04-30",
            trend="bull",
            volatility="low",
            regime="bull_low_vol",
            confidence=0.75,
            details={},
        )
        with (
            patch("nuri.quant.regime.classifier.classify_regime", return_value=fake),
            patch(
                "nuri.api.routes.actions._build_actions",
                return_value={"urgent": [], "portfolio": [], "check": [], "hold": []},
            ),
            patch("nuri.api.routes.actions._build_opportunities", return_value=[]),
        ):
            ctx = _collect_context()
        assert ctx["regime"]["regime"] == "bull_low_vol"
        assert ctx["regime"]["confidence"] == 75  # round(0.75*100, 0)

    def test_actions_key_has_all_4_buckets(self):
        """4-bucket shape 보존 — PR #429 가 추가한 portfolio bucket 이 brief 에도 노출."""
        from nuri.alerts.premarket_brief import _collect_context

        with patch(
            "nuri.api.routes.actions._build_actions",
            return_value={
                "urgent": [],
                "portfolio": [
                    {
                        "ticker": "BAC",
                        "action": "HOLD",
                        "confidence": 62,
                        "pnl_pct": -1.1,
                        "position_pct": 19.8,
                        "reasons": ["리밸런스 권고"],
                    }
                ],
                "check": [],
                "hold": [],
            },
        ):
            ctx = _collect_context()
        assert "portfolio" in ctx["actions"]
        assert ctx["actions"]["portfolio"][0]["ticker"] == "BAC"


class TestFormatBriefEmbed:
    """format_brief_embed — Discord payload shape + 4-bucket routing."""

    def test_empty_ctx_still_produces_valid_embed(self):
        from nuri.alerts.premarket_brief import format_brief_embed

        ctx = {
            "regime": None,
            "macro": None,
            "vix": None,
            "usd_krw": None,
            "fear_greed": None,
            "siege": None,
            "actions": {},
            "opportunities": [],
            "macro_events": [],
            "portfolio_totals": None,
        }
        embed = format_brief_embed(ctx)
        # Title/color/footer 는 empty 여도 존재해야 Discord 렌더 가능
        assert "title" in embed
        assert "color" in embed
        assert "fields" in embed
        assert isinstance(embed["fields"], list)

    def test_urgent_bucket_triggers_red_color(self):
        from nuri.alerts.premarket_brief import COLOR_RED, format_brief_embed

        ctx = {
            "actions": {
                "urgent": [{"ticker": "CRASH", "action": "SELL", "confidence": 85, "pnl_pct": -30, "position_pct": 5}]
            }
        }
        assert format_brief_embed(ctx)["color"] == COLOR_RED

    def test_siege_rejected_triggers_amber_color(self):
        from nuri.alerts.premarket_brief import COLOR_AMBER, format_brief_embed

        ctx = {
            "actions": {},
            "siege": {
                "certified": False,
                "score": 58,
                "passed": 10,
                "failed": 1,
                "warnings": 6,
                "total": 17,
                "failing_errors": [],
            },
        }
        assert format_brief_embed(ctx)["color"] == COLOR_AMBER

    def test_portfolio_bucket_rendered_distinct_from_urgent(self):
        """PR #429 alpha/portfolio 분리 — brief 도 두 bucket 따로 label."""
        from nuri.alerts.premarket_brief import format_brief_embed

        ctx = {
            "actions": {
                "urgent": [],
                "portfolio": [
                    {
                        "ticker": "BAC",
                        "action": "HOLD",
                        "confidence": 62,
                        "pnl_pct": -1.1,
                        "position_pct": 19.8,
                        "reasons": [],
                    }
                ],
                "check": [],
                "hold": [],
            }
        }
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

        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
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
            "siege": {
                "certified": True,
                "score": 95,
                "passed": 16,
                "failed": 0,
                "warnings": 1,
                "total": 17,
                "failing_errors": [],
            },
            "actions": {
                "urgent": [],
                "portfolio": [],
                "check": [],
                "hold": [
                    {
                        "ticker": "NVDA",
                        "action": "BUY",
                        "confidence": 62,
                        "pnl_pct": 11.5,
                        "position_pct": 14.7,
                        "reasons": [],
                    }
                ],
            },
            "opportunities": [
                {"ticker": "AMD", "score": 57, "change_5d": 5, "rsi": 60, "signal": "momentum", "pros": [], "cons": []}
            ],
            "macro_events": [
                {
                    "category": "demand_growth",
                    "sentiment": 0.85,
                    "confidence": 0.82,
                    "headline": "AI chip demand surges",
                }
            ],
            "portfolio_totals": {"total_usd": 27000, "by_account": [("brokerage_alpha", 18000)]},
        }
        md = format_brief_markdown(ctx)
        assert "## Regime" in md
        assert "## Certification" in md
        assert "## Hold" in md
        assert "## Opportunities" in md
        assert "## 24h Macro Events" in md
        assert "## Portfolio" in md
        assert "$27,000" in md


class TestFreshnessSurface:
    """#513 — premarket_brief 가 freshness gate 결과를 사용자에게 surface.

    PR #512 가 backend 정책 (FRESHNESS_POLICIES) 등록 + dual-layer write/read filter
    추가했지만 brief 본문에 표시되지 않으면 사용자 가시성 0. 이 테스트는 surface
    누락 (regression) 방지.
    """

    def test_freshness_pass_only_renders_compact_summary(self):
        from nuri.alerts.premarket_brief import format_brief_embed

        ctx = {
            "actions": {},
            "freshness": {
                "pass": 6,
                "warn": 0,
                "fail": 0,
                "details": [
                    {"key": "prices", "label": "주가", "status": "PASS", "message": "최신 (2h)"},
                    {"key": "portfolio", "label": "포트폴리오 sync", "status": "PASS", "message": "최신 (11h)"},
                ],
            },
        }
        fields = format_brief_embed(ctx)["fields"]
        labels = [f["name"] for f in fields]
        assert any("Data Freshness" in lbl for lbl in labels), f"Got: {labels}"
        fresh_field = next(f for f in fields if "Data Freshness" in f["name"])
        # PASS-only → compact summary "6P / 0W / 0F" 만, 항목별 detail 안 포함
        assert "6P" in fresh_field["value"]
        assert "0W" in fresh_field["value"]
        assert "0F" in fresh_field["value"]

    def test_freshness_warn_renders_amber_color(self):
        from nuri.alerts.premarket_brief import COLOR_AMBER, format_brief_embed

        ctx = {
            "actions": {},
            "freshness": {
                "pass": 5,
                "warn": 1,
                "fail": 0,
                "details": [
                    {"key": "portfolio", "label": "포트폴리오 sync", "status": "WARN", "message": "30h 경과"},
                ],
            },
        }
        # WARN 1+ → AMBER (기존 SIEGE AMBER 와 동일 priority)
        assert format_brief_embed(ctx)["color"] == COLOR_AMBER

    def test_freshness_fail_renders_red_color_and_problem_detail(self):
        from nuri.alerts.premarket_brief import COLOR_RED, format_brief_embed

        ctx = {
            "actions": {},
            "freshness": {
                "pass": 4,
                "warn": 0,
                "fail": 2,
                "details": [
                    {"key": "prices", "label": "주가", "status": "PASS", "message": "최신"},
                    {
                        "key": "portfolio",
                        "label": "포트폴리오 sync",
                        "status": "FAIL",
                        "message": "80h 경과 — sync 필요",
                    },
                    {"key": "consensus", "label": "Consensus", "status": "FAIL", "message": "stale"},
                ],
            },
        }
        # FAIL 1+ → RED (urgent action 과 동일 priority — 사용자 즉시 attention)
        assert format_brief_embed(ctx)["color"] == COLOR_RED
        # FAIL 항목 detail 표시 (PASS 항목은 noise 절감으로 생략)
        fields = format_brief_embed(ctx)["fields"]
        fresh_field = next(f for f in fields if "Data Freshness" in f["name"])
        assert "포트폴리오 sync" in fresh_field["value"]
        assert "Consensus" in fresh_field["value"]
        assert "주가" not in fresh_field["value"]  # PASS 는 detail 생략

    def test_freshness_section_in_markdown(self):
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "freshness": {
                "pass": 5,
                "warn": 1,
                "fail": 0,
                "details": [
                    {"key": "prices", "label": "주가", "status": "PASS", "message": "최신 (2h)"},
                    {"key": "portfolio", "label": "포트폴리오 sync", "status": "WARN", "message": "30h 경과"},
                ],
            },
        }
        md = format_brief_markdown(ctx)
        assert "## Data Freshness" in md
        # 모든 항목 detail 출력 (markdown 은 noise 절감 룰 X)
        assert "주가" in md
        assert "포트폴리오 sync" in md
        assert "5P / 1W / 0F" in md

    def test_freshness_missing_skips_section(self):
        """ctx 에 freshness 없으면 section 자체 생략 (graceful)."""
        from nuri.alerts.premarket_brief import format_brief_embed, format_brief_markdown

        ctx = {"actions": {}}  # freshness key 부재
        embed = format_brief_embed(ctx)
        labels = [f["name"] for f in embed["fields"]]
        assert not any("Freshness" in lbl for lbl in labels)
        md = format_brief_markdown(ctx)
        assert "Data Freshness" not in md


class TestGenerateBrief:
    """E2E — generate_brief 가 ctx + embed + markdown + persist 경로를 모두 반환."""

    def test_returns_dict_with_expected_keys(self, empty_db_ctx, tmp_path, monkeypatch):
        from nuri.alerts import premarket_brief as pb

        # persist target 을 tmp 로 redirect
        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
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

    def test_subsystem_exceptions_are_caught_not_raised(self, tmp_path, monkeypatch):
        """_collect_context 는 각 subsystem raise 해도 graceful degrade — logger.warning
        만 기록하고 브리프 생성 계속. except 블록 coverage lock (82-193 missing)."""
        from nuri.alerts import premarket_brief as pb

        # 모든 subsystem 에 실제 exception raise 주입 → except 블록이 전부 실행
        with (
            patch("nuri.quant.regime.classifier.classify_regime", side_effect=RuntimeError("regime fail")),
            patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=RuntimeError("macro fail")),
            patch("nuri.trading.engine.certification.certify", side_effect=RuntimeError("siege fail")),
            patch("nuri.api.routes.actions._build_actions", side_effect=RuntimeError("actions fail")),
            patch("nuri.api.routes.actions._build_opportunities", side_effect=RuntimeError("ops fail")),
            patch("nuri.core.db.query", side_effect=RuntimeError("db fail")),
        ):
            ctx = pb._collect_context()
        # 모든 subsystem 실패했지만 ctx dict 자체는 반환 — 값은 None/빈 리스트
        assert ctx is not None
        assert ctx["regime"] is None
        assert ctx["macro"] is None
        assert ctx["siege"] is None

    def test_embed_populated_covers_all_sections(self):
        """ctx 전부 채워서 format_brief_embed 내 모든 conditional branch 실행.
        (226/230/239/241/243/245/253/278-288/297-301 miss line)."""
        from nuri.alerts.premarket_brief import format_brief_embed

        ctx = {
            "regime": {"regime": "bull_low_vol", "trend": "bull", "volatility": "low", "confidence": 80},
            "macro": {"score": 65.0, "interpretation": "Good"},
            "vix": {"value": 15.0, "date": "2026-04-20"},
            "fear_greed": {"value": 70, "date": "2026-04-21"},
            "usd_krw": {"value": 1470, "date": "2026-04-20"},
            "siege": {
                "certified": False,
                "score": 58,
                "passed": 10,
                "failed": 1,
                "warnings": 6,
                "total": 17,
                "failing_errors": [{"id": "position_limit", "desc": "종목 비중", "detail": "BAC>15%"}],
            },
            "actions": {
                "urgent": [{"ticker": "CRASH", "action": "SELL", "confidence": 85, "pnl_pct": -30, "position_pct": 5}],
                "portfolio": [
                    {"ticker": "BAC", "action": "HOLD", "confidence": 62, "pnl_pct": -1, "position_pct": 19.8}
                ],
                "check": [{"ticker": "PL", "action": "HOLD", "confidence": 74, "pnl_pct": 46.8, "position_pct": 1.4}],
                "hold": [],
            },
            "opportunities": [
                {"ticker": "AMD", "score": 57, "change_5d": 5, "rsi": 60, "verdict_level": "positive"},
                {"ticker": "IONQ", "score": 63, "change_5d": 31, "rsi": 84, "verdict_level": "neutral"},
                {"ticker": "XLE", "score": 35, "change_5d": -1, "rsi": 22, "verdict_level": "danger"},
            ],
            "macro_events": [
                {
                    "category": "demand_growth",
                    "sentiment": 0.85,
                    "confidence": 0.82,
                    "headline": "AI chip demand surges",
                }
            ],
            "portfolio_totals": {
                "total_usd": 27000,
                "by_account": [("brokerage_alpha", 18000), ("brokerage_beta", 9000)],
            },
        }
        embed = format_brief_embed(ctx)
        assert "fields" in embed
        names = [f["name"] for f in embed["fields"]]
        # 모든 섹션 label 존재 — 모든 branch 통과한 결과
        assert any("Regime" in n for n in names)
        assert any("지표" in n for n in names)
        assert any("Certification" in n for n in names)
        assert any("Urgent" in n for n in names)
        assert any("Portfolio" in n for n in names)
        assert any("Check" in n for n in names)
        assert any("Opportunities" in n for n in names)
        assert any("Macro Events" in n for n in names)
        assert any("Portfolio" in n for n in names)


class TestMainCLI:
    """main() CLI — argparse + stdout + generate_brief 호출 경로 (413-445 miss)."""

    def test_main_stdout_mode_prints_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        """--stdout 로 호출 시 markdown 표준출력 + Discord skip + exit 0."""
        from nuri.alerts import premarket_brief as pb

        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)
        # Discord webhook 없는 env 에서 실행 — send_brief 는 silent fallback
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        rc = pb.main(["--stdout", "--no-discord"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Pre-market Brief" in captured.out

    def test_main_default_attempts_discord_send(self, tmp_path, monkeypatch):
        """default (no --no-discord) 경로 — send_brief 호출 branch cover."""
        from nuri.alerts import premarket_brief as pb

        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)

        send_calls = []
        monkeypatch.setattr(pb, "send_brief", lambda embed: send_calls.append(embed) or True)
        rc = pb.main([])
        assert rc == 0
        assert len(send_calls) == 1  # Discord 호출 시도됨

    def test_main_send_brief_failure_does_not_crash(self, tmp_path, monkeypatch):
        """send_brief False 반환해도 main() exit 0 (scheduler job 중단 금지)."""
        from nuri.alerts import premarket_brief as pb

        monkeypatch.setattr(pb, "__file__", str(tmp_path / "nuri" / "alerts" / "premarket_brief.py"))
        (tmp_path / "nuri" / "alerts").mkdir(parents=True)
        monkeypatch.setattr(pb, "send_brief", lambda _embed: False)
        assert pb.main([]) == 0


class TestMarkdownEdgeCases:
    """format_brief_markdown 의 conditional branch 커버 (349/360/373/375 miss)."""

    def test_markdown_with_opportunities_pros_cons_rendered(self):
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "opportunities": [
                {
                    "ticker": "AMD",
                    "score": 57,
                    "change_5d": 5,
                    "rsi": 60,
                    "signal": "momentum",
                    "pros": ["pro1", "pro2"],
                    "cons": ["con1"],
                },
            ],
        }
        md = format_brief_markdown(ctx)
        assert "✓ pro1" in md
        assert "✗ con1" in md

    def test_markdown_with_siege_failing_errors_rendered(self):
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "siege": {
                "certified": False,
                "score": 58,
                "passed": 10,
                "failed": 1,
                "warnings": 6,
                "total": 17,
                "failing_errors": [{"id": "position_limit", "desc": "비중 초과", "detail": "BAC 19.8%>15%"}],
            },
        }
        md = format_brief_markdown(ctx)
        assert "❌ position_limit" in md
        assert "BAC 19.8%>15%" in md


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
        assert job.get("tz") == "US/Eastern", "premarket_brief must use US/Eastern tz for DST auto-handling"
        assert job["cron"] == "0 9 * * 1-5", "premarket_brief must fire at US 09:00 weekdays (pre-market 30min before)"

    def test_create_scheduler_accepts_tz_job(self):
        """create_scheduler 가 tz kwarg 가 있는 job 도 crash 없이 등록 + tz 반영."""
        from nuri.scheduler import create_scheduler

        scheduler = create_scheduler()
        try:
            job = scheduler.get_job("premarket_brief")
            assert job is not None
            # APScheduler CronTrigger.timezone 은 pytz tzinfo — zone 이름으로 직접 확인.
            tz_name = str(getattr(job.trigger, "timezone", ""))
            assert tz_name in ("US/Eastern", "America/New_York"), (
                f"premarket_brief trigger timezone should be US/Eastern, got {tz_name!r}"
            )
        finally:
            # BlockingScheduler 는 start() 전 shutdown() 이 raise. 등록만 검증하고 조용히 종료.
            if getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)

    def test_weekday_semantics_mon_fri_not_tue_sat(self):
        """codex #432 Review CRITICAL lock: APScheduler day_of_week 는
        Mon=0 base 라 crontab literal `1-5` 를 그대로 넘기면 Tue-Sat 로
        fire 됨. 올바른 동작 — Monday 는 fire, Saturday 는 skip.

        Revert detection: 만약 mapping 이 없어지거나 "1-5" 를 직접 넘기면
        Monday fire test 가 fail. 유사 DST-aware weekday regression 방지."""
        from datetime import datetime

        import pytz

        from nuri.scheduler import create_scheduler

        scheduler = create_scheduler()
        try:
            job = scheduler.get_job("premarket_brief")
            assert job is not None, "premarket_brief job must be registered"
            trig = job.trigger
            eastern = pytz.timezone("US/Eastern")

            # (a) Monday 월 09:00 직전에서 찾은 다음 fire time = 같은 Monday 09:00
            mon_0859 = eastern.localize(datetime(2026, 4, 20, 8, 59, 0))  # Monday
            next_fire = trig.get_next_fire_time(None, mon_0859)
            assert next_fire is not None
            assert next_fire.weekday() == 0, (
                f"Monday 08:59 이후 다음 fire 가 Monday(weekday=0) 여야 함 — got weekday={next_fire.weekday()} ({next_fire})"
            )
            assert next_fire.hour == 9 and next_fire.minute == 0

            # (b) Friday 09:00 직후에서 찾은 다음 fire time = Monday (Sat 아님)
            fri_0901 = eastern.localize(datetime(2026, 4, 24, 9, 1, 0))  # Friday
            next_after_fri = trig.get_next_fire_time(None, fri_0901)
            assert next_after_fri is not None
            assert next_after_fri.weekday() == 0, (
                f"Friday 09:01 이후 다음 fire 가 Monday 여야 함 (Saturday 발화 금지). got weekday={next_after_fri.weekday()} ({next_after_fri})"
            )

            # (c) Saturday 08:00 에서 찾은 다음 fire time 도 Monday (Saturday 자체 skip)
            sat_0800 = eastern.localize(datetime(2026, 4, 25, 8, 0, 0))
            next_after_sat = trig.get_next_fire_time(None, sat_0800)
            assert next_after_sat is not None
            assert next_after_sat.weekday() == 0, (
                f"Saturday 에서 찾은 다음 fire 는 Monday 여야 함. got weekday={next_after_sat.weekday()}"
            )
        finally:
            if getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)


class TestPremarketBriefExceptionFallbacks:
    """Lock-tests for exception/branch coverage gaps."""

    def test_collect_context_freshness_exception(self):
        """get_freshness_summary raise → swallowed (lines 83-84, 92-93, 110-111)."""
        from nuri.alerts.premarket_brief import _collect_context

        with (
            patch("nuri.core.freshness.get_freshness_summary", side_effect=Exception("freshness fail")),
            patch("nuri.trading.recommend.buy_candidate_emitter.emit_buy_candidates", side_effect=Exception("bc")),
            patch("nuri.quant.validation.market_signals.detect_all", side_effect=Exception("sig")),
            patch("nuri.quant.regime.classifier.classify_regime", return_value=None),
            patch("nuri.quant.regime.macro_score.compute_macro_score", side_effect=Exception("macro")),
            patch("nuri.trading.engine.certification.certify", side_effect=Exception("cert")),
            patch(
                "nuri.api.routes.actions._build_actions",
                return_value={"urgent": [], "portfolio": [], "check": [], "hold": []},
            ),
            patch("nuri.api.routes.actions._build_opportunities", return_value=[]),
            patch("nuri.api.routes.actions._get_macro_events", return_value=[]),
        ):
            ctx = _collect_context()
        assert isinstance(ctx, dict)
        # freshness/buy_candidates/shadow_signals 가 None or absent — 어느 쪽이든 graceful

    def test_format_brief_embed_freshness_pass(self, monkeypatch):
        """모든 freshness PASS 시 ✅ tier_emoji (line 501)."""
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "freshness": {
                "pass": 5,
                "warn": 0,
                "fail": 0,
                "details": [
                    {"status": "PASS", "label": "prices", "message": "ok"},
                ],
            },
        }
        md = format_brief_markdown(ctx)
        assert "✅" in md

    def test_format_brief_buy_candidates_listed(self):
        """bc.candidates 비어있지 않을 때 markdown에 ticker line (lines 540-551)."""
        from dataclasses import dataclass, field

        from nuri.alerts.premarket_brief import format_brief_markdown

        @dataclass
        class FakeCand:
            ticker: str = "AAPL"
            score: int = 80
            deploy_pct: int = 5
            entry: float = 200.0
            stop: float = 190.0
            tp1: float = 220.0
            tp2: float = 240.0
            why_now: str = "rsi oversold"
            sources: dict = field(default_factory=lambda: {"a": 80.0})

        @dataclass
        class FakeBC:
            blocked_reason: str | None = None
            regime: str = "bull"
            vix: float = 15.0
            timestamp_kst: str = "2026-05-04 08:00 KST"
            candidates: list = field(default_factory=list)
            total_deploy_pct: int = 0
            skipped: list = field(default_factory=list)

        bc = FakeBC(candidates=[FakeCand()], total_deploy_pct=5, skipped=[1, 2])
        md = format_brief_markdown({"buy_candidates": bc})
        assert "AAPL" in md
        assert "Why now" in md
        assert "skipped" in md

    def test_format_brief_embed_buy_candidates_field(self):
        """embed 의 buy_candidates field branch (lines 400-408)."""
        from dataclasses import dataclass, field

        from nuri.alerts.premarket_brief import format_brief_embed

        @dataclass
        class FakeCand:
            ticker: str = "AAPL"
            score: int = 80
            deploy_pct: int = 5
            entry: float = 200.0
            stop: float = 190.0
            tp1: float = 220.0
            tp2: float = 240.0
            why_now: str = "rsi oversold"
            sources: dict = field(default_factory=lambda: {"a": 80.0})

        @dataclass
        class FakeBC:
            blocked_reason: str | None = None
            regime: str = "bull"
            vix: float = 15.0
            timestamp_kst: str = "2026-05-04 08:00 KST"
            candidates: list = field(default_factory=lambda: [FakeCand()])
            total_deploy_pct: int = 5
            skipped: list = field(default_factory=list)

        embed = format_brief_embed({"buy_candidates": FakeBC()})
        assert isinstance(embed, dict)
        # Should include buy candidates field
        names = [f.get("name", "") for f in embed.get("fields", [])]
        assert any("BUY" in n for n in names)

    def test_format_brief_embed_buy_candidates_empty_list_skips_field(self):
        """premarket_brief.py 400->417: bc.candidates 비어있으면 elif False → Opportunities 로 진행 (#611)."""
        from dataclasses import dataclass, field

        from nuri.alerts.premarket_brief import format_brief_embed

        @dataclass
        class FakeBC:
            blocked_reason: str | None = None  # blocked_reason 없음 → 첫 if False
            regime: str = "bull"
            vix: float = 15.0
            candidates: list = field(default_factory=list)  # 빈 list → elif False (400 분기)
            total_deploy_pct: int = 0
            skipped: list = field(default_factory=list)
            timestamp_kst: str = "2026-05-04 08:00 KST"

        embed = format_brief_embed({"buy_candidates": FakeBC()})
        names = [f.get("name", "") for f in embed.get("fields", [])]
        # 빈 candidates → BUY Candidates field 미생성
        assert not any("BUY Candidates" in n for n in names)

    def test_format_brief_markdown_buy_candidates_empty_skips_section(self):
        """premarket_brief.py 540->553: bc.candidates 비어있으면 BUY Candidates section 출력 생략 (#611)."""
        from dataclasses import dataclass, field

        from nuri.alerts.premarket_brief import format_brief_markdown

        @dataclass
        class FakeBC:
            blocked_reason: str | None = None
            regime: str = "bull"
            vix: float = 15.0
            candidates: list = field(default_factory=list)  # 빈 → elif False
            total_deploy_pct: int = 0
            skipped: list = field(default_factory=list)
            timestamp_kst: str = "2026-05-04 08:00 KST"

        md = format_brief_markdown({"buy_candidates": FakeBC()})
        # BUY Candidates 헤더 없어야 함 (540 False 분기)
        assert "## BUY Candidates" not in md

    def test_format_brief_markdown_buy_candidates_no_skipped(self):
        """premarket_brief.py 549->551: bc.skipped 비어있으면 'skipped:' 줄 출력 생략 (#611)."""
        from dataclasses import dataclass, field

        from nuri.alerts.premarket_brief import format_brief_markdown

        @dataclass
        class FakeCand:
            ticker: str = "AAPL"
            score: int = 80
            deploy_pct: int = 5
            entry: float = 200.0
            stop: float = 190.0
            tp1: float = 220.0
            tp2: float = 240.0
            why_now: str = "test"
            sources: dict = field(default_factory=lambda: {"a": 80.0})

        @dataclass
        class FakeBC:
            blocked_reason: str | None = None
            regime: str = "bull"
            vix: float = 15.0
            candidates: list = field(default_factory=lambda: [FakeCand()])
            total_deploy_pct: int = 5
            skipped: list = field(default_factory=list)  # 빈 → 549 False 분기
            timestamp_kst: str = "2026-05-04 08:00 KST"

        md = format_brief_markdown({"buy_candidates": FakeBC()})
        assert "AAPL" in md
        # skipped 비어있어 "skipped:" 라인 미출력 (549 False 확인)
        assert "skipped:" not in md

    def test_send_brief_exception(self):
        """send_webhook raise → False (lines 601-603)."""
        from nuri.alerts.premarket_brief import send_brief

        with patch("nuri.alerts.discord_bot.send_webhook", side_effect=RuntimeError("net")):
            assert send_brief({}) is False


# ─── Phase 4 #616 statement coverage closure ──────────────────────────


class TestPremarketBriefStatementCoverage:
    """CI ground-truth missing statements (premarket_brief.py 95% → 100%)."""

    def test_quick_macro_indicator_value_set(self, tmp_path, monkeypatch):
        """L147: quick macro indicator rows truthy → ctx[key] 설정."""
        import nuri.core.db as db_mod
        from nuri.alerts.premarket_brief import _collect_context
        from nuri.core.db import get_db, init_db

        p = tmp_path / "macro.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)
        with get_db(p) as conn:
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('vix', '2026-05-06', 18.5)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('usd_krw', '2026-05-06', 1300.0)")
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('fear_greed', '2026-05-06', 60.0)")
        ctx = _collect_context()
        assert ctx["vix"] == {"value": 18.5, "date": "2026-05-06"}
        assert ctx["fear_greed"]["value"] == 60.0

    def test_portfolio_totals_iteration(self, tmp_path, monkeypatch):
        """L231-236: portfolio rows iter → totals 계산."""
        import nuri.core.db as db_mod
        from nuri.alerts.premarket_brief import _collect_context
        from nuri.core.db import get_db, init_db

        p = tmp_path / "totals.db"
        init_db(p)
        monkeypatch.setattr(db_mod, "DB_PATH", p)
        with get_db(p) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES ('main', 'AAPL', 10, 200, 'USD')"
            )
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) "
                "VALUES ('main', '005930.KS', 100, 70000, 'KRW')"
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES ('AAPL', '2026-05-06', 200, 210, 199, 205, 1000)"
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES ('005930.KS', '2026-05-06', 70000, 71000, 69000, 70500, 1000)"
            )
            conn.execute("INSERT INTO macro (indicator, date, value) VALUES ('usd_krw', '2026-05-06', 1300.0)")
        ctx = _collect_context()
        assert ctx["portfolio_totals"] is not None
        assert ctx["portfolio_totals"]["total_usd"] > 0

    def test_short_ticker_line_multi_account_breakdown(self):
        """L283-288: multi-account 시 breakdown line 추가."""
        from nuri.alerts.premarket_brief import _short_ticker_line

        item = {
            "ticker": "AAPL",
            "action": "BUY",
            "confidence": 80,
            "pnl_pct": 5.0,
            "position_pct": 12.0,
            "accounts": [
                {"account": "main", "position_pct": 8.0, "pnl_pct": 4.0},
                {"account": "swing", "position_pct": 4.0, "pnl_pct": 6.0},
            ],
        }
        result = _short_ticker_line(item)
        assert "[" in result and "]" in result
        assert "main" in result and "swing" in result

    def test_brief_embed_buy_blocked(self):
        """L393: bc.blocked_reason truthy → BUY Candidates blocked field."""
        from dataclasses import dataclass

        from nuri.alerts.premarket_brief import format_brief_embed

        @dataclass
        class FakeBC:
            blocked_reason: str = "VIX>30"
            regime: str = "bear"
            vix: float = 35.0
            candidates: list | None = None
            total_deploy_pct: int = 0

        embed = format_brief_embed({"buy_candidates": FakeBC()})
        names = [f["name"] for f in embed["fields"]]
        assert any("blocked" in n for n in names)

    def test_markdown_action_reasons_lines(self, tmp_path):
        """L530: action items 의 reasons 출력."""
        from nuri.alerts.premarket_brief import format_brief_markdown

        ctx = {
            "actions": {
                "urgent": [
                    {
                        "ticker": "AAA",
                        "action": "SELL",
                        "confidence": 80,
                        "pnl_pct": -8.0,
                        "position_pct": 5.0,
                        "reasons": ["손절선 돌파", "drift critical"],
                    }
                ],
            }
        }
        md = format_brief_markdown(ctx)
        assert "손절선 돌파" in md
        assert "drift critical" in md

    def test_markdown_buy_blocked(self):
        """L536-539: bc.blocked_reason markdown path."""
        from dataclasses import dataclass

        from nuri.alerts.premarket_brief import format_brief_markdown

        @dataclass
        class FakeBC:
            blocked_reason: str = "VIX>30 신규 매수 차단"
            regime: str = "bear"
            vix: float = 35.0
            candidates: list | None = None
            total_deploy_pct: int = 0
            timestamp_kst: str = ""
            skipped: list | None = None

        md = format_brief_markdown({"buy_candidates": FakeBC()})
        assert "blocked" in md
        assert "VIX>30" in md
