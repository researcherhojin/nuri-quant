"""Consensus CLI presentation — pretty-print results to stdout.

Used by `python -m nuri.trading.agents.consensus`. Pulls in price targets +
external data summary at print time (lazy imports to avoid module-load cost).
"""

from __future__ import annotations

import logging

from .models import ConsensusResult

__all__ = ["print_consensus"]

logger = logging.getLogger(__name__)


def print_consensus(results: list[ConsensusResult], *, verbose: bool = False) -> None:
    """합의 결과 CLI 출력.

    Args:
        results: ConsensusResult 리스트
        verbose: True 시 종목별 supporting verdicts (합의 의견의 reasoning) 함께 출력
    """
    if not results:
        print("합의 결과 없음")
        return

    print(f"\n{'=' * 120}")
    print(f"  Multi-Agent Consensus ({len(results)} tickers, 10 agents)")
    print(f"{'=' * 120}")
    header_agents = ["Tech", "Fund", "Macro", "Risk", "Smart", "Wall", "KR", "Opt", "Crypto", "Ret"]
    print(f"  {'Ticker':<10} {'Action':<6} {'Conf':>5} {'Agree':>6} " + " ".join(f"{h:>5}" for h in header_agents))
    print(f"  {'-' * 110}")

    agent_order = [
        "technical",
        "fundamental",
        "macro",
        "risk",
        "smart_money",
        "wallstreet",
        "korean_market",
        "options",
        "crypto",
        "retail",
    ]

    for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
        agent_map = {v.agent_name: v for v in r.verdicts}
        cols = []
        for name in agent_order:
            v = agent_map.get(name)
            if v:
                icon = {"BUY": "B", "SELL": "S", "HOLD": "H"}.get(v.action, "?")
                cols.append(f"{icon}{v.confidence:.0f}")
            else:
                cols.append("--")

        print(
            f"  {r.ticker:<10} {r.final_action:<6} {r.final_confidence:>4.0f} {r.agreement_rate:>5.0%} "
            f"{' '.join(f'{c:>5}' for c in cols)}"
        )

    # 합의 supporters reasoning 출력 (verbose 모드 또는 단일 종목)
    show_supporters = verbose or len(results) == 1
    if show_supporters:
        for r in sorted(results, key=lambda x: x.final_confidence, reverse=True):
            supporters = [v for v in r.verdicts if v.action == r.final_action]
            if not supporters:
                continue
            print(
                f"\n  ▸ {r.ticker} {r.final_action} ({r.final_confidence:.0f}, agree={r.agreement_rate:.0%}) — supporters:"
            )
            for v in sorted(supporters, key=lambda x: x.confidence, reverse=True):
                print(f"      {v.agent_name}({v.confidence:.0f}): {v.reasoning}")

    # 반대 의견 요약
    dissents = [(r.ticker, r.dissent) for r in results if r.dissent]
    if dissents:
        print(f"\n  Dissent ({sum(len(d) for _, d in dissents)} opinions):")
        for ticker, ds in dissents[:5]:
            for d in ds:
                print(f"    {ticker}: {d}")

    # 가격 타겟 출력
    try:
        from nuri.trading.recommend.price_targets import calculate_targets, format_target_tree

        buy_hold = [r for r in results if r.final_action in ("BUY", "HOLD")]
        if buy_hold:
            print(f"\n{'=' * 85}")
            print("  Price Targets (BUY/HOLD 종목)")
            print(f"{'=' * 85}")
            for r in sorted(buy_hold, key=lambda x: x.final_confidence, reverse=True)[:10]:
                target = calculate_targets(r.ticker)
                if "error" not in target:
                    print(format_target_tree(target))
                    print(f"  {'─' * 50}")
    except Exception as e:
        logger.debug("가격 타겟 출력 실패: %s", e)

    # 외부 데이터 요약 출력
    try:
        from nuri.collectors.external import get_external

        tickers_with_data = set()
        for r in results:
            ext = get_external(r.ticker)
            if ext:
                tickers_with_data.add(r.ticker)
        if tickers_with_data:
            print(f"\n{'=' * 85}")
            print(f"  External Data ({len(tickers_with_data)} tickers)")
            print(f"{'=' * 85}")
            for r in results:
                if r.ticker not in tickers_with_data:
                    continue
                ext = get_external(r.ticker)
                parts = []
                for d in ext:
                    if d["data_type"] == "consensus":
                        parts.append(f"TipRanks:{d['value']}")
                    elif d["data_type"] == "superinvestor_count":
                        parts.append(f"슈퍼투자자:{d['value']}명")
                    elif d["data_type"] == "target_price" and d["source"] == "tipranks":
                        parts.append(f"목표가:${d['numeric_value']:,.0f}")
                if parts:
                    print(f"  {r.ticker:<10} {' | '.join(parts)}")
    except Exception as e:
        logger.debug("외부 데이터 출력 실패: %s", e)
    print()
