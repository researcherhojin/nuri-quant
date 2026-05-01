"""full-scan 완료 후 Discord + Telegram 알림 전송.

Makefile의 full-scan 마지막에 호출되어
레짐, 위반 건수, 주요 종목 요약을 전송한다.

사용법:
    python scripts/notify_scan_result.py
"""
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_summary() -> str:
    """full-scan 결과 요약 메시지 생성."""
    lines = []

    # 레짐
    try:
        from nuri.quant.regime.classifier import classify_regime
        r = classify_regime()
        if r:
            lines.append(f"📊 레짐: {r.regime} ({r.confidence * 100:.0f}%)")
            lines.append(f"   VIX: {r.details.get('vix', 'N/A')} | F&G: {r.details.get('fear_greed', 'N/A')}")
    except Exception:
        lines.append("📊 레짐: 조회 실패")

    # 리밸런스 위반
    try:
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        report = generate_advisor_report()
        v = report["total_violations"]
        c = report["violations_by_severity"].get("critical", 0)
        lines.append(f"🚨 규칙 위반: {v}건 (critical {c}건)")
        if report["total_recovery_usd"] > 0:
            lines.append(f"💵 회수 가능: ${report['total_recovery_usd']:,.0f}")
        for a in report["actions"][:3]:
            lines.append(f"   • {a['ticker']}: {a['reason']}")
    except Exception:
        lines.append("🚨 리밸런스: 조회 실패")

    # 매크로
    try:
        from nuri.quant.regime.macro_score import compute_macro_score
        m = compute_macro_score()
        lines.append(f"🌍 매크로: {m.total_score:.0f}/100 ({m.interpretation})")
    except Exception:
        pass

    return "\n".join(lines)


def main():
    summary = _build_summary()
    title = "📋 Nuri-Quant Full Scan 완료"
    sent = False

    # Discord
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if webhook:
        try:
            import requests
            embed = {
                "title": title,
                "description": summary,
                "color": 0x3498DB,
            }
            requests.post(webhook, json={"embeds": [embed]}, timeout=10)
            logger.info("Discord 알림 전송 완료")
            sent = True
        except Exception as e:
            logger.warning("Discord 전송 실패: %s", e)

    # Telegram
    try:
        from nuri.alerts.telegram import send_telegram
        msg = f"<b>{title}</b>\n\n{summary}"
        if send_telegram(msg):
            sent = True
    except Exception as e:
        logger.debug("Telegram 전송 실패: %s", e)

    if not sent:
        print(f"\n{title}")
        print(summary)
        print("\n(DISCORD_WEBHOOK_URL 또는 TELEGRAM_BOT_TOKEN 설정 시 자동 발송)")


if __name__ == "__main__":
    main()
