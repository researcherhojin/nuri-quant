"""Discord embed builder helpers (#529 Phase 2 polish).

Pure builder functions — no Discord SDK / no I/O. 결과 dict 는
`DiscordPublisher.publish_embed(channel, embed=...)` 또는
`discord.Embed.from_dict(embed_dict)` 어느 쪽에도 그대로 투입 가능.

Discord embed limits (2026-04 docs):
    - title         ≤ 256
    - description   ≤ 4000   (실제 4096 이지만 안전 마진)
    - field.name    ≤ 256
    - field.value   ≤ 1024
    - footer.text   ≤ 2048
    - 최대 25 fields (그 이상은 Discord 가 reject)

설계:
    - 길이 초과 → 자동 truncate (`…` suffix). raise X — 알림 손실 방지.
    - 25 fields 초과 → warn log + 24개로 truncate (마지막 1 field 는 "+N more" 요약).
    - footer 기본값: "nuri-quant • {today_kst()}".
    - color 는 status/outcome 별 4-tier 팔레트.

Color palette (hex int):
    GREEN  0x2ECC71  pass / success
    AMBER  0xF39C12  warn
    RED    0xE74C3C  fail / block / error
    BLUE   0x3498DB  info / neutral
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

# ─── 길이 제약 ───
TITLE_MAX = 256
DESCRIPTION_MAX = 4000
FIELD_NAME_MAX = 256
FIELD_VALUE_MAX = 1024
FOOTER_MAX = 2048
MAX_FIELDS = 25

# ─── 색상 팔레트 ───
COLOR_GREEN = 0x2ECC71
COLOR_AMBER = 0xF39C12
COLOR_RED = 0xE74C3C
COLOR_BLUE = 0x3498DB

# Outcome → color map (build_actor_outcome_embed)
_OUTCOME_COLORS = {
    "pass": COLOR_GREEN,
    "warn": COLOR_AMBER,
    "block": COLOR_RED,
    "error": COLOR_RED,
}

# Freshness status → color map (build_freshness_embed)
_FRESHNESS_COLORS = {
    "PASS": COLOR_GREEN,
    "WARN": COLOR_AMBER,
    "FAIL": COLOR_RED,
}


def _truncate(text: str, limit: int) -> str:
    """초과분은 잘라내고 ellipsis(…) 부착."""
    if text is None:  # pragma: no cover — None-input defensive guard
        return ""
    if len(text) <= limit:
        return text
    # 1자 ellipsis 자리 확보
    return text[: max(0, limit - 1)] + "…"


def _default_footer() -> str:
    """기본 footer: 'nuri-quant • YYYY-MM-DD HH:MM KST'."""
    return f"nuri-quant • {today_kst()} {kst_now().strftime('%H:%M')} KST"


def _normalize_fields(fields: Optional[dict[str, str]]) -> list[dict[str, Any]]:
    """fields dict → Discord embed fields list.

    25 초과 시 24개로 자르고 마지막에 "(+N more)" 요약 field 추가.
    """
    if not fields:
        return []

    items = list(fields.items())
    if len(items) > MAX_FIELDS:
        overflow = len(items) - (MAX_FIELDS - 1)
        logger.warning("discord embed fields=%d > %d, truncating", len(items), MAX_FIELDS)
        kept = items[: MAX_FIELDS - 1]
        result = [
            {
                "name": _truncate(str(name), FIELD_NAME_MAX),
                "value": _truncate(str(value), FIELD_VALUE_MAX),
                "inline": True,
            }
            for name, value in kept
        ]
        result.append({"name": "…", "value": f"(+{overflow} more)", "inline": False})
        return result

    return [
        {
            "name": _truncate(str(name), FIELD_NAME_MAX),
            "value": _truncate(str(value), FIELD_VALUE_MAX),
            "inline": True,
        }
        for name, value in items
    ]


def build_status_embed(
    title: str,
    success: bool,
    body: str,
    fields: Optional[dict[str, str]] = None,
    footer: Optional[str] = None,
) -> dict[str, Any]:
    """일반 상태 embed (success → green / fail → red).

    /buy-candidates, /health 같은 명령 결과 surfacing 에 사용.
    """
    color = COLOR_GREEN if success else COLOR_RED
    return {
        "title": _truncate(title, TITLE_MAX),
        "description": _truncate(body, DESCRIPTION_MAX),
        "color": color,
        "fields": _normalize_fields(fields),
        "footer": {"text": _truncate(footer or _default_footer(), FOOTER_MAX)},
    }


def build_warn_embed(
    title: str,
    body: str,
    fields: Optional[dict[str, str]] = None,
    footer: Optional[str] = None,
) -> dict[str, Any]:
    """경고 embed (amber). 데이터 stale, soft-penalty surface 등."""
    return {
        "title": _truncate(title, TITLE_MAX),
        "description": _truncate(body, DESCRIPTION_MAX),
        "color": COLOR_AMBER,
        "fields": _normalize_fields(fields),
        "footer": {"text": _truncate(footer or _default_footer(), FOOTER_MAX)},
    }


def build_freshness_embed(check_results: list[dict]) -> dict[str, Any]:
    """`nuri.core.freshness.check_all_freshness()` 결과 → embed.

    title: "Data Freshness — N/M PASS"
    color: 최악 status 기준 (FAIL > WARN > PASS)
    fields: 각 check 별 "{key}" → "{status} • {age_hours}h"
    """
    total = len(check_results)
    passed = sum(1 for r in check_results if r.get("status") == "PASS")
    has_fail = any(r.get("status") == "FAIL" for r in check_results)
    has_warn = any(r.get("status") == "WARN" for r in check_results)

    if has_fail:
        color = COLOR_RED
    elif has_warn:
        color = COLOR_AMBER
    else:
        color = COLOR_GREEN

    fields_dict: dict[str, str] = {}
    for r in check_results:
        key = str(r.get("key", "?"))
        status = str(r.get("status", "?"))
        age = r.get("age_hours")
        age_str = f"{age}h" if age is not None else "n/a"
        fields_dict[key] = f"{status} • {age_str}"

    return {
        "title": _truncate(f"Data Freshness — {passed}/{total} PASS", TITLE_MAX),
        "description": _truncate(
            "신선도 정책별 SLA 점검 결과 (PASS=초록 / WARN=호박 / FAIL=빨강).",
            DESCRIPTION_MAX,
        ),
        "color": color,
        "fields": _normalize_fields(fields_dict),
        "footer": {"text": _truncate(_default_footer(), FOOTER_MAX)},
    }


def build_actor_outcome_embed(
    actor_name: str,
    outcome: str,
    summary: str,
    run_id: str,
) -> dict[str, Any]:
    """Layer A actor decision surface.

    outcome ∈ {pass, warn, block, error} — 그 외는 BLUE (neutral) 로 fallback.
    title: "{actor} → {OUTCOME}"
    footer: "{run_id} • {today_kst()} HH:MM KST"
    """
    outcome_norm = (outcome or "").lower().strip()
    color = _OUTCOME_COLORS.get(outcome_norm, COLOR_BLUE)
    title = f"{actor_name} → {outcome_norm.upper() or 'UNKNOWN'}"
    footer = f"run_id={run_id} • {today_kst()} {kst_now().strftime('%H:%M')} KST"
    return {
        "title": _truncate(title, TITLE_MAX),
        "description": _truncate(summary, DESCRIPTION_MAX),
        "color": color,
        "fields": [],
        "footer": {"text": _truncate(footer, FOOTER_MAX)},
    }
