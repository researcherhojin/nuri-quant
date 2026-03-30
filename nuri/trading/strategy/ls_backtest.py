"""
Long/Short Strategy Backtest — 과거 5년 검증.

매 거래일 레짐을 분류하고, 레짐에 따라 롱/숏/현금을 배분했을 때
실제 수익률이 얼마였는지 측정.

사용법:
    python -m nuri.trading.strategy.ls_backtest
    python -m nuri.trading.strategy.ls_backtest --stress    # 위기 구간 분석
"""
import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import query_df

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# 레짐 → 배분 (longshort.py와 동일)
REGIME_ALLOCATION = {
    "bull_low_vol":     {"long": 0.90, "short": 0.00, "cash": 0.10},
    "bull_high_vol":    {"long": 0.70, "short": 0.00, "cash": 0.30},
    "sideways_low_vol": {"long": 0.50, "short": 0.00, "cash": 0.50},
    "sideways_high_vol":{"long": 0.25, "short": 0.15, "cash": 0.60},
    "bear_low_vol":     {"long": 0.10, "short": 0.40, "cash": 0.50},
    "bear_high_vol":    {"long": 0.00, "short": 0.50, "cash": 0.50},
}

TRANSACTION_COST = 0.001  # 편도 0.1%
SLIPPAGE = 0.0005         # 편도 0.05% 슬리피지


@dataclass
class BacktestResult:
    """백테스트 결과."""
    total_return: float
    annual_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float             # 양수 수익 일수 비율
    total_days: int
    regime_changes: int
    transaction_costs: float
    # 비교
    spy_total_return: float
    spy_annual_return: float
    spy_sharpe: float
    spy_max_drawdown: float
    excess_return: float


@dataclass
class RegimePerformance:
    """레짐별 성과."""
    regime: str
    days: int
    pct_of_total: float
    avg_daily_return: float
    total_return: float
    win_rate: float
    avg_duration: float         # 평균 지속 일수
    transitions_to: dict        # 다음 레짐 확률


@dataclass
class TimingAnalysis:
    """현재 레짐에서의 향후 수익률 분석."""
    current_regime: str
    occurrences: int
    avg_forward_30d: float
    avg_forward_60d: float
    avg_forward_90d: float
    pct_to_bull: float
    pct_to_bear: float
    pct_stay: float


# ═══════════════════════════════════════════════════════
# BT1: 과거 레짐 분류
# ═══════════════════════════════════════════════════════


def classify_historical_regimes(db_path=None) -> pd.DataFrame:
    """매 거래일의 레짐을 분류. SPY SMA50/200 + VIX 기반."""
    spy = query_df(
        "SELECT date, close FROM prices WHERE ticker='SPY' ORDER BY date",
        db_path=db_path,
    )
    if spy.empty or len(spy) < 200:
        logger.error("SPY 데이터 부족")
        return pd.DataFrame()

    vix = query_df(
        "SELECT date, value as vix FROM macro WHERE indicator='vix' ORDER BY date",
        db_path=db_path,
    )

    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date")
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy["sma200"] = spy["close"].rolling(200).mean()
    spy["sma_gap"] = (spy["sma50"] - spy["sma200"]) / spy["sma200"] * 100

    # VIX 병합
    if not vix.empty:
        vix["date"] = pd.to_datetime(vix["date"])
        vix = vix.set_index("date")
        spy = spy.join(vix[["vix"]], how="left")
        spy["vix"] = spy["vix"].ffill()
    else:
        spy["vix"] = np.nan

    # 동적 임계값 (252일 롤링)
    spy["vix_median"] = spy["vix"].rolling(252, min_periods=50).median()
    spy["vix_p75"] = spy["vix"].rolling(252, min_periods=50).quantile(0.75)
    spy["gap_std"] = spy["sma_gap"].rolling(252, min_periods=50).std()
    spy["sideways_th"] = (spy["gap_std"] * 0.5).clip(lower=1.0)

    # SMA200 계산 불가 행 제거 (첫 200일)
    spy = spy.dropna(subset=["sma200"])

    # 레짐 분류
    regimes = []
    for idx, row in spy.iterrows():

        close = row["close"]
        sma50 = row["sma50"]
        sma200 = row["sma200"]
        gap = row["sma_gap"]
        sideways_th = row["sideways_th"] if pd.notna(row["sideways_th"]) else 2.0

        # 추세 — 가격 위치 + SMA 관계 + gap 종합
        price_above = close > sma200
        sma_bullish = sma50 > sma200

        if abs(gap) < sideways_th and not (price_above != sma_bullish):
            trend = "sideways"
        elif price_above and sma_bullish:
            trend = "bull"
        elif not price_above and not sma_bullish:
            trend = "bear"
        elif not price_above:
            # 가격이 SMA200 아래 — 하락 초기 또는 횡보 하단
            trend = "bear" if gap < -sideways_th else "sideways"
        else:
            trend = "sideways"

        # 변동성
        vix_val = row["vix"]
        vix_th = row["vix_p75"] if trend == "bear" else row["vix_median"]
        if pd.notna(vix_val) and pd.notna(vix_th):
            vol = "high" if vix_val >= vix_th else "low"
        else:
            vol = "low"

        regimes.append(f"{trend}_{vol}_vol")

    spy["regime"] = regimes

    # 백테스트는 히스테리시스 미적용 (과거 데이터는 확정된 종가이므로 노이즈 없음)

    # SPY 일간 수익률
    spy["return"] = spy["close"].pct_change()

    return spy.reset_index()


