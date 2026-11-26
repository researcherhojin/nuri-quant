"""
Telegram 봇 알림 — 레짐 전환, 규칙 위반, 매매 시그널 알림.

환경변수:
    TELEGRAM_BOT_TOKEN — Telegram Bot API 토큰
    TELEGRAM_CHAT_ID — 알림 수신 채팅 ID

사용법:
    from nuri.alerts.telegram import send_telegram
    send_telegram("레짐 전환: bull → sideways_high_vol")
"""

import html
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
    # 전송 시점에 환경변수 조회 (테스트에서 모듈 변수를 패치한 경우 폴백)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "") or _BOT_TOKEN
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "") or _CHAT_ID

    if not bot_token or not chat_id:
        logger.debug("TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 스킵")
        return False

    import requests

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
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
    safe_from = html.escape(str(from_regime))
    safe_to = html.escape(str(to_regime))
    return f"🔄 <b>레짐 전환</b>\n{safe_from} → <b>{safe_to}</b>\n신뢰도: {confidence:.0f}%"


def format_violation_alert(violations: list[dict]) -> str:
    """규칙 위반 Telegram 메시지."""
    lines = [f"🚨 <b>투자 규칙 위반 {len(violations)}건</b>"]
    for v in violations[:5]:
        emoji = "🔴" if v.get("severity") == "critical" else "🟡"
        safe_ticker = html.escape(str(v["ticker"]))
        safe_detail = html.escape(str(v.get("reason", v.get("violation_type", ""))))
        lines.append(f"{emoji} {safe_ticker}: {safe_detail}")
    if len(violations) > 5:
        lines.append(f"... 외 {len(violations) - 5}건")
    return "\n".join(lines)


def format_signal_alert(ticker: str, action: str, confidence: float, price: float) -> str:
    """매매 시그널 Telegram 메시지."""
    emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
    safe_ticker = html.escape(str(ticker))
    safe_action = html.escape(str(action))
    return f"{emoji} <b>{safe_ticker}</b> {safe_action}\n신뢰도: {confidence:.0f} | 가격: ${price:,.2f}"
