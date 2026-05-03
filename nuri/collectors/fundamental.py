"""
펀더멘탈 데이터 수집기 — yfinance Ticker.info 기반.

PE, P/B, PEG, ROE, 마진, 성장률, 부채비율, 베타 등 16개 지표 수집.

이전 OpenBB equity.fundamental.metrics는 openbb-core 버전 충돌(`OBBject_EquityInfo`
import error)로 모든 종목 수집 실패. yfinance Ticker.info의 다음 필드를 직접
사용:
    marketCap, trailingPE, forwardPE, priceToBook, pegRatio,
    returnOnEquity, returnOnAssets, grossMargins, operatingMargins,
    profitMargins, revenueGrowth, earningsGrowth, debtToEquity,
    currentRatio, dividendYield, beta

사용법:
    python -m nuri.collectors.fundamental
"""

import logging
import math
from typing import Any

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)

# yfinance Ticker.info 필드 → DB 컬럼 매핑
YF_FIELDS = {
    "marketCap": "market_cap",
    "trailingPE": "pe_ratio",
    "forwardPE": "forward_pe",
    "priceToBook": "price_to_book",
    "pegRatio": "peg_ratio",
    "returnOnEquity": "roe",
    "returnOnAssets": "roa",
    "grossMargins": "gross_margin",
    "operatingMargins": "operating_margin",
    "profitMargins": "profit_margin",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "dividendYield": "dividend_yield",
    "dividendRate": "annual_dividend_usd",
    "beta": "beta",
}


