"""
CBOE Put/Call Ratio 수집기.

CBOE 옵션 데이터에서 Put/Call Ratio를 수집하여 시장 심리 지표로 활용.
PCR > 1.0: 약세 심리 (풋 매수 과다), PCR < 0.7: 강세 심리 (콜 매수 과다).

소스 우선순위: CBOE JSON API → FRED ECPCRATIO → 없으면 스킵.

사용법:
    python -m nuri.collectors.cboe
"""

import logging

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector, parse_date, today_str
from nuri.core.db import upsert_macro

# CBOE 일별 시장 통계
CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/daily.json"
CBOE_TOTPC_URL = "https://cdn.cboe.com/api/global/us_options/market_statistics/totalpc.json"


class CBOECollector(BaseCollector):
    """CBOE Put/Call Ratio 수집."""

    def __init__(self):
        super().__init__("cboe")

    def collect(self, **kwargs) -> list[dict]:
        """CBOE에서 Put/Call Ratio 수집.

        전면 실패는 `[]` 가 아니라 **raise** 다 (#1042, coingecko #1043 과 동일 규약).
        `[]` 로 돌려주면 보고할 게 없던 날과 DB 기록이 같아진다 — 둘 다
        `collector_runs.status='finished'` 가 박히고 `#ops` 알림도 안 뜬다.

        ⚠️ 이 수집기에서 그 raise 는 **좀처럼 안 터진다.** 5차 `_collect_db_stale` 이
        DB 에 이전 값이 하나라도 있으면 성공으로 돌려주기 때문에, 라이브 소스 4개가
        전부 죽어도 여기까지 안 온다. 즉 여기서 고치는 건 "총체적 장애가 성공으로
        기록되는" 축이고, **"DB_STALE 재사용이 영원히 성공으로 집계되는" 축은 그대로
        남아 있었는데**, #1242 가 `macro_market` 정책(금리 3종 + put/call 그룹 MIN)에
        PCR 을 편입해 이제 그 stale 은 132h 에서 FAIL 로 표면화된다 — 2026-08-30
        실제로 그 경로가 6일 얼어붙은 PCR 을 잡았다.
        """
        errors: list[Exception] = []

        # 1차: CBOE daily.json
        try:
            records = self._collect_daily()
            if records:
                return records
        except Exception as e:
            self.logger.warning("CBOE daily API 실패: %s", e)
            errors.append(e)

        # 2차: CBOE totalpc.json
        try:
            records = self._collect_totalpc()
            if records:
                return records
        except Exception as e:
            self.logger.warning("CBOE totalpc 폴백도 실패: %s", e)
            errors.append(e)

        # (구 3차 FRED ECPCRATIO 티어는 제거 — 2026-08-30 외부 실검증: FRED 가
        # "The series does not exist" 400 을 반환한다 (CBOE 시리즈 델리스트). 죽은
        # 티어는 매 실행 api_key 가 박힌 요청 URL 을 WARNING 로그로 흘리기만 했다.)

        # 3차: yfinance SPY 옵션 체인으로 PCR 직접 계산
        try:
            records = self._collect_yfinance_spy_pcr()
            if records:
                return records
        except Exception as e:
            self.logger.warning("yfinance SPY PCR 폴백 실패: %s", e)
            errors.append(e)

        # 4차: DB stale 재사용 (graceful degrade)
        try:
            stale = self._collect_db_stale()
            if stale:
                return stale
        except Exception as e:
            self.logger.warning("DB stale fallback 실패: %s", e)
            errors.append(e)

        # coingecko 는 `errors and not records` 를 쓰지만 여기는 `errors` 만 본다.
        # 각 티어가 값을 건지면 즉시 return 하므로, 이 줄에 닿았다는 것 자체가 이미
        # "한 건도 못 건졌다" 는 뜻이다 — `not records` 를 덧붙이면 records 가 비지
        # 않을 수도 있다는 잘못된 인상만 준다.
        if errors:
            self.logger.error(
                "CBOE 모든 소스 실패 (%d건) — 첫 원인을 올린다",
                len(errors),
            )
            # `errors[-1]` 이 아니라 `errors[0]`: 마지막은 항상 DB stale(로컬 DB) 이라
            # 알림에 올리면 운영자가 네트워크 원인 대신 DB 를 뒤지게 된다.
            raise errors[0]

        # 예외는 없었는데 전부 빈 응답 = NO_DATA. 그 구분을 지키는 게 이 변경의 요점이다.
        self.logger.warning("CBOE: 모든 소스가 빈 응답 — NO_DATA (예외 없음)")
        return []

    def _collect_yfinance_spy_pcr(self) -> list[dict]:
        """yfinance SPY 옵션 체인에서 PCR을 proxy로 계산.

        ⚠ 한계: CBOE 공식 Equity PCR (전체 미국 주식 옵션 기반, 통상 0.6~0.8)과
        다름. SPY 단일 만기 PCR은 헤지 수요 때문에 보통 1.0~2.0 범위.
        절대값보다 추세 (전일 대비 상승/하락)로 사용해야 정확.
        source='yfinance_SPY'로 명시하여 downstream에서 구분 가능.

        가장 가까운 만기일의 콜/풋 거래량을 합산해 PCR = put_vol / call_vol.
        """
        import yfinance as yf

        ticker = yf.Ticker("SPY")
        expirations = ticker.options
        if not expirations:
            return []
        # 가장 가까운 만기 (보통 weekly/monthly)
        nearest = expirations[0]
        chain = ticker.option_chain(nearest)
        # yfinance 는 장외/부분 응답에서 chain 이나 calls/puts 를 None 으로 준다 —
        # 미가드 시 'NoneType' not subscriptable 로 티어가 죽는다 (2026-08-29 mini 실측,
        # CBOE 403 국면에서 마지막 라이브 소스가 이 버그로 같이 죽어 PCR 이 6일 얼었다).
        if chain is None or getattr(chain, "calls", None) is None or getattr(chain, "puts", None) is None:
            return []
        call_vol = float(chain.calls["volume"].fillna(0).sum())
        put_vol = float(chain.puts["volume"].fillna(0).sum())
        if call_vol <= 0:
            return []
        pcr = put_vol / call_vol
        self.logger.info(
            "yfinance SPY PCR: %.3f (만기 %s, calls=%d puts=%d)",
            pcr,
            nearest,
            int(call_vol),
            int(put_vol),
        )
        return [
            {
                "indicator": "put_call_ratio",
                "date": today_str(),
                "value": round(pcr, 4),
                "source": "yfinance_SPY",
            }
        ]

    def _collect_db_stale(self) -> list[dict]:
        """DB의 가장 최근 PCR 값을 stale로 재사용 (오늘 데이터 없을 때만).

        codex Review (2026-04-28): 같은 메서드 2번 정의 → 첫 정의는 dead code.
        통합 단일 정의 유지.
        """
        from nuri.core.db import query

        rows = query("SELECT date, value FROM macro WHERE indicator = 'put_call_ratio' ORDER BY date DESC LIMIT 1")
        if not rows:
            return []
        row = rows[0]
        prev_date = row["date"] if hasattr(row, "__getitem__") else row[0]
        prev_value = row["value"] if hasattr(row, "__getitem__") else row[1]
        if prev_date == today_str():
            return []  # 오늘 이미 있음 — fallback 불필요
        self.logger.warning(
            "CBOE: 라이브 데이터 없음, DB stale 재사용 (%s = %.3f)",
            prev_date,
            prev_value,
        )
        return [
            {
                "indicator": "put_call_ratio",
                "date": prev_date,  # 원래 날짜 유지 (freshness가 stale로 감지)
                "value": float(prev_value),
                "source": "DB_STALE",
            }
        ]

    def _collect_daily(self) -> list[dict]:
        """CBOE daily market statistics JSON에서 PCR 추출."""
        resp = requests.get(CBOE_OPTIONS_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        records = []
        today = today_str()

        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, list) and items:
            latest = items[-1] if len(items) > 1 else items[0]
            pcr = self._extract_pcr(latest)
            if pcr is not None:
                raw_date = latest.get("TRADE_DATE", latest.get("date", today))
                date_str = parse_date(raw_date) or today
                records.append(
                    {
                        "indicator": "put_call_ratio",
                        "date": date_str,
                        "value": float(pcr),
                        "source": "CBOE",
                    }
                )
                self.logger.info("CBOE Put/Call Ratio: %.3f (%s)", pcr, date_str)
        elif isinstance(data, dict):
            pcr = self._extract_pcr(data)
            if pcr is not None:
                records.append(
                    {
                        "indicator": "put_call_ratio",
                        "date": today,
                        "value": float(pcr),
                        "source": "CBOE",
                    }
                )

        return records

    def _collect_totalpc(self) -> list[dict]:
        """CBOE Total Put/Call 폴백."""
        resp = requests.get(CBOE_TOTPC_URL, headers=DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        records = []
        items = data.get("data", []) if isinstance(data, dict) else data
        if isinstance(items, list):
            for item in items[-30:]:
                pcr = self._extract_pcr(item)
                raw_date = item.get("TRADE_DATE", item.get("date", ""))
                date_str = parse_date(raw_date)
                if pcr is not None and date_str:
                    records.append(
                        {
                            "indicator": "put_call_ratio",
                            "date": date_str,
                            "value": float(pcr),
                            "source": "CBOE",
                        }
                    )

        self.logger.info("CBOE totalpc: %d건", len(records))
        return records

    @staticmethod
    def _extract_pcr(item: dict) -> float | None:
        """다양한 키 이름에서 PCR 값 추출."""
        for key in ("TOTAL_PUT_CALL_RATIO", "PUT_CALL_RATIO", "put_call_ratio", "pcr", "ratio"):
            val = item.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        put_vol = item.get("TOTAL_PUT_VOLUME", item.get("put_volume"))
        call_vol = item.get("TOTAL_CALL_VOLUME", item.get("call_volume"))
        if put_vol and call_vol:
            try:
                return float(put_vol) / float(call_vol)
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        return None

    def save(self, data: list[dict]) -> int:
        """매크로 테이블에 저장."""
        return upsert_macro(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = CBOECollector()
    collector.run()