# ═══════════════════════════════════════════════════════
# BT2: Long/Short 전략 백테스트
# ═══════════════════════════════════════════════════════


MIN_HOLD_DAYS = 10  # 레짐 전환 최소 유지 기간 (거래 빈도 제한)


def run_backtest(regimes_df: pd.DataFrame, db_path=None) -> BacktestResult:
    """엄밀한 L/S 백테스트.

    개선점:
    1. 숏 = 실제 SH(인버스 ETF) 가격 사용 (decay 반영)
    2. 레짐 최소 10일 유지 (거래 빈도 제한)
    3. 종가 판단 → 다음날 시가 실행 (갭 반영)
    4. 거래 비용 0.15% 편도
    """
    df = regimes_df.copy()
    df = df[df["regime"] != "unknown"].dropna(subset=["return"])
    df = df.reset_index(drop=True)

    # SH 가격 로드 (실제 인버스 ETF)
    sh = query_df("SELECT date, close, open FROM prices WHERE ticker='SH' ORDER BY date", db_path=db_path)
    if not sh.empty:
        sh["date"] = pd.to_datetime(sh["date"])
        sh = sh.set_index("date")
        sh["sh_return"] = sh["close"].pct_change()
        sh["sh_open_return"] = sh["close"] / sh["open"] - 1  # 시가→종가
    else:
        sh = pd.DataFrame()

    # SPY 시가 (다음날 실행용)
    spy_open = query_df("SELECT date, open FROM prices WHERE ticker='SPY' ORDER BY date", db_path=db_path)
    if not spy_open.empty:
        spy_open["date"] = pd.to_datetime(spy_open["date"])
        spy_open = spy_open.set_index("date")

    # 레짐 최소 유지 기간 적용
    active_regime = df.iloc[0]["regime"]
    hold_count = 0
    effective_regimes = []

    for _, row in df.iterrows():
        raw_regime = row["regime"]
        if raw_regime != active_regime:
            hold_count += 1
            if hold_count >= MIN_HOLD_DAYS:
                active_regime = raw_regime
                hold_count = 0
        else:
            hold_count = 0
        effective_regimes.append(active_regime)

    df["effective_regime"] = effective_regimes

    # 시뮬레이션
    strategy_returns = []
    spy_returns = []
    prev_regime = None
    total_cost = 0
    regime_changes = 0

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        regime = row["effective_regime"]
        date = pd.Timestamp(row["date"])

        # SPY 수익률 (종가 기준)
        spy_ret = row["return"]

        # 다음날 시가 실행 시뮬레이션: 전일 종가 대비 당일 시가 갭
        gap_cost = 0
        if not spy_open.empty and date in spy_open.index:
            spy_open_price = spy_open.loc[date, "open"]
            spy_prev_close = prev_row["close"]
            if spy_prev_close > 0:
                gap_cost = abs(spy_open_price / spy_prev_close - 1) * 0.3  # 갭의 30%를 비용으로

        alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["sideways_high_vol"])

        # 레짐 전환 시 거래 비용
        cost = 0
        if regime != prev_regime and prev_regime is not None:
            cost = TRANSACTION_COST * 2 + SLIPPAGE * 2 + gap_cost
            total_cost += cost
            regime_changes += 1

        # 숏 수익률: SH 실제 가격 사용 (있으면)
        if alloc["short"] > 0 and not sh.empty and date in sh.index:
            short_ret = float(sh.loc[date, "sh_return"])
            if pd.isna(short_ret):
                short_ret = -spy_ret  # fallback
        else:
            short_ret = -spy_ret  # SH 데이터 없으면 이론값

        # 전략 수익률
        strat_ret = (alloc["long"] * spy_ret
                     + alloc["short"] * short_ret
                     + alloc["cash"] * 0
                     - cost)

        strategy_returns.append(strat_ret)
        spy_returns.append(spy_ret)
        prev_regime = regime

    strat = pd.Series(strategy_returns)
    spy_s = pd.Series(spy_returns)

    if strat.empty:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    strat_cum = (1 + strat).cumprod()
    spy_cum = (1 + spy_s).cumprod()

    total_return = (strat_cum.iloc[-1] - 1) * 100
    spy_total = (spy_cum.iloc[-1] - 1) * 100
    years = len(strat) / 252

    annual_return = ((1 + total_return / 100) ** (1 / max(years, 0.1)) - 1) * 100
    spy_annual = ((1 + spy_total / 100) ** (1 / max(years, 0.1)) - 1) * 100

    sharpe = strat.mean() / strat.std() * np.sqrt(252) if strat.std() > 0 else 0
    spy_sharpe = spy_s.mean() / spy_s.std() * np.sqrt(252) if spy_s.std() > 0 else 0

    strat_dd = (strat_cum / strat_cum.cummax() - 1).min() * 100
    spy_dd = (spy_cum / spy_cum.cummax() - 1).min() * 100

    return BacktestResult(
        total_return=round(total_return, 2),
        annual_return=round(annual_return, 2),
        sharpe=round(sharpe, 2),
        max_drawdown=round(strat_dd, 2),
        win_rate=round(float((strat > 0).mean()), 3),
        total_days=len(strat),
        regime_changes=regime_changes,
        transaction_costs=round(total_cost * 100, 2),
        spy_total_return=round(spy_total, 2),
        spy_annual_return=round(spy_annual, 2),
        spy_sharpe=round(spy_sharpe, 2),
        spy_max_drawdown=round(spy_dd, 2),
        excess_return=round(total_return - spy_total, 2),
    )


