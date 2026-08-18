"""Pre-market daily brief — 사용자 명령 없이도 매일 자동 실행되는 판단 trigger.

Scheduler 는 **US/Eastern 09:00 평일** (pre-market 30분 전) 에 자동 호출해
Discord + 로컬 artifact 를 생성. DST 자동 처리됨 (EDT 기간 KST 22:00, EST
기간 KST 23:00). 사용자가 "오늘 장 어때?" 안 물어도 brief 가 먼저 뜸.

Single source of truth (codex Plan consult Q2/Scope): 기존 actions API 의
helper 를 재사용 — 새 로직 추가 없이 composition 만.
- `_build_actions` — 4-bucket 종합 (stop-loss/SIEGE bucket 분리는 PR #429 후)
- `_build_opportunities` — 비보유 scan candidates
- `_get_macro_events` — 24h macro events (DB)
- `discord_bot.send_webhook` — 전송 공통 (daily_report 와 동일 경로)

데이터 출처 (모두 DB):
- Regime / macro_score / VIX / USD/KRW / F&G — DB `macro` 테이블 + classifier
- SIEGE — `certify(caller="cli:premarket_brief")` (persist 됨, audit trail)
- 4-bucket actions — `_build_actions()`
- Opportunities — `_build_opportunities()`
- Macro events — `macro_events` 테이블 (24h window)
- Portfolio totals — `portfolio` + `prices` join + `macro.usd_krw`

Freshness 의존 (codex Plan consult Scope):
- `consensus` scheduler job (07:05 KST) 산출물 재사용. 07:05 이후 US/Eastern
  09:00 이면 약 ~4~5시간 gap — brief 는 T-1 close + morning consensus 기준.
- `stock_us_night` / `stock_us_dawn` 은 23:30~06:00 KST 에 돌아 prices 최신화.

외부 뉴스 (Warsh 발언, Trump 인터뷰 등) 는 session-time 에 Claude 가
WebSearch 로 fetch — scheduler 가 외부 API 를 돌리면 STRATEGY §4.4 egress 룰
복잡도 증가. Brief 는 정량 baseline 제공, qualitative 오버레이는 session 시점.

Artifact 정책 (codex Plan Q4 A+B):
- Brief 생성 성공 시 **항상** `data/reports/briefs/{date}.md` persist (Discord 성공 여부 무관).
- Discord 실패해도 scheduler job exit 0 — persist 자체가 primary artifact.
- `data/` 는 `.gitignore` 돼있어 commit 됨 없음.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from nuri.core.timezone import kst_now, today_kst
from nuri.trading.recommend.buy_candidate_emitter import format_vix

logger = logging.getLogger(__name__)


COLOR_GREEN = 0x00FF00
COLOR_AMBER = 0xFFA500
COLOR_RED = 0xFF0000
COLOR_BLUE = 0x3498DB


def _collect_context(db_path=None) -> dict:
    """Brief 에 필요한 모든 context 를 DB 에서 수집.

    Fault-tolerant: 각 subsystem 실패는 dict key None 으로 degrade, brief 자체
    는 생성 계속. logger.warning 으로 추적.
    """
    ctx: dict = {
        "regime": None,
        "macro": None,
        "vix": None,
        "usd_krw": None,
        "fear_greed": None,
        "siege": None,
        "actions": None,
        "opportunities": None,
        "macro_events": [],
        "portfolio_totals": None,
        "shadow_signals": [],  # PR C (codex #3): market-wide crash precursor
        "buy_candidates": None,  # #507 Phase 1: cash deploy candidate emit
        "freshness": None,  # #513: 데이터 신선도 surface (PASS/WARN/FAIL 3-tier)
    }

    # Data freshness (#513) — backend gate (#512 PR) 가 작동해도 brief 에 surface 되지 않으면
    # 사용자 가시성 0. 매 brief 에 PASS/WARN/FAIL 3-tier summary + per-policy detail 표시.
    # FAIL 1+ → embed RED, WARN 1+ → embed AMBER 가능 (기존 SIEGE AMBER 와 동일 priority).
    try:
        from nuri.core.freshness import get_freshness_summary

        ctx["freshness"] = get_freshness_summary(db_path)
    except Exception:
        logger.warning("freshness summary 실패", exc_info=True)

    # BUY candidates (#507) — sell-bias 결함 fix. emitter 가 0 emit 일때도
    # blocked_reason 으로 surface (VIX>30 / regime / threshold 미달 모두 표시).
    try:
        from nuri.trading.recommend.buy_candidate_emitter import emit_buy_candidates

        emitted = emit_buy_candidates(db_path=db_path)
        ctx["buy_candidates"] = emitted
        # 발행한 후보를 원장에 남긴다 (#1078). 여기서 부르는 이유: `emit_buy_candidates`
        # 자체는 CLI 로도 돌려 보는 함수라 호출만으로 기록하면 조회가 원장을 오염시킨다.
        # **발행하는 지점이 기록하는 지점**이다. 기록 실패가 브리핑을 막지 않도록 자체
        # try 로 감싼다 — 관측이 본 작업을 게이트하면 안 된다 (#894).
        try:
            from nuri.trading.recommend.tracker import save_buy_candidates

            save_buy_candidates(emitted, db_path=db_path)
        except Exception:
            logger.warning("buy candidates 영속화 실패 (브리핑은 계속)", exc_info=True)
        # 미실행 원장 (#1094) — 위 `save_buy_candidates` 는 **발행된 후보만** 남긴다.
        # 차단된 날(오늘처럼 regime=recovery 로 0건)은 그쪽에 아무것도 안 남아 원장에서
        # "아무 일도 없던 날" 로 보인다. 이건 그 반대편을 남긴다: 실행하지 않은 것과
        # 그 사유. 없으면 사후 채점이 실행한 것만 보게 되어 생존 편향이 된다.
        try:
            from nuri.core.db import record_candidate_run

            record_candidate_run(emitted, db_path=db_path)
        except Exception:
            logger.warning("candidate run 기록 실패 (브리핑은 계속)", exc_info=True)
    except Exception:
        logger.warning("buy candidates emit 실패", exc_info=True)

    # Shadow signals — SHADOW (`actionable: false`) 는 candidates 에 안 들어가니까
    # brief 에서만 surface. detect_all 은 내부적으로 graceful degrade.
    try:
        from nuri.quant.validation.market_signals import detect_all

        ctx["shadow_signals"] = [
            {
                "signal_id": s.signal_id,
                "fired": s.fired,
                "level": s.level,
                "threshold": s.threshold,
                "detail": s.detail,
            }
            for s in detect_all(db_path=db_path)
        ]
    except Exception:
        logger.warning("shadow signals detect 실패", exc_info=True)

    # Regime
    try:
        from nuri.quant.regime.classifier import classify_regime

        r = classify_regime(db_path=db_path)
        if r:
            ctx["regime"] = {
                "regime": r.regime,
                "trend": r.trend,
                "volatility": r.volatility,
                "confidence": round(float(r.confidence) * 100, 0),
            }
    except Exception:
        logger.warning("regime classify 실패", exc_info=True)

    # Macro score
    try:
        from nuri.quant.regime.macro_score import compute_macro_score

        m = compute_macro_score(db_path=db_path)
        ctx["macro"] = {"score": round(m.total_score, 1), "interpretation": m.interpretation}
    except Exception:
        logger.warning("macro score 실패", exc_info=True)

    # Quick macro indicators
    try:
        from nuri.core.db import query

        for ind, key in (("vix", "vix"), ("usd_krw", "usd_krw"), ("fear_greed", "fear_greed")):
            rows = query(
                "SELECT value, date FROM macro WHERE indicator = ? ORDER BY date DESC LIMIT 1",
                (ind,),
                db_path=db_path,
            )
            if rows:
                ctx[key] = {"value": float(rows[0]["value"]), "date": rows[0]["date"]}
    except Exception:
        logger.warning("quick macro indicators 실패", exc_info=True)

    # SIEGE certify
    try:
        from nuri.trading.engine.certification import certify

        cert = certify(caller="cli:premarket_brief", swallow_persist_errors=True, db_path=db_path)
        ctx["siege"] = {
            "certified": cert.certified,
            "score": round(cert.score, 1),
            "passed": cert.passed,
            "failed": cert.failed,
            "warnings": cert.warnings,
            "total": cert.total_conditions,
            "failing_errors": [
                {"id": c.id, "desc": c.description, "detail": (c.detail or "")[:100]}
                for c in cert.conditions
                if not c.passed and c.severity == "error"
            ],
        }
    except Exception:
        logger.warning("SIEGE certify 실패", exc_info=True)

    # 4-bucket actions (cache bypass)
    try:
        from nuri.api.routes.actions import _actions_cache, _build_actions

        _actions_cache["data"] = None
        a = _build_actions()
        ctx["actions"] = {k: a.get(k, []) for k in ("urgent", "portfolio", "check", "hold")}
    except Exception:
        logger.warning("build_actions 실패", exc_info=True)

    # Top opportunities (비보유)
    try:
        from nuri.api.routes.actions import _build_opportunities, _opportunities_cache

        _opportunities_cache["data"] = None
        ops = _build_opportunities() or []
        ctx["opportunities"] = ops[:5]
    except Exception:
        logger.warning("build_opportunities 실패", exc_info=True)

    # Last 24h macro events
    try:
        from nuri.core.db import query

        rows = query(
            """
            SELECT published_at, category, sentiment, confidence,
                   SUBSTR(headline, 1, 100) as headline
            FROM macro_events
            WHERE published_at >= datetime('now', '-1 day')
              AND category != 'neutral'
              AND confidence >= 0.5
              AND ABS(sentiment) >= 0.5
            ORDER BY ABS(sentiment) DESC LIMIT 5
            """,
            db_path=db_path,
        )
        ctx["macro_events"] = [dict(r) for r in rows]
    except Exception:
        logger.warning("macro events 조회 실패", exc_info=True)

    # Portfolio totals
    try:
        from nuri.core.db import query

        rows = query(
            """
            SELECT p.account, p.ticker, p.quantity, p.avg_price, p.currency, pr.close
            FROM portfolio p
            LEFT JOIN (
                SELECT ticker, close FROM prices
                WHERE (ticker, date) IN (SELECT ticker, MAX(date) FROM prices GROUP BY ticker)
            ) pr ON p.ticker = pr.ticker
            """,
            db_path=db_path,
        )
        rate_row = query(
            "SELECT value FROM macro WHERE indicator='usd_krw' ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        rate = float(rate_row[0]["value"]) if rate_row else 1400.0
        from nuri.core.ticker_names import is_kr_ticker

        by_acct: dict[str, float] = {}
        total_usd = 0.0
        for r in rows:
            px = r["close"] or r["avg_price"] or 0
            qty = r["quantity"] or 0
            is_kr = is_kr_ticker(r["ticker"])
            val_usd = px * qty / rate if is_kr else px * qty
            by_acct[r["account"]] = by_acct.get(r["account"], 0.0) + val_usd
            total_usd += val_usd
        ctx["portfolio_totals"] = {
            "total_usd": total_usd,
            "by_account": sorted(by_acct.items(), key=lambda x: -x[1]),
        }
    except Exception:
        logger.warning("portfolio totals 실패", exc_info=True)

    return ctx


def _brief_color(ctx: dict) -> int:
    """Brief 색상 priority — RED > AMBER > BLUE.

    RED:    urgent action OR freshness FAIL (#513)
    AMBER:  SIEGE not certified OR freshness WARN (#513)
    BLUE:   평상시
    """
    actions = ctx.get("actions") or {}
    fresh = ctx.get("freshness") or {}
    if actions.get("urgent") or fresh.get("fail", 0) > 0:
        return COLOR_RED
    siege = ctx.get("siege") or {}
    if siege.get("certified") is False or fresh.get("warn", 0) > 0:
        return COLOR_AMBER
    return COLOR_BLUE


def _short_ticker_line(item: dict) -> str:
    """Brief 한 줄. KR 종목은 사람이 읽을 수 있게 ticker 옆에 종목명 병기.
    multi-account 보유는 끝에 계좌별 비중 breakdown 추가 (#527 합산-누설 fix)."""
    from nuri.core.ticker_names import get_ticker_name

    t = item.get("ticker", "?")
    action = item.get("action", "?")
    conf = item.get("confidence", 0)
    pnl = item.get("pnl_pct", 0)
    pos = item.get("position_pct", 0)

    name = get_ticker_name(t)
    label = f"{name} ({t})" if name else t
    head = f"{label} ({action} conf {conf}, pnl {pnl:+.1f}%, pos {pos:.1f}%)"

    accounts = item.get("accounts") or []
    if len(accounts) > 1:
        # 계좌 비중 큰 순으로 정렬. 메인 라인의 `pnl` 는 worst-account 의 손익이라
        # multi-account 종목에선 misleading — breakdown 에 계좌별 pnl 동반 표시.
        sorted_accounts = sorted(accounts, key=lambda a: a.get("position_pct", 0), reverse=True)
        breakdown = " · ".join(
            f"{a.get('account', '?')} {a.get('position_pct', 0):.1f}%/{a.get('pnl_pct', 0):+.1f}%"
            for a in sorted_accounts
        )
        return f"{head} [{breakdown}]"
    return head


def format_brief_embed(ctx: dict) -> dict:
    """Discord embed 형식 (daily_report 와 동일 shape)."""
    fields: list[dict] = []

    # Regime + macro 한 줄
    regime = ctx.get("regime")
    macro = ctx.get("macro")
    if regime:
        rm = f"{regime['regime']} / trend {regime['trend']} / vol {regime['volatility']} (conf {regime['confidence']:.0f}%)"
    else:
        rm = "regime 미확정"
    if macro:
        rm += f"\nMacro score: {macro['score']} — {macro['interpretation']}"
    fields.append({"name": "📊 Regime + Macro", "value": rm, "inline": False})

    # Quick macro indicators
    vix = ctx.get("vix")
    fg = ctx.get("fear_greed")
    krw = ctx.get("usd_krw")
    parts = []
    if vix:
        parts.append(f"VIX {vix['value']:.1f}")
    if fg:
        parts.append(f"F&G {fg['value']:.0f}")
    if krw:
        parts.append(f"USD/KRW {krw['value']:.0f}")
    if parts:
        fields.append({"name": "🧭 지표", "value": " · ".join(parts), "inline": False})

    # SIEGE
    siege = ctx.get("siege")
    if siege:
        status = "CERTIFIED" if siege["certified"] else "REJECTED"
        siege_line = f"{status} ({siege['score']:.0f}% — {siege['passed']}P/{siege['failed']}F/{siege['warnings']}W)"
        if siege["failing_errors"]:
            siege_line += "\n" + "\n".join(f"❌ {e['id']}: {e['detail']}" for e in siege["failing_errors"][:3])
        fields.append({"name": "🛡️ Certification", "value": siege_line, "inline": False})

    # Data Freshness (#513) — backend gate 결과를 사용자에게 surface.
    # PR #512 가 portfolio policy 등록 + dual-layer write/read filter 했지만
    # brief 본문에 표시되지 않으면 사용자 가시성 0. WARN/FAIL 시 즉시 attention.
    fresh = ctx.get("freshness") or {}
    if fresh.get("details"):
        n_pass, n_warn, n_fail = fresh.get("pass", 0), fresh.get("warn", 0), fresh.get("fail", 0)
        if n_fail > 0:
            tier_emoji = "❌"
        elif n_warn > 0:
            tier_emoji = "⚠️"
        else:
            tier_emoji = "✅"
        header = f"{tier_emoji} {n_pass}P / {n_warn}W / {n_fail}F"
        # WARN/FAIL 만 detail 출력 (PASS 는 count 만으로 충분 — noise 절감)
        problem_lines = [
            f"{'❌' if d['status'] == 'FAIL' else '⚠️'} {d['label']}: {d['message']}"
            for d in fresh["details"]
            if d["status"] != "PASS"
        ]
        value = header + ("\n" + "\n".join(problem_lines) if problem_lines else "")
        fields.append({"name": "🕐 Data Freshness", "value": value, "inline": False})

    # SHADOW crash precursor signals (PR C, codex #3). `actionable: false` 이므로
    # action 에 직접 영향 없음 — "Surface" 단계 추적용. fired=True 는 주목 필요.
    shadow = ctx.get("shadow_signals") or []
    if shadow:
        shadow_lines = []
        for s in shadow:
            emoji = "⚠️" if s["fired"] else "·"
            shadow_lines.append(f"{emoji} {s['signal_id']}: {s['detail']}")
        fired_count = sum(1 for s in shadow if s["fired"])
        total = len(shadow)
        fields.append(
            {
                "name": f"🌑 SHADOW crash precursor — {fired_count}/{total} fired",
                "value": "\n".join(shadow_lines),
                "inline": False,
            }
        )

    # Action buckets
    actions = ctx.get("actions") or {}
    for bucket, emoji, label in (
        ("urgent", "🚨", "Urgent"),
        ("portfolio", "📊", "Portfolio (리밸런스 권고)"),
        ("check", "🟡", "Check"),
    ):
        items = actions.get(bucket) or []
        if items:
            lines = [_short_ticker_line(it) for it in items[:3]]
            more = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
            fields.append(
                {
                    "name": f"{emoji} {label} — {len(items)}",
                    "value": "\n".join(lines) + more,
                    "inline": False,
                }
            )

    # BUY Candidates (#507) — opportunities 보다 우선 surface (entry/stop/target 명시)
    bc = ctx.get("buy_candidates")
    if bc is not None:
        if bc.blocked_reason:
            fields.append(
                {
                    "name": "🛒 BUY Candidates — 0 (blocked)",
                    "value": f"{bc.blocked_reason}\nregime={bc.regime} · VIX={format_vix(bc.vix)}",
                    "inline": False,
                }
            )
        elif bc.candidates:
            cand_lines = []
            for c in bc.candidates[:5]:
                cand_lines.append(
                    f"**{c.ticker}** {c.score}/100 · deploy {c.deploy_pct}% · "
                    f"entry ${c.entry} stop ${c.stop} TP1 ${c.tp1}\n"
                    f"  · {c.why_now}"
                )
            fields.append(
                {
                    "name": f"🛒 BUY Candidates — {len(bc.candidates)} (total {bc.total_deploy_pct}% cash)",
                    "value": "\n".join(cand_lines),
                    "inline": False,
                }
            )

    # Opportunities
    ops = ctx.get("opportunities") or []
    if ops:
        op_lines = []
        for o in ops:
            verdict_level = o.get("verdict_level", "")
            marker = {"positive": "🟢", "neutral": "🟡", "danger": "🔴"}.get(verdict_level, "⚪")
            op_lines.append(
                f"{marker} {o.get('ticker', '?'):<6} "
                f"score {o.get('score', 0) or 0:.0f} · "
                f"5D {o.get('change_5d', 0) or 0:+.1f}% · "
                f"RSI {o.get('rsi', 0) or 0:.0f}"
            )
        fields.append(
            {
                "name": f"💡 Top Opportunities (비보유) — {len(ops)}",
                "value": "\n".join(op_lines),
                "inline": False,
            }
        )

    # Macro events (24h)
    events = ctx.get("macro_events") or []
    if events:
        ev_lines = [f"{e['category']} (sent {e['sentiment']:+.2f}): {e['headline'][:70]}" for e in events[:3]]
        fields.append({"name": "📰 24h Macro Events", "value": "\n".join(ev_lines), "inline": False})

    # Portfolio totals
    totals = ctx.get("portfolio_totals")
    if totals:
        acct_lines = [f"{a}: ${v:,.0f}" for a, v in totals["by_account"]]
        acct_lines.append(f"**TOTAL: ${totals['total_usd']:,.0f}** (equity only)")
        fields.append({"name": "💰 Portfolio", "value": "\n".join(acct_lines), "inline": False})

    return {
        "title": f"🌅 Nuri-Quant Pre-market Brief — {today_kst()}",
        "description": "Session 없이 자동 생성. qualitative 뉴스는 다음 Claude session 에서 cross-ref.",
        "color": _brief_color(ctx),
        "fields": fields,
        "footer": {"text": f"Nuri-Quant · {kst_now().strftime('%H:%M KST')}"},
    }


def format_brief_markdown(ctx: dict) -> str:
    """로컬 persist 용 markdown — Claude 가 다음 session 에 읽을 수 있게."""
    lines = [f"# Pre-market Brief — {today_kst()}", ""]
    lines.append(f"Generated: {kst_now().isoformat()}")
    lines.append("")

    regime = ctx.get("regime")
    macro = ctx.get("macro")
    if regime:
        lines.append(f"## Regime: {regime['regime']}")
        lines.append(f"- trend: {regime['trend']}, vol: {regime['volatility']}, conf: {regime['confidence']:.0f}%")
    if macro:
        lines.append(f"- Macro score: {macro['score']} ({macro['interpretation']})")
    lines.append("")

    parts = []
    for key, label in (("vix", "VIX"), ("fear_greed", "F&G"), ("usd_krw", "USD/KRW")):
        v = ctx.get(key)
        if v:
            parts.append(f"{label} {v['value']:.2f} ({v['date']})")
    if parts:
        lines.append("## Indicators")
        lines.append("- " + " · ".join(parts))
        lines.append("")

    siege = ctx.get("siege")
    if siege:
        lines.append(f"## Certification: {'CERTIFIED' if siege['certified'] else 'REJECTED'} ({siege['score']:.1f}%)")
        lines.append(f"- {siege['passed']}P / {siege['failed']}F / {siege['warnings']}W of {siege['total']}")
        for e in siege["failing_errors"]:
            lines.append(f"- ❌ {e['id']}: {e['desc']} — {e['detail']}")
        lines.append("")

    # Data Freshness (#513) — markdown 출력. embed 와 동일 로직 (#512 backend → user surface).
    fresh = ctx.get("freshness") or {}
    if fresh.get("details"):
        n_pass, n_warn, n_fail = fresh.get("pass", 0), fresh.get("warn", 0), fresh.get("fail", 0)
        if n_fail > 0:
            tier_emoji = "❌"
        elif n_warn > 0:
            tier_emoji = "⚠️"
        else:
            tier_emoji = "✅"
        lines.append(f"## Data Freshness {tier_emoji} {n_pass}P / {n_warn}W / {n_fail}F")
        for d in fresh["details"]:
            if d["status"] == "PASS":
                emoji = "✅"
            elif d["status"] == "WARN":
                emoji = "⚠️"
            else:
                emoji = "❌"
            lines.append(f"- {emoji} {d['label']}: {d['message']}")
        lines.append("")

    shadow = ctx.get("shadow_signals") or []
    if shadow:
        fired_count = sum(1 for s in shadow if s["fired"])
        lines.append(f"## SHADOW crash precursor ({fired_count}/{len(shadow)} fired)")
        for s in shadow:
            emoji = "⚠️" if s["fired"] else "·"
            lines.append(f"- {emoji} {s['signal_id']}: {s['detail']}")
        lines.append("")

    actions = ctx.get("actions") or {}
    for bucket in ("urgent", "portfolio", "check", "hold"):
        items = actions.get(bucket) or []
        if items:
            lines.append(f"## {bucket.title()} ({len(items)})")
            for it in items:
                lines.append(f"- {_short_ticker_line(it)}")
                for reason in (it.get("reasons") or [])[:2]:
                    lines.append(f"  · {reason}")
            lines.append("")

    bc = ctx.get("buy_candidates")
    if bc is not None:
        if bc.blocked_reason:
            lines.append("## BUY Candidates (0 — blocked)")
            lines.append(f"- **{bc.blocked_reason}**")
            lines.append(f"- regime={bc.regime} · VIX={format_vix(bc.vix)}")
            lines.append("")
        elif bc.candidates:
            lines.append(f"## BUY Candidates ({len(bc.candidates)} — total deploy {bc.total_deploy_pct}% of cash)")
            lines.append(f"- regime={bc.regime} · VIX={format_vix(bc.vix)} · {bc.timestamp_kst}")
            for i, c in enumerate(bc.candidates, 1):
                lines.append(f"{i}. **{c.ticker}** score={c.score}/100 deploy={c.deploy_pct}%")
                lines.append(f"   - Why now: {c.why_now}")
                lines.append(f"   - Entry ${c.entry} / Stop ${c.stop} / TP1 ${c.tp1} / TP2 ${c.tp2}")
                src = " · ".join(f"{k}={v:.0f}" for k, v in c.sources.items())
                lines.append(f"   - Sources: {src}")
            if bc.skipped:
                lines.append(f"   - skipped: {len(bc.skipped)} (held/cooldown/leverage)")
            lines.append("")

    ops = ctx.get("opportunities") or []
    if ops:
        lines.append(f"## Opportunities (비보유, top {len(ops)})")
        for o in ops:
            lines.append(
                f"- {o.get('ticker', '?')} score={o.get('score', 0) or 0:.0f} "
                f"5D={o.get('change_5d', 0) or 0:+.1f}% RSI={o.get('rsi', 0) or 0:.0f} "
                f"signal={o.get('signal', '-')}"
            )
            for p in (o.get("pros") or [])[:2]:
                lines.append(f"  ✓ {p}")
            for c in (o.get("cons") or [])[:2]:
                lines.append(f"  ✗ {c}")
        lines.append("")

    events = ctx.get("macro_events") or []
    if events:
        lines.append("## 24h Macro Events")
        for e in events:
            lines.append(f"- [{e['category']}] sent={e['sentiment']:+.2f} conf={e['confidence']:.2f}: {e['headline']}")
        lines.append("")

    totals = ctx.get("portfolio_totals")
    if totals:
        lines.append("## Portfolio")
        for a, v in totals["by_account"]:
            lines.append(f"- {a}: ${v:,.0f}")
        lines.append(f"- **TOTAL**: ${totals['total_usd']:,.0f} (equity only)")

    return "\n".join(lines)


def persist_brief(markdown: str, date: Optional[str] = None) -> Path:
    """Brief 를 로컬 파일에 저장 — 다음 session 이 auto pick up."""
    d = date or today_kst()
    base = Path(__file__).resolve().parents[2] / "data" / "reports" / "briefs"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{d}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def send_brief(embed: dict) -> bool:
    """Discord webhook 전송. 실패 시 False."""
    try:
        from nuri.alerts.discord_bot import send_webhook

        return send_webhook(embed)
    except Exception:
        logger.warning("Discord webhook 전송 실패", exc_info=True)
        return False


def generate_brief(db_path=None) -> dict:
    """Entry point for scheduler / CLI. Context 수집 + embed + markdown + persist.

    `db_path` 는 선택이다 — 스케줄러와 CLI 는 인자 없이 부르고 기본 DB 를 쓴다.
    받는 이유는 테스트가 이 경로를 명시적으로 격리할 수 있게 하기 위해서다
    (#1051). 전엔 db_path 배선이 전혀 없어 테스트가 조심해도 새로 들어갔다.
    """
    ctx = _collect_context(db_path=db_path)
    embed = format_brief_embed(ctx)
    markdown = format_brief_markdown(ctx)
    path = persist_brief(markdown)
    logger.info(f"Brief persisted to {path}")
    return {"ctx": ctx, "embed": embed, "markdown": markdown, "path": str(path)}


def main(argv: list[str] | None = None) -> int:
    """CLI: scheduler 와 manual 양쪽 entry. --no-discord 로 stdout only."""
    import argparse

    parser = argparse.ArgumentParser(description="Pre-market daily brief")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord webhook")
    parser.add_argument("--stdout", action="store_true", help="Print markdown to stdout")
    args = parser.parse_args(argv)

    result = generate_brief()
    if args.stdout or args.no_discord:
        print(result["markdown"])
    if not args.no_discord:
        ok = send_brief(result["embed"])
        if ok:
            logger.info("Discord brief 전송 완료")
        else:
            logger.info("Discord 전송 skip — stdout + local persist 만 사용")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