def _safe_num(val) -> float | None:
    """yfinance dict 필드 → None 안전 float (NaN/Inf 방지)."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# KIS Open API inquire-price (FHKST01010100) 응답 필드 → fundamentals 컬럼 매핑.
# yfinance KR 한계 (#465): trailingPE / priceToBook 미제공 → KIS 공식 데이터로 보충.
# eps/bps/lstn_stcn 은 market_cap 계산에만 사용 (별도 컬럼 없음 — scope creep 회피, codex Plan).
KIS_FIELDS = {
    "per": "pe_ratio",  # KIS trailing P/E
    "pbr": "price_to_book",  # KIS P/B
}


def _kis_record_skeleton(ticker: str, today: str) -> dict:
    """모든 fundamentals 컬럼을 None 으로 초기화 — _upsert_fundamentals named binding 호환.

    KIS 가 채우지 않는 yfinance-only 컬럼 (forward_pe / roe / margin / growth 등) 은
    None 으로 명시적 채워야 sqlite3 NamedParam binding 에러 방지.
    """
    return {
        "ticker": ticker,
        "date": today,
        "market_cap": None,
        "pe_ratio": None,
        "forward_pe": None,
        "price_to_book": None,
        "peg_ratio": None,
        "roe": None,
        "roa": None,
        "gross_margin": None,
        "operating_margin": None,
        "profit_margin": None,
        "revenue_growth": None,
        "earnings_growth": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "dividend_yield": None,
        "beta": None,
        "annual_dividend_usd": None,
        "dividend_yield_pct": None,
    }


def _fetch_kis_kr(ticker: str, creds, token, today: str) -> dict | None:
    """KR 종목 KIS inquire-price 응답에서 fundamentals 추출.

    Returns record dict (yfinance shape 호환, missing columns = None) or None on failure.
    market_cap = stck_prpr × lstn_stcn 계산 (raw KIS 응답에 직접 없음).
    """
    import requests

    code = ticker.replace(".KS", "").replace(".KQ", "")
    url = f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": creds.app_key,
        "appsecret": creds.app_secret,
        "tr_id": "FHKST01010100",
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        output = resp.json().get("output", {})
        if not output or not output.get("stck_prpr"):
            return None

        record = _kis_record_skeleton(ticker, today)
        non_null = 0
        for src_field, db_field in KIS_FIELDS.items():
            val = _safe_num(output.get(src_field))
            if val == 0:  # KIS 가 미제공 종목 (예: 우선주) 은 0 → None 처리
                val = None
            record[db_field] = val
            if val is not None:
                non_null += 1

        # market_cap = 현재가 × 상장주식수 (KIS 가 직접 제공 안함)
        price = _safe_num(output.get("stck_prpr"))
        shares = _safe_num(output.get("lstn_stcn"))
        if price and shares:
            record["market_cap"] = price * shares
            non_null += 1

        if non_null == 0:
            return None
        return record
    except Exception:
        return None


class FundamentalCollector(BaseCollector):
    """yfinance Ticker.info로 펀더멘탈 데이터 수집."""

    def __init__(self):
        super().__init__("fundamental")

    def collect(self, source: str = "portfolio", **kwargs) -> list[dict]:
        """펀더멘탈 수집. source='universe' 시 S&P500/KOSPI200 전체 (#272 Phase 2b).

        KR 종목 (.KS/.KQ): KIS Open API inquire-price (FHKST01010100) 가 trailing PER/PBR
        직접 제공 — yfinance KR 한계 우회 (#465). KIS 자격 증명 부재 / 토큰 발급 실패 시
        기존 yfinance 경로로 graceful fallback (forward_pe / roe / margin / growth 만 채움).
        US 종목: yfinance 그대로.
        """
        import logging as _logging

        import yfinance as yf
        from tqdm import tqdm

        tickers = self._get_tickers(source=source)
        if not tickers:
            self.logger.warning("수집할 종목이 없습니다")
            return []

        # MAX_FAILURE_RATE(10%) 가드 활성화 — yfinance/KIS fail 누적 시 save 거부.
        # asymmetric data age 방지 (어제 row 그대로 + 오늘 70% 결손 silent save 차단).
        self._expected_count = len(tickers)

        self.logger.info(f"펀더멘탈 수집 대상: {len(tickers)}종목 (source={source})")
        from nuri.core.timezone import today_kst

        today = today_kst()
        results: list[dict] = []
        skipped: list[str] = []
        failed: list[str] = []

        # ── KR sub-batch: KIS inquire-price (sequential, rate-limited) ──
        # yfinance KR limit (trailingPE/priceToBook 미제공) 우회. KIS 실패 시 KR 도
        # yfinance fallback 으로 넘어가 forward_pe/roe/margin/growth 만이라도 채움.
        kr_tickers = [t for t in tickers if t.endswith((".KS", ".KQ"))]
        kis_by_ticker: dict[str, dict] = {}
        if kr_tickers:
            kis_results = self._collect_kr_via_kis(kr_tickers, today)
            kis_by_ticker = {r["ticker"]: r for r in kis_results}
            self.logger.info(
                "🇰🇷 KIS 펀더멘탈: ✅ %d / %d KR ticker (yfinance loop 가 ROE/margin/growth 보충)",
                len(kis_by_ticker),
                len(kr_tickers),
            )

        # ── 전체 sub-batch: yfinance 10-thread parallel ──
        # KIS 가 채운 KR 도 yfinance 한 번 더 돌려 ROE / revenue_growth / profit_margin /
        # debt_to_equity 같은 yfinance-only fields 보존 (codex Round 1 P1 fix).
        # KIS 의 pe_ratio/price_to_book/market_cap 은 merge 단계에서 우선 적용.
        yf_tickers = list(tickers)
        if not yf_tickers:
            results.extend(kis_by_ticker.values())
            return results

        # universe 모드: yfinance ERROR 노이즈 억제
        _yflog = _logging.getLogger("yfinance")
        _orig_level = _yflog.level
        if source != "portfolio":
            _yflog.setLevel(_logging.CRITICAL)

        # Parallel yfinance fetch — yfinance는 KRX와 달리 ~10 concurrent OK.
        # 순차 (746 × 0.4s) = 5분 → parallel 10 = 약 30-50초.
        import concurrent.futures

        def _fetch_one(ticker: str) -> tuple[str, dict | None, str]:
            """Returns (ticker, record_or_None, status). status: 'ok'|'skipped'|'failed'."""
            try:
                info = yf.Ticker(ticker).info
                if not info or "regularMarketPrice" not in info:
                    return ticker, None, "skipped"

                record: dict = {"ticker": ticker, "date": today}
                non_null = 0
                for src_field, db_field in YF_FIELDS.items():
                    val = _safe_num(info.get(src_field))
                    record[db_field] = val
                    if val is not None:
                        non_null += 1

                dy = record.get("dividend_yield")
                record["dividend_yield_pct"] = round(dy * 100, 2) if dy else None

                if non_null == 0:
                    return ticker, None, "skipped"
                return ticker, record, "ok"
            except Exception:
                return ticker, None, "failed"

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(_fetch_one, t): t for t in yf_tickers}
                iterator = tqdm(
                    concurrent.futures.as_completed(futures),
                    total=len(yf_tickers),
                    desc=f"  fundamentals [{source}]",
                    unit="tk",
                    disable=len(yf_tickers) < 20,
                )
                for fut in iterator:
                    ticker, record, status = fut.result()
                    if status == "ok" and record is not None:
                        results.append(record)
                    elif status == "skipped":
                        skipped.append(ticker)
                    else:
                        failed.append(ticker)
        finally:
            _yflog.setLevel(_orig_level)

        # ── KIS merge: KR ticker 의 KIS pe/pbr/market_cap 을 yfinance record 에 우선 적용 ──
        # codex Round 1 P1 — KR 가 yfinance loop 바이패스했을 때 ROE/margin/growth 손실
        # 회귀 차단. KIS 채운 columns 만 override, yfinance enrichment 보존.
        if kis_by_ticker:
            yf_seen = {r["ticker"] for r in results}
            for record in results:
                kis_data = kis_by_ticker.get(record["ticker"])
                if kis_data is None:
                    continue
                for col in ("pe_ratio", "price_to_book", "market_cap"):
                    val = kis_data.get(col)
                    if val is not None:
                        record[col] = val
            # yfinance 가 fail 한 KR ticker — KIS-only record 추가 (yfinance fallback)
            for ticker, kis_record in kis_by_ticker.items():
                if ticker not in yf_seen:
                    results.append(kis_record)

        if len(tickers) >= 20:
            sample_failed = ", ".join((failed + skipped)[:5]) + (
                f" 외 {len(failed) + len(skipped) - 5}개" if len(failed) + len(skipped) > 5 else ""
            )
            self.logger.info(
                "📊 펀더멘탈: ✅ %d 성공 / ⚠️  %d 데이터부족 / ❌ %d 실패 (총 %d) — issues: %s",
                len(results),
                len(skipped),
                len(failed),
                len(tickers),
                sample_failed or "없음",
            )

            # 필드별 N/A 분석 — 사용자 질문 응답: "N/A는 데이터 없는 거? 못 가져온 거?"
            # 답: 성공 ticker 안에서 None 비율을 측정 → 진짜 데이터 부재 vs API 한계 구분
            if results:
                self.logger.info("📋 필드별 coverage (성공 %d ticker 중 non-null 비율):", len(results))
                for db_field in ["pe_ratio", "forward_pe", "roe", "revenue_growth", "debt_to_equity", "dividend_yield"]:
                    non_null = sum(1 for r in results if r.get(db_field) is not None)
                    pct = non_null / len(results) * 100
                    flag = "✅" if pct >= 80 else "⚠️ " if pct >= 50 else "🔴"
                    self.logger.info(
                        "   %s %-20s %5.1f%% (%d/%d) — N/A 는 yfinance가 미제공",
                        flag,
                        db_field,
                        pct,
                        non_null,
                        len(results),
                    )

        return results

    def _collect_kr_via_kis(self, kr_tickers: list[str], today: str) -> list[dict]:
        """KR sub-batch — KIS Open API inquire-price 로 PER/PBR/시가총액 수집.

        Sequential + KIS_REQUEST_INTERVAL_PROD (0.4s) 페이싱 (KIS rate limit).
        자격 증명 / 토큰 발급 실패 시 빈 리스트 반환 → caller 가 yfinance fallback.
        """
        import time as _time

        try:
            from nuri.collectors.kis_realtime import (
                KIS_REQUEST_INTERVAL_PROD,
                get_access_token,
                load_credentials,
            )
        except ImportError:
            self.logger.warning("KIS module import 실패 — KR 전부 yfinance fallback")
            return []

        creds = load_credentials("prod")
        if not creds:
            self.logger.info("KIS 자격 증명 부재 — KR 전부 yfinance fallback (forward_pe 만)")
            return []

        token = get_access_token(creds)
        if not token:
            self.logger.warning("KIS 토큰 발급 실패 — KR 전부 yfinance fallback")
            return []

        self.logger.info(
            "🇰🇷 KIS inquire-price sequential (interval=%.1fs, ~%.0fs total) — %d KR ticker",
            KIS_REQUEST_INTERVAL_PROD,
            KIS_REQUEST_INTERVAL_PROD * len(kr_tickers),
            len(kr_tickers),
        )

        results: list[dict] = []
        for ticker in kr_tickers:
            record = _fetch_kis_kr(ticker, creds, token, today)
            if record:
                results.append(record)
            _time.sleep(KIS_REQUEST_INTERVAL_PROD)
        return results

    def save(self, data: Any) -> int:
        """펀더멘탈 데이터 DB 저장."""
        if not data:
            return 0
        return _upsert_fundamentals(data)


def _upsert_fundamentals(records: list[dict]) -> int:
    """fundamentals 테이블에 upsert."""
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO fundamentals
               (ticker, date, market_cap, pe_ratio, forward_pe, price_to_book,
                peg_ratio, roe, roa, gross_margin, operating_margin, profit_margin,
                revenue_growth, earnings_growth, debt_to_equity, current_ratio,
                dividend_yield, beta, annual_dividend_usd, dividend_yield_pct)
               VALUES (:ticker, :date, :market_cap, :pe_ratio, :forward_pe, :price_to_book,
                       :peg_ratio, :roe, :roa, :gross_margin, :operating_margin, :profit_margin,
                       :revenue_growth, :earnings_growth, :debt_to_equity, :current_ratio,
                       :dividend_yield, :beta, :annual_dividend_usd, :dividend_yield_pct)""",
            records,
        )
        return len(records)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nuri-Quant 펀더멘탈 수집기 (yfinance)")
    parser.add_argument(
        "--source", default="portfolio", choices=["portfolio", "universe", "all"], help="ticker 소스 (#272 Phase 2b)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = FundamentalCollector()
    count = collector.run(source=args.source)

    # 결과 출력
    rows = query(
        "SELECT ticker, pe_ratio, forward_pe, roe, revenue_growth, debt_to_equity FROM fundamentals ORDER BY ticker"
    )
    if rows:
        print(f"\n{'=' * 70}")
        print(f"  펀더멘탈 수집 완료: {count}종목")
        print(f"{'=' * 70}")
        print(f"  {'Ticker':<12} {'PE':>8} {'Fwd PE':>8} {'ROE':>8} {'매출성장':>8} {'D/E':>8}")
        print(f"  {'-' * 56}")
        for r in rows:
            pe = f"{r['pe_ratio']:.1f}" if r["pe_ratio"] else "N/A"
            fpe = f"{r['forward_pe']:.1f}" if r["forward_pe"] else "N/A"
            roe = f"{r['roe'] * 100:.1f}%" if r["roe"] else "N/A"
            rg = f"{r['revenue_growth'] * 100:.1f}%" if r["revenue_growth"] else "N/A"
            de = f"{r['debt_to_equity']:.1f}" if r["debt_to_equity"] else "N/A"
            print(f"  {r['ticker']:<12} {pe:>8} {fpe:>8} {roe:>8} {rg:>8} {de:>8}")
        print()
