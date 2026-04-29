"""BUY candidate backtracking — Session N에서 emit한 후보의 baseline vs 현재 가격 비교.

Usage:
    .venv/bin/python scripts/compare_buy_candidates.py --session 8
    .venv/bin/python scripts/compare_buy_candidates.py --session 8 --as-of 2026-05-01

생성: ledger 갱신 (`baseline → t+1d/t+5d` 비교 row 추가) + 콘솔 출력 정렬 표.
근거: docs/STRATEGY.md §5.10 — Phase 1 emit 정확성 검증 데이터로 활용.
"""

import argparse
import json
from pathlib import Path

import yfinance as yf

LEDGER = Path("data/reports/buy_tracking/candidate_ledger.jsonl")


def load_session(session: int) -> list[dict]:
    if not LEDGER.exists():
        raise FileNotFoundError(f"{LEDGER} 없음 — Session 8 baseline 기록 먼저 필요")
    rows = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("session") == session:
            rows.append(rec)
    return rows


def fetch_current(ticker: str, as_of: str | None) -> tuple[float, str]:
    """as_of=None → 가장 최근. as_of=YYYY-MM-DD → 그날 close (없으면 직전)."""
    if as_of:
        h = yf.Ticker(ticker).history(start=as_of, period="5d", interval="1d")
    else:
        h = yf.Ticker(ticker).history(period="2d", interval="1d")
    if h.empty:
        return 0.0, ""
    return float(h["Close"].iloc[-1]), h.index[-1].strftime("%Y-%m-%d")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session", type=int, required=True, help="대상 session 번호 (e.g. 8)")
    p.add_argument("--as-of", type=str, default=None, help="비교 기준일 (YYYY-MM-DD), 미지정 시 최신")
    args = p.parse_args()

    rows = load_session(args.session)
    if not rows:
        print(f"Session {args.session} 후보 없음")
        return

    print(f"Session {args.session} ({len(rows)}종) — baseline vs current\n")
    header = f"{'Ticker':12s} {'Tier':10s} {'Score':>5s} {'Baseline':>14s} {'Current':>14s} {'1d%':>7s} {'vs TP1':>8s} {'vs Stop':>8s}  Verdict"
    print(header)
    print("-" * len(header))

    results = []
    for r in rows:
        cur, cur_date = fetch_current(r["ticker"], args.as_of)
        if not cur:
            print(
                f"  {r['ticker']:12s} {r['tier']:10s} {r['score']:>5} {r['baseline_close']:>14.4f} {'?':>14}  (no data)"
            )
            continue
        ret = (cur / r["baseline_close"] - 1) * 100
        vs_tp1 = (cur / r["tp1_plus_21pct"] - 1) * 100
        vs_stop = (cur / r["stop_minus_7pct"] - 1) * 100
        if cur >= r["tp1_plus_21pct"]:
            verdict = "✅ TP1 hit"
        elif cur <= r["stop_minus_7pct"]:
            verdict = "❌ STOP hit"
        elif ret > 0:
            verdict = f"📈 +{ret:.1f}%"
        else:
            verdict = f"📉 {ret:.1f}%"
        print(
            f"  {r['ticker']:12s} {r['tier']:10s} {r['score']:>5} "
            f"{r['baseline_close']:>14.4f} {cur:>14.4f} {ret:>+6.1f}% {vs_tp1:>+7.1f}% {vs_stop:>+7.1f}%  {verdict}"
        )
        results.append(
            {
                "ticker": r["ticker"],
                "session": r["session"],
                "current": cur,
                "current_date": cur_date,
                "ret_pct": ret,
                "verdict": verdict,
            }
        )

    # 통계 — Tier별
    print()
    by_tier: dict[str, list[float]] = {}
    for r, res in zip(rows, results):
        by_tier.setdefault(r["tier"], []).append(res["ret_pct"])
    print("Tier별 평균 return:")
    for tier, returns in sorted(by_tier.items()):
        avg = sum(returns) / len(returns)
        print(f"  {tier:10s} n={len(returns)} avg={avg:+.2f}%")


if __name__ == "__main__":
    main()
