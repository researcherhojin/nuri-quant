# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
"""
매크로 지표 수집기 — FRED API + yfinance fallback.

(yfinance.download None-or-DataFrame, pandas Hashable.strftime stub — runtime 정상.)

FRED_API_KEY가 있으면 FRED 우선, 없으면 yfinance에서 핵심 지표를 직접 수집.

사용법:
    python -m nuri.collectors.macro
"""
import logging
import os
from datetime import timedelta

import pandas as pd
from dotenv import load_dotenv

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_macro
from nuri.core.timezone import kst_now

load_dotenv()

# FRED 시리즈 ID 매핑 (확장: 풀 수익률 곡선 + 경제 지표 + crash precursor)
FRED_SERIES = {
    # 기존
    "fed_funds_rate": "FEDFUNDS",
    "cpi_yoy": "CPIAUCSL",
    "wti_oil": "DCOILWTICO",
    "usd_krw": "DEXKOUS",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
    # 풀 수익률 곡선 (리서치: 3M-10Y 스프레드가 2Y-10Y보다 경기침체 예측력 높음)
    "us_3m_yield": "DGS3MO",     # 3-Month Treasury
    "us_1y_yield": "DGS1",       # 1-Year
    "us_2y_yield": "DGS2",       # 2-Year
    "us_5y_yield": "DGS5",       # 5-Year
    "us_10y_yield": "DGS10",     # 10-Year
    "us_30y_yield": "DGS30",     # 30-Year
    # 추가 경제 지표
    "consumer_sentiment": "UMCSENT",  # 미시건대 소비자 심리
    "ism_manufacturing": "MANEMP",    # ISM 제조업 고용
    # PR C (codex bubble-bear #3): crash precursor data.
    # BofA US High Yield Option-Adjusted Spread — 신용 스트레스 조기 신호.
    # Gilchrist-Zakrajsek 2012: HY OAS > 500bps + 63d 변화 > +150bps 경기침체 경고.
    # 1997 년부터 daily 공개, FRED_API_KEY 필수 (yfinance fallback 없음).
    "hy_oas": "BAMLH0A0HYM2",
}

# yfinance fallback 심볼 매핑 (FRED 없을 때 사용)
YFINANCE_SYMBOLS = {
    "us_10y_yield": "^TNX",      # 10Y Treasury Yield
    "us_2y_yield": "^IRX",       # 13-week T-Bill (2Y proxy)
    "us_5y_yield": "^FVX",       # 5Y Treasury Yield
    "us_30y_yield": "^TYX",      # 30Y Treasury Yield
    "vix": "^VIX",               # CBOE VIX
    "wti_oil": "CL=F",           # WTI Crude Oil Futures
    "usd_krw": "KRW=X",          # USD/KRW
    # btc_usd는 CoinGecko collector에서 전담 (btc_usd_cg)
    "gold": "GC=F",              # Gold Futures (안전자산)
    # 추가 지표 (#362 Part A, 2026-04-28 live probe 9/10 + DXY 대체 symbol)
    # 지수 — regime classifier + macro agent breadth 지표
    "nasdaq_composite": "^IXIC",   # NASDAQ Composite (tech breadth)
    "sp500": "^GSPC",              # S&P 500 (broad US market — SPY 와 별도 index 직접 추적)
    "dow": "^DJI",                 # Dow Jones (blue-chip 30)
    "nasdaq100_futures": "NQ=F",   # NASDAQ 100 Futures (after-hours sentiment)
    "sox": "^SOX",                 # Philadelphia Semiconductor (KR 반도체 spillover proxy)
    # 환율 — DX=F yfinance 미제공 (live probe), DX-Y.NYB ICE Dollar Index 채택
    "dxy": "DX-Y.NYB",             # ICE U.S. Dollar Index (USD strength)
    # 원자재 — gold/wti 외 산업/안전자산 polish
    "silver": "SI=F",              # Silver Futures
    "natgas": "NG=F",              # Natural Gas Futures
    "copper": "HG=F",              # Copper Futures (industrial demand barometer)
    "wheat": "ZW=F",               # Wheat Futures (food inflation)
}


