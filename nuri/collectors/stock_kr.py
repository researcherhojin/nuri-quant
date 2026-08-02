# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false
"""
한국 주가 데이터 수집기 — pykrx 기반 KOSPI/KOSDAQ 수집.

(pykrx return DataFrame | None / Index.strftime stub — runtime 정상.)

pykrx는 KRX/네이버 금융 데이터를 사용하며, EOD(종가) 데이터만 지원.
티커는 DB에 '005930.KS' 형태로 저장되지만, pykrx에는 '005930'으로 전달.

사용법:
    python -m nuri.collectors.stock_kr
    python -m nuri.collectors.stock_kr --days 30
"""

import argparse
import logging
from datetime import timedelta
from typing import Optional

import pandas as pd
from pykrx import stock as krx

from nuri.collectors.base import BaseCollector
from nuri.core.db import upsert_prices


def _call_with_timeout(func, timeout_sec: int, *args, **kwargs):
    """ThreadPool 기반 timeout 헬퍼 — pykrx hang 방지.

    macOS/Linux signal.alarm 보다 안전 (메인 스레드 외에서도 동작).

    Returns:
        함수 결과 또는 None (timeout 시).
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            return None
        except Exception:
            raise


def _reference_tickers() -> list[str]:
    """시스템이 **이미 의존한다고 선언한** KR 기준 티커.

    브리프의 KR 벤치마크(`069500.KS`)는 보유 종목이 아니라 `source=portfolio` 에
    안 잡히고, `universe.yaml` 은 KRX 구성종목 자동 동기화(`make universe-sync`)라
    ETF 를 손으로 넣어도 다음 sync 에 지워진다. 그래서 어느 경로로도 수집되지
    않았고 — 프로덕션 `prices` 에 **0행**이다(2026-08-02 실측). 소비자는 넷인데
    (브리프 벤치마크 · 섹터 무버 fallback · 이벤트 수집 · risk_signals) 공급자가
    없었다.

    목록을 새로 하드코딩하지 않고 config 선언에서 뽑는다 — 벤치마크를 바꾸면
    수집 대상이 따라 움직여야지, 두 곳을 손으로 맞추면 또 갈라진다.
    """
    from nuri.core.rules import BRIEF_BENCHMARK
    from nuri.core.ticker_names import is_kr_ticker

    return sorted({str(t) for t in BRIEF_BENCHMARK.values() if t and is_kr_ticker(str(t))})


class StockKRCollector(BaseCollector):
    """pykrx로 한국 주가 수집 (KOSPI/KOSDAQ) + 지수 수집 (yfinance)."""

    # 한국 시장 지수 — yfinance 티커 → DB 저장 티커 (#247)
    INDEX_TICKERS = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}

    def __init__(self):
        super().__init__("stock_kr")

    def collect(self, days: int = 5, source: str = "portfolio", **kwargs) -> pd.DataFrame:
        """pykrx로 한국 종목 OHLCV + yfinance로 KOSPI/KOSDAQ 지수 수집.

        Args:
            source: 'portfolio' (default, 보유) | 'universe' (KOSPI 200 전체) | 'all'
                    #272 Phase 2c bug fix — collect-universe에서 KR 사일로 잔존 해결.
        """
        # 기준 티커는 source 와 무관하게 항상 붙인다 — 보유도 universe 도 아니지만
        # 브리프·타당성 검사가 매일 읽는다.
        reference = _reference_tickers()
        tickers = sorted(set(self._get_tickers(market="kr", source=source)) | set(reference))
        if not tickers:
            self.logger.warning("수집할 한국 종목이 없습니다")
            return pd.DataFrame()

        self.logger.info(f"수집 대상: {len(tickers)} 한국 종목 ({days}일, source={source}, 기준 {len(reference)}종)")

        # KST 기준 날짜 (KRX는 한국 영업일 기준)
        from nuri.core.timezone import kst_now

        now_kst = kst_now()
        end_date = now_kst.strftime("%Y%m%d")
        start_date = (now_kst - timedelta(days=days)).strftime("%Y%m%d")

        # 순차 fetch — KRX는 동시 요청 rate-limit. parallel 시 첫 ~60건만 빠르고
        # 그 다음부터 동시에 5+ 요청이 hang. 순차 + 100ms delay 가 가장 안정적.
        # 순차 + per-call 5s timeout = 최악 ~17분, 정상 ~30초 (203 × 0.15s).
        import time as _time

        from tqdm import tqdm

        frames: list = []
        succeeded: list[str] = []
        failed: list[str] = []
        iterator = tqdm(tickers, desc="  KR prices", unit="tk", disable=len(tickers) < 20)
        for ticker_with_suffix in iterator:
            df = self._collect_ticker(ticker_with_suffix, start_date, end_date)
            if df is not None and not df.empty:
                frames.append(df)
                succeeded.append(ticker_with_suffix)
            else:
                failed.append(ticker_with_suffix)
            # KRX rate-limit 회피: 짧은 delay (전체 ~30초 추가, hang 회피)
            _time.sleep(0.1)

        if len(tickers) >= 20:
            sample_failed = ", ".join(failed[:5]) + (f" 외 {len(failed) - 5}개" if len(failed) > 5 else "")
            self.logger.info(
                "📊 KR 주가: ✅ %d 성공 / ❌ %d 실패 (%.1f%%) — failed: %s",
                len(succeeded),
                len(failed),
                len(succeeded) / len(tickers) * 100,
                sample_failed or "없음",
            )

        # KOSPI/KOSDAQ 지수 수집 (#247)
        index_df = self._collect_indices(days)
        if index_df is not None and not index_df.empty:
            frames.append(index_df)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _collect_ticker(self, ticker_full: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """단일 한국 종목 수집. pykrx hang 방지 위해 5초 타임아웃 적용."""
        # .KS 접미사 제거 (pykrx는 순수 숫자 코드 사용)
        ticker_code = ticker_full.replace(".KS", "").replace(".KQ", "")

        try:
            raw = _call_with_timeout(krx.get_market_ohlcv, 5, start_date, end_date, ticker_code)
            if raw is None:
                self.logger.debug(f"{ticker_full}: pykrx 호출 timeout (>5s) — KRX 응답 지연")
                return None
            if raw.empty:
                self.logger.warning(f"{ticker_full}: 데이터 없음")
                return None

            # pykrx 한국어 컬럼 → Nuri-Quant 표준 컬럼 매핑
            df = pd.DataFrame(
                {
                    "ticker": ticker_full,
                    "date": raw.index.strftime("%Y-%m-%d"),
                    "open": raw["시가"].values,
                    "high": raw["고가"].values,
                    "low": raw["저가"].values,
                    "close": raw["종가"].values,
                    "volume": raw["거래량"].values,
                    "adj_close": raw["종가"].values,  # pykrx는 수정종가 미제공
                }
            )

            return df

        except Exception as e:
            self.logger.warning(f"{ticker_full} ({ticker_code}): 수집 실패 — {e}")
            return None

    def _collect_indices(self, days: int) -> Optional[pd.DataFrame]:
        """yfinance로 KOSPI/KOSDAQ 지수 수집 (#247).

        pykrx get_index_ohlcv는 컬럼명 변경으로 깨져 있어 yfinance 사용.
        """
        import yfinance as yf

        frames = []
        for yf_ticker, db_ticker in self.INDEX_TICKERS.items():
            try:
                raw = yf.download(yf_ticker, period=f"{days}d", progress=False)
                if raw.empty:
                    self.logger.warning(f"{db_ticker}: yfinance 지수 데이터 없음")
                    continue

                # 멀티인덱스 컬럼 처리
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)

                df = pd.DataFrame(
                    {
                        "ticker": db_ticker,
                        "date": raw.index.strftime("%Y-%m-%d"),
                        "open": raw["Open"].values,
                        "high": raw["High"].values,
                        "low": raw["Low"].values,
                        "close": raw["Close"].values,
                        "volume": raw["Volume"].values.astype(int),
                        "adj_close": raw["Close"].values,
                    }
                )
                frames.append(df)
                self.logger.info(f"  {db_ticker}: {len(df)}건 지수 데이터")

            except Exception as e:
                self.logger.warning(f"{db_ticker}: 지수 수집 실패 — {e}")

        return pd.concat(frames, ignore_index=True) if frames else None

    def save(self, data: pd.DataFrame) -> int:
        """수집된 주가를 DB에 저장."""
        if data.empty:
            return 0
        return upsert_prices(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nuri-Quant 한국 주가 수집기 (pykrx)")
    parser.add_argument("--days", type=int, default=5, help="수집 일수 (기본 5일)")
    parser.add_argument(
        "--source",
        default="portfolio",
        choices=["portfolio", "universe", "all"],
        help="ticker 소스 (#272 Phase 2c). KOSPI 200 전체 수집 시 universe 사용",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = StockKRCollector()
    collector.run(days=args.days, source=args.source)
