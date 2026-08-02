"""Mechanical profit-protection signals → #brief (Tier 1e: 트레일링 give-back).

브리프는 지금까지 **손실 쪽만** 밀어줬다 — 손절 이탈(Tier 1a)·집중도/섹터/슬리브
(1b/1c/1d). 이익을 지켜야 할 때는 한 번도 알리지 않았다. 트레일링 스톱은
`price_targets.check_trailing_stop_signals()` 가 이미 계산하고 있었지만 유일한
소비자가 `api/routes/targets.py` 라 **대시보드를 직접 열어야만** 보였다. 스케줄러
job 도, 디스코드 경로도 없었다(2026-08-02 감사). 여기서 그 배달만 만든다.

Escalation Ladder: **Surface 등급**이다. 새 룰도, 임계 변경도 없다 — 이미 계산되는
결정론 신호를 사용자에게 도달시키기만 한다. 집행은 사용자다(§7.1).

⚠️ **되돌릴 이익이 있었을 때만 트레일링이다.** `check_trailing_stop_signals()` 는
HWM 을 `max(고점, 진입가)` 로 바닥 처리하므로, 진입가 위로 간 적 없는 종목도
HWM=진입가가 되어 -15% 손실이 그대로 "트레일링 도달"로 잡힌다. 그걸 그대로
알리면 (a) 이익 보호가 아닌 것을 이익 보호라 부르고 (b) 이미 손절 알림이 나간
종목에 중복으로 얹힌다. 그래서 최고점이 진입가 대비 최소
`config/rules.yaml brief.trailing_min_peak_gain_pct` 만큼 올라갔던 포지션만 남기고,
같은 날 손절 이탈로 이미 표면화된 (ticker, account) 는 제외한다.

Privacy: Discord 는 사용자 private 채널이라 ticker+PnL 노출 OK (risk_signals 선례).
테스트는 합성 티커만.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from nuri.core.rules import BRIEF_TRAILING_MIN_PEAK_GAIN_PCT, get_account_strategy_name
from nuri.core.ticker_names import get_ticker_name, is_kr_ticker
from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)

Session = Literal["kr", "us"]


def scan_trailing_giveback(
    session: Optional[Session] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """트레일링 임계에 닿은 보유 중 **실제로 이익을 반납한 것**만.

    계산은 재구현하지 않고 canonical `check_trailing_stop_signals()` 를 그대로 쓴다.
    여기서 하는 건 세 가지 필터뿐:

    1. session (KR `.KS`/`.KQ` vs 그 외) — `is_kr_ticker()` 경유 (#764)
    2. pension 계좌 제외 — daily action 대상이 아니다 (risk_signals 와 동일 정책)
    3. **최고점이 진입가 대비 최소 임계만큼 올라갔던 포지션만** — 그래야 "반납"이다

    반환 dict 는 원본 + `peak_gain_pct` / `given_back_pct`(고점이익 중 반납 비율).
    """
    from nuri.trading.recommend.price_targets import check_trailing_stop_signals

    out: list[dict[str, Any]] = []
    for sig in check_trailing_stop_signals(db_path=db_path):
        ticker = str(sig["ticker"])
        if session == "kr" and not is_kr_ticker(ticker):
            continue
        if session == "us" and is_kr_ticker(ticker):
            continue
        if get_account_strategy_name(sig.get("account")) == "pension":
            continue

        entry, hwm = sig.get("entry_price"), sig.get("high_water_mark")
        if not entry or not hwm:
            continue
        peak_gain = (hwm - entry) / entry * 100
        if peak_gain < BRIEF_TRAILING_MIN_PEAK_GAIN_PCT:
            # 오른 적 없는 포지션 — 이건 반납이 아니라 그냥 손실이고, 손절 알림 소관.
            continue

        current = sig.get("current_price") or 0
        out.append(
            {
                **sig,
                "peak_gain_pct": peak_gain,
                # 고점 이익 중 얼마를 되돌렸나 — "+30% 갔다가 +10% 남았다" 를 한 수로.
                "given_back_pct": (hwm - current) / (hwm - entry) * 100 if hwm > entry else None,
            }
        )

    out.sort(key=lambda s: s.get("given_back_pct") or 0, reverse=True)  # 많이 반납한 순
    return out


def scan_take_profit(
    session: Optional[Session] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """익절 목표(TP1/TP2)에 닿은 보유 — 트레일링과 같은 배달 공백이었다.

    계산은 canonical `check_take_profit_signals()` 를 그대로 쓴다(리더는 그쪽에서
    이미 제외 — 고정 익절 폐기, 추세 트레일로 관리). 여기서는 session 과 pension
    만 거른다.
    """
    from nuri.trading.recommend.price_targets import check_take_profit_signals

    out: list[dict[str, Any]] = []
    for sig in check_take_profit_signals(db_path=db_path):
        ticker = str(sig["ticker"])
        if session == "kr" and not is_kr_ticker(ticker):
            continue
        if session == "us" and is_kr_ticker(ticker):
            continue
        if get_account_strategy_name(sig.get("account")) == "pension":
            continue
        out.append(sig)
    out.sort(key=lambda s: s["return_pct"], reverse=True)  # 많이 오른 순
    return out


def _build_tp_payload(sig: dict[str, Any], date: str) -> dict[str, Any]:
    """익절 도달 1건 → #brief payload.

    손절(🔴)·트레일링(🟡)과 시각적으로 가른다(🟢) — 셋 다 오늘 볼 것이지만
    이건 유일하게 **좋은 소식**이고, 요구하는 행동도 다르다(부분 매도).
    카드는 룰이 뭐라 하는지 말할 뿐 매도를 지시하지 않는다(§7.1).
    """
    from nuri.agents.discord.outbox import format_money

    ticker = str(sig["ticker"])
    name = get_ticker_name(ticker)
    label = f"{ticker} {name}" if name else ticker
    tier = "1차" if sig["level"] == "target_1" else "2차"

    head = f"🟢 {label} · {tier} 익절 도달 · {sig.get('account', '')}".rstrip(" ·")
    now_line = (
        f"　현재 {format_money(sig['current_price'], ticker)}"
        f" / 진입 {format_money(sig['entry_price'], ticker)} ({sig['return_pct']:+.1f}%)"
        f" · 목표 {format_money(sig['target_price'], ticker)}"
    )
    rule = f"　룰 {sig['stock_type']} {tier} 익절 → {sig['sell_pct']:.0f}% 매도 구간"

    return {
        "kind": "SELL",
        "ticker": ticker,
        "summary": "\n".join([head, now_line, rule]),
        "note": sig.get("account"),
        "reason": f"{tier} 익절 도달 ({sig['return_pct']:+.1f}%)",
        "date": date,
        "current": sig["current_price"],
        "return_pct": sig["return_pct"],
        "level": sig["level"],
    }


def stage_take_profit_briefs(
    session: Optional[Session] = None,
    date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """익절 도달을 #brief outbox 에 stage. staged 건수 반환.

    트레일링으로 이미 표면화된 (ticker, account) 는 건너뛴다 — 고점에서 되돌리는
    중인 포지션에 "익절 도달" 카드를 함께 보내면 서로 다른 방향을 가리킨다.
    되돌림이 더 급한 신호이므로 그쪽을 남긴다.
    """
    from nuri.agents.discord.outbox import stage_brief

    d = date or today_kst()
    trailing = {(s["ticker"], s.get("account")) for s in scan_trailing_giveback(session, db_path=db_path)}

    staged = 0
    for sig in scan_take_profit(session, db_path=db_path):
        if (sig["ticker"], sig.get("account")) in trailing:
            logger.debug("take-profit skip %s — 트레일링으로 이미 표면화", sig["ticker"])
            continue
        outbox_id = stage_brief(
            payload=_build_tp_payload(sig, d),
            dedupe_key=f"take-profit:{sig['ticker']}:{sig.get('account', '')}:{sig['level']}:{d}",
            priority="normal",
            actor_name="profit-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("take-profit briefs staged: %d (session=%s)", staged, session or "all")
    return staged


def _build_giveback_payload(sig: dict[str, Any], date: str) -> dict[str, Any]:
    """트레일링 도달 1건 → #brief SELL payload.

    손절 카드(🔴)와 시각적으로 가른다(🟡) — 둘 다 오늘 볼 것이지만 성격이 다르다.
    손절은 손실 확대 차단, 이쪽은 **남은 이익 보호**다. 카드는 룰이 이 상태를 뭐라
    부르는지 말할 뿐 매도를 지시하지 않는다(§7.1, footer 가 이미 manual execute only).
    """
    from nuri.agents.discord.outbox import format_money

    ticker = str(sig["ticker"])
    name = get_ticker_name(ticker)
    label = f"{ticker} {name}" if name else ticker

    head = f"🟡 {label} · 트레일링 도달 · {sig.get('account', '')}".rstrip(" ·")

    # 진입가 대비는 **직접** 계산한다. `peak_gain - |drop|` 로 합치면 틀린다 —
    # 퍼센트 변화는 기준이 달라 뺄셈으로 합성되지 않는다(+21.6% 뒤 -29.9% 는
    # -8.3% 가 아니라 -14.8%). 실데이터 렌더에서 잡힌 오류다.
    entry, current, hwm = sig["entry_price"], sig["current_price"], sig["high_water_mark"]
    from_entry = (current - entry) / entry * 100
    now_line = (
        f"　현재 {format_money(current, ticker)}"
        f" / 고점 {format_money(hwm, ticker)} ({sig['drop_pct']:+.1f}%)"
        f" · 진입 {format_money(entry, ticker)} 대비 {from_entry:+.1f}%"
    )

    bits = [f"룰 {sig['stock_type']} 트레일링 {sig['threshold']}% · 청산가 {format_money(sig['stop_price'], ticker)}"]
    # "고점이익의 168% 반납" 은 무의미하다. 진입가 아래로 내려갔으면 이익은 전부
    # 반납된 것이고, 그 사실을 그렇게 말하는 게 맞다.
    if current < entry:
        bits.append(f"고점 +{sig['peak_gain_pct']:.0f}% 이익 전량 반납 (진입가 아래)")
    elif sig.get("given_back_pct") is not None:
        bits.append(f"고점 +{sig['peak_gain_pct']:.0f}% 중 {min(sig['given_back_pct'], 100):.0f}% 반납")
    rule = "　" + " · ".join(bits)

    return {
        "kind": "SELL",
        "ticker": ticker,
        "summary": "\n".join([head, now_line, rule]),
        "note": sig.get("account"),
        "reason": f"트레일링 도달 (고점 대비 {sig['drop_pct']:+.1f}% ≤ {sig['threshold']}%)",
        "date": date,
        "current": sig["current_price"],
        "high_water_mark": sig["high_water_mark"],
        "peak_gain_pct": sig["peak_gain_pct"],
    }


def stage_trailing_briefs(
    session: Optional[Session] = None,
    date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """트레일링 도달을 #brief outbox 에 stage. staged 건수 반환.

    같은 (ticker, account) 가 **오늘 손절 이탈로 이미 표면화**됐으면 건너뛴다 —
    한 포지션에 두 장의 카드가 가면 사용자는 둘 중 무엇이 진짜인지 판단해야 한다.
    손절이 더 급한 신호이므로 그쪽을 남긴다.
    """
    from nuri.agents.discord.outbox import stage_brief
    from nuri.alerts.risk_signals import scan_stop_breaches

    d = date or today_kst()
    breached = {(b["ticker"], b["account"]) for b in scan_stop_breaches(session, db_path=db_path)}

    staged = 0
    for sig in scan_trailing_giveback(session, db_path=db_path):
        key = (sig["ticker"], sig.get("account"))
        if key in breached:
            logger.debug("trailing skip %s — 손절 이탈로 이미 표면화", sig["ticker"])
            continue
        outbox_id = stage_brief(
            payload=_build_giveback_payload(sig, d),
            dedupe_key=f"trailing:{sig['ticker']}:{sig.get('account', '')}:{d}",
            priority="high",
            actor_name="profit-signals",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("trailing give-back briefs staged: %d (session=%s)", staged, session or "all")
    return staged


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="트레일링 give-back → #brief (Tier 1e)")
    parser.add_argument("--session", choices=("kr", "us"), default=None, help="세션 필터 (기본: 전체)")
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 목록만 출력")
    args = parser.parse_args(argv)

    sigs = scan_trailing_giveback(args.session)
    if not sigs:
        print("트레일링 give-back 없음 (되돌릴 이익이 있었던 포지션 기준)")
        return 0
    for s in sigs:
        print(
            f"  {s['ticker']} [{s.get('account')}] 고점 대비 {s['drop_pct']:+.1f}% "
            f"(최고 +{s['peak_gain_pct']:.1f}% → 반납 {s.get('given_back_pct') or 0:.0f}%)"
        )
    if args.dry_run:
        print(f"[dry-run] {len(sigs)}건 — stage 안 함")
        return 0
    print(f"staged {stage_trailing_briefs(args.session)}건 → #brief")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
