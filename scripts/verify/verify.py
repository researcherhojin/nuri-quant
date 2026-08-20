"""
Nuri-Quant 기능 검증 스크립트 — 모든 분석을 실행하고 결과를 파일로 저장.

결과 디렉토리: data/reports/YYYY-MM-DD/
  ├── portfolio.csv                # 종목별 현황 (비중, 손익)
  ├── risk.json                    # 리스크 지표 (Sharpe, VaR, MDD)
  ├── sector.csv / region.csv      # 섹터/지역 노출도
  ├── correlation.csv / .png       # 상관행렬 + 히트맵
  ├── rebalance_mvo.csv / _rp.csv  # MVO / Risk Parity 리밸런싱
  ├── factors.csv                  # 멀티팩터 스코어
  ├── signal_results.csv           # C-1: 시그널 개별 거래
  ├── signal_scorecard.csv         # C-1: 시그널별 승률/PF
  ├── superinvestor_*.csv          # C-2: 슈퍼투자자 추종 결과
  ├── validation_report.html       # C-4: 통합 대시보드
  ├── tearsheet.html               # QuantStats 성과 리포트
  └── summary.txt                  # 전체 요약

사용법:
    python scripts/verify/verify.py
    python scripts/verify/verify.py --skip-backtest   # 백테스트 제외 (빠르게)
    make verify / make verify-fast
"""

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

# 프로젝트 루트를 path에 추가.
# `parents[2]` 인 이유: 이 파일은 `<root>/scripts/verify/verify.py` 라 두 단계로는
# `scripts/` 에서 멈춘다. 예전 위치가 `scripts/verify.py` 였고 옮길 때 이 줄이 같이
# 안 따라왔다. 그래서 리포트가 `scripts/data/reports/` 로 나갔는데, `data/reports/`
# 와 달리 거기는 gitignore 가 안 걸려 실보유 종목·수량·손익이 담긴 CSV 가 untracked
# 로 노출됐다 (#1062).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("verify")


def create_report_dir() -> Path:
    """오늘 날짜 리포트 디렉토리 생성 (KST)."""
    from nuri.core.timezone import today_kst

    report_dir = ROOT / "data" / "reports" / today_kst()
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def verify_portfolio(report_dir: Path, summary: list[str]) -> None:
    """포트폴리오 현황 검증."""
    logger.info("─── 포트폴리오 현황 ───")
    from nuri.analysis.portfolio import analyze_portfolio, print_summary

    df = analyze_portfolio()
    if df.empty:
        summary.append("[SKIP] 포트폴리오: 데이터 없음")
        return

    df.to_csv(report_dir / "portfolio.csv", index=False)
    print_summary(df)

    warnings = df.attrs.get("warnings", [])
    total = df.attrs.get("total_value_usd", 0)
    summary.append(f"[OK] 포트폴리오: {len(df)}종목, 총 ${total:,.0f}")
    for w in warnings:
        summary.append(f"  {w}")


def verify_risk(report_dir: Path, summary: list[str]) -> None:
    """리스크 분석 검증."""
    logger.info("─── 리스크 분석 ───")
    from nuri.analysis.risk import analyze_risk, print_risk

    metrics = analyze_risk()
    if not metrics:
        summary.append("[SKIP] 리스크: 데이터 없음")
        return

    # numpy 타입을 JSON 호환으로 변환
    serializable = {}
    for k, v in metrics.items():
        if isinstance(v, (list, dict)):
            serializable[k] = v
        elif hasattr(v, "item"):  # numpy scalar
            serializable[k] = v.item()
        else:
            serializable[k] = v
    with open(report_dir / "risk.json", "w") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print_risk(metrics)

    sharpe = metrics.get("sharpe_ratio", 0)
    mdd = metrics.get("max_drawdown_pct", 0)
    summary.append(f"[OK] 리스크: Sharpe {sharpe:.2f}, MDD {mdd:+.1f}%")

    if metrics.get("stop_loss_alerts"):
        for a in metrics["stop_loss_alerts"]:
            summary.append(f"  🚨 손절선: {a['ticker']} {a['pnl_pct']:+.1f}%")


