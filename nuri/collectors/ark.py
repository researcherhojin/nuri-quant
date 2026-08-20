"""
ARK Invest 매매 추적 수집기.

소스: ark-funds.com 공식 ETF 별 보유 CSV (`assets.ark-funds.com`).

이전 소스 2개는 둘 다 죽어 있었다 (#1143) — `cathiesark.com` 은 500/503, 통합
`ARK_TRADE.csv` 는 301 후 404. 그 자리를 메우던 yfinance 폴백은 `top_holdings`
(상위 10개) 스냅샷을 `direction="Hold"` / `shares=0.0` 으로 적었는데, 이건 매매가
아니어서 신호가 없을 뿐 아니라 아래 델타 계산의 기준선을 오염시킨다. 그래서 제거했다.

ARK 는 **매매 내역이 아니라 일별 보유 스냅샷**을 공개한다. 따라서 Buy/Sell 은 직전
수집분 대비 `shares` 증감으로 파생한다 — 저장 단위가 `(date, ticker, fund)` 라
파생에 필요한 과거분은 이미 테이블에 있다.

사용법:
    python -m nuri.collectors.ark
"""

import csv
import io
import logging

import requests

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector, parse_date
from nuri.core.db import get_tickers, query, upsert_ark
from nuri.core.rules import ARK_MIN_TRADE_PCT

# ETF 별 보유 CSV. 통합 파일이 없어졌으므로 펀드마다 따로 받는다.
# 한 펀드가 실패해도 나머지는 수집된다 (부분 성공 허용).
ARK_HOLDINGS_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"
ARK_HOLDINGS_FILES = {
    "ARKK": "ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": "ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": "ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKQ": "ARK_AUTONOMOUS_TECH._&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    "ARKF": "ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
}