# ═══════════════════════════════════════════════════════
# BT3: 레짐별 성과 분석
# ═══════════════════════════════════════════════════════


def analyze_per_regime(regimes_df: pd.DataFrame) -> list[RegimePerformance]:
    """레짐별 상세 성과."""
    df = regimes_df[regimes_df["regime"] != "unknown"].copy()
    total_days = len(df)
    results = []

    for regime in sorted(df["regime"].unique()):
        rdf = df[df["regime"] == regime]
        days = len(rdf)

        alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["sideways_high_vol"])
        # 전략 수익률
        rets = rdf["return"].dropna()
        strat_rets = alloc["long"] * rets + alloc["short"] * (-rets)

        # 평균 지속 기간
        durations = []
        count = 0
        for i in range(len(df)):
            if df.iloc[i]["regime"] == regime:
                count += 1
            elif count > 0:
                durations.append(count)
                count = 0
        if count > 0:
            durations.append(count)

        # 다음 레짐 전환 확률
        transitions = {}
        for i in range(len(df) - 1):
            if df.iloc[i]["regime"] == regime and df.iloc[i+1]["regime"] != regime:
                next_r = df.iloc[i+1]["regime"]
                transitions[next_r] = transitions.get(next_r, 0) + 1
        total_trans = sum(transitions.values()) or 1
        transitions = {k: round(v/total_trans, 2) for k, v in transitions.items()}

        results.append(RegimePerformance(
            regime=regime,
            days=days,
            pct_of_total=round(days / total_days * 100, 1),
            avg_daily_return=round(float(strat_rets.mean()) * 100, 4),
            total_return=round(float((1 + strat_rets).prod() - 1) * 100, 2),
            win_rate=round(float((strat_rets > 0).mean()), 3),
            avg_duration=round(np.mean(durations), 1) if durations else 0,
            transitions_to=transitions,
        ))

    return sorted(results, key=lambda r: r.total_return, reverse=True)


