# pyright: reportMissingImports=false
"""기관/외인 수급 수집기 — 한국: KIS Open API / 미국: finnhub(선택).

(finnhub optional dep — 미설치 시 dynamic skip, runtime 정상.)

한국(.KS/.KQ) 종목은 KIS Open API `investor-trade-by-stock-daily` (FHPTJ04160001)
사용. 1 호출 = 30일 history per ticker. 기존 pykrx 경로는 KRX 정책 변경으로
HTTP 400 반환 → 전면 교체 (#247).

자격 증명: `nuri/collectors/kis_realtime.py`의 `load_credentials("prod")` 재사용.
KIS creds 미설정 시 명시적 skip + `pipeline_events` surface (STRATEGY §2.6 Surface).

사용법:
    python -m nuri.collectors.institutional
"""

from __future__ import annotations

import logging
import os
import time
from datetime import timedelta
from typing import Any

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db
from nuri.core.events import emit_event
from nuri.core.timezone import kst_now, today_kst

logger = logging.getLogger(__name__)

# KIS Open API endpoint
KIS_INVESTOR_TRADE_PATH = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
KIS_INVESTOR_TRADE_TR_ID = "FHPTJ04160001"


class InstitutionalCollector(BaseCollector):
    """기관/외인 수급 수집기."""

    def __init__(self):
        super().__init__("institutional")

    def collect(self, **kwargs) -> list[dict]:
        """수급 데이터 수집."""
        results = []

        # 한국 종목: KIS Open API
        kr_tickers = self._get_tickers(market="kr")
        if kr_tickers:
            kr_data = self._collect_kr_kis(kr_tickers)
            results.extend(kr_data)

        # 미국 종목: finnhub (API 키 필요)
        finnhub_key = os.getenv("FINNHUB_API_KEY")
        if finnhub_key:
            us_tickers = self._get_tickers(market="us")
            if us_tickers:
                us_data = self._collect_us(us_tickers, finnhub_key)
                results.extend(us_data)
        else:
            self.logger.info("FINNHUB_API_KEY 미설정 — 미국 수급 수집 건너뜀")

        return results

    def _collect_kr_kis(self, tickers: list[str]) -> list[dict]:
        """KIS Open API 투자자매매동향(일별)로 한국 종목 수급 수집.

        1 호출 = 종목당 최근 30일 history. rate limit 0.4s 간격.
        KIS creds 미설정 시 즉시 []+pipeline_events surface.
        """
        import requests

        from nuri.collectors.kis_realtime import (
            KIS_RATE_LIMIT_RETRY_DELAY_SEC,
            KIS_REQUEST_INTERVAL_PROD,
            _is_rate_limit,
            get_access_token,
            load_credentials,
        )

        # 1. creds 로드 (Surface §2.6 — 실패 시 infra issue로 emit, 시장 해석 분리)
        creds = load_credentials("prod")
        if creds is None or not creds.is_valid():
            self.logger.warning("KIS creds 미설정 — KR institutional flows skip. see docs/KIS_INTEGRATION.md")
            try:
                emit_event(
                    event_type="step_blocked",
                    step="collect",
                    payload={
                        "collector": "institutional",
                        "reason": "kis_creds_missing",
                        "affected_tickers": len(tickers),
                    },
                )
            except Exception:
                pass
            return []

        # 2. token 발급
        token = get_access_token(creds)
        if not token:
            self.logger.error("KIS token 발급 실패 — KR institutional flows skip")
            try:
                emit_event(
                    event_type="step_failed",
                    step="collect",
                    payload={"collector": "institutional", "reason": "kis_token_failed"},
                )
            except Exception:
                pass
            return []

        # 3. ticker 별 호출
        try:
            from tqdm import tqdm

            iterator = tqdm(tickers, desc="KIS investor-trade (KR)", unit="ticker")
        except ImportError:
            iterator = tickers

        url = f"{creds.base_url}{KIS_INVESTOR_TRADE_PATH}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": KIS_INVESTOR_TRADE_TR_ID,
            "custtype": "P",
        }
        # KIS TIME LIMIT: today's date rejected before 15:40 KST daily settlement.
        # Always query T-1 — 30-day history window covers T-1 back to T-30.
        query_date = (kst_now() - timedelta(days=1)).strftime("%Y%m%d")
        results: list[dict] = []
        failed: list[str] = []

        for ticker_full in iterator:
            code = ticker_full.replace(".KS", "").replace(".KQ", "")
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": query_date,
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            }
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    self.logger.debug("%s: HTTP %d", ticker_full, resp.status_code)
                    failed.append(ticker_full)
                    time.sleep(KIS_REQUEST_INTERVAL_PROD)
                    continue
                body = resp.json()
                if _is_rate_limit(body):
                    self.logger.warning(
                        "%s: rate limit — %ss 대기 후 재시도", ticker_full, KIS_RATE_LIMIT_RETRY_DELAY_SEC
                    )
                    time.sleep(KIS_RATE_LIMIT_RETRY_DELAY_SEC)
                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                    body = resp.json() if resp.status_code == 200 else {}
                if body.get("rt_cd") != "0":
                    self.logger.debug("%s: rt_cd=%s msg=%s", ticker_full, body.get("rt_cd"), body.get("msg1"))
                    failed.append(ticker_full)
                    time.sleep(KIS_REQUEST_INTERVAL_PROD)
                    continue

                out2 = body.get("output2") or []
                for row in out2:
                    record = _parse_kis_row(row, ticker_full)
                    if record:
                        results.append(record)
            except Exception as e:
                self.logger.debug("%s: exception — %s", ticker_full, e)
                failed.append(ticker_full)
            finally:
                time.sleep(KIS_REQUEST_INTERVAL_PROD)

        self._failed_tickers = failed
        self.logger.info(
            "KR institutional: %d records from %d/%d tickers (%d failed)",
            len(results),
            len(tickers) - len(failed),
            len(tickers),
            len(failed),
        )
        return results

    def _collect_us(self, tickers: list[str], api_key: str) -> list[dict]:
        """finnhub으로 미국 종목 기관 보유 비중 수집."""
        results = []
        today = today_kst()

        try:
            import finnhub

            client = finnhub.Client(api_key=api_key)

            for ticker in tickers:
                try:
                    data = client.ownership(ticker, limit=1)
                    if data and "ownership" in data and data["ownership"]:
                        record = {
                            "ticker": ticker,
                            "date": today,
                            "market": "US",
                            "institution_net": None,
                            "foreign_net": None,
                            "individual_net": None,
                            "source": "finnhub",
                        }
                        results.append(record)
                except Exception as e:
                    self.logger.debug(f"{ticker}: finnhub 수집 실패 — {e}")

        except ImportError:
            self.logger.warning("finnhub-python 미설치. pip install finnhub-python")

        return results

    def save(self, data: Any) -> int:
        if not data:
            return 0
        return _upsert_institutional(data)


