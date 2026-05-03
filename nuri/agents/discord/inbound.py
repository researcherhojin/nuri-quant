"""Discord inbound listener — #agent-control + #agent-dev-log 의 message + reaction 수신.

epic #577 / E1 (#582). outbox 와 sibling — single-writer rule (outbound) 위반 아님.
emit 위치: data/discord_inbound/{label}/{ts_kst}_{event}.json (gitignored).

2 채널 외 메시지/리액션은 default-deny 무시. ticker/PnL mask 는 placeholder —
정식 stream gate 는 E3 (#579) 가 담당.

env:
    DISCORD_CHANNEL_AGENT_CONTROL_ID    HITL gate 채널 (필수)
    DISCORD_CHANNEL_AGENT_DEV_LOG_ID    transcript 관찰 채널 (필수)
    NURI_DISCORD_INBOUND_DIR            출력 디렉토리 override (테스트용)
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Mask placeholder — naive monetary literal redaction. tickers + PnL 복합 패턴
# 미포함 (E3 정식 가드 도착 전 임시). 분리된 표현식으로 character-class escape 회피.
_MONEY_RE = re.compile(r"[$₩]\s?[\d,]+(?:\.\d+)?\s?[KMBkmb]?")


def _channel_targets() -> dict[int, str]:
    """env 에서 (channel_id → label) 매핑 read. 미설정/비숫자 ID 는 skip.

    Call-site 마다 read — 테스트가 monkeypatch 로 env 갈아끼울 수 있도록.
    """
    targets: dict[int, str] = {}
    for env_key, label in (
        ("DISCORD_CHANNEL_AGENT_CONTROL_ID", "agent-control"),
        ("DISCORD_CHANNEL_AGENT_DEV_LOG_ID", "agent-dev-log"),
    ):
        raw = os.getenv(env_key, "").strip()
        if raw.isdigit():
            targets[int(raw)] = label
    return targets


def _inbound_dir() -> Path:
    override = os.getenv("NURI_DISCORD_INBOUND_DIR", "").strip()
    if override:
        return Path(override)
    return REPO_ROOT / "data" / "discord_inbound"


def mask_placeholder(text: str) -> str:
    """E1 임시 mask — `$1.5M` / `₩1,000,000` 등 monetary literal 만 redact.

    E3 (#579) 가 정식 stream gate (broker name + ticker+PnL 등 4 categories).
    """
    return _MONEY_RE.sub("[REDACTED]", text or "")


def _emit_event(label: str, event_type: str, payload: dict[str, Any]) -> Path:
    out_dir = _inbound_dir() / label
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = kst_now().strftime("%Y%m%dT%H%M%S%f")
    path = out_dir / f"{ts}_{event_type}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def emit_message(message: Any, *, targets: dict[int, str] | None = None) -> Path | None:
    """on_message 처리 본체 — file path 반환 (target 외 / bot author 시 None).

    sync 함수: async wrapper 와 unit test 양쪽 공용.
    """
    targets = targets if targets is not None else _channel_targets()
    label = targets.get(message.channel.id)
    if not label:
        return None
    if getattr(message.author, "bot", False):
        return None  # 봇 자기 outbound 메시지 echo 방지
    payload = {
        "type": "message",
        "channel_id": str(message.channel.id),
        "channel_label": label,
        "author_id": str(message.author.id),
        "author_name": getattr(message.author, "display_name", None) or str(message.author),
        "message_id": str(message.id),
        "content_masked": mask_placeholder(message.content or ""),
        "ts_kst": kst_now().isoformat(),
    }
    return _emit_event(label, "message", payload)


def emit_reaction(payload_obj: Any, kind: str, *, targets: dict[int, str] | None = None) -> Path | None:
    """on_raw_reaction_add / _remove 본체. RawReactionActionEvent 받음.

    raw 변형 사용 — message cache miss 무관, off-channel 만 거름.
    """
    targets = targets if targets is not None else _channel_targets()
    label = targets.get(payload_obj.channel_id)
    if not label:
        return None
    body = {
        "type": kind,
        "channel_id": str(payload_obj.channel_id),
        "channel_label": label,
        "user_id": str(payload_obj.user_id),
        "message_id": str(payload_obj.message_id),
        "emoji": str(payload_obj.emoji),
        "ts_kst": kst_now().isoformat(),
    }
    return _emit_event(label, kind, body)


def attach(bot: Any) -> bool:
    """discord.py Bot/Client 에 inbound listener 등록. env 미설정 시 no-op.

    on_message — message_content intent 필요 (privileged). bot.py 에서 활성화.
    on_raw_reaction_add/remove — default intents 로 충분.
    """
    targets = _channel_targets()
    if not targets:
        logger.warning(
            "DISCORD_CHANNEL_AGENT_CONTROL_ID / DISCORD_CHANNEL_AGENT_DEV_LOG_ID 미설정 — "
            "inbound listener no-op (#agent-control + #agent-dev-log 채널 ID 등록 필요)"
        )
        return False

    @bot.event
    async def on_message(message: Any) -> None:
        try:
            emit_message(message, targets=targets)
        except OSError:
            logger.exception("inbound message emit failed")

    @bot.event
    async def on_raw_reaction_add(payload_obj: Any) -> None:
        try:
            emit_reaction(payload_obj, "reaction_add", targets=targets)
        except OSError:
            logger.exception("inbound reaction_add emit failed")

    @bot.event
    async def on_raw_reaction_remove(payload_obj: Any) -> None:
        try:
            emit_reaction(payload_obj, "reaction_remove", targets=targets)
        except OSError:
            logger.exception("inbound reaction_remove emit failed")

    logger.info("inbound listener attached — channels=%s", list(targets.values()))
    return True