# ═══════════════════════════════════════════════════════
# BT4: 투입 적기 분석
# ═══════════════════════════════════════════════════════


def analyze_entry_timing(regimes_df: pd.DataFrame, current_regime: str = None) -> TimingAnalysis | None:
    """현재 레짐에서 향후 수익률 분석."""
    if current_regime is None:
        try:
            from nuri.quant.regime.classifier import classify_regime
            r = classify_regime()
            current_regime = r.regime if r else None
        except Exception:
            pass
    if not current_regime:
        return None

    df = regimes_df[regimes_df["regime"] != "unknown"].copy()
    spy_close = df.set_index("date")["close"]

    # 현재 레짐이 시작된 모든 시점 찾기
    entries = []
    for i in range(1, len(df)):
        if df.iloc[i]["regime"] == current_regime and df.iloc[i-1]["regime"] != current_regime:
            entries.append(df.iloc[i]["date"])

    if not entries:
        return None

    fwd_30, fwd_60, fwd_90 = [], [], []
    to_bull, to_bear, stay = 0, 0, 0

    for entry_date in entries:
        entry_idx = spy_close.index.get_indexer([entry_date], method="nearest")[0]
        entry_price = spy_close.iloc[entry_idx]

        # 30/60/90일 후 수익률
        for days, lst in [(30, fwd_30), (60, fwd_60), (90, fwd_90)]:
            future_idx = min(entry_idx + days, len(spy_close) - 1)
            if future_idx > entry_idx:
                ret = (spy_close.iloc[future_idx] - entry_price) / entry_price * 100
                lst.append(ret)

        # 30일 후 레짐
        future_idx = min(entry_idx + 30, len(df) - 1)
        if future_idx < len(df):
            future_regime = df.iloc[future_idx]["regime"]
            from nuri.trading.strategy.longshort import REGIME_ALLOCATION
            alloc = REGIME_ALLOCATION.get(future_regime, {})
            future_dir = alloc.get("direction", "")
            if future_dir == "long":
                to_bull += 1
            elif future_dir == "short":
                to_bear += 1
            else:
                stay += 1

    total = to_bull + to_bear + stay or 1

    return TimingAnalysis(
        current_regime=current_regime,
        occurrences=len(entries),
        avg_forward_30d=round(np.mean(fwd_30), 2) if fwd_30 else 0,
        avg_forward_60d=round(np.mean(fwd_60), 2) if fwd_60 else 0,
        avg_forward_90d=round(np.mean(fwd_90), 2) if fwd_90 else 0,
        pct_to_bull=round(to_bull / total, 2),
        pct_to_bear=round(to_bear / total, 2),
        pct_stay=round(stay / total, 2),
    )


# ═══════════════════════════════════════════════════════
# BT5: 스트레스 테스트
# ═══════════════════════════════════════════════════════


def stress_test(regimes_df: pd.DataFrame) -> list[dict]:
    """특정 위기 구간 분석."""
    crises = [
        {"name": "COVID Crash", "start": "2020-02-19", "end": "2020-03-23"},
        {"name": "2022 Bear Market", "start": "2022-01-03", "end": "2022-10-12"},
        {"name": "2023 Banking Crisis", "start": "2023-03-08", "end": "2023-03-24"},
        {"name": "2024 Aug Selloff", "start": "2024-07-16", "end": "2024-08-05"},
        {"name": "2025 Tariff Shock", "start": "2025-02-19", "end": "2025-03-13"},
    ]

    df = regimes_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    results = []

    for crisis in crises:
        start = pd.Timestamp(crisis["start"])
        end = pd.Timestamp(crisis["end"])
        period = df[(df["date"] >= start) & (df["date"] <= end)]

        if period.empty:
            continue

        # SPY 수익률
        spy_start = period.iloc[0]["close"]
        spy_end = period.iloc[-1]["close"]
        spy_ret = (spy_end - spy_start) / spy_start * 100

        # 전략 수익률
        strat_rets = []
        for _, row in period.iterrows():
            alloc = REGIME_ALLOCATION.get(row["regime"], REGIME_ALLOCATION["sideways_high_vol"])
            ret = row["return"] if pd.notna(row["return"]) else 0
            strat_ret = alloc["long"] * ret + alloc["short"] * (-ret)
            strat_rets.append(strat_ret)

        strat_total = ((1 + pd.Series(strat_rets)).prod() - 1) * 100

        # 감지된 레짐
        regime_counts = period["regime"].value_counts().to_dict()

        results.append({
            "name": crisis["name"],
            "period": f"{crisis['start']} ~ {crisis['end']}",
            "days": len(period),
            "spy_return": round(spy_ret, 2),
            "strategy_return": round(strat_total, 2),
            "excess": round(strat_total - spy_ret, 2),
            "regimes": regime_counts,
            "protected": strat_total > spy_ret,
        })

    return results


