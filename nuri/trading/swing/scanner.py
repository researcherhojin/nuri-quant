# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportOptionalOperand=false
"""
시장 스캐너 — 전체 유니버스에서 스윙 트레이드 후보 탐색.

`prices` 테이블에서 수백 종목을 읽어 스캔 — 네트워크를 타지 않는다 (#1119).
거래량 급증, 모멘텀, 기술적 브레이크아웃 3중 필터.

Universe는 config/universe.yaml에서 로드 (외부화).
폴백: hardcoded list.

사용법:
    python -m nuri.trading.swing.scanner                     # us core (85종목, 0.17초)
    python -m nuri.trading.swing.scanner --market kr         # kr kospi200 (203종목, 0.21초)
    python -m nuri.trading.swing.scanner --extended          # us core + sp500 ext (543종목, 0.74초)
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 스캔 유니버스 — config/universe.yaml에서 로드
# ═══════════════════════════════════════════════════════

# Fallback hardcoded lists (config 파일 누락/오류 시)
_FALLBACK_US_CORE = [
    "AAPL",
    "MSFT",
    "GOOG",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "AMD",
    "AVGO",
    "INTC",
    "QCOM",
    "ORCL",
    "CRM",
    "ADBE",
    "NFLX",
    "JPM",
    "BAC",
    "GS",
    "V",
    "MA",
    "BRK-B",
    "JNJ",
    "PFE",
    "LLY",
    "UNH",
    "MRK",
    "ABBV",
    "XOM",
    "CVX",
    "KO",
    "PEP",
    "WMT",
    "PG",
    "HD",
    "COST",
    "PLTR",
    "RKLB",
    "IONQ",
    "OKLO",
    "SOFI",
    "ARM",
    "SMCI",
    "MSTR",
    "NBIS",
    "PL",
    "TEM",
    "SPY",
    "QQQ",
    "IWM",
    "ARKK",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
]

_FALLBACK_KR_KOSPI200 = [
    "005930.KS",
    "000660.KS",
    "373220.KS",
    "207940.KS",
    "005380.KS",
    "006400.KS",
    "035420.KS",
    "000270.KS",
    "068270.KS",
    "028260.KS",
    "105560.KS",
    "055550.KS",
    "066570.KS",
    "003670.KS",
    "034730.KS",
    "138930.KS",
    "012330.KS",
    "096770.KS",
    "051910.KS",
    "003550.KS",
]


def _load_universe(group_keys: list[str]) -> list[str]:
    """config/universe.yaml에서 종목 목록 로드.

    Args:
        group_keys: 합칠 그룹 이름 리스트 (예: ["us_core", "us_sp500_extended"])

    Returns:
        중복 제거된 종목 리스트
    """
    import yaml

    config_path = Path(__file__).parent.parent.parent.parent / "config" / "universe.yaml"
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"{config_path} 없음 — fallback 사용")
        return []
    except Exception as e:
        logger.error(f"universe.yaml 로드 실패: {e} — fallback 사용")
        return []

    seen: set[str] = set()
    result: list[str] = []
    for key in group_keys:
        group = config.get(key)
        if not group:
            logger.warning(f"universe.yaml에 {key} 그룹 없음")
            continue
        for ticker in group.get("tickers", []):
            # YAML 1.1이 ON/OFF/YES/NO를 bool로 변환하는 것을 방어
            if not isinstance(ticker, str):
                logger.warning(f"non-string ticker 무시: {ticker!r} ({key})")
                continue
            if ticker and ticker not in seen:
                seen.add(ticker)
                result.append(ticker)
    return result


def get_us_universe(extended: bool = False) -> list[str]:
    """미국 universe 반환. extended=True면 S&P 500 확장."""
    keys = ["us_core", "us_sp500_extended"] if extended else ["us_core"]
    universe = _load_universe(keys)
    if not universe:
        return list(_FALLBACK_US_CORE)
    return universe


def get_kr_universe() -> list[str]:
    """한국 universe 반환 (KOSPI 200)."""
    universe = _load_universe(["kr_kospi200"])
    if not universe:
        return list(_FALLBACK_KR_KOSPI200)
    return universe


# Backward compat (deprecated — use get_us_universe / get_kr_universe)
US_UNIVERSE = _FALLBACK_US_CORE
KR_UNIVERSE = _FALLBACK_KR_KOSPI200


@dataclass
class ScanResult:
    """스캔 결과."""

    ticker: str
    price: float
    change_1d: float  # 전일 대비 수익률 (%)
    change_5d: float  # 5일 수익률 (%)
    volume_ratio: float  # 거래량 / 20일 평균 (배수)
    rsi: float
    bb_position: float  # 0=하단, 0.5=중간, 1=상단 이탈
    signal: str  # "volume_spike", "momentum", "breakout", "bounce"
    score: float  # 종합 점수 (높을수록 후보)


def _fetch_prices(tickers: list[str], days: int = 60, db_path=None) -> pd.DataFrame | None:
    """`prices` 테이블에서 최근 `days` 거래일을 읽어 yfinance batch 와 같은 모양으로 만든다.

    예전에는 `yf.download(tickers, period=...)` 였다. 그건 **요청 핸들러 안에서 도는
    외부 네트워크 호출**이라 `/api/scan` 이 매 요청 야후를 쳤고(실측 1.7초, 캐시 없음),
    동기 핸들러가 AnyIO 40-스레드 풀을 그만큼 오래 점유했다 (#1119). `nuri/api/CLAUDE.md`
    가 스스로 적어둔 계약 — *this layer queries and renders, it never computes strategy* —
    에도 어긋났다.

    수집기가 이미 같은 데이터를 `prices` 에 넣는다. 실측(2026-08-21): 스캔 유니버스
    US 85/85 · KR 202/203 종목이 60거래일 이상 보유(중앙값 1,298행), OHLCV 완비.
    미달 종목은 프레임에서 빠지고 `_analyze_ticker` 가 None 으로 흘린다.

    반환 모양은 바뀌지 않는다 — `_analyze_ticker` 가 `data[ticker]["Close"]` 로 읽으므로
    (ticker, field) MultiIndex 컬럼을 유지한다. 값은 이제 **마지막 수집 종가**다.
    """
    from nuri.core.db import query_df

    if not tickers:
        return None
    placeholders = ",".join("?" * len(tickers))
    df = query_df(
        f"SELECT ticker, date, close, volume FROM prices WHERE ticker IN ({placeholders}) ORDER BY date",  # noqa: S608 — placeholders 는 ? 만
        tuple(tickers),
        db_path=db_path,
    )
    if df is None or df.empty:
        logger.error("prices 조회 결과 없음 — 수집이 돌았는지 확인 (make collect)")
        return None

    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="ticker", values=["close", "volume"])
    # (field, ticker) → (ticker, field) 로 뒤집고 yfinance 컬럼명에 맞춘다
    wide.columns = pd.MultiIndex.from_tuples(
        [(tkr, {"close": "Close", "volume": "Volume"}[field]) for field, tkr in wide.columns]
    )
    wide = wide.sort_index().tail(days)
    return wide if not wide.empty else None


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


def scan_market(market: str = "us", top_n: int = 20, extended: bool = False) -> list[ScanResult]:
    """시장 스캔 → 상위 N개 후보 반환.

    Args:
        market: "us" 또는 "kr"
        top_n: 상위 N개 결과 반환
        extended: True면 us_sp500_extended 포함 (us만 적용)
    """
    if market == "us":
        universe = get_us_universe(extended=extended)
    else:
        universe = get_kr_universe()
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
    print(
        f"  {'Ticker':<8} {'Price':>10} {'1D':>7} {'5D':>7} {'VolRatio':>8} {'RSI':>5} {'BB':>5} {'Signal':<14} {'Score':>6}"
    )
    print(f"  {'-' * 82}")

    for r in results:
        print(
            f"  {r.ticker:<8} ${r.price:>9,.2f} {r.change_1d:>+6.1f}% {r.change_5d:>+6.1f}% "
            f"{r.volume_ratio:>7.1f}x {r.rsi:>5.0f} {r.bb_position:>4.2f} {r.signal:<14} {r.score:>5.0f}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entry — argparse + 오케스트레이션 (testable)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Market Scanner")
    parser.add_argument("--market", choices=["us", "kr"], default="us")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--extended", action="store_true", help="us_sp500_extended 포함 (us만 적용)")
    args = parser.parse_args(argv)

    results = scan_market(market=args.market, top_n=args.top, extended=args.extended)
    print_scan(results)
    return 0


if __name__ == "__main__":  # pragma: no cover  # invariant: 표준 entry idiom — main() 이 testable
    raise SystemExit(main())
