#!/usr/bin/env python3
"""E3-3 Stage 2 prerequisite — backfill VIX 5Y + prices 5Y for frozen universe.

STRATEGY §3.6 Stage 2 (paired counterfactual main hard gate) requires:
- VIX 5Y history (current 1Y is binding constraint for regime classify)
- Frozen universe with 5Y prices (current ~17 tickers too narrow for N≥200)

Frozen universe (codex Plan consult — survivorship-bias defense):
- Use `config/universe.yaml us_core.tickers` (85 tickers, today's curated list)
- **Known limitation**: today's us_core embeds survivorship — tickers delisted
  during 2021-2026 are not present. Documented in Stage 2 report as caveat.
  Affects magnitude of paired delta but not directional signal (codex framing).
- 50-100 ticker target band per codex; us_core 85 fits.

Idempotent — yfinance refetch + upsert_prices/upsert_macro UNIQUE constraints
make re-runs safe. Existing rows updated in place.

사용:
    .venv/bin/python scripts/e3_3_backfill.py [--dry-run] [--vix-only] [--prices-only]
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
import yaml

from nuri.collectors.stock import StockCollector
from nuri.core.db import query, upsert_macro, upsert_prices
from nuri.core.timezone import today_kst

LOG = logging.getLogger("e3_3_backfill")

VIX_PERIOD_5Y = "5y"  # codex PR400-round1 — semantic period (provider-stable vs "1825d")
PRICES_PERIOD_5Y = "5y"
UNIVERSE_KEY = "us_core"  # codex Plan consult — frozen subset


def _load_frozen_universe() -> list[str]:
    """`config/universe.yaml us_core.tickers` 로드. 85개 (2026-04-19 기준)."""
    path = Path("config/universe.yaml")
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — repo root 에서 실행해야 함")
    with path.open() as f:
        u = yaml.safe_load(f) or {}
    section = u.get(UNIVERSE_KEY) or {}
    tickers = section.get("tickers") or []
    if not tickers:
        raise RuntimeError(f"{UNIVERSE_KEY}.tickers empty — universe.yaml drift?")
    return sorted(tickers)


def backfill_vix(dry_run: bool = False) -> int:
    """yfinance ^VIX 5Y 수집 → upsert_macro. 반환: upsert 수."""
    import warnings

    import yfinance as yf
    warnings.filterwarnings("ignore")

    LOG.info("📈 VIX 5Y backfill (^VIX)")
    raw = yf.download("^VIX", period=VIX_PERIOD_5Y, progress=False)
    if raw.empty:
        LOG.error("VIX yfinance fetch empty — network 또는 ticker symbol issue")
        return 0

    df = raw.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    records = [
        {"indicator": "vix", "date": row["date"], "value": float(row["close"]), "source": "yfinance"}
        for _, row in df.iterrows()
        if not pd.isna(row.get("close"))
    ]
    LOG.info(f"  fetched {len(records)} rows ({records[0]['date']} ~ {records[-1]['date']})")

    if dry_run:
        LOG.info("  [dry-run] skipping upsert_macro")
        return len(records)

    n = upsert_macro(records)
    LOG.info(f"  ✅ upserted {n} rows to macro table")
    return n


def backfill_prices(tickers: list[str], dry_run: bool = False) -> tuple[int, int, list[str]]:
    """frozen universe 의 각 ticker → 5Y prices upsert. 반환: (성공, 실패, failed_list)."""
    collector = StockCollector()
    start_date = collector._period_to_start_date(PRICES_PERIOD_5Y)
    end_date = today_kst()  # codex PR400-round1 — repo timezone rule

    LOG.info(f"📊 Prices 5Y backfill — {len(tickers)} tickers ({start_date} ~ {end_date})")

    succeeded: list[str] = []
    failed: list[str] = []
    total_rows = 0

    # yfinance 10-thread parallel — collectors/stock.py 와 동일 패턴
    import concurrent.futures

    from tqdm import tqdm

    def _fetch_one(ticker: str):
        return ticker, collector._collect_ticker(ticker, start_date, end_date)

    # yfinance 로그 노이즈 억제 (delisted 티커는 정상 케이스)
    _yflog = logging.getLogger("yfinance")
    _orig = _yflog.level
    _yflog.setLevel(logging.CRITICAL)

    frames: list[pd.DataFrame] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_one, t): t for t in tickers}
            for fut in tqdm(concurrent.futures.as_completed(futures), total=len(tickers),
                            desc="  prices [e3_3]", unit="tk"):
                ticker = futures[fut]
                try:
                    _, df = fut.result(timeout=60)
                    if df is not None and not df.empty:
                        frames.append(df)
                        succeeded.append(ticker)
                        total_rows += len(df)
                    else:
                        failed.append(ticker)
                except Exception as e:
                    LOG.debug(f"{ticker}: {e}")
                    failed.append(ticker)
    finally:
        _yflog.setLevel(_orig)

    LOG.info(f"  fetched {len(succeeded)}/{len(tickers)} tickers, {total_rows} rows total")
    if failed:
        LOG.warning(f"  failed ({len(failed)}): {', '.join(failed[:10])}"
                    + (f" ... +{len(failed)-10} more" if len(failed) > 10 else ""))

    if dry_run:
        LOG.info("  [dry-run] skipping upsert_prices")
        return len(succeeded), len(failed), failed

    if frames:
        big = pd.concat(frames, ignore_index=True)
        n = upsert_prices(big)
        LOG.info(f"  ✅ upserted {n} price rows ({len(succeeded)} tickers)")
    return len(succeeded), len(failed), failed


def verify_post_backfill(tickers: list[str]) -> dict:
    """backfill 후 실제 DB coverage 재측정. CI / 다음 sub-task 의 input."""
    LOG.info("🔍 post-backfill verification")
    # VIX rows
    r = query("SELECT MIN(date) min_d, MAX(date) max_d, COUNT(*) n "
              "FROM macro WHERE indicator = 'vix'")
    vix_n, vix_min, vix_max = r[0]["n"], r[0]["min_d"], r[0]["max_d"]
    LOG.info(f"  VIX: {vix_n} rows, {vix_min} ~ {vix_max}")

    # 각 frozen ticker 의 row count + min_date
    placeholders = ",".join(["?"] * len(tickers))
    r = query(
        f"SELECT ticker, MIN(date) min_d, COUNT(*) n FROM prices "
        f"WHERE ticker IN ({placeholders}) GROUP BY ticker",
        tuple(tickers),
    )
    coverage = {row["ticker"]: {"n": row["n"], "min_d": row["min_d"]} for row in r}
    full_5y = sum(1 for v in coverage.values() if v["n"] >= 1000 and v["min_d"] <= "2021-04-30")
    missing = [t for t in tickers if t not in coverage]
    partial = [t for t, v in coverage.items() if v["n"] < 1000 or v["min_d"] > "2021-04-30"]
    LOG.info(f"  Prices: {full_5y}/{len(tickers)} tickers with 5Y coverage")
    if missing:
        LOG.warning(f"    missing ({len(missing)}): {', '.join(missing[:10])}")
    if partial:
        LOG.warning(f"    partial ({len(partial)}): {', '.join(partial[:10])}")

    return {
        "vix_rows": vix_n,
        "vix_range": (vix_min, vix_max),
        "tickers_full_5y": full_5y,
        "tickers_missing": missing,
        "tickers_partial": partial,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch만, DB 미반영")
    parser.add_argument("--vix-only", action="store_true")
    parser.add_argument("--prices-only", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    tickers = _load_frozen_universe()
    LOG.info(f"frozen universe ({UNIVERSE_KEY}): {len(tickers)} tickers")

    t0 = time.time()
    if not args.prices_only:
        backfill_vix(dry_run=args.dry_run)
    if not args.vix_only:
        backfill_prices(tickers, dry_run=args.dry_run)

    if not args.dry_run:
        verify_post_backfill(tickers)

    LOG.info(f"⏱  total {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