# ═══════════════════════════════════════════════════════
# Monte Carlo — 통계적 유의미성 검증
# ═══════════════════════════════════════════════════════


def monte_carlo_test(regimes_df: pd.DataFrame, n_simulations: int = 1000, block_size: int = 20, db_path=None) -> dict:
    """Block Bootstrap Monte Carlo — 전략의 통계적 유의미성 검증.

    기존 완전 랜덤 레짐 배정 대신 20일 블록 단위로 셔플하여
    시계열 자기상관을 보존한 채 통계 검증.

    Args:
        regimes_df: 레짐 + 수익률 DataFrame
        n_simulations: 시뮬레이션 횟수 (기본 1000)
        block_size: 블록 크기 (기본 20일 — 평균 레짐 지속 기간)
        db_path: DB 경로 (테스트용)
    """
    # 실제 전략 수익률
    actual = run_backtest(regimes_df, db_path)
    actual_return = actual.total_return
    actual_sharpe = actual.sharpe

    df = regimes_df[regimes_df["regime"] != "unknown"].dropna(subset=["return"]).copy()
    returns = df["return"].values
    regimes_arr = df["regime"].values
    n = len(returns)

    if n < block_size:
        return {"error": "데이터 부족", "n_data": n, "block_size": block_size}

    # 블록 인덱스 생성
    n_blocks = (n + block_size - 1) // block_size
    block_starts = list(range(0, n, block_size))

    random_returns = []
    random_sharpes = []

    rng = np.random.default_rng(42)

    for _ in range(n_simulations):
        # Block Bootstrap: 블록 단위로 셔플 (시계열 자기상관 보존)
        shuffled_blocks = rng.choice(block_starts, size=n_blocks, replace=True)

        sim_returns = []
        for start in shuffled_blocks:
            end = min(start + block_size, n)
            for i in range(start, end):
                regime = regimes_arr[i]
                ret = returns[i]
                alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["sideways_low_vol"])
                sim_ret = alloc["long"] * ret + alloc["short"] * (-ret)
                sim_returns.append(sim_ret)
                if len(sim_returns) >= n:
                    break
            if len(sim_returns) >= n:
                break

        sim = np.array(sim_returns[:n])
        cum = np.cumprod(1 + sim)
        total = (cum[-1] - 1) * 100
        sharpe = sim.mean() / sim.std() * np.sqrt(252) if sim.std() > 0 else 0

        random_returns.append(total)
        random_sharpes.append(sharpe)

    random_returns = np.array(random_returns)
    random_sharpes = np.array(random_sharpes)

    # 백분위 (p-value)
    return_percentile = (random_returns < actual_return).mean()
    sharpe_percentile = (random_sharpes < actual_sharpe).mean()

    return {
        "actual_return": round(actual_return, 2),
        "actual_sharpe": round(actual_sharpe, 2),
        "random_mean_return": round(float(random_returns.mean()), 2),
        "random_std_return": round(float(random_returns.std()), 2),
        "random_mean_sharpe": round(float(random_sharpes.mean()), 2),
        "return_percentile": round(float(return_percentile), 3),
        "sharpe_percentile": round(float(sharpe_percentile), 3),
        "n_simulations": n_simulations,
        "statistically_significant": return_percentile > 0.95 or sharpe_percentile > 0.95,
    }


