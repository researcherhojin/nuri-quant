# pyright: reportAttributeAccessIssue=false
"""
ETF 자금흐름 수집기 — 섹터 ETF AUM/거래량 추적.

(OpenBB BaseApp 동적 attribute (etf 등) stub 부재 — runtime 정상.)

OpenBB etf.info primary + yfinance `Ticker.info` fallback → total_assets, volume_avg,
nav_price. OpenBB 상류 bug (#274, upstream #7379/#7460) 동안 yfinance 로 자동 수집.

AUM 변화를 주기적으로 수집하여 섹터 자금흐름(rotation)을 추정한다.

사용법:
    python -m nuri.collectors.etf_flows
"""

import logging
from typing import Any

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query_df

logger = logging.getLogger(__name__)

# 11 SPDR 섹터 ETF + 주요 지수 ETF
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financial",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrial",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

INDEX_ETFS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "EFA": "EAFE (International)",
    "EEM": "Emerging Markets",
}

ALL_ETFS = {**SECTOR_ETFS, **INDEX_ETFS}


class EtfFlowsCollector(BaseCollector):
    """섹터/지수 ETF AUM 추적 수집기."""

    def __init__(self):
        super().__init__("etf_flows")

    def collect(self, **kwargs) -> list[dict]:
        """ETF 정보 수집. OpenBB etf.info primary + yfinance `Ticker.info` fallback."""
        import warnings

        from tqdm import tqdm

        warnings.filterwarnings("ignore")

        from nuri.core.timezone import today_kst

        today = today_kst()
        results = []
        failed: list[str] = []

        etfs_list = list(ALL_ETFS.items())
        self.logger.info(f"ETF 정보 수집: {len(etfs_list)}개")
        iterator = tqdm(etfs_list, desc="  etf_flows", unit="etf", disable=len(etfs_list) < 10)

        for ticker, label in iterator:
            rec = self._fetch_etf(ticker, label, today)
            if rec is None:
                failed.append(ticker)
                continue
            results.append(rec)
            if len(etfs_list) < 10 and rec.get("total_assets"):
                self.logger.info(f"  {ticker} ({label}): AUM=${rec['total_assets'] / 1e9:.1f}B")

        sample = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
        self.logger.info(
            "📊 ETF flows: ✅ %d 성공 / ❌ %d 실패 (총 %d) — failed: %s",
            len(results),
            len(failed),
            len(etfs_list),
            sample or "없음",
        )
        return results

    def _fetch_etf(self, ticker: str, label: str, today: str) -> dict | None:
        """단일 ETF 정보. OpenBB → yfinance 직접 폴백."""
        # 1차: OpenBB
        try:
            from openbb import obb

            r = obb.etf.info(ticker, provider="yfinance")
            df = r.to_df()
            if not df.empty:
                row = df.iloc[0]
                return {
                    "ticker": ticker,
                    "date": today,
                    "name": str(row.get("name", label))[:100],
                    "total_assets": float(row["total_assets"]) if pd.notna(row.get("total_assets")) else None,
                    "volume_avg": float(row["volume_avg"]) if pd.notna(row.get("volume_avg")) else None,
                    "nav_price": float(row["nav_price"]) if pd.notna(row.get("nav_price")) else None,
                }
        except Exception as e:
            self.logger.debug(f"{ticker}: OpenBB etf.info 실패 — {e}")

        # 2차: yfinance 직접 호출 (OpenBB 장애 시 폴백)
        try:
            import yfinance as yf

            info = yf.Ticker(ticker).info or {}
            if not info:
                return None

            name = info.get("longName") or info.get("shortName") or label
            total_assets = info.get("totalAssets")

            # total_assets 가 없는 row 는 failed 처리: analyze_sector_rotation 이
            # `aum_current - aum_prev` 를 수행하는데 한쪽이 None 이면 TypeError → 분석 전체 실패.
            if not pd.notna(total_assets):
                return None

            # yfinance .info 의 missing 필드는 float('nan') 으로 자주 반환되어 Python `or`
            # 가 truthy 로 취급한다 (nan 은 0 이 아님). secondary 필드로 fallback 하려면
            # pd.notna 로 명시적 NaN/None 체크 후 선택해야 한다.
            av_primary = info.get("averageVolume")
            volume_avg = av_primary if pd.notna(av_primary) else info.get("averageVolume10days")

            nav_primary = info.get("navPrice")
            nav_price = nav_primary if pd.notna(nav_primary) else info.get("regularMarketPrice")

            # NaN → None 정규화: volume_avg / nav_price 는 downstream 에서 None 허용.
            return {
                "ticker": ticker,
                "date": today,
                "name": str(name)[:100],
                "total_assets": float(total_assets),
                "volume_avg": float(volume_avg) if pd.notna(volume_avg) else None,
                "nav_price": float(nav_price) if pd.notna(nav_price) else None,
            }
        except Exception as e:
            self.logger.debug(f"{ticker}: yfinance etf info 폴백 실패 — {e}")
            return None

    def save(self, data: Any) -> int:
        """etf_flows 테이블에 upsert."""
        if not data:
            return 0
        return _upsert_etf_flows(data)


