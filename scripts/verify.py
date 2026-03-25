"""
Nuri-Quant 기능 검증 스크립트 — 모든 분석을 실행하고 결과를 파일로 저장.

결과 디렉토리: data/reports/YYYY-MM-DD/
  ├── portfolio.csv          # 종목별 현황 (비중, 손익)
  ├── risk.json              # 리스크 지표 (Sharpe, VaR, MDD)
  ├── sector.csv             # 섹터 노출도
  ├── region.csv             # 지역 노출도 (US/KR)
  ├── correlation.csv        # 상관행렬
  ├── correlation.png        # 상관관계 히트맵
  ├── rebalance_mvo.csv      # MVO 리밸런싱 제안
  ├── rebalance_rp.csv       # Risk Parity 리밸런싱 제안
  ├── factors.csv            # 멀티팩터 스코어
  ├── backtest.json          # 백테스트 결과
  ├── tearsheet.html         # QuantStats HTML 티어시트
  └── summary.txt            # 전체 요약

사용법:
    python scripts/verify.py
    python scripts/verify.py --skip-backtest   # 백테스트 제외 (빠르게)
"""
import argparse
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("verify")


def create_report_dir() -> Path:
    """오늘 날짜 리포트 디렉토리 생성."""
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = ROOT / "data" / "reports" / today
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
    from nuri.analysis.correlation import analyze_correlation, print_correlation, save_heatmap

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
            corr, annot=True, fmt=".2f",
            cmap="RdYlGn_r", center=0, vmin=-1, vmax=1,
            ax=ax, square=True,
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
    summary.append(f"[OK] 팩터: {len(df)}종목, Top {top} ({top_score:.3f})")


def verify_backtest(report_dir: Path, summary: list[str]) -> None:
    """백테스트 검증."""
    logger.info("─── 백테스트 (VectorBT) ───")
    from nuri.quant.backtest.engine import run_momentum_backtest, print_backtest

    result = run_momentum_backtest(top_n=5, rebalance_days=20)
    if not result:
        summary.append("[SKIP] 백테스트: 데이터 부족")
        return

    with open(report_dir / "backtest.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print_backtest(result)

    # tearsheet도 리포트 디렉토리로 복사
    tearsheet_src = ROOT / "data" / "exports" / "backtest_tearsheet.html"
    if tearsheet_src.exists():
        import shutil
        shutil.copy2(tearsheet_src, report_dir / "tearsheet.html")

    ret = result.get("total_return_pct", 0)
    sharpe = result.get("sharpe_ratio", 0)
    summary.append(f"[OK] 백테스트: 수익률 {ret:+.1f}%, Sharpe {sharpe:.2f}")


def verify_performance(report_dir: Path, summary: list[str]) -> None:
    """QuantStats 성과 분석 검증."""
    logger.info("─── 성과 분석 (QuantStats) ───")
    from nuri.analysis.performance import (
        get_portfolio_returns,
        get_benchmark_returns,
        print_performance,
        generate_html_report,
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


def main():
    parser = argparse.ArgumentParser(description="Nuri-Quant 기능 검증")
    parser.add_argument("--skip-backtest", action="store_true", help="백테스트 건너뛰기")
    args = parser.parse_args()

    report_dir = create_report_dir()
    summary: list[str] = []

    print(f"\n{'═' * 60}")
    print(f"  Nuri-Quant 기능 검증")
    print(f"  결과 저장: {report_dir}")
    print(f"{'═' * 60}\n")

    steps = [
        ("포트폴리오", verify_portfolio),
        ("리스크", verify_risk),
        ("섹터", verify_sector),
        ("상관관계", verify_correlation),
        ("리밸런싱", verify_rebalance),
        ("멀티팩터", verify_factors),
        ("성과분석", verify_performance),
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

    # 요약 저장
    summary_text = "\n".join(summary)
    (report_dir / "summary.txt").write_text(
        f"Nuri-Quant 검증 결과 — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'=' * 50}\n{summary_text}\n",
        encoding="utf-8",
    )

    # 최종 출력
    print(f"{'═' * 60}")
    print(f"  검증 완료 — 요약")
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


if __name__ == "__main__":
    main()