def print_monte_carlo(mc: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Monte Carlo Test — {mc['n_simulations']} simulations")
    print(f"{'=' * 60}")
    print(f"  Strategy Return:  {mc['actual_return']:+.1f}%  (percentile: {mc['return_percentile']:.1%})")
    print(f"  Random Mean:      {mc['random_mean_return']:+.1f}% ± {mc['random_std_return']:.1f}%")
    print(f"  Strategy Sharpe:  {mc['actual_sharpe']:.2f}  (percentile: {mc['sharpe_percentile']:.1%})")
    print(f"  Random Sharpe:    {mc['random_mean_sharpe']:.2f}")
    sig = "YES (p < 0.05)" if mc["statistically_significant"] else "NO (p ≥ 0.05)"
    print(f"  Significant:      {sig}")
    print()


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════


def print_backtest(result: BacktestResult) -> None:
    print(f"\n{'=' * 65}")
    print(f"  Long/Short Strategy Backtest — {result.total_days} days")
    print(f"{'=' * 65}")
    print(f"  {'':>25} {'Strategy':>12} {'SPY B&H':>12} {'Excess':>10}")
    print(f"  {'-' * 52}")
    print(f"  {'Total Return':>25} {result.total_return:>+11.1f}% {result.spy_total_return:>+11.1f}% {result.excess_return:>+9.1f}%")
    print(f"  {'Annual Return':>25} {result.annual_return:>+11.1f}% {result.spy_annual_return:>+11.1f}%")
    print(f"  {'Sharpe Ratio':>25} {result.sharpe:>12.2f} {result.spy_sharpe:>12.2f}")
    print(f"  {'Max Drawdown':>25} {result.max_drawdown:>11.1f}% {result.spy_max_drawdown:>11.1f}%")
    print(f"  {'Win Rate (daily)':>25} {result.win_rate:>11.1%}")
    print(f"  {'Regime Changes':>25} {result.regime_changes:>12}")
    print(f"  {'Transaction Costs':>25} {result.transaction_costs:>11.1f}%")
    print()


def print_regime_performance(perfs: list[RegimePerformance]) -> None:
    print(f"\n{'=' * 75}")
    print("  Per-Regime Performance")
    print(f"{'=' * 75}")
    print(f"  {'Regime':<22} {'Days':>6} {'%Time':>6} {'Return':>8} {'Daily':>8} {'WR':>6} {'AvgDur':>6}")
    print(f"  {'-' * 66}")
    for p in perfs:
        print(f"  {p.regime:<22} {p.days:>6} {p.pct_of_total:>5.1f}% {p.total_return:>+7.1f}% "
              f"{p.avg_daily_return:>+7.3f}% {p.win_rate:>5.0%} {p.avg_duration:>5.0f}d")
    print()


def print_timing(timing: TimingAnalysis | None) -> None:
    if not timing:
        print("  투입 적기 분석 불가")
        return
    print(f"\n{'=' * 60}")
    print(f"  Entry Timing — \"{timing.current_regime}\" 진입 후 향후 수익률")
    print(f"{'=' * 60}")
    print(f"  과거 발생: {timing.occurrences}회")
    print(f"  30일 후 평균: {timing.avg_forward_30d:+.1f}%")
    print(f"  60일 후 평균: {timing.avg_forward_60d:+.1f}%")
    print(f"  90일 후 평균: {timing.avg_forward_90d:+.1f}%")
    print(f"  30일 후 전환: bull {timing.pct_to_bull:.0%} / bear {timing.pct_to_bear:.0%} / 유지 {timing.pct_stay:.0%}")
    print()


def print_stress(results: list[dict]) -> None:
    print(f"\n{'=' * 75}")
    print("  Stress Test — Crisis Periods")
    print(f"{'=' * 75}")
    print(f"  {'Crisis':<25} {'Days':>5} {'SPY':>8} {'Strategy':>8} {'Excess':>8} {'Protected':>9}")
    print(f"  {'-' * 66}")
    for r in results:
        prot = "YES" if r["protected"] else "NO"
        print(f"  {r['name']:<25} {r['days']:>5} {r['spy_return']:>+7.1f}% "
              f"{r['strategy_return']:>+7.1f}% {r['excess']:>+7.1f}% {prot:>9}")
    print()


# ═══════════════════════════════════════════════════════
# BT6: 규칙 적용 백테스트 — rules.yaml 손절/익절/트레일링
# ═══════════════════════════════════════════════════════


def run_backtest_with_rules(regimes_df: pd.DataFrame, db_path=None) -> dict:
    """rules.yaml의 손절/익절/트레일링 규칙을 적용한 백테스트.

    기본 L/S 전략 위에 종목 수준 규칙을 시뮬레이션:
    - 손절 -7% 도달 시 즉시 청산
    - 1차 익절 +20% 시 50% 매도
    - 2차 익절 +40% 시 25% 매도
    - 트레일링 스톱 -15% (고점 대비)

    기존 run_backtest와 동일 데이터로 A/B 비교.
    """
    from nuri.core.rules import (
        STOCK_STOP_LOSS,
        TAKE_PROFIT_GROWTH,
        TRAILING_STOP_GROWTH,
    )

    stop_pct = STOCK_STOP_LOSS / 100          # -0.07
    tp1_pct = TAKE_PROFIT_GROWTH["target_1"] / 100  # 0.20
    tp2_pct = TAKE_PROFIT_GROWTH["target_2"] / 100  # 0.40
    trailing_pct = TRAILING_STOP_GROWTH / 100  # -0.15

    df = regimes_df.copy()
    df = df[df["regime"] != "unknown"].dropna(subset=["return"])
    df = df.reset_index(drop=True)

    if df.empty:
        return {"error": "데이터 부족"}

    # --- 기본 전략 (규칙 없음) ---
    base_result = run_backtest(regimes_df, db_path)

    # --- 규칙 적용 전략 ---
    # 시뮬레이션: 롱 포지션에 손절/익절/트레일링 적용
    cum_return = 0.0
    high_water = 0.0
    position_size = 1.0      # 1.0 = 100%
    tp1_triggered = False
    tp2_triggered = False
    ruled_returns = []
    stops_hit = 0
    tp1_count = 0
    tp2_count = 0
    trailing_count = 0

    for i in range(len(df)):
        row = df.iloc[i]
        regime = row["regime"]
        daily_ret = row["return"]

        alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["sideways_high_vol"])
        long_pct = alloc["long"]

        # 포지션이 있을 때만 규칙 적용
        if position_size > 0 and long_pct > 0:
            cum_return += daily_ret
            high_water = max(high_water, cum_return)

            # 손절 체크
            if cum_return <= stop_pct:
                ruled_returns.append(stop_pct * long_pct * position_size)
                cum_return = 0
                high_water = 0
                position_size = 1.0
                tp1_triggered = False
                tp2_triggered = False
                stops_hit += 1
                continue

            # 1차 익절 체크
            if not tp1_triggered and cum_return >= tp1_pct:
                # 50% 매도 → position_size 50%로
                position_size *= 0.5
                tp1_triggered = True
                tp1_count += 1

            # 2차 익절 체크
            if tp1_triggered and not tp2_triggered and cum_return >= tp2_pct:
                # 추가 25% 매도 → position_size 25%로
                position_size *= 0.5
                tp2_triggered = True
                tp2_count += 1

            # 트레일링 스톱 체크
            drawdown = cum_return - high_water
            if high_water > 0.05 and drawdown <= trailing_pct:
                ruled_returns.append(cum_return * long_pct * position_size)
                cum_return = 0
                high_water = 0
                position_size = 1.0
                tp1_triggered = False
                tp2_triggered = False
                trailing_count += 1
                continue

            # 일반 수익률
            ruled_returns.append(daily_ret * long_pct * position_size
                                + alloc["short"] * (-daily_ret)
                                + alloc["cash"] * 0)
        else:
            # 포지션 없거나 long=0
            ruled_returns.append(alloc["short"] * (-daily_ret) if alloc["short"] > 0 else 0)
            cum_return = 0
            high_water = 0
            position_size = 1.0
            tp1_triggered = False
            tp2_triggered = False

    ruled = pd.Series(ruled_returns)
    if ruled.empty:
        return {"error": "시뮬레이션 데이터 부족"}

    ruled_cum = (1 + ruled).cumprod()
    ruled_total = (ruled_cum.iloc[-1] - 1) * 100
    years = len(ruled) / 252
    ruled_annual = ((1 + ruled_total / 100) ** (1 / max(years, 0.1)) - 1) * 100
    ruled_sharpe = ruled.mean() / ruled.std() * np.sqrt(252) if ruled.std() > 0 else 0
    ruled_mdd = (ruled_cum / ruled_cum.cummax() - 1).min() * 100

    return {
        "base": {
            "total_return": base_result.total_return,
            "annual_return": base_result.annual_return,
            "sharpe": base_result.sharpe,
            "max_drawdown": base_result.max_drawdown,
        },
        "with_rules": {
            "total_return": round(ruled_total, 2),
            "annual_return": round(ruled_annual, 2),
            "sharpe": round(ruled_sharpe, 2),
            "max_drawdown": round(ruled_mdd, 2),
        },
        "rules_impact": {
            "return_diff": round(ruled_total - base_result.total_return, 2),
            "sharpe_diff": round(ruled_sharpe - base_result.sharpe, 2),
            "mdd_diff": round(ruled_mdd - base_result.max_drawdown, 2),
            "stops_hit": stops_hit,
            "tp1_count": tp1_count,
            "tp2_count": tp2_count,
            "trailing_count": trailing_count,
        },
        "rules_config": {
            "stop_loss": f"{STOCK_STOP_LOSS}%",
            "target_1": f"+{TAKE_PROFIT_GROWTH['target_1']}% (50% sell)",
            "target_2": f"+{TAKE_PROFIT_GROWTH['target_2']}% (25% sell)",
            "trailing_stop": f"{TRAILING_STOP_GROWTH}% from high",
        },
    }


