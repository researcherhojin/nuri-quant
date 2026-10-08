"""
CBOE Put/Call Ratio 수집기.

CBOE 옵션 데이터에서 Put/Call Ratio를 수집하여 시장 심리 지표로 활용.
PCR > 1.0: 약세 심리 (풋 매수 과다), PCR < 0.7: 강세 심리 (콜 매수 과다).

소스 우선순위: CBOE 일별 통계 파일 → yfinance SPY 옵션 체인 → DB stale → 전면 실패 raise.

사용법:
    python -m nuri.collectors.cboe
"""

import logging
from datetime import date, timedelta

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector, today_str
from nuri.core.db import upsert_macro
from nuri.core.timezone import today_kst

# CBOE 일별 시장 통계 — 거래일마다 파일 하나, URL 의 날짜가 미국 거래일이다(파일 안에는 날짜가 없다).
# 주말·휴장일·미발행 날짜는 403 이라 옛 파일이 새 날짜로 둔갑하지 않는다 (2026-10-08 실측).
# 예전 `api/global/.../daily.json`·`totalpc.json` 은 2026-08-30 부터 403 이라 제거했다.
CBOE_DAILY_URL = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{date}_daily_options"
# 에이전트 임계(1.2 / 0.7 / 0.8–1.0)가 쓰는 스케일 — 예전 파서도 TOTAL 을 우선했다.
CBOE_RATIO_NAME = "TOTAL PUT/CALL RATIO"
# 한 번에 거슬러 볼 달력일 — 에이전트 lookback(5 거래일)을 한 실행으로 채운다. 투자 임계가 아니다.
CBOE_LOOKBACK_CALENDAR_DAYS = 10


class CBOECollector(BaseCollector):
    """CBOE Put/Call Ratio 수집."""

    def __init__(self):
        super().__init__("cboe")

    def collect(self, **kwargs) -> list[dict]:
        """CBOE에서 Put/Call Ratio 수집.

        전면 실패는 `[]` 가 아니라 **raise** 다 (#1042, coingecko #1043 과 동일 규약).
        `[]` 로 돌려주면 보고할 게 없던 날과 DB 기록이 같아진다 — 둘 다
        `collector_runs.status='finished'` 가 박히고 `#ops` 알림도 안 뜬다.

        ⚠️ 이 수집기에서 그 raise 는 **좀처럼 안 터진다.** 3차 `_collect_db_stale` 이
        DB 에 이전 값이 하나라도 있으면 성공으로 돌려주기 때문에, 라이브 소스 2개가
        전부 죽어도 여기까지 안 온다. 즉 여기서 고치는 건 "총체적 장애가 성공으로
        기록되는" 축이고, **"DB_STALE 재사용이 영원히 성공으로 집계되는" 축은 그대로
        남아 있었는데**, #1242 가 `macro_market` 정책(금리 3종 + put/call 그룹 MIN)에
        PCR 을 편입해 이제 그 stale 은 132h 에서 FAIL 로 표면화된다 — 2026-08-30
        실제로 그 경로가 6일 얼어붙은 PCR 을 잡았다.
        """
        errors: list[Exception] = []

        # 1차: CBOE 일별 통계 파일
        try:
            records = self._collect_daily()
            if records:
                return records
        except Exception as e:
            self.logger.warning("CBOE 일별 통계 파일 실패: %s", e)
            errors.append(e)

        # (구 3차 FRED ECPCRATIO 티어는 제거 — 2026-08-30 외부 실검증: FRED 가
        # "The series does not exist" 400 을 반환한다 (CBOE 시리즈 델리스트). 죽은
        # 티어는 매 실행 api_key 가 박힌 요청 URL 을 WARNING 로그로 흘리기만 했다.)

        # 2차: yfinance SPY 옵션 체인으로 PCR 직접 계산 — 스케일이 CBOE 와 다르다(아래 docstring)
        try:
            records = self._collect_yfinance_spy_pcr()
            if records:
                return records
        except Exception as e:
            self.logger.warning("yfinance SPY PCR 폴백 실패: %s", e)
            errors.append(e)

        # 3차: DB stale 재사용 (graceful degrade)
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
        """CBOE 일별 통계 파일에서 최근 거래일들의 TOTAL put/call 비율을 모은다.

        오늘(KST)부터 `CBOE_LOOKBACK_CALENDAR_DAYS` 일을 거슬러 날짜마다 파일을 요청한다. 403·404 는
        비거래일·미발행이라 건너뛴다. 받은 파일이 하나도 없으면 raise — 비거래일만 열흘 이어질 수는
        없으니 접근 차단이나 경로 변경이다. 행 날짜는 URL 의 거래일이다 (`today_str()` 가 아니다).
        """
        start = date.fromisoformat(today_kst())
        records: list[dict] = []
        fetched = 0
        for back in range(CBOE_LOOKBACK_CALENDAR_DAYS):
            day = (start - timedelta(days=back)).isoformat()
            resp = requests.get(CBOE_DAILY_URL.format(date=day), headers=DEFAULT_HEADERS, timeout=20)
            if resp.status_code in (403, 404):
                continue
            resp.raise_for_status()
            fetched += 1
            pcr = self._total_ratio(resp.json())
            if pcr is not None:
                records.append({"indicator": "put_call_ratio", "date": day, "value": pcr, "source": "CBOE"})
        if not fetched:
            raise RuntimeError(f"CBOE 일별 통계 파일이 최근 {CBOE_LOOKBACK_CALENDAR_DAYS}일 동안 없다")
        if not records:
            raise ValueError(f"CBOE 일별 통계 파일 {fetched}개에 '{CBOE_RATIO_NAME}' 이 없다 — 형식 변경")
        self.logger.info(
            "CBOE Put/Call Ratio: %d 거래일 (최신 %s = %.2f)", len(records), records[0]["date"], records[0]["value"]
        )
        return records

    @staticmethod
    def _total_ratio(data: dict) -> float | None:
        """`ratios` 목록에서 TOTAL 비율. 값은 문자열("0.87")로 온다."""
        for item in data.get("ratios") or []:
            if item.get("name") == CBOE_RATIO_NAME:
                try:
                    return float(item["value"])
                except (KeyError, TypeError, ValueError):
                    return None
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
