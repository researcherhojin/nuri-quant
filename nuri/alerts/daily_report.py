"""
일일 리포트 생성기 — 포트폴리오 분석 + 리스크 + 이벤트 종합.

Discord 전송 또는 stdout 출력.

사용법:
    python -m nuri.alerts.daily_report
"""
import logging
import os
from datetime import timedelta

from dotenv import load_dotenv

from nuri.alerts.formatters import format_daily_report
from nuri.analysis.portfolio import analyze_portfolio
from nuri.analysis.risk import analyze_risk
from nuri.core.db import query
from nuri.core.timezone import kst_now

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
    tomorrow = (kst_now().replace(tzinfo=None) + timedelta(days=1)).strftime("%Y-%m-%d")
    events = query(
        "SELECT * FROM events WHERE date = ? ORDER BY importance DESC",
        (tomorrow,),
    )

    # 리밸런스 어드바이저 — 규칙 위반 + 매도 수량
    rebalance_info = None
    try:
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        rebalance_info = generate_advisor_report()
    except Exception as e:
        logger.debug("리밸런스 어드바이저 실패: %s", e)

    # Embed 생성
    embed = format_daily_report(portfolio_summary, risk_metrics, fear_greed, events)

    # 리밸런스 결과 필드 추가
    if rebalance_info and rebalance_info.get("has_critical"):
        actions = rebalance_info["actions"]
        critical = [a for a in actions if a["severity"] == "critical"][:5]
        if critical:
            lines = [
                f"{'🔴' if a['action'] == 'SELL_ALL' else '🟡'} {a['ticker']} {a['sell_shares']}주 "
                f"→ {a['reason']} (회수 ~${a['sell_value_usd']:,.0f})"
                for a in critical
            ]
            embed["fields"].append({
                "name": f"🚨 규칙 위반 {rebalance_info['total_violations']}건 (즉시 조치)",
                "value": "\n".join(lines),
                "inline": False,
            })
            embed["fields"].append({
                "name": "💵 총 회수 가능",
                "value": f"~${rebalance_info['total_recovery_usd']:,.0f}",
                "inline": True,
            })
            embed["color"] = 0xE74C3C  # 빨강

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


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: 일일 리포트 → Discord 전송, 실패 시 stdout."""
    del argv  # 인자 없음
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("일일 리포트 생성 시작")
    embed = generate_report()

    # Discord 전송 시도, 실패 시 stdout
    if not send_discord(embed):
        print_report(embed)

    logger.info("일일 리포트 완료")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