def verify_sector(report_dir: Path, summary: list[str]) -> None:
    """섹터 노출도 검증."""
    logger.info("─── 섹터 분석 ───")
    from nuri.analysis.sector import analyze_sector, print_sector

    sector_df, region_df, warnings = analyze_sector()
    if sector_df.empty:
        summary.append("[SKIP] 섹터: 데이터 없음")
        return

    sector_df.to_csv(report_dir / "sector.csv", index=False)
    region_df.to_csv(report_dir / "region.csv", index=False)
    print_sector(sector_df, region_df, warnings)

    top = sector_df.iloc[0]
    summary.append(f"[OK] 섹터: {len(sector_df)}개, 최대 {top['sector']} {top['weight_pct']:.1f}%")
    for w in warnings:
        summary.append(f"  {w}")


def verify_correlation(report_dir: Path, summary: list[str]) -> None:
    """상관관계 분석 검증."""
    logger.info("─── 상관관계 분석 ───")
    from nuri.analysis.correlation import analyze_correlation, print_correlation

    corr, warnings = analyze_correlation(min_days=20)
    if corr.empty:
        summary.append("[SKIP] 상관관계: 데이터 부족")
        return

    corr.to_csv(report_dir / "correlation.csv")
    print_correlation(corr, warnings)

    # 히트맵을 리포트 디렉토리에 저장
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(
            corr,
            annot=True,
            fmt=".2f",
            cmap="RdYlGn_r",
            center=0,
            vmin=-1,
            vmax=1,
            ax=ax,
            square=True,
        )
        ax.set_title("Nuri-Quant Portfolio Correlation Matrix")
        fig.tight_layout()
        fig.savefig(report_dir / "correlation.png", dpi=150)
        plt.close(fig)
    except Exception as e:
        logger.warning(f"히트맵 생성 실패: {e}")

    high_corr = len(warnings)
    summary.append(f"[OK] 상관관계: {len(corr)}종목, 고상관 쌍 {high_corr}개")


def verify_rebalance(report_dir: Path, summary: list[str]) -> None:
    """리밸런싱 제안 검증 (MVO + RP)."""
    logger.info("─── 리밸런싱 (MVO) ───")
    from nuri.analysis.rebalance import analyze_rebalance, print_rebalance

    for method, filename in [("mvo", "rebalance_mvo.csv"), ("rp", "rebalance_rp.csv")]:
        try:
            df = analyze_rebalance(method=method)
            if df.empty:
                summary.append(f"[SKIP] 리밸런싱({method}): 데이터 부족")
                continue

            df.to_csv(report_dir / filename, index=False)
            print_rebalance(df)

            actionable = df[df["action"] != "HOLD"]
            label = df.attrs.get("method", method.upper())
            summary.append(f"[OK] 리밸런싱({label}): {len(actionable)}건 매매 제안")
        except Exception as e:
            summary.append(f"[FAIL] 리밸런싱({method}): {e}")
            logger.error(traceback.format_exc())


def verify_factors(report_dir: Path, summary: list[str]) -> None:
    """멀티팩터 스코어 검증."""
    logger.info("─── 멀티팩터 스코어 ───")
    from nuri.quant.factors.composite import compute_composite, print_composite

    df = compute_composite()
    if df.empty:
        summary.append("[SKIP] 팩터: 데이터 없음")
        return

    df.to_csv(report_dir / "factors.csv")
    print_composite(df)

    top = df.index[0]
    top_score = df.iloc[0]["composite_score"]

    # 변별력 검사 (#1102). 이 단계는 원래 종목 수와 1위 점수만 찍었고, 그 둘은 붕괴해도
    # 멀쩡해 보인다 — value/quality 가 채점 대상의 99% 에서 상수 0.5 이던 넉 달 내내
    # 여기는 초록이었다. 합성 스코어가 **순위를 만들지 못하면 그건 신호가 아니라 상수**이므로,
    # 값의 정상 범위가 아니라 **퍼짐**을 본다.
    #
    # 임계 0.05: 붕괴 상태의 실측 p10~p90 은 0.0585 였고 그중 대부분이 momentum 단독
    # 기여였다. 성분 하나만 살아 있어도 그 정도는 나온다는 뜻이라 그 위에 둔다.
    # 부분 상수도 같이 본다 — 전체 폭은 momentum 이 떠받치고 성분 하나만 죽는 형태가
    # 실제로 벌어진 일이라, 폭만 보면 그 절반을 놓친다.
    spread = float(df["composite_score"].quantile(0.9) - df["composite_score"].quantile(0.1))
    flat = [
        col
        for col in ("value_score", "quality_score", "momentum_score")
        if len(df) > 1 and float(df[col].nunique()) / len(df) < 0.10
    ]
    if spread < 0.05 or flat:
        why = f"p10~p90 폭 {spread:.4f}"
        if flat:
            why += f", 사실상 상수인 성분 {flat}"
        summary.append(f"[FAIL] 팩터: {len(df)}종목이지만 변별력이 없다 ({why})")
    else:
        summary.append(f"[OK] 팩터: {len(df)}종목, Top {top} ({top_score:.3f}), p10~p90 폭 {spread:.4f}")