class ARKCollector(BaseCollector):
    """ARK Invest 일일 보유 추적 + 전일 대비 매매 파생."""

    def __init__(self):
        super().__init__("ark")

    def collect(self, **kwargs) -> list[dict]:
        """ETF 5종의 보유 CSV 를 받아 보유 종목만 남기고, 직전 보유분과 비교한다."""
        db_path = kwargs.get("db_path")
        held_tickers = set(get_tickers(db_path=db_path))

        records: list[dict] = []
        errors: list[Exception] = []
        failed: list[str] = []
        for fund, filename in ARK_HOLDINGS_FILES.items():
            url = f"{ARK_HOLDINGS_BASE}/{filename}"
            try:
                records.extend(self._collect_fund(url, fund, held_tickers, db_path))
            except Exception as e:
                errors.append(e)
                failed.append(fund)
                self.logger.warning("ARK %s 보유 CSV 실패 (%s): %s", fund, url.split("/")[2], e)

        if failed:
            self.logger.warning("ARK 펀드 %d/%d 실패: %s", len(failed), len(ARK_HOLDINGS_FILES), ", ".join(failed))

        # 전면 실패는 빈 수집과 다르다 (#1043, collectors/CLAUDE.md). 조건이 `len(errors) == 5`
        # 가 아니라 `errors and not records` 인 이유: 일부가 예외이고 나머지는 우리 보유 종목과
        # 겹치는 항목이 없어 빈 경우도 실패다. 반대로 5개 다 200 인데 겹치는 종목이 하나도
        # 없으면 예외가 없어 `[]` 가 그대로 나간다 — 그게 NO_DATA 다.
        # `errors[-1]` 이 아니라 `errors[0]`: 마지막 것만 올리면 첫 펀드의 원인이 알림에서 사라진다.
        if errors and not records:
            raise errors[0]
        if not records:
            self.logger.warning("ARK 보유 종목과 겹치는 항목 없음 (NO_DATA — 수집 자체는 성공)")
            return []

        directions = {d: sum(1 for r in records if r["direction"] == d) for d in ("Buy", "Sell", "Hold")}
        self.logger.info("ARK 보유 %d건 (보유 종목 필터) — %s", len(records), directions)
        return records

    def _collect_fund(self, url: str, fund: str, held_tickers: set, db_path=None) -> list[dict]:
        """한 ETF 의 보유 CSV 를 파싱하고 직전 보유분 대비 방향을 파생한다."""
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        records = []
        seen: set[str] = set()
        csv_date = None

        for row in reader:
            # 현재 컬럼: date, fund, company, ticker, cusip, shares, market value ($), weight (%)
            # 마지막 행은 면책 문구 한 줄이라 ticker 가 비어 자연히 걸러진다. 비상장 보유분도 마찬가지.
            ticker = _clean(row.get("ticker") or row.get("Ticker"))
            if not ticker or ticker not in held_tickers:
                continue

            date = parse_date(_clean(row.get("date") or row.get("Date")))
            if not date:
                continue

            # shares 를 못 읽으면 행을 버린다 — 0.0 으로 눕히면 방향 파생이 그걸
            # **전량 청산**으로 읽는다. 소스 포맷이 흔들린 것을 매도 신호로 바꾸지 않는다.
            shares = _to_float_or_none(row.get("shares") or row.get("Shares"))
            if shares is None:
                self.logger.warning("ARK %s %s: shares 파싱 실패 — 행 건너뜀", fund, ticker)
                continue

            # 'weight (%)' 가 현재 컬럼명. 예전 통합 CSV 의 '% of ETF' 도 받아 둔다.
            # weight 는 방향 파생에 안 쓰이므로 못 읽으면 0.0 이어도 신호를 왜곡하지 않는다.
            weight = _to_float_or_none(row.get("weight (%)") or row.get("% of ETF") or row.get("weight"))

            csv_date = date
            seen.add(ticker)
            records.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "direction": self._derive_direction(ticker, fund, date, shares, db_path),
                    "shares": shares,
                    "weight": weight if weight is not None else 0.0,
                    "fund": _clean(row.get("fund") or row.get("Fund")) or fund,
                }
            )

        if csv_date:
            records.extend(self._exit_records(fund, csv_date, seen, held_tickers, db_path))
        return records

    def _exit_records(self, fund: str, date: str, seen: set[str], held_tickers: set, db_path=None) -> list[dict]:
        """어제 있었는데 오늘 CSV 에 없는 종목 → 전량 청산 (#1143 codex P1).

        **부재는 CSV 에 행으로 나타나지 않는다.** ARK 가 한 종목을 완전히 털면 그 종목은
        그냥 사라지므로, 오늘 행만 훑는 파생은 `_derive_direction` 을 호출조차 못 하고
        가장 강한 신호인 전량 청산이 통째로 유실된다. 펀드 간 이동도 같은 구멍이다 —
        떠난 펀드에서는 아무 일도 안 일어나고 새 펀드에서는 첫 관측이라 Hold 다.

        `shares=0.0` 으로 적어 두면 이 행 자체가 "여기서 0 이 됐다" 는 기록이 되고,
        재진입 때 기준선 조회가 이걸 보고 첫 관측으로 되돌린다 (pre-exit 규모와 비교해
        엉뚱한 Sell 을 내지 않는다).
        """
        prev = query(
            "SELECT ticker, shares FROM ark a WHERE a.fund = ? AND a.date < ? AND a.date = ("
            "  SELECT MAX(b.date) FROM ark b "
            "  WHERE b.fund = a.fund AND b.ticker = a.ticker AND b.date < ?"
            ")",
            (fund, date, date),
            db_path=db_path,
        )
        return [
            {
                "date": date,
                "ticker": r["ticker"],
                "direction": "Sell",
                "shares": 0.0,
                "weight": 0.0,
                "fund": fund,
            }
            for r in prev
            # shares > 0 조건이 청산 반복을 막는다 — 어제 이미 0 으로 적힌 종목은
            # '보유 중이었다' 에 해당하지 않으므로 매일 Sell 을 다시 내지 않는다.
            if r["shares"] > 0 and r["ticker"] not in seen and r["ticker"] in held_tickers
        ]

    def _derive_direction(self, ticker: str, fund: str, date: str, shares: float, db_path=None) -> str:
        """직전 보유분 대비 shares 증감 → Buy / Sell / Hold.

        기준선 후보는 `shares > 0` 인 행 **또는 우리가 적은 청산 표식**(`Sell` + 0)이다.
        과거 yfinance 폴백이 남긴 `shares=0.0` / `Hold` 행은 실제 0 이 아니라 값을 몰라서
        0 인 것이라 기준선에서 빼야 한다 — 그걸 기준선으로 잡으면 다음 수집분이 통째로
        Buy 로 보인다 (#1143).

        기준선이 청산 표식이면 오늘은 **재진입**이므로 첫 관측으로 되돌린다 (Hold).
        pre-exit 규모와 비교하면, 더 작게 재진입한 경우가 Sell 로 뒤집힌다.
        비교 대상이 아예 없어도 (첫 관측) 방향을 주장하지 않는다.
        """
        prev = query(
            "SELECT shares FROM ark WHERE ticker = ? AND fund = ? AND date < ? "
            "AND (shares > 0 OR direction = 'Sell') ORDER BY date DESC LIMIT 1",
            (ticker, fund, date),
            db_path=db_path,
        )
        if not prev:
            return "Hold"

        before = prev[0]["shares"]
        if before <= 0:
            return "Hold"  # 청산 표식 → 재진입은 새 포지션이다

        change_pct = (shares - before) / before * 100
        if change_pct >= ARK_MIN_TRADE_PCT:
            return "Buy"
        if change_pct <= -ARK_MIN_TRADE_PCT:
            return "Sell"
        return "Hold"

    def save(self, data: list[dict]) -> int:
        """ARK 보유/매매 내역을 DB에 저장."""
        return upsert_ark(data)


def _clean(value) -> str:
    return str(value).strip() if value else ""


def _to_float_or_none(raw) -> float | None:
    """'1,713,664' / '9.36%' / '$601,701,703.70' → float. 파싱 불가 시 **None**.

    0.0 을 돌려주면 안 된다 — 방향 파생이 shares 0 을 전량 청산으로 읽으므로,
    소스 포맷이 흔들린 것이 매도 신호로 둔갑한다 (#1143 codex P2).
    """
    s = _clean(raw).replace(",", "").replace("%", "").replace("$", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    collector = ARKCollector()
    collector.run()
