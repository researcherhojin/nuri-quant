"""수집 데이터 타당성 점검 → #ops.

SIEGE freshness 게이트는 **최신성만** 본다 — `certification._ticker_age_hours()` 가
`MAX(date)` 하나만 읽고, 값이 말이 되는지는 아무도 묻지 않는다. 그래서 상류가
무엇을 주든 "22시간 전 ✅" 로 통과한다. 실제로 `prices.KOSPI` 는 최근 39일 중
16일이 일간 5% 를 넘는데(중앙값 4.4%) 게이트는 그것에 대해 한 마디도 하지 않았다.
(2026-08-02 실측. 수집기는 결백하다 — 저장값은 yfinance `^KS11` 과 완전히 일치한다.)

**게이트가 아니라 표면화다.** 인증 조건으로 넣으면 `total_conditions` 와 점수를
건드린다. 관측은 관측하는 대상을 막지 않는다(#894).

검사는 둘뿐이고, 둘 다 "진짜 폭락"과 "깨진 피드"를 혼동하지 않는 것만 고른다:

1. **물리적으로 불가능한 OHLC** — close 가 [low, high] 밖, low > high, 음수 가격.
   시장이 아무리 험해도 이런 행은 나오지 않는다. 오탐이 원리적으로 없다.
2. **짝 프록시 대비 괴리** — 같은 시장을 다른 경로로 재는 시리즈와 같은 날 수익률이
   임계 이상 벌어지면 경고. 진짜 폭락이면 프록시도 같이 빠지므로 조용하다.

자체 이력 분포(z-score·백분위)는 **의도적으로 쓰지 않는다**. 진짜 폭락 때 피드가
맞는 바로 그 순간에 발화해서, 튜닝으로 죽이게 되고 결국 아무 말도 안 하는 검사가 된다.

⚠️ 프록시 데이터가 없으면 **검사 불가 사실 자체를 알린다.** 조용히 통과하는 검사는
이 레포가 반복해서 당한 실패다(dead gate). 현재 `KOSPI` 의 짝 `069500.KS` 는
prices 에 0행이라 괴리 검사가 돌지 못하고, 그게 지금 가장 먼저 나갈 메시지다.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date as dt_date
from pathlib import Path
from typing import Any, Optional

from nuri.core.db import query

logger = logging.getLogger(__name__)


def _config() -> dict[str, Any]:
    from nuri.core.alerts_config import _load_config

    return (_load_config() or {}).get("data_sanity") or {}


def scoped_tickers() -> list[str]:
    """검사 대상 — 틀리면 인증·측정을 오도하는 시리즈만.

    전체 `prices` 는 수천 시리즈지만, 그중 판단을 좌우하는 건 SIEGE freshness
    primary/secondary 와 §3.11 측정 벤치마크뿐이다. 레포가 이미 그 티커들을
    나머지보다 높이 취급한다(`stock.py --source freshness` 가 같은 집합을 뽑는다).
    """
    from nuri.core.rules import RULES

    out: set[str] = set()
    for policy in ((RULES.get("siege_gates") or {}).get("asset_classes") or {}).values():
        if policy.get("freshness_primary"):
            out.add(str(policy["freshness_primary"]))
        for sec in policy.get("freshness_secondary") or []:
            out.add(str(sec))
    mm = RULES.get("measurement_mode") or {}
    if mm.get("benchmark"):  # 판정 기준 (문자열, 사전등록 잠금)
        out.add(str(mm["benchmark"]))
    for v in (mm.get("benchmark_by_market") or {}).values():  # 시장별 (map)
        if v:
            out.add(str(v))
    return sorted(out)


def check_impossible_ohlc(ticker: str, bars: int, db_path: Optional[Path] = None) -> list[str]:
    """물리적으로 불가능한 행 — 시장 상황과 무관하게 데이터가 깨진 경우.

    오탐이 원리적으로 없다: 어떤 폭락도 `low > high` 를 만들지 않는다.
    """
    rows = query(
        "SELECT date, open, high, low, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
        (ticker, bars),
        db_path=db_path,
    )
    bad: list[str] = []
    for r in rows:
        o, h, low, c = r["open"], r["high"], r["low"], r["close"]
        if any(v is not None and v <= 0 for v in (o, h, low, c)):
            bad.append(f"{r['date']} 0 이하 가격")
        elif h is not None and low is not None and h < low:
            bad.append(f"{r['date']} high < low")
        elif c is not None and h is not None and low is not None and not (low <= c <= h):
            bad.append(f"{r['date']} close 가 [low, high] 밖")
    return bad


def check_proxy_divergence(
    ticker: str,
    proxy: str,
    cfg: dict[str, Any],
    db_path: Optional[Path] = None,
) -> Optional[str]:
    """짝 프록시와 같은 날 수익률 괴리. 프록시 데이터가 없으면 그 사실을 반환.

    진짜 시장 급변이면 프록시도 같이 움직이므로 조용하다 — 이게 자체 이력 분포
    대신 이걸 고른 이유다.
    """

    def _closes(t: str) -> dict[str, float]:
        rows = query(
            "SELECT date, close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
            (t, int(cfg.get("lookback_bars", 20)) + 3),
            db_path=db_path,
        )
        return {str(r["date"]): float(r["close"]) for r in rows if r["close"]}

    base, ref = _closes(ticker), _closes(proxy)
    if not ref:
        return f"프록시 {proxy} 데이터 없음 — 괴리 검사 불가 (수집 대상에 없음)"
    common = sorted(set(base) & set(ref), reverse=True)
    if len(common) < 2:
        return f"프록시 {proxy} 와 겹치는 날짜 부족 — 괴리 검사 불가"

    # 프록시가 뒤처져 있으면 최근 봉은 아무도 안 본 것이다. 오래된 겹침만 비교하고
    # "이상 없음" 이라 말하면 그게 정확히 이 레포가 반복해서 당한 조용한 통과다
    # (dev 복제본에 2개월 묵은 069500.KS 34행이 있어 실제로 그렇게 통과했다).
    lag = (dt_date.fromisoformat(max(base)) - dt_date.fromisoformat(common[0])).days
    max_lag = int(cfg.get("proxy_max_lag_days", 5))
    if lag > max_lag:
        return f"프록시 {proxy} 가 {lag}일 뒤처짐 (최근 겹침 {common[0]}, 기준 {max(base)}) — 최근 봉 괴리 검사 불가"

    def _gap(newer: str, older: str) -> tuple[float, float, float]:
        r_base = (base[newer] - base[older]) / base[older] * 100
        r_ref = (ref[newer] - ref[older]) / ref[older] * 100
        return r_base, r_ref, abs(r_base - r_ref)

    lim_1d = float(cfg.get("divergence_1d_pp", 8.0))
    for i in range(len(common) - 1):
        d, prev = common[i], common[i + 1]
        r_base, r_ref, gap = _gap(d, prev)
        if gap >= lim_1d:
            return f"{d} 1일 수익률 {r_base:+.1f}% vs 프록시 {proxy} {r_ref:+.1f}% (괴리 {gap:.1f}%p ≥ {lim_1d:.0f}%p)"

    # 3일 누적 — 매일 조금씩 틀린 피드는 1일 임계를 절대 안 넘고 통과한다.
    lim_3d = float(cfg.get("divergence_3d_pp", 12.0))
    if len(common) > 3:
        r_base, r_ref, gap = _gap(common[0], common[3])
        if gap >= lim_3d:
            return (
                f"{common[3]}~{common[0]} 3일 누적 {r_base:+.1f}% vs 프록시 {proxy} {r_ref:+.1f}%"
                f" (괴리 {gap:.1f}%p ≥ {lim_3d:.0f}%p)"
            )
    return None


def scan(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """대상 시리즈 전수 점검 → 발견 목록."""
    cfg = _config()
    if not cfg.get("enabled", True):
        return []
    bars = int(cfg.get("lookback_bars", 20))
    proxies = cfg.get("proxies") or {}

    findings: list[dict[str, Any]] = []
    for ticker in scoped_tickers():
        for msg in check_impossible_ohlc(ticker, bars, db_path=db_path):
            findings.append({"ticker": ticker, "kind": "impossible_ohlc", "detail": msg})
        proxy = proxies.get(ticker)
        if proxy:
            msg = check_proxy_divergence(ticker, str(proxy), cfg, db_path=db_path)
            if msg:
                kind = "proxy_unavailable" if "불가" in msg else "proxy_divergence"
                findings.append({"ticker": ticker, "kind": kind, "detail": msg})
    return findings


def _recently_alerted(dedupe_key: str, days: int, db_path: Optional[Path] = None) -> bool:
    """같은 발견이 최근 N일 안에 이미 나갔나.

    outbox 의 `dedupe_key` 는 **pending 행만** 막는다 — 발송되고 나면 다음 실행에서
    그대로 다시 올라온다. 상시 조건(프록시 미수집 같은)은 그래서 매일 같은 카드를
    반복하게 되고, 그러면 사용자는 #ops 전체를 안 보게 된다.
    """
    rows = query(
        "SELECT 1 FROM discord_outbox WHERE channel = 'ops' AND dedupe_key = ?"
        " AND created_at >= datetime('now', ?) LIMIT 1",
        (dedupe_key, f"-{days} days"),
        db_path=db_path,
    )
    return bool(rows)


def stage_findings(db_path: Optional[Path] = None) -> int:
    """발견을 #ops 로 stage. staged 건수 반환.

    문구는 아는 것만 말하고 멈춘다 — 큰 괴리가 진짜 시장 사건인지 깨진 피드인지
    이 검사는 알 수 없고, 아는 척하면 안 된다.
    """
    from nuri.agents.discord.outbox import stage_ops

    cfg = _config()
    staged = 0
    for f in scan(db_path=db_path):
        dedupe_key = f"data-sanity:{f['ticker']}:{f['kind']}"
        window = int(
            cfg.get("repeat_days_unavailable", 7)
            if f["kind"] == "proxy_unavailable"
            else cfg.get("repeat_days_finding", 1)
        )
        if _recently_alerted(dedupe_key, window, db_path=db_path):
            logger.debug("data sanity skip %s — %d일 내 이미 알림", dedupe_key, window)
            continue

        if f["kind"] == "impossible_ohlc":
            summary = f"⚠️ {f['ticker']} 데이터 오류 — {f['detail']} (시장 상황과 무관한 깨진 행)"
        elif f["kind"] == "proxy_unavailable":
            summary = f"ℹ️ {f['ticker']} 타당성 검사 미실행 — {f['detail']}"
        else:
            summary = (
                f"⚠️ {f['ticker']} 타당성 경고 — {f['detail']}."
                " 실제 시장 급변일 수도, 상류 데이터 오류일 수도 있다. freshness 는 여전히 PASS."
            )
        outbox_id = stage_ops(
            payload={"kind": "data_sanity", "summary": summary, "ticker": f["ticker"], "check": f["kind"]},
            dedupe_key=dedupe_key,
            actor_name="data-sanity",
            db_path=db_path,
        )
        if outbox_id is not None:
            staged += 1
    if staged:
        logger.info("data sanity findings staged: %d", staged)
    return staged


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="수집 데이터 타당성 점검 → #ops")
    parser.add_argument("--dry-run", action="store_true", help="stage 없이 목록만 출력")
    args = parser.parse_args(argv)

    findings = scan()
    print(f"검사 대상: {', '.join(scoped_tickers())}")
    if not findings:
        print("이상 없음")
        return 0
    for f in findings:
        print(f"  [{f['kind']}] {f['ticker']}: {f['detail']}")
    if args.dry_run:
        print(f"[dry-run] {len(findings)}건 — stage 안 함")
        return 0
    print(f"staged {stage_findings()}건 → #ops")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