def verify_backtest(report_dir: Path, summary: list[str]) -> None:
    """전략 검증 (walk-forward null-safe gate — #701/#702 단일 경로)."""
    logger.info("─── Strategy Walk-Forward 검증 ───")
    from nuri.quant.validation.strategy_walkforward import run_strategy_validation

    try:
        result = run_strategy_validation(cost_bps=10.0, persist=False)  # check-only (DB 미기록)
    except ValueError as exc:
        summary.append(f"[SKIP] walk-forward: {exc}")
        return

    with open(report_dir / "walkforward.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    gate = result["gate"]
    # 판정을 `[OK]` 문장 안에 문자열로 넣지 않는다 (#1115). 이전엔 게이트가 떨어져도
    # `[OK] walk-forward: … gate FAIL` 로 나갔다 — 접두어를 세는 사람에게도, grep 하는
    # 스크립트에게도 통과로 읽힌다. 접두어가 곧 판정이어야 한다.
    prefix = "[OK]" if gate["passed"] else "[FAIL]"
    summary.append(f"{prefix} walk-forward: OOS Sharpe {result['oos_sharpe_pooled']:+.2f}, p={gate['p_value']:.3f}")


def verify_performance(report_dir: Path, summary: list[str]) -> None:
    """QuantStats 성과 분석 검증."""
    logger.info("─── 성과 분석 (QuantStats) ───")
    from nuri.analysis.performance import (
        get_benchmark_returns,
        get_portfolio_returns,
        print_performance,
    )

    port = get_portfolio_returns()
    bench = get_benchmark_returns()

    if port.empty:
        summary.append("[SKIP] 성과분석: 데이터 없음")
        return

    print_performance(port, bench)

    # HTML 티어시트를 리포트 디렉토리에도 생성
    try:
        import quantstats as qs

        qs.reports.html(
            port,
            benchmark=bench if not bench.empty else None,
            output=str(report_dir / "tearsheet.html"),
            title="Nuri-Quant Portfolio Performance",
        )
    except Exception as e:
        logger.warning(f"HTML 티어시트 생성 실패: {e}")

    summary.append("[OK] 성과분석: 티어시트 생성 완료")


def verify_signal_backtest(report_dir: Path, summary: list[str]) -> None:
    """Phase C-1: 시그널 백테스트 검증."""
    logger.info("─── 시그널 백테스트 (C-1) ───")
    from dataclasses import asdict

    import pandas as pd

    from nuri.quant.validation.signal_backtest import backtest_signals, generate_scorecard, print_scorecard

    results = backtest_signals()
    if not results:
        summary.append("[SKIP] 시그널 백테스트: 시그널 없음")
        return

    scorecards = generate_scorecard(results)
    print_scorecard(scorecards)

    pd.DataFrame([asdict(r) for r in results]).to_csv(report_dir / "signal_results.csv", index=False)
    pd.DataFrame([asdict(s) for s in scorecards]).to_csv(report_dir / "signal_scorecard.csv", index=False)

    total_cards = [s for s in scorecards if s.ticker is None]
    best = max(total_cards, key=lambda s: s.profit_factor) if total_cards else None
    summary.append(f"[OK] 시그널 백테스트: {len(results)}건 거래, {len(total_cards)}개 시그널")
    if best:
        summary.append(f"     최고 PF: {best.signal_id} ({best.profit_factor:.1f})")


def verify_superinvestor_backtest(report_dir: Path, summary: list[str]) -> None:
    """Phase C-2: 슈퍼투자자 추종 검증."""
    logger.info("─── 슈퍼투자자 추종 (C-2) ───")
    from dataclasses import asdict

    import pandas as pd

    from nuri.quant.validation.superinvestor_backtest import (
        backtest_superinvestor,
        generate_scorecard,
        print_scorecard,
    )

    results = backtest_superinvestor()
    scorecards = generate_scorecard(results, hold_days=120)
    print_scorecard(scorecards)

    if results:
        pd.DataFrame([asdict(r) for r in results]).to_csv(report_dir / "superinvestor_results.csv", index=False)
    if scorecards:
        pd.DataFrame([asdict(s) for s in scorecards]).to_csv(report_dir / "superinvestor_scorecard.csv", index=False)

    summary.append(f"[OK] 슈퍼투자자: {len(results)}건 추종, {len(scorecards)}명")


def verify_validation_scorecard(report_dir: Path, summary: list[str]) -> None:
    """Phase C-4: 통합 스코어카드 검증."""
    logger.info("─── 통합 스코어카드 (C-4) ───")
    from nuri.quant.validation.scorecard import generate_validation_report

    path = generate_validation_report(output_dir=report_dir)
    if path:
        summary.append(f"[OK] 스코어카드: {path.name}")
    else:
        summary.append("[SKIP] 스코어카드: C-1 CSV 필요")


def verify_regime(report_dir: Path, summary: list[str]) -> None:
    """Phase D: 레짐 분류 + 매크로 스코어 + 전략."""
    logger.info("─── 시장 레짐 (D-1~D-3) ───")
    from nuri.quant.regime.classifier import classify_regime, print_regime
    from nuri.quant.regime.macro_score import compute_macro_score, print_macro_score
    from nuri.quant.regime.strategy_map import map_regime_to_strategy, print_strategy

    regime = classify_regime()
    print_regime(regime)

    macro = compute_macro_score()
    print_macro_score(macro)

    strategy = map_regime_to_strategy(regime, macro)
    print_strategy(strategy)

    if regime:
        summary.append(f"[OK] 레짐: {regime.regime} (신뢰도 {regime.confidence:.0%})")
    else:
        summary.append("[SKIP] 레짐: SPY 데이터 부족")
    summary.append(f"[OK] 매크로: {macro.total_score:.0f}/100 ({macro.interpretation})")


def verify_gate(report_dir: Path, summary: list[str]) -> None:
    """SIEGE Gate: 파이프라인 준비 상태 검증."""
    logger.info("─── Pipeline Gate ───")
    from nuri.trading.engine.gate import check_all_gates, print_gate

    gates = check_all_gates()
    for phase, result in gates.items():
        print_gate(result)
        status = "READY" if result.ready else "BLOCKED"
        summary.append(f"[GATE] {phase}: {status} ({result.passed}/{result.total})")


def verify_candidates(report_dir: Path, summary: list[str]) -> None:
    """Phase E: 매매 후보 + 충돌 감지 + 성과 메모리."""
    logger.info("─── 매매 후보 (E-1 + Conflicts + Memory) ───")
    from nuri.trading.engine.conflicts import detect_conflicts, print_conflicts
    from nuri.trading.engine.memory import detect_drift, print_memory_status, save_snapshot
    from nuri.trading.recommend.candidates import print_candidates, screen_candidates

    # E-1 후보 (drift + conflict 자동 반영됨)
    candidates = screen_candidates(lookback_days=5)
    print_candidates(candidates)

    buys = [c for c in candidates if c.direction == "BUY" and c.regime_fit]
    sells = [c for c in candidates if c.direction == "SELL" and c.regime_fit]
    conflicted = set(c.ticker for c in candidates if c.conflict)
    summary.append(f"[OK] 매매 후보: BUY {len(buys)}건, SELL {len(sells)}건, 충돌 {len(conflicted)}종목")

    # Conflict 상세
    conflicts = detect_conflicts(candidates)
    if conflicts:
        print_conflicts(conflicts)
        summary.append(f"[WARN] 시그널 충돌: {len(conflicts)}건 ({', '.join(c.ticker for c in conflicts[:5])})")

    # Learning Memory 스냅샷 + drift
    n = save_snapshot()
    if n:
        logger.info(f"Learning Memory 스냅샷 {n}건 저장")
    drifts = detect_drift()
    print_memory_status(drifts)
    critical = [d for d in drifts if d.status in ("critical", "degrading")]
    if critical:
        summary.append(f"[WARN] 성과 하락 시그널: {', '.join(d.signal_id for d in critical)}")


def main() -> int:
    """검증 실행. **`[FAIL]` 이 하나라도 있으면 1을 반환한다** (#1115).

    이전엔 반환값이 없어 `make verify`(213s) · `make verify-fast`(127s) 가 무엇을 찾든
    항상 0 으로 끝났다. 요약에 `[FAIL]` 을 찍어놓고도 종료코드는 성공이라, 배포 전 게이트로
    쓰라고 만든 두 타깃이 실은 리포트 생성기였다. 실패할 수 없는 게이트는 게이트가 아니다 —
    #910/#911(pre-push 테스트 단계가 3.5개월 no-op) · #953/#954(훅 2개가 조용히 exit 0)
    와 같은 계열이다.

    `[SKIP]` 은 실패가 아니다. 데이터가 없어 검사를 못 한 것과 검사가 떨어진 것은 다르고,
    둘을 같이 취급하면 신선한 설치가 영구 빨강이 되어 아무도 안 본다.
    """
    parser = argparse.ArgumentParser(description="Nuri-Quant 기능 검증")
    parser.add_argument("--skip-backtest", action="store_true", help="백테스트 건너뛰기")
    args = parser.parse_args()

    report_dir = create_report_dir()
    summary: list[str] = []

    print(f"\n{'═' * 60}")
    print("  Nuri-Quant 기능 검증")
    print(f"  결과 저장: {report_dir}")
    print(f"{'═' * 60}\n")

    steps = [
        # SIEGE Gate: 데이터 준비 상태 확인
        ("파이프라인 게이트", verify_gate),
        # Phase A/B: 기본 분석
        ("포트폴리오", verify_portfolio),
        ("리스크", verify_risk),
        ("섹터", verify_sector),
        ("상관관계", verify_correlation),
        ("리밸런싱", verify_rebalance),
        ("멀티팩터", verify_factors),
        ("성과분석", verify_performance),
        # Phase C: 검증
        ("시그널 백테스트", verify_signal_backtest),
        ("슈퍼투자자 추종", verify_superinvestor_backtest),
        ("통합 스코어카드", verify_validation_scorecard),
        # Phase D: 레짐
        ("시장 레짐", verify_regime),
        # Phase E: 추천
        ("매매 후보", verify_candidates),
    ]

    if not args.skip_backtest:
        steps.append(("백테스트", verify_backtest))

    for name, func in steps:
        try:
            func(report_dir, summary)
        except Exception as e:
            summary.append(f"[FAIL] {name}: {e}")
            logger.error(f"{name} 실패:\n{traceback.format_exc()}")
        print()  # 단계 간 구분

    # 요약 저장 (KST timestamp)
    from nuri.core.timezone import kst_now

    summary_text = "\n".join(summary)
    (report_dir / "summary.txt").write_text(
        f"Nuri-Quant 검증 결과 — {kst_now().strftime('%Y-%m-%d %H:%M')}\n{'=' * 50}\n{summary_text}\n",
        encoding="utf-8",
    )

    # 최종 출력
    print(f"{'═' * 60}")
    print("  검증 완료 — 요약")
    print(f"{'═' * 60}")
    for line in summary:
        print(f"  {line}")
    print(f"\n  📁 결과 디렉토리: {report_dir}")

    # 생성된 파일 목록
    files = sorted(report_dir.iterdir())
    print(f"  📄 생성된 파일 ({len(files)}개):")
    for f in files:
        size = f.stat().st_size
        if size > 1024 * 1024:
            size_str = f"{size / 1024 / 1024:.1f}MB"
        elif size > 1024:
            size_str = f"{size / 1024:.1f}KB"
        else:
            size_str = f"{size}B"
        print(f"     {f.name:<25} {size_str:>8}")
    print()

    failed = [line for line in summary if line.startswith("[FAIL]")]
    if failed:
        print(f"  ✗ {len(failed)}건 실패:")
        for line in failed:
            print(f"     {line}")
        print()
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — main() 은 테스트가 직접 부른다. runpy 로
    # 돌리면 실제 검증 전체(213s · 네트워크 · 리포트 디렉터리 생성)가 실행된다.
    sys.exit(main())
