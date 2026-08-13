"""BriefAuditor — Discord-as-dev-loop self-quality actor.

Why this exists (2026-05-02 user escalation):
사용자가 #brief 채널 screenshot 공유. NVDA 가 BUY → BUY → SELL 같은 conviction
0.810 으로 같은 시간대 emit. 숫자만 dump 되고 가격/근거/충돌 surface 없음.
사용자: "당신이 알아서 개발할 수 있는 형태로 디스코드를 활용해주세요."

→ Discord 가 단순 출력 sink 가 아니라 **claude/codex 가 본인 emit 품질을
self-audit 하고 개선 ticket 을 자동으로 #incidents 에 띄우는 dev loop** 가
되게 함. 사용자는 #incidents 만 보면 다음 PR scope 가 추출됨.

Phase 0 (이 모듈, deterministic only — ZERO LLM):
    C1 conflict           — 같은 ticker BUY+SELL 24h 내 동시 emit
    C2 noise              — 같은 ticker > 3 emit 24h 내
    C3 identical_conv     — 최근 N emit 의 conviction 이 모두 동일 (broken scoring)

Phase 1 (deferred):
    C4 missing_price      — content_preview 에 $ 가 없음 (brief 포맷 결함)
    LLM-based root cause  — codex 가 issue 의 의미 narrative
    Auto-PR draft         — issue → PR scope yaml emit

Hard constraint:
    - 절대 매매 권고 X. 시스템 출력 quality 만 audit.
    - 사용자 reaction (👍/👎) 학습 deferred — Discord bot read access 필요.
    - 같은 issue_id 24h 내 1회만 emit (dedupe via incidents channel content_preview).

Layer: B (deterministic computation on past audit data).

Output gate:
    PASS  — 0 issues found
    WARN  — issues found and emitted (or already emitted within 24h)
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from typing import Any, Optional

from nuri.agents.base import Actor, ActorResult, Layer, Outcome, RunContext
from nuri.core.db import query

logger = logging.getLogger(__name__)

# 자가점검 emit/dedupe 채널 — _emit_incident(stage_ops) 와 _dedupe_recent 가
# 반드시 일치해야 함 (불일치 시 dedupe 미스 → 6h 마다 재emit 스팸).
_AUDIT_CHANNEL = "ops"

DEFAULT_AUDIT_HOURS = 24
NOISE_THRESHOLD = 3  # 같은 ticker > 3 emit / 24h
IDENTICAL_CONV_TOLERANCE = 1e-3  # conviction 차이 < 0.001 → identical
IDENTICAL_CONV_MIN_SAMPLES = 5  # 최소 5 emit 이상에서만 검출

# Issue type → 사람이 읽는 한 줄 의미 (digest summary 에 surface — cryptic 코드 대신)
_ISSUE_MEANING = {
    "conflict": "같은 종목에 BUY+SELL 24h 내 동시 emit (자기모순)",
    "noise": "같은 종목 24h 내 3회 초과 emit (중복 스팸)",
    "identical_conv": "conviction 점수가 전부 동일 (scoring 결함)",
}

# Issue type → suggested fix path (보고서에 surface)
_SUGGESTED_FIX = {
    "conflict": "nuri/agents/discord/brief_card.py — same-ticker BUY+SELL 합쳐서 CONFLICT card 1건만 emit",
    "noise": "nuri/agents/actors/decision_compiler.py — 같은 ticker repeat-emit cooldown (last_emit_at + 6h 룰)",
    "identical_conv": "nuri/agents/actors/decision_compiler.py:188 conviction 가중치 산출 검증 — 입력 변동성 부재 가능",
}


class BriefAuditor(Actor):
    """Audit recent #brief decision emits and surface quality issues to #incidents.

    Usage:
        result = BriefAuditor().run({"hours": 24})
        # → result.output["issues_emitted"] = N
    """

    name = "brief-auditor"
    version = "0.1.0"
    layer = Layer.B

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        hours = int(input_data.get("hours") or DEFAULT_AUDIT_HOURS)
        db_path = input_data.get("db_path")

        decisions = _fetch_recent_decisions(hours, db_path)

        issues: list[dict[str, Any]] = []
        issues.extend(_check_conflict(decisions))
        issues.extend(_check_noise(decisions))
        issues.extend(_check_identical_conv(decisions))

        new_issues = _dedupe_recent(issues, hours, db_path)

        emit_results = []
        for issue in new_issues:
            ok = _emit_incident(issue, ctx.run_id, db_path)
            emit_results.append({"issue_id": issue["issue_id"], "ok": ok})

        return ActorResult(
            output={
                "audit_hours": hours,
                "decisions_audited": len(decisions),
                "issues_found": len(issues),
                "issues_emitted": len(new_issues),
                "issues_dedupe_skipped": len(issues) - len(new_issues),
                "issues": issues,
                "emit_results": emit_results,
            },
            outcome=Outcome.WARN if new_issues else Outcome.PASS,
            sample_n=len(decisions),
            input_summary=f"audit {hours}h / {len(decisions)} decisions / {len(new_issues)} new issues",
        )


# ─── data layer ────────────────────────────────────────────────


def _fetch_recent_decisions(hours: int, db_path: Optional[Any]) -> list[dict[str, Any]]:
    """Read agent_decisions actually published to #brief within last N hours.

    HOLD 는 #brief 발송 안 됨 — BUY/SELL 만 audit 대상.

    status filter:
        'emitted'    — 현재 활성
        'superseded' — 이전에 발송 후 같은 ticker 의 새 emit 으로 덮어쓰여짐.
                       발송 자체는 이미 일어났으므로 #brief 품질 audit 에 포함해야
                       conflict / noise 가 정확히 잡힘.
    """
    rows = query(
        """SELECT decision_id, ticker, action, conviction, created_at, run_id
             FROM agent_decisions
            WHERE status IN ('emitted','superseded')
              AND action IN ('BUY','SELL')
              AND created_at > datetime('now', ?)
            ORDER BY created_at""",
        (f"-{hours} hours",),
        db_path=db_path,
    )
    return [dict(r) for r in rows]


def _dedupe_recent(
    issues: list[dict[str, Any]],
    hours: int,
    db_path: Optional[Any],
) -> list[dict[str, Any]]:
    """Drop issues whose dedupe_key was staged to outbox within last N hours.

    Outbox dedupe_key 패턴 `brief_quality:<issue_id>` 로 조회. status 무관 (pending/sent/failed/dropped 모두) — 24h 내 1회만 surface.
    """
    if not issues:
        return []
    rows = query(
        """SELECT dedupe_key FROM discord_outbox
            WHERE channel = ?
              AND dedupe_key IS NOT NULL
              AND created_at > datetime('now', ?)""",
        (_AUDIT_CHANNEL, f"-{hours} hours"),
        db_path=db_path,
    )
    seen_keys = {r["dedupe_key"] for r in rows if r["dedupe_key"]}
    return [i for i in issues if f"brief_quality:{i['issue_id']}" not in seen_keys]


# ─── checks ───────────────────────────────────────────────────


def _check_conflict(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C1: same ticker BUY + SELL within audit window."""
    by_ticker: dict[str, set[str]] = defaultdict(set)
    decisions_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        by_ticker[d["ticker"]].add(d["action"])
        decisions_by_ticker[d["ticker"]].append(d)

    issues = []
    for ticker, actions in by_ticker.items():
        if "BUY" in actions and "SELL" in actions:
            ticker_decisions = decisions_by_ticker[ticker]
            issue_id = _make_issue_id("conflict", [ticker])
            evidence_lines = [
                f"  - {d['action']} {d['decision_id']} conv={d['conviction']:.3f} @ {d['created_at']}"
                for d in ticker_decisions
            ]
            issues.append(
                {
                    "issue_id": issue_id,
                    "type": "conflict",
                    "affected": [ticker],
                    "evidence": "\n".join(evidence_lines[:8]),  # 8개로 제한
                    "n_decisions": len(ticker_decisions),
                    "suggested_fix": _SUGGESTED_FIX["conflict"],
                }
            )
    return issues