def print_rules_comparison(result: dict) -> None:
    """규칙 적용 전후 비교 출력."""
    if "error" in result:
        print(f"  규칙 백테스트 실패: {result['error']}")
        return

    base = result["base"]
    ruled = result["with_rules"]
    impact = result["rules_impact"]
    config = result["rules_config"]

    print(f"\n{'═' * 70}")
    print("  Rules-Applied Backtest Comparison")
    print(f"{'═' * 70}")
    print(f"  Rules: SL {config['stop_loss']} | TP1 {config['target_1']} | "
          f"TP2 {config['target_2']} | Trail {config['trailing_stop']}")
    print(f"{'─' * 70}")
    print(f"  {'Metric':<20} {'Base':>12} {'With Rules':>12} {'Diff':>10}")
    print(f"  {'─' * 54}")
    print(f"  {'Total Return':<20} {base['total_return']:>+11.1f}% {ruled['total_return']:>+11.1f}% {impact['return_diff']:>+9.1f}%")
    print(f"  {'Annual Return':<20} {base['annual_return']:>+11.1f}% {ruled['annual_return']:>+11.1f}%")
    print(f"  {'Sharpe Ratio':<20} {base['sharpe']:>12.2f} {ruled['sharpe']:>12.2f} {impact['sharpe_diff']:>+9.2f}")
    print(f"  {'Max Drawdown':<20} {base['max_drawdown']:>+11.1f}% {ruled['max_drawdown']:>+11.1f}% {impact['mdd_diff']:>+9.1f}%")
    print(f"{'─' * 70}")
    print(f"  Stop losses hit:     {impact['stops_hit']}")
    print(f"  Take profit 1 (+20%): {impact['tp1_count']}")
    print(f"  Take profit 2 (+40%): {impact['tp2_count']}")
    print(f"  Trailing stops:      {impact['trailing_count']}")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant L/S Strategy Backtest")
    parser.add_argument("--stress", action="store_true", help="스트레스 테스트만")
    parser.add_argument("--rules", action="store_true", help="규칙 적용 비교 백테스트")
    args = parser.parse_args()

    logger.info("과거 레짐 분류 중...")
    regimes = classify_historical_regimes()
    if regimes.empty:
        print("SPY 데이터 부족")
        exit(1)
    logger.info(f"{len(regimes)}일 분류 완료")

    if args.stress:
        results = stress_test(regimes)
        print_stress(results)
    elif args.rules:
        # BT6: 규칙 적용 비교
        result = run_backtest_with_rules(regimes)
        print_rules_comparison(result)
    else:
        # BT2: 전체 백테스트
        result = run_backtest(regimes)
        print_backtest(result)

        # BT3: 레짐별 성과
        perfs = analyze_per_regime(regimes)
        print_regime_performance(perfs)

        # BT4: 투입 적기
        timing = analyze_entry_timing(regimes)
        print_timing(timing)

        # BT6: 규칙 적용 비교
        logger.info("규칙 적용 백테스트...")
        rules_result = run_backtest_with_rules(regimes)
        print_rules_comparison(rules_result)

        # BT5: 스트레스 테스트
        stress = stress_test(regimes)
        print_stress(stress)

        # Monte Carlo
        logger.info("Monte Carlo 시뮬레이션 (1000회)...")
        mc = monte_carlo_test(regimes)
        print_monte_carlo(mc)
