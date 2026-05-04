"""CLI entry — `python -m nuri.trading.agents.consensus`.

Single-ticker mode also persists to recommendations + decisions for evidence
trail continuity (frontend /decision page).
"""

from __future__ import annotations

import argparse
import logging

from . import (
    analyze_portfolio,
    analyze_ticker,
    print_consensus,
    save_to_recommendations,
)

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant 멀티 에이전트 합의")
    parser.add_argument("--ticker", help="특정 종목만")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="합의 의견의 supporting verdicts reasoning 함께 출력"
    )
    args = parser.parse_args()

    if args.ticker:
        result = analyze_ticker(args.ticker)
        print_consensus([result], verbose=args.verbose)
        # 단일 종목도 DB 저장 (frontend evidence 연속성)
        saved = save_to_recommendations([result])
        if saved:
            logger.info(f"recommendations 테이블에 {saved}건 저장")
        # Decision Intelligence: 의사결정 저널 기록
        from nuri.trading.engine.decisions import record_decisions

        dec_count = record_decisions([result])
        logger.info(f"decisions 테이블에 {dec_count}건 기록")
    else:
        results = analyze_portfolio()
        print_consensus(results, verbose=args.verbose)
        saved = save_to_recommendations(results)
        if saved:  # pragma: no cover — info log when save succeeds
            logger.info(f"recommendations 테이블에 {saved}건 저장 (frontend /decision 활성화)")
        # Decision Intelligence: 의사결정 저널 기록
        from nuri.trading.engine.decisions import record_decisions

        dec_count = record_decisions(results)
        logger.info(f"decisions 테이블에 {dec_count}건 기록")


if __name__ == "__main__":  # pragma: no cover
    main()