def _check_noise(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C2: same ticker > NOISE_THRESHOLD emits in window."""
    counts = Counter(d["ticker"] for d in decisions)
    decisions_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        decisions_by_ticker[d["ticker"]].append(d)

    issues = []
    for ticker, n in counts.items():
        if n > NOISE_THRESHOLD:
            issue_id = _make_issue_id("noise", [ticker])
            ticker_decisions = decisions_by_ticker[ticker]
            actions_seq = " → ".join(d["action"] for d in ticker_decisions[:8])
            issues.append(
                {
                    "issue_id": issue_id,
                    "type": "noise",
                    "affected": [ticker],
                    "evidence": f"  - {n} emits in window: {actions_seq}",
                    "n_decisions": n,
                    "suggested_fix": _SUGGESTED_FIX["noise"],
                }
            )
    return issues


def _check_identical_conv(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C3: all recent emits have identical conviction (broken scoring signal)."""
    if len(decisions) < IDENTICAL_CONV_MIN_SAMPLES:
        return []
    convictions = [d["conviction"] for d in decisions]
    spread = max(convictions) - min(convictions)
    if spread >= IDENTICAL_CONV_TOLERANCE:
        return []
    affected_tickers = sorted({d["ticker"] for d in decisions})
    issue_id = _make_issue_id("identical_conv", affected_tickers)
    return [
        {
            "issue_id": issue_id,
            "type": "identical_conv",
            "affected": affected_tickers,
            "evidence": (
                f"  - {len(decisions)} emits, conviction spread={spread:.6f} "
                f"(tolerance {IDENTICAL_CONV_TOLERANCE})\n"
                f"  - sample: {convictions[0]:.6f} on tickers {affected_tickers[:6]}"
            ),
            "n_decisions": len(decisions),
            "suggested_fix": _SUGGESTED_FIX["identical_conv"],
        }
    ]


# ─── emit ─────────────────────────────────────────────────────


def _make_issue_id(issue_type: str, affected: list[str]) -> str:
    """Deterministic 12-char hash so dedupe survives re-runs.

    Same issue_type + same affected ticker set → same id.
    """
    key = f"{issue_type}:{','.join(sorted(affected))}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _emit_incident(issue: dict[str, Any], run_id: str, db_path: Optional[Any]) -> bool:
    """Stage self-audit issue to #ops outbox (시스템 자가점검 — 매매 신호 아님).

    #incidents(사용자 조치용)와 분리해 #ops(운영 상태)로 보낸다. dispatcher 가
    6h cron 마다 종합. dedupe_key 로 24h 내 중복 방지 (outbox 자체).
    """
    try:
        from nuri.agents.discord.outbox import stage_ops

        affected = ", ".join(issue["affected"][:3]) + ("…" if len(issue["affected"]) > 3 else "")
        meaning = _ISSUE_MEANING.get(issue["type"], issue["type"])
        stage_ops(
            payload={
                "kind": f"brief_quality_{issue['type']}",
                # cryptic "CONFLICT on TSLA: n=19" 대신 사람이 읽는 한 줄.
                "summary": f"{affected} ({issue['n_decisions']}회) — {meaning}",
                "issue_id": issue["issue_id"],
                "affected": issue["affected"],
                "evidence": issue["evidence"],
                "suggested_fix": issue["suggested_fix"],
            },
            dedupe_key=f"brief_quality:{issue['issue_id']}",
            actor_name="brief-auditor",
            run_id=run_id,
            db_path=db_path,
        )
        return True
    except Exception:  # noqa: BLE001 — stage must not break audit
        # 호출자에게 False 로 알리되 **원인은 남긴다** — 반환값만으로는
        # 왜 실패했는지 알 수 없어 며칠째 발행이 안 돼도 진단이 안 된다.
        logger.exception("outbox staging 실패: stage_ops")
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m nuri.agents.actors.brief_auditor [--hours N]"""
    import argparse

    parser = argparse.ArgumentParser(prog="brief-auditor")
    parser.add_argument("--hours", type=int, default=DEFAULT_AUDIT_HOURS)
    args = parser.parse_args(argv)

    result = BriefAuditor().run({"hours": args.hours})
    print(
        f"audited={result.output['decisions_audited']} "
        f"found={result.output['issues_found']} "
        f"emitted={result.output['issues_emitted']} "
        f"deduped={result.output['issues_dedupe_skipped']}"
    )
    for i in result.output["issues"]:
        print(f"  [{i['issue_id']}] {i['type']}: {','.join(i['affected'])}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
