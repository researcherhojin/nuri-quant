"""
뉴스 센티먼트 분석 — 키워드 사전 기반 감성 점수.

기존 news 테이블의 title에서 긍정/부정 키워드를 매칭하여
sentiment 컬럼을 업데이트한다. (-1.0 ~ +1.0)

사용법:
    python -m nuri.analysis.sentiment
"""
import logging
import re

from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)

# 긍정 키워드 (영어)
POSITIVE = {
    "surge", "surges", "surging", "soar", "soars", "soaring",
    "rally", "rallies", "rallying", "jump", "jumps", "jumping",
    "beat", "beats", "beating", "exceed", "exceeds", "exceeded",
    "upgrade", "upgrades", "upgraded", "bullish",
    "record", "high", "growth", "grow", "grows", "growing",
    "gain", "gains", "gaining", "profit", "profitable",
    "strong", "stronger", "strength", "boom", "booming",
    "outperform", "outperforms", "buy", "positive",
    "optimistic", "optimism", "recovery", "recover",
    "breakout", "breakthrough", "innovation", "innovative",
    "best", "top", "upside", "up", "rise", "rises", "rising",
}

# 부정 키워드 (영어)
NEGATIVE = {
    "crash", "crashes", "crashing", "plunge", "plunges", "plunging",
    "drop", "drops", "dropping", "fall", "falls", "falling",
    "miss", "misses", "missed", "decline", "declines", "declining",
    "downgrade", "downgrades", "downgraded", "bearish",
    "loss", "losses", "losing", "lose", "deficit",
    "weak", "weaker", "weakness", "slump", "slumps", "slumping",
    "underperform", "underperforms", "sell", "negative",
    "pessimistic", "pessimism", "recession", "recessionary",
    "bankruptcy", "bankrupt", "default", "defaults",
    "worst", "bottom", "downside", "down", "risk", "risky",
    "cut", "cuts", "cutting", "layoff", "layoffs",
    "warning", "warns", "warned", "concern", "concerns",
    "fear", "fears", "investigation", "lawsuit", "fraud",
}


def compute_sentiment(title: str) -> float:
    """뉴스 제목에서 감성 점수 계산. -1.0 ~ +1.0"""
    if not title:
        return 0.0

    words = set(re.findall(r'[a-zA-Z]+', title.lower()))
    pos = len(words & POSITIVE)
    neg = len(words & NEGATIVE)
    total = pos + neg

    if total == 0:
        return 0.0

    return round((pos - neg) / total, 3)


def analyze_sentiment() -> dict:
    """전체 뉴스의 센티먼트 업데이트 + 통계 반환."""
    # sentiment가 NULL인 뉴스 가져오기
    news = query("SELECT id, title FROM news WHERE sentiment IS NULL")

    if not news:
        logger.info("새로 분석할 뉴스 없음")
        # 기존 통계 반환
        return _get_stats()

    logger.info(f"센티먼트 분석 대상: {len(news)}건")

    updates = []
    for row in news:
        score = compute_sentiment(row["title"])
        updates.append({"id": row["id"], "sentiment": score})

    # 일괄 업데이트
    with get_db() as conn:
        conn.executemany(
            "UPDATE news SET sentiment = :sentiment WHERE id = :id",
            updates,
        )

    logger.info(f"센티먼트 업데이트 완료: {len(updates)}건")
    return _get_stats()


def _get_stats() -> dict:
    """센티먼트 통계."""
    rows = query("""
        SELECT
            COUNT(*) as total,
            AVG(sentiment) as avg_sentiment,
            SUM(CASE WHEN sentiment > 0.1 THEN 1 ELSE 0 END) as positive,
            SUM(CASE WHEN sentiment < -0.1 THEN 1 ELSE 0 END) as negative,
            SUM(CASE WHEN sentiment BETWEEN -0.1 AND 0.1 THEN 1 ELSE 0 END) as neutral
        FROM news WHERE sentiment IS NOT NULL
    """)
    if rows:
        return rows[0]
    return {}


def print_sentiment(stats: dict) -> None:
    """센티먼트 통계 출력."""
    if not stats or stats.get("total", 0) == 0:
        print("센티먼트 데이터가 없습니다.")
        return

    total = stats["total"]
    avg = stats.get("avg_sentiment", 0) or 0
    pos = stats.get("positive", 0)
    neg = stats.get("negative", 0)
    neu = stats.get("neutral", 0)

    label = "긍정" if avg > 0.05 else ("부정" if avg < -0.05 else "중립")

    print(f"\n{'=' * 50}")
    print("  뉴스 센티먼트 분석 (키워드 기반)")
    print(f"{'=' * 50}")
    print(f"  전체 뉴스:  {total}건")
    print(f"  평균 점수:  {avg:+.3f} ({label})")
    print(f"  긍정:       {pos}건 ({pos/total*100:.1f}%)")
    print(f"  부정:       {neg}건 ({neg/total*100:.1f}%)")
    print(f"  중립:       {neu}건 ({neu/total*100:.1f}%)")

    # 종목별 센티먼트
    by_ticker = query("""
        SELECT ticker, AVG(sentiment) as avg_s, COUNT(*) as cnt
        FROM news
        WHERE sentiment IS NOT NULL
        GROUP BY ticker
        ORDER BY avg_s DESC
    """)
    if by_ticker:
        print(f"\n  {'Ticker':<12} {'센티먼트':>10} {'뉴스 수':>8}")
        print(f"  {'-' * 32}")
        for r in by_ticker:
            avg_s = r["avg_s"] or 0
            print(f"  {r['ticker']:<12} {avg_s:>+10.3f} {r['cnt']:>8}")

    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: 종목별 감성 분석 통계 출력."""
    del argv  # 인자 없음
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = analyze_sentiment()
    print_sentiment(stats)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
