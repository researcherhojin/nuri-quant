"""
시장 스캐너 — 전체 유니버스에서 스윙 트레이드 후보 탐색.

yfinance batch download로 수백 종목을 빠르게 스캔.
거래량 급증, 모멘텀, 기술적 브레이크아웃 3중 필터.

사용법:
    python -m nuri.trading.swing.scanner
    python -m nuri.trading.swing.scanner --market kr
"""
import argparse
import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 스캔 유니버스
# ═══════════════════════════════════════════════════════

# 미국: 유동성 높은 대형주 + 고성장 중소형주 100개
US_UNIVERSE = [
    # Mega cap
    "AAPL", "MSFT", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "UNH", "JPM", "V", "MA", "HD", "PG", "JNJ", "XOM", "CVX", "ABBV",
    "KO", "PEP", "MRK", "LLY", "AVGO", "COST", "WMT", "ADBE", "CRM",
    "NFLX", "AMD", "QCOM", "INTC", "BA", "CAT", "GS", "MS", "AXP",
    "DIS", "CMCSA", "VZ", "T", "NKE", "SBUX", "MCD", "LOW",
    # Growth / momentum
    "PLTR", "RKLB", "IONQ", "OKLO", "SOFI", "HOOD", "COIN", "UBER",
    "ABNB", "RIVN", "NIO", "SNAP", "ROKU", "DKNG", "MARA",
    "ARM", "SMCI", "MSTR", "APP", "DUOL", "HIMS", "RDDT",
    "CRWD", "PANW", "ZS", "NET", "DDOG", "MDB", "SNOW",
    # ETF
    "SPY", "QQQ", "IWM", "ARKK", "XLK", "XLF", "XLE", "XLV",
    # 사용자 보유종목 (이미 prices에 있음)
    "TSLL", "BULL", "FIG", "VOO", "TEM", "NBIS", "PL", "LLY",
]

# 한국: KOSPI/KOSDAQ 시가총액 상위
KR_UNIVERSE = [
    "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS",
    "006400.KS", "035420.KS", "000270.KS", "068270.KS", "028260.KS",
    "105560.KS", "055550.KS", "066570.KS", "003670.KS", "034730.KS",
    "138930.KS", "012330.KS", "096770.KS", "051910.KS", "003550.KS",
]


@dataclass
class ScanResult:
    """스캔 결과."""
    ticker: str
    price: float
    change_1d: float        # 전일 대비 수익률 (%)
    change_5d: float        # 5일 수익률 (%)
    volume_ratio: float     # 거래량 / 20일 평균 (배수)
    rsi: float
    bb_position: float      # 0=하단, 0.5=중간, 1=상단 이탈
    signal: str             # "volume_spike", "momentum", "breakout", "bounce"
    score: float            # 종합 점수 (높을수록 후보)


def _fetch_prices(tickers: list[str], days: int = 60) -> pd.DataFrame | None:
    """yfinance batch download."""
    import yfinance as yf
    try:
        df = yf.download(tickers, period=f"{days}d", group_by="ticker", progress=False)
        if df.empty:
            return None
        return df
    except Exception as e:
        logger.error(f"yfinance download 실패: {e}")
        return None


