"""
Discord 메시지 포맷터 — 분석 결과를 Discord Embed 형식으로 변환.

색상: 초록(양수), 빨강(음수), 노랑(경고)
"""
from datetime import datetime
from typing import Optional

# Discord Embed 색상
COLOR_GREEN = 0x2ECC71
COLOR_RED = 0xE74C3C
COLOR_YELLOW = 0xF39C12
COLOR_BLUE = 0x3498DB


def format_daily_report(
    portfolio_summary: dict,
    risk_metrics: dict,
    fear_greed: Optional[float] = None,
    events: list[dict] | None = None,
) -> dict:
    """일일 리포트 Discord Embed."""
    total = portfolio_summary.get("total_value_usd", 0)
    warnings = portfolio_summary.get("warnings", [])

    fields = [
        {
            "name": "💰 총 평가액",
            "value": f"${total:,.0f}",
            "inline": True,
        },
    ]

    if risk_metrics:
        fields.extend([
            {
                "name": "📊 Sharpe Ratio",
                "value": f"{risk_metrics.get('sharpe_ratio', 0):.2f}",
                "inline": True,
            },
            {
                "name": "📉 Max Drawdown",
                "value": f"{risk_metrics.get('max_drawdown_pct', 0):+.1f}%",
                "inline": True,
            },
            {
                "name": "⚡ VaR 95%",
                "value": f"{risk_metrics.get('var_95_daily_pct', 0):+.2f}%",
                "inline": True,
            },
        ])

    if fear_greed is not None:
        fg_label = _fear_greed_label(fear_greed)
        fields.append({
            "name": "😱 Fear & Greed",
            "value": f"{fear_greed:.0f} ({fg_label})",
            "inline": True,
        })

    # 경고
    if warnings:
        fields.append({
            "name": "⚠️ 투자규칙 경고",
            "value": "\n".join(warnings[:5]),
            "inline": False,
        })

    # 손절선 경고
    stop_alerts = risk_metrics.get("stop_loss_alerts", [])
    if stop_alerts:
        alert_text = "\n".join(f"{a['ticker']}: {a['pnl_pct']:+.1f}%" for a in stop_alerts[:5])
        fields.append({
            "name": "🚨 손절선 도달",
            "value": alert_text,
            "inline": False,
        })

    # 이벤트
    if events:
        event_text = "\n".join(f"{e['date']} {e['description']}" for e in events[:5])
        fields.append({
            "name": "📅 예정 이벤트",
            "value": event_text,
            "inline": False,
        })

    color = COLOR_RED if warnings or stop_alerts else COLOR_GREEN

    return {
        "title": f"📋 Nuri-Quant Daily Report — {datetime.now().strftime('%Y-%m-%d')}",
        "color": color,
        "fields": fields,
        "footer": {"text": "Nuri-Quant"},
    }


def format_price_alert(ticker: str, change_pct: float, price: float) -> dict:
    """급등락 알림 Embed."""
    direction = "급등" if change_pct > 0 else "급락"
    color = COLOR_GREEN if change_pct > 0 else COLOR_RED
    emoji = "🚀" if change_pct > 0 else "💥"

    return {
        "title": f"{emoji} {ticker} {direction} 알림",
        "color": color,
        "fields": [
            {"name": "변동률", "value": f"{change_pct:+.2f}%", "inline": True},
            {"name": "현재가", "value": f"${price:,.2f}", "inline": True},
        ],
        "footer": {"text": "Nuri-Quant 급등락 알림"},
    }


def format_ark_alert(trades: list[dict]) -> dict:
    """ARK 매매 알림 Embed."""
    lines = []
    for t in trades[:10]:
        emoji = "🟢" if t["direction"].upper() == "BUY" else "🔴"
        lines.append(f"{emoji} {t['ticker']} {t['direction']} {t['shares']:,.0f}주 ({t['fund']})")

    return {
        "title": "🏛️ ARK Invest 매매 알림",
        "color": COLOR_BLUE,
        "description": "\n".join(lines) if lines else "매매 내역 없음",
        "footer": {"text": "Nuri-Quant ARK 추적"},
    }


def format_event_reminder(event: dict) -> dict:
    """이벤트 D-1 알림 Embed."""
    return {
        "title": f"📅 내일 이벤트: {event.get('description', '')}",
        "color": COLOR_YELLOW,
        "fields": [
            {"name": "날짜", "value": event.get("date", ""), "inline": True},
            {"name": "유형", "value": event.get("event_type", ""), "inline": True},
            {"name": "종목", "value": event.get("ticker", "전체"), "inline": True},
        ],
        "footer": {"text": "Nuri-Quant 이벤트 알림"},
    }


def _fear_greed_label(score: float) -> str:
    """Fear & Greed 점수 → 레이블."""
    if score <= 20:
        return "극단적 공포"
    elif score <= 40:
        return "공포"
    elif score <= 60:
        return "중립"
    elif score <= 80:
        return "탐욕"
    else:
        return "극단적 탐욕"
