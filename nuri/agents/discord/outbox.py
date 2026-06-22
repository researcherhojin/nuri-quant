"""Discord outbox public API + digest layout helpers (Codex Round 6, 2026-05-02).

Caller-facing convenience wrapping `nuri.core.db.discord_outbox_ops`. 모든 actor 가
`stage_brief()` / `stage_ops()` / `stage_incident()` / `stage_rollout()` 4개 helper
하나만 호출하면 됨 — channel string 실수 / payload 형식 mismatch 방지.

**중요 invariant (Codex 단호한 권고)**:
모든 channel emit 은 **이 모듈** 또는 watchdog (recursion 방지) 만 직접 publish.
actor 가 `DiscordPublisher` 를 직접 호출하면 single-writer 깨짐 → CI 검사 추가
(future) + code review 차단.

Layout helpers:
    bucket_brief_digest(events) — Codex 권장 actionability bucket layout 으로
    여러 BUY/SELL/HOLD/BLOCK event 를 1 embed dict 로 합친다. dispatcher 가 호출.

Payload schema (#571 brief content extension):
    Required:
        kind        — BUY | SELL | HOLD | BLOCK | CONFLICT | INFO
        ticker      — symbol (US: AAPL / KR: 005930.KS)
    Optional core:
        conviction  — float [0..1] consensus confidence
        regime      — text e.g. "top 0.72"
        causal      — text e.g. "0.68"
        horizon     — text e.g. "growth" | "swing" | "value"
        reason      — short label e.g. "stop-loss" | "TP1 reached"
        note        — free-form
        decision_id — dedupe key
    Optional #571 Phase 1 (BUY/SELL only — HOLD/INFO/BLOCK 은 surface 안 함):
        price_levels: {
            entry          — float (현재가 또는 명시 진입가)
            stop           — float (-7%/-10%/-5% per growth/value/swing)
            tp1            — float (1차 익절 — 50% sell trigger)
            tp2            — float (2차 익절 — 25% / all sell trigger)
            trailing_pct   — float ladder (e.g., -15)
        }
        ↳ canonical source: `nuri.trading.recommend.price_targets.calculate_targets()`.
        ↳ caller 는 위 함수 그대로 호출 → 결과 키 매핑해 attach.
        ↳ 누락 / error 시 silent omit (legacy payload back-compat).
    #571 Phase 2 (BUY/SELL only — decision_compiler 가 자동 첨부):
        horizon     — "growth" | "value" | "swing" (price_targets.classify_stock_type)
        position    — "new" | "held" | "held/winner" | "held/loser" (현재가 vs 평단 ±5%)
    Optional #571 Phase 3+ (별 후속): signal_top2, invalidation, counter-evidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from nuri.core.db import stage_outbox
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

# Discord embed limits — agents/discord/embeds.py 와 동일 (Single source of truth
# 아니지만 import 순환 회피 위해 중복 정의)
_TITLE_MAX = 256
_DESC_MAX = 4000
_FIELD_NAME_MAX = 256
_FIELD_VALUE_MAX = 1024
_MAX_FIELDS = 25

_PRIORITY_BY_ACTION = {
    "BUY": 0,
    "SELL": 0,
    "BLOCK": 1,
    "CONFLICT": 1,
    "HOLD": 2,
    "INFO": 2,
}

# 사용자가 본 통증의 색상 단서 — bucket 별 색
_BUCKET_COLORS = {
    "Action Now": 0x2ECC71,  # green
    "Blocked / Conflict": 0xE74C3C,  # red
    "Lower Priority": 0x95A5A6,  # gray
}


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def stage_brief(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #brief outbox. Dispatcher 가 종합해서 발송."""
    return stage_outbox(
        "brief",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_ops(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #ops outbox."""
    return stage_outbox(
        "ops",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_incident(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #incidents outbox."""
    return stage_outbox(
        "incidents",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_rollout(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #research-rollout outbox."""
    return stage_outbox(
        "rollout",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def stage_agent_control(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> Optional[int]:
    """Stage one event into #agent-control outbox (HITL gate, E1 #582).

    agent loop 의 verdict (PASS / NEEDS_REWORK / ABSTAIN) 를 사용자 ✅/❌ 응답
    대상으로 publish. inbound (E4) 가 reaction 잡으면 dedupe_key 로 매칭.
    """
    return stage_outbox(
        "agent_control",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


def _privacy_gate_payload(payload: dict[str, Any]) -> list[Any]:
    """E3 #579 — agent transcript stream gate. payload 의 모든 텍스트를 직렬화해
    privacy 검사 4 카테고리 통과 여부 확인. caller 가 violation list 로 publish 차단."""
    # Lazy import to avoid CLI-script dep at module import time.
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "verify"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from check_privacy_leak import gate_text  # type: ignore[import-not-found]

    text = json.dumps(payload, ensure_ascii=False, default=str)
    return gate_text(text, source="<agent_dev_log>")


def stage_agent_dev_log(
    payload: dict[str, Any],
    dedupe_key: Optional[str] = None,
    priority: str = "normal",
    actor_name: Optional[str] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Any] = None,
    skip_privacy_gate: bool = False,
) -> Optional[int]:
    """Stage one event into #agent-dev-log outbox (transcript, E2 #578).

    Codex (Architect, spec) → Claude (Builder, patch) → Qwen (Adversarial Reviewer)
    각 단계의 산출물을 read-only transcript 로 publish.

    E3 #579: payload 가 broker name / ticker+PnL / monetary literal 누설을
    포함하면 publish 차단 (return None) + WARNING log. `skip_privacy_gate=True`
    는 테스트/내부 디버깅 한정.
    """
    if not skip_privacy_gate:
        try:
            findings = _privacy_gate_payload(payload)
        except Exception as exc:
            # gate 실패는 fail-open 보다 fail-closed — 누설 의심 시 publish 차단.
            logger.warning("privacy gate raised (%s); blocking publish for safety", exc)
            return None
        if findings:
            logger.warning(
                "privacy gate blocked agent_dev_log publish — %d violation(s): %s",
                len(findings),
                [f"{f.category}:{f.pattern}" for f in findings[:3]],
            )
            return None

    return stage_outbox(
        "agent_dev_log",
        payload,
        priority=priority,
        dedupe_key=dedupe_key,
        actor_name=actor_name,
        run_id=run_id,
        db_path=db_path,
    )


# ─── digest layout (Codex Round 6 actionability bucket pattern) ──────────


def _classify_event(payload: dict[str, Any]) -> str:
    """Map event payload → bucket name.

    payload['kind']: BUY/SELL/HOLD/BLOCK/CONFLICT/INFO
    """
    kind = (payload.get("kind") or "").upper()
    pri = _PRIORITY_BY_ACTION.get(kind, 2)
    if pri == 0:
        return "Action Now"
    if pri == 1:
        return "Blocked / Conflict"
    return "Lower Priority"


def _format_price_levels(price_levels: Optional[dict[str, Any]]) -> Optional[str]:
    """Render price_levels dict as compact line (#571 Phase 1).

    `↳ entry $132 / stop $123 / TP1 $158 / TP2 $185 · trail -15%`

    None / 결측 시 None 반환 (caller 가 omit). 사용자 룰: BUY/SELL recommendation
    은 entry/stop/target_1/target_2/trailing 명시 의무 (`nuri/trading/recommend/CLAUDE.md`
    "Price levels mandatory").
    """
    if not price_levels or not isinstance(price_levels, dict):
        return None
    entry = price_levels.get("entry")
    stop = price_levels.get("stop")
    tp1 = price_levels.get("tp1")
    tp2 = price_levels.get("tp2")
    trailing_pct = price_levels.get("trailing_pct")

    def _fmt_price(v: Any) -> str:
        if v is None:  # pragma: no cover — caller pre-filters None at L297-303
            return "—"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "—"
        return f"${f:,.2f}" if f < 1000 else f"${f:,.0f}"

    parts = []
    if entry is not None:
        parts.append(f"entry {_fmt_price(entry)}")
    if stop is not None:
        parts.append(f"stop {_fmt_price(stop)}")
    if tp1 is not None:
        parts.append(f"TP1 {_fmt_price(tp1)}")
    if tp2 is not None:
        parts.append(f"TP2 {_fmt_price(tp2)}")
    if not parts:
        return None
    main = " / ".join(parts)
    if trailing_pct is not None:
        try:
            t = float(trailing_pct)
            main += f" · trail {t:+.0f}%"
        except (TypeError, ValueError):
            pass
    return f"  ↳ {main}"


def _format_event_line(payload: dict[str, Any]) -> str:
    """Compact event renderer (Codex format + #571 price_levels extension).

    Single line:
        `NVDA | SELL | conv 0.81 | regime bear 0.72 | causal 0.68 | reason: stop-loss`

    With price_levels (BUY/SELL recommendations):
        `NVDA | BUY | conv 0.81 | regime bull 0.72 | causal 0.68`
        `  ↳ entry $132 / stop $123 / TP1 $158 / TP2 $185 · trail -15%`
    """
    kind = (payload.get("kind") or "?").upper()
    ticker = payload.get("ticker", "?")
    parts = [str(ticker), kind]
    if "conviction" in payload:
        parts.append(f"conv {float(payload['conviction']):.2f}")
    # #571 Phase 2: position 도 surface (new / held / held-winner / held-loser).
    for opt in ("regime", "causal", "horizon", "position", "reason", "note"):
        if opt in payload and payload[opt] is not None:
            parts.append(f"{opt}: {payload[opt]}")
    head = " | ".join(parts)

    # #571 Phase 1: BUY/SELL 만 price_levels surface — HOLD/INFO/BLOCK 은 noise.
    if kind in ("BUY", "SELL"):
        levels_line = _format_price_levels(payload.get("price_levels"))
        if levels_line:
            return f"{head}\n{levels_line}"
    return head


def bucket_brief_digest(
    events: list[dict[str, Any]],
    title_prefix: str = "Nuri Brief Digest",
) -> dict[str, Any]:
    """Compose multiple stage_brief() payloads into ONE digest embed.

    Codex layout:
        Title:       "Nuri Brief Digest | YYYY-MM-DD HH:MM KST | N opinions"
        Description: "BUY 2 | SELL 1 | BLOCK 2 | manual execute only"
        Fields:      Action Now / Blocked|Conflict / Lower Priority
                     each = compact one-line list, hard cap to fit Discord limits

    Returns Discord embed dict — caller passes to DiscordPublisher.publish_embed.
    """
    if not events:
        return {
            "title": _truncate(
                f"{title_prefix} | {today_kst()} {kst_now().strftime('%H:%M')} KST | 0 opinions", _TITLE_MAX
            ),
            "description": "(no pending events)",
            "color": _BUCKET_COLORS["Lower Priority"],
            "fields": [],
            "footer": {"text": "manual execute only"},
        }

    counts = {"BUY": 0, "SELL": 0, "BLOCK": 0, "CONFLICT": 0, "HOLD": 0, "INFO": 0}
    buckets: dict[str, list[str]] = {
        "Action Now": [],
        "Blocked / Conflict": [],
        "Lower Priority": [],
    }
    for ev in events:
        kind = (ev.get("kind") or "").upper()
        if kind in counts:
            counts[kind] += 1
        bucket = _classify_event(ev)
        buckets[bucket].append(_format_event_line(ev))

    n = len(events)
    title = f"{title_prefix} | {today_kst()} {kst_now().strftime('%H:%M')} KST | {n} opinions"

    desc_parts = []
    for kind in ("BUY", "SELL", "BLOCK", "CONFLICT", "HOLD"):
        if counts[kind]:
            desc_parts.append(f"{kind} {counts[kind]}")
    desc = " | ".join(desc_parts) + " | manual execute only" if desc_parts else "manual execute only"

    fields = []
    for bucket_name in ("Action Now", "Blocked / Conflict", "Lower Priority"):
        lines = buckets[bucket_name]
        if not lines:
            continue
        # Truncate per-event to keep value < 1024.
        # #571 Phase 1: events with price_levels are 2-line (head + ↳ levels)
        # so per-event cap raised 200→260 to fit multi-line without cutting
        # the levels mid-string.
        body_lines: list[str] = []
        running = 0
        for ln in lines:
            ln_trunc = _truncate(ln, 260)
            if running + len(ln_trunc) + 1 > _FIELD_VALUE_MAX:
                hidden = len(lines) - len(body_lines)
                body_lines.append(f"… (+{hidden} more)")
                break
            body_lines.append(ln_trunc)
            running += len(ln_trunc) + 1
        fields.append(
            {
                "name": _truncate(f"{bucket_name} ({len(lines)})", _FIELD_NAME_MAX),
                "value": _truncate("\n".join(body_lines), _FIELD_VALUE_MAX),
                "inline": False,
            }
        )
        if len(fields) >= _MAX_FIELDS:  # pragma: no cover — only 3 buckets, cap unreachable
            break

    color = (
        _BUCKET_COLORS["Action Now"]
        if buckets["Action Now"]
        else (
            _BUCKET_COLORS["Blocked / Conflict"] if buckets["Blocked / Conflict"] else _BUCKET_COLORS["Lower Priority"]
        )
    )

    return {
        "title": _truncate(title, _TITLE_MAX),
        "description": _truncate(desc, _DESC_MAX),
        "color": color,
        "fields": fields,
        "footer": {"text": "manual execute only — STRATEGY §7.1"},
    }


# BriefAuditor 자가점검 kind → 사람이 이해하는 그룹 메타 (cryptic 코드 대신).
# label=친화적 제목, what=한 줄 의미, action=개발 조치. 없는 kind 는 raw 그대로.
_QUALITY_KIND_META: dict[str, dict[str, str]] = {
    "brief_quality_conflict": {
        "label": "⚠️ 자기모순 신호",
        "what": "같은 종목에 BUY+SELL 을 24h 내 동시 emit (추천 신뢰도 결함)",
        "action": "조치(개발): brief_card.py — BUY+SELL 을 CONFLICT 카드 1건으로 통합",
    },
    "brief_quality_noise": {
        "label": "🔁 중복 스팸",
        "what": "같은 종목을 24h 내 3회 초과 emit (시그널이 묻힘)",
        "action": "조치(개발): decision_compiler.py — 종목별 6h repeat-emit 쿨다운",
    },
    "brief_quality_identical_conv": {
        "label": "📊 scoring 결함",
        "what": "conviction 점수가 전부 동일 (가중치 산출 검증 필요)",
        "action": "조치(개발): decision_compiler.py — conviction 입력 변동성 점검",
    },
}

# SREIncidentAgent 인프라 인시던트 kind → 사람이 이해하는 메타 (#incidents).
# brief_quality(자가점검)와 달리 **실제 운영 사고**라 "매매 신호 아님" disclaimer 안 붙는다.
# 영향 수치(42분째 등)는 producer 가 만든 summary 한 줄이 담고, 여기선 의미+조치를 제공.
_SRE_KIND_META: dict[str, dict[str, str]] = {
    "sre_scheduler_heartbeat": {
        "label": "🔴 스케줄러 정지",
        "what": "스케줄러 heartbeat 갱신 중단 — 데이터 수집이 멈춤",
        "action": "조치: watchdog 자동 재시작 동작 / 수동 `launchctl kickstart -k gui/$(id -u)/com.nuri-quant.scheduler`",
    },
    "sre_disk_full": {
        "label": "💾 디스크 부족",
        "what": "디스크 사용률이 임계 초과 — 수집/백업 실패 위험",
        "action": "조치: data/backups·오래된 로그/export 정리",
    },
    "sre_db_lock": {
        "label": "🔒 DB 접근 장애",
        "what": "DB SELECT 실패 — 락 또는 파일 접근 불가",
        "action": "조치: 동시 쓰기 확인 후 필요시 스케줄러 재시작",
    },
    "sre_orphan_run": {
        "label": "👻 멈춘 작업",
        "what": "agent run 이 정상 종료 없이 장시간 미완료(orphan)",
        "action": "조치: 해당 actor 로그 확인 후 재실행 / 데몬 재시작",
    },
    "sre_actor_failure_streak": {
        "label": "🔁 작업 연속 실패",
        "what": "특정 actor 가 연속 실패 중 — 수집/분석 중단",
        "action": "조치: scheduler.err 로그 확인 후 원인 수정",
    },
    "sre_data_freshness_critical": {
        "label": "📉 데이터 신선도 위험",
        "what": "복수 데이터 소스가 stale — 판단 근거 신뢰도 저하",
        "action": "조치: 해당 collector 수동 실행 / 수집 스케줄 점검",
    },
}


def bucket_generic_digest(
    events: list[dict[str, Any]],
    channel_label: str,
    color: int = 0x3498DB,
) -> dict[str, Any]:
    """Generic digest for #ops / #incidents / #rollout.

    No actionability bucketing — group by 'kind' or 'category' if present,
    otherwise flat list.
    """
    if not events:
        return {
            "title": _truncate(
                f"{channel_label} Digest | {today_kst()} {kst_now().strftime('%H:%M')} KST | 0 events", _TITLE_MAX
            ),
            "description": "(no pending events)",
            "color": color,
            "fields": [],
            "footer": {"text": "auto digest"},
        }

    n = len(events)
    title = f"{channel_label} Digest | {today_kst()} {kst_now().strftime('%H:%M')} KST | {n} events"

    by_group: dict[str, list[str]] = {}
    for ev in events:
        group = str(ev.get("kind") or ev.get("category") or "general")
        line = ev.get("summary") or _format_event_line(ev)
        by_group.setdefault(group, []).append(str(line))

    fields = []
    for group, lines in by_group.items():
        meta = _QUALITY_KIND_META.get(group) or _SRE_KIND_META.get(group)
        group_name = f"{meta['label']} ({len(lines)})" if meta else f"{group} ({len(lines)})"
        body_lines: list[str] = []
        # 자가점검 kind 는 그룹 맨 위에 "무엇인지" 한 줄을 먼저 박는다.
        if meta:
            body_lines.append(f"ℹ️ {meta['what']}")
        running = sum(len(b) + 1 for b in body_lines)
        for ln in lines:
            ln_trunc = _truncate(ln, 200)
            if running + len(ln_trunc) + 1 > _FIELD_VALUE_MAX:
                hidden = len(lines) - (len(body_lines) - (1 if meta else 0))
                body_lines.append(f"… (+{hidden} more)")
                break
            body_lines.append(ln_trunc)
            running += len(ln_trunc) + 1
        # 자가점검 kind 는 맨 아래 "조치" 를 붙인다 (사용자가 할 일이 아니라 코드 개선).
        if meta and running + len(meta["action"]) + 1 <= _FIELD_VALUE_MAX:
            body_lines.append(f"→ {meta['action']}")
        fields.append(
            {
                "name": _truncate(group_name, _FIELD_NAME_MAX),
                "value": _truncate("\n".join(body_lines), _FIELD_VALUE_MAX),
                "inline": False,
            }
        )
        if len(fields) >= _MAX_FIELDS:
            break

    # 자가점검 kind 가 하나라도 있으면 "매매 신호 아님" 을 description 에 명시.
    has_quality = any(g in _QUALITY_KIND_META for g in by_group)
    description = (
        f"※ 매매 신호 아님 — 시스템 자가점검 결과 ({n}건). 아래 '조치'는 코드 개선 백로그입니다."
        if has_quality
        else f"{n} aggregated events"
    )

    return {
        "title": _truncate(title, _TITLE_MAX),
        "description": _truncate(description, _DESC_MAX),
        "color": color,
        "fields": fields,
        "footer": {"text": "auto digest"},
    }
