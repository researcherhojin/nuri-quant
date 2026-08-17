"""
Telegram 봇 알림 — 레짐 전환, 규칙 위반, 매매 시그널 알림.

환경변수:
    TELEGRAM_BOT_TOKEN — Telegram Bot API 토큰
    TELEGRAM_CHAT_ID — 알림 수신 채팅 ID

사용법:
    from nuri.alerts.telegram import send_telegram
    send_telegram("레짐 전환: bull → sideways_high_vol")
"""

import logging
import os

logger = logging.getLogger(__name__)

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Telegram 메시지 전송.

    Args:
        message: 전송할 메시지 (HTML 또는 Markdown)
        parse_mode: "HTML" 또는 "Markdown"

    Returns:
        성공 여부
    """
    if not _BOT_TOKEN or not _CHAT_ID:
        logger.debug("TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 스킵")
        return False

    import requests

    url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": _CHAT_ID,
                "text": message,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram 알림 전송 완료")
        return True
    except Exception as e:
        logger.warning("Telegram 전송 실패: %s", e)
        return False


def format_regime_alert(from_regime: str, to_regime: str, confidence: float) -> str:
    """레짐 전환 Telegram 메시지."""
    return f"🔄 <b>레짐 전환</b>\n{from_regime} → <b>{to_regime}</b>\n신뢰도: {confidence:.0f}%"


def format_violation_alert(violations: list[dict]) -> str:
    """규칙 위반 Telegram 메시지."""
    lines = [f"🚨 <b>투자 규칙 위반 {len(violations)}건</b>"]
    for v in violations[:5]:
        emoji = "🔴" if v.get("severity") == "critical" else "🟡"
        lines.append(f"{emoji} {v['ticker']}: {v.get('reason', v.get('violation_type', ''))}")
    if len(violations) > 5:
        lines.append(f"... 외 {len(violations) - 5}건")
    return "\n".join(lines)


def format_signal_alert(ticker: str, action: str, confidence: float, price: float) -> str:
    """매매 시그널 Telegram 메시지."""
    emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
    return f"{emoji} <b>{ticker}</b> {action}\n신뢰도: {confidence:.0f} | 가격: ${price:,.2f}"
