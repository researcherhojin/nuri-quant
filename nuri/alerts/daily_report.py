"""
일일 리포트 생성기 — 포트폴리오 분석 + 리스크 + 이벤트 종합.

Discord 전송 또는 stdout 출력.

사용법:
    python -m nuri.alerts.daily_report
"""
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

from nuri.alerts.formatters import format_daily_report
from nuri.analysis.portfolio import analyze_portfolio
from nuri.analysis.risk import analyze_risk
from nuri.core.db import query

load_dotenv()
logger = logging.getLogger(__name__)


def generate_report() -> dict:
    """일일 리포트 데이터 생성."""
    # 포트폴리오 분석
    portfolio_df = analyze_portfolio()
    portfolio_summary = {
        "total_value_usd": portfolio_df.attrs.get("total_value_usd", 0) if not portfolio_df.empty else 0,
        "warnings": portfolio_df.attrs.get("warnings", []) if not portfolio_df.empty else [],
    }

    # 리스크 분석
    risk_metrics = analyze_risk()

    # Fear & Greed
    fg_rows = query(
        "SELECT value FROM macro WHERE indicator = 'fear_greed' ORDER BY date DESC LIMIT 1"
    )
    fear_greed = fg_rows[0]["value"] if fg_rows else None

    # 내일 이벤트
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    events = query(
        "SELECT * FROM events WHERE date = ? ORDER BY importance DESC",
        (tomorrow,),
    )

    # Embed 생성
    embed = format_daily_report(portfolio_summary, risk_metrics, fear_greed, events)

    return embed


def send_discord(embed: dict) -> bool:
    """Discord로 리포트 전송. Webhook 방식 (간단)."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL 미설정 — stdout 출력으로 대체")
        return False

    import requests
    resp = requests.post(
        webhook_url,
        json={"embeds": [embed]},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Discord 리포트 전송 완료")
    return True


def print_report(embed: dict) -> None:
    """리포트를 stdout으로 출력."""
    print(f"\n{'=' * 60}")
    print(f"  {embed.get('title', 'Daily Report')}")
    print(f"{'=' * 60}")

    for field in embed.get("fields", []):
        print(f"  {field['name']}: {field['value']}")

    print(f"{'=' * 60}\n")


def main():
    logger.info("일일 리포트 생성 시작")
    embed = generate_report()

    # Discord 전송 시도, 실패 시 stdout
    if not send_discord(embed):
        print_report(embed)

    logger.info("일일 리포트 완료")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    main()