def _parse_kis_row(row: dict, ticker_full: str) -> dict | None:
    """KIS output2 row → institutional_flows record.

    Args:
        row: KIS API output2 단일 행 (dict)
        ticker_full: '005930.KS' 형식
    """
    bsop_date = row.get("stck_bsop_date")
    if not bsop_date or len(str(bsop_date)) != 8:
        return None
    try:
        date_str = f"{bsop_date[:4]}-{bsop_date[4:6]}-{bsop_date[6:8]}"
    except Exception:
        return None

    return {
        "ticker": ticker_full,
        "date": date_str,
        "market": "KR",
        "institution_net": _safe_int(row.get("orgn_ntby_qty")),
        "foreign_net": _safe_int(row.get("frgn_ntby_qty")),
        "individual_net": _safe_int(row.get("prsn_ntby_qty")),
        "source": "kis_openapi",
    }


def _safe_int(val) -> int | None:
    """KIS 응답 문자열 → int (NaN/빈값/비정상은 None)."""
    if val is None or val == "":
        return None
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _upsert_institutional(records: list[dict]) -> int:
    """UNIQUE(ticker, date, market) ON CONFLICT → UPDATE (B1 lesson, PR #311)."""
    if not records:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT INTO institutional_flows
               (ticker, date, market, institution_net, foreign_net,
                individual_net, source)
               VALUES (:ticker, :date, :market, :institution_net, :foreign_net,
                       :individual_net, :source)
               ON CONFLICT(ticker, date, market) DO UPDATE SET
                   institution_net = excluded.institution_net,
                   foreign_net = excluded.foreign_net,
                   individual_net = excluded.individual_net,
                   source = excluded.source""",
            records,
        )
        return len(records)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = InstitutionalCollector()
    count = collector.run()
    print(f"수급 데이터 수집 완료: {count}건")

    if count == 0:
        print("  KIS Open API 또는 .env 설정 확인 필요")
        print("  FINNHUB_API_KEY를 .env에 설정하면 미국 수급도 수집 가능")