def _upsert_etf_flows(records: list[dict], db_path=None) -> int:
    """etf_flows 테이블에 upsert."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO etf_flows
               (ticker, date, name, total_assets, volume_avg, nav_price)
               VALUES (:ticker, :date, :name, :total_assets, :volume_avg, :nav_price)""",
            records,
        )
        return len(records)


def analyze_sector_rotation(days: int = 30, db_path=None) -> pd.DataFrame | None:
    """섹터 ETF AUM 변화로 자금흐름 분석.

    Returns:
        DataFrame with columns: ticker, sector, aum_current, aum_prev,
                                 aum_change_pct, volume_trend
    """
    df = query_df(
        """SELECT ticker, date, total_assets, volume_avg, nav_price
           FROM etf_flows
           WHERE ticker IN ({})
           ORDER BY ticker, date""".format(",".join(f"'{t}'" for t in SECTOR_ETFS)),
        db_path=db_path,
    )

    if df.empty or len(df["date"].unique()) < 2:
        logger.warning("섹터 로테이션 분석 불가: 최소 2일 이상의 데이터 필요")
        return None

    results = []
    for ticker in SECTOR_ETFS:
        tdf = df[df["ticker"] == ticker].sort_values("date")
        if len(tdf) < 2:
            continue

        latest = tdf.iloc[-1]
        earliest = tdf.iloc[0]

        aum_current = latest["total_assets"]
        aum_prev = earliest["total_assets"]

        if aum_prev and aum_prev > 0:
            aum_change_pct = (aum_current - aum_prev) / aum_prev * 100
        else:
            aum_change_pct = 0.0

        # 거래량 트렌드 (최근 vs 이전)
        if len(tdf) >= 4:
            mid = len(tdf) // 2
            vol_recent = tdf.iloc[mid:]["volume_avg"].mean()
            vol_earlier = tdf.iloc[:mid]["volume_avg"].mean()
            vol_trend = (vol_recent - vol_earlier) / vol_earlier * 100 if vol_earlier > 0 else 0.0
        else:
            vol_trend = 0.0

        results.append(
            {
                "ticker": ticker,
                "sector": SECTOR_ETFS[ticker],
                "aum_current": aum_current,
                "aum_prev": aum_prev,
                "aum_change_pct": round(aum_change_pct, 2),
                "volume_trend_pct": round(vol_trend, 2),
            }
        )

    if not results:
        return None

    result_df = pd.DataFrame(results).sort_values("aum_change_pct", ascending=False)
    return result_df


def print_sector_rotation(df: pd.DataFrame | None) -> None:
    """섹터 로테이션 CLI 출력."""
    if df is None or df.empty:
        print("섹터 로테이션 데이터 없음 (최소 2일 이상 수집 필요)")
        return

    print(f"\n{'=' * 65}")
    print("  섹터 ETF 자금흐름 (AUM 변화)")
    print(f"{'=' * 65}")
    print(f"  {'ETF':<6} {'섹터':<25} {'AUM($B)':>10} {'AUM변화':>10} {'거래량추세':>10}")
    print(f"  {'-' * 60}")

    for _, row in df.iterrows():
        aum_b = row["aum_current"] / 1e9 if row["aum_current"] else 0
        print(
            f"  {row['ticker']:<6} {row['sector']:<25} "
            f"{aum_b:>9.1f} {row['aum_change_pct']:>+9.1f}% {row['volume_trend_pct']:>+9.1f}%"
        )
    print()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    collector = EtfFlowsCollector()
    collector.run()

    # 분석 (데이터가 2일 이상 쌓이면)
    result = analyze_sector_rotation()
    print_sector_rotation(result)