def _analyze_ticker(ticker: str, data: pd.DataFrame) -> ScanResult | None:
    """단일 종목 기술적 분석."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker not in data.columns.get_level_values(0):
                return None
            close = data[ticker]["Close"].dropna()
            volume = data[ticker]["Volume"].dropna()
        else:
            close = data["Close"].dropna()
            volume = data["Volume"].dropna()

        if len(close) < 20:
            return None

        price = float(close.iloc[-1])
        if price <= 0:
            return None

        # 수익률
        change_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) >= 2 else 0
        change_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0

        # 거래량 비율 (최근 / 20일 평균)
        vol_avg = volume.tail(20).mean()
        vol_ratio = float(volume.iloc[-1] / vol_avg) if vol_avg > 0 else 1.0

        # RSI 14
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if pd.notna(rs.iloc[-1]) else 50

        # BB position (0=하단, 1=상단)
        sma20 = close.rolling(20).mean().iloc[-1]
        std20 = close.rolling(20).std().iloc[-1]
        if std20 > 0:
            bb_pos = (price - (sma20 - 2 * std20)) / (4 * std20)
            bb_pos = max(0, min(1, bb_pos))
        else:
            bb_pos = 0.5

        # 시그널 분류
        signal = "none"
        score = 0

        # 거래량 급증 (2배 이상)
        if vol_ratio >= 2.0:
            signal = "volume_spike"
            score += vol_ratio * 10

        # 모멘텀 (5일 수익률 양호 + RSI 상승)
        if change_5d > 5 and rsi > 50:
            signal = "momentum" if signal == "none" else signal
            score += change_5d * 2

        # BB 하단 반등 (RSI 과매도 근처에서 반등)
        if bb_pos < 0.2 and change_1d > 0 and rsi < 40:
            signal = "bounce"
            score += (40 - rsi) + (1 - bb_pos) * 20

        # BB 상단 돌파 (브레이크아웃)
        if bb_pos > 0.95 and vol_ratio > 1.5:
            signal = "breakout"
            score += bb_pos * 20 + vol_ratio * 5

        if signal == "none":
            return None  # 시그널 없으면 제외

        return ScanResult(
            ticker=ticker,
            price=round(price, 2),
            change_1d=round(float(change_1d), 2),
            change_5d=round(float(change_5d), 2),
            volume_ratio=round(vol_ratio, 2),
            rsi=round(rsi, 1),
            bb_position=round(bb_pos, 3),
            signal=signal,
            score=round(score, 1),
        )
    except Exception as e:
        logger.debug(f"{ticker} 분석 실패: {e}")
        return None


def scan_market(market: str = "us", top_n: int = 20) -> list[ScanResult]:
    """시장 스캔 → 상위 N개 후보 반환."""
    raw_universe = US_UNIVERSE if market == "us" else KR_UNIVERSE
    # 중복 제거 (순서 유지)
    seen = set()
    universe = []
    for t in raw_universe:
        if t not in seen:
            seen.add(t)
            universe.append(t)
    logger.info(f"{market.upper()} 시장 스캔: {len(universe)}종목")

    data = _fetch_prices(universe)
    if data is None:
        logger.error("가격 데이터 수집 실패")
        return []

    results = []
    for ticker in universe:
        result = _analyze_ticker(ticker, data)
        if result:
            results.append(result)

    # score 내림차순
    results.sort(key=lambda r: r.score, reverse=True)
    logger.info(f"스캔 결과: {len(results)}건 시그널, 상위 {top_n}건 반환")
    return results[:top_n]


def print_scan(results: list[ScanResult]) -> None:
    if not results:
        print("스캔 결과 없음")
        return

    print(f"\n{'=' * 90}")
    print(f"  Market Scanner — {len(results)} candidates")
    print(f"{'=' * 90}")
    print(f"  {'Ticker':<8} {'Price':>10} {'1D':>7} {'5D':>7} {'VolRatio':>8} {'RSI':>5} {'BB':>5} {'Signal':<14} {'Score':>6}")
    print(f"  {'-' * 82}")

    for r in results:
        print(f"  {r.ticker:<8} ${r.price:>9,.2f} {r.change_1d:>+6.1f}% {r.change_5d:>+6.1f}% "
              f"{r.volume_ratio:>7.1f}x {r.rsi:>5.0f} {r.bb_position:>4.2f} {r.signal:<14} {r.score:>5.0f}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Market Scanner")
    parser.add_argument("--market", choices=["us", "kr"], default="us")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    results = scan_market(market=args.market, top_n=args.top)
    print_scan(results)