class MacroCollector(BaseCollector):
    """매크로 지표 수집 (FRED + yfinance fallback)."""

    def __init__(self):
        super().__init__("macro")
        self.api_key = os.getenv("FRED_API_KEY", "")

    def collect(self, days: int = 365, **kwargs) -> list[dict]:
        """매크로 지표 수집 — FRED 우선 + yfinance 보충 (#362 codex Review P1).

        Pre-#362 동작: FRED 결과 1건이라도 있으면 즉시 return → yfinance 분기 stub.
        결과적으로 FRED_API_KEY 환경에서는 yfinance-only indicator (^IXIC, ^GSPC,
        DX-Y.NYB 등 #362 Part A 10개 + Part B 향후 ECOS missing 도) 가 영구 미수집.

        Fix: 두 source 모두 호출 후 indicator 단위로 merge — FRED 우선, FRED 에
        없는 key 는 yfinance 보충. legacy 8 indicator 는 FRED 가 채우면 yfinance
        를 무시 (per-row dup 방지).
        """
        fred_records: list[dict] = []
        if self.api_key and self.api_key != "your_fred_api_key_here":
            fred_records = self._collect_fred(days)

        # FRED 가 비었으면 legacy 경로 — yfinance only.
        if not fred_records:
            self.logger.info("FRED 미사용 → yfinance fallback으로 매크로 수집")
            return self._collect_yfinance(days)

        # FRED + yfinance merge — yfinance-only indicator 보충.
        yf_records = self._collect_yfinance(days)
        fred_indicators = {r["indicator"] for r in fred_records}
        yf_supplement = [r for r in yf_records if r["indicator"] not in fred_indicators]
        if yf_supplement:
            yf_only_keys = sorted({r["indicator"] for r in yf_supplement})
            self.logger.info(
                "FRED + yfinance merge — FRED 외 yfinance-only %d개 보충: %s",
                len(yf_only_keys), yf_only_keys,
            )
        return fred_records + yf_supplement

    def _collect_fred(self, days: int) -> list[dict]:
        """FRED API에서 매크로 지표 수집."""
        from fredapi import Fred

        fred = Fred(api_key=self.api_key)
        start_date = (kst_now().replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")

        records = []
        for indicator, series_id in FRED_SERIES.items():
            try:
                series = fred.get_series(series_id, observation_start=start_date)
                for date, value in series.dropna().items():
                    records.append({
                        "indicator": indicator,
                        "date": date.strftime("%Y-%m-%d"),
                        "value": float(value),
                        "source": "FRED",
                    })
            except Exception as e:
                self.logger.warning(f"{indicator} ({series_id}): FRED 수집 실패 — {e}")

        return records

    def _collect_yfinance(self, days: int) -> list[dict]:
        """yfinance에서 직접 매크로 지표 수집 (API 키 불필요)."""
        import warnings

        import yfinance as yf
        warnings.filterwarnings("ignore")

        start = (kst_now().replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")
        records = []

        for indicator, symbol in YFINANCE_SYMBOLS.items():
            try:
                raw = yf.download(symbol, start=start, progress=False)
                if raw.empty:
                    continue

                df = raw.reset_index()
                # MultiIndex 컬럼 처리
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df.columns = [c.lower() for c in df.columns]
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

                for _, row in df.iterrows():
                    value = row.get("close")
                    if pd.isna(value):
                        continue

                    # ^TNX는 수익률을 10배로 반환 → 보정 불필요 (이미 %)
                    # KRW=X는 1 USD = X KRW → 역수 필요 없음
                    records.append({
                        "indicator": indicator,
                        "date": row["date"],
                        "value": float(value),
                        "source": "yfinance",
                    })

                self.logger.info(f"  {indicator} ({symbol}): {len(df)}건")
            except Exception as e:
                self.logger.warning(f"{indicator} ({symbol}): yfinance 수집 실패 — {e}")

        return records

    def save(self, data: list[dict]) -> int:
        return upsert_macro(data)


def main(argv: list[str] | None = None) -> int:
    """CLI entry — --days N 으로 backfill 기간 조정."""
    import argparse

    parser = argparse.ArgumentParser(description="Macro indicator collector (FRED + yfinance)")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="수집 기간 (일). PR C (codex #3): 5Y backfill 은 --days 1825",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = MacroCollector()
    # BaseCollector.run 은 collect() 에 kwargs 전달 — collect(days=...) 로 흐름.
    collector.run(days=args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
