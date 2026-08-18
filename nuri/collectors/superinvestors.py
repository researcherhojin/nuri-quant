# pyright: reportGeneralTypeIssues=false
"""
슈퍼투자자 포트폴리오 수집기 — SEC EDGAR 13F 기반.

(edgartools EntityFiling iter() stub 부재 — runtime 정상.)

edgartools를 사용하여 SEC EDGAR에서 직접 13F 공시를 파싱.
API 키 불필요. 분기별 갱신.

사용법:
    python -m nuri.collectors.superinvestors
"""

import logging
from typing import Any, Optional

import pandas as pd

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db, query

logger = logging.getLogger(__name__)

# 추적 대상 슈퍼투자자 (이름, SEC CIK)
SUPERINVESTORS = {
    "Warren Buffett": "0001067983",  # Berkshire Hathaway
    "Bill Gates": "0001166559",  # Bill & Melinda Gates Foundation
    "Ray Dalio": "0001350694",  # Bridgewater Associates
    "Bill Ackman": "0001336528",  # Pershing Square
    "David Tepper": "0001656456",  # Appaloosa Management
    "National Pension Service": "0001608046",  # 국민연금 (NPS Korea)
    "Scott Bessent (Key Square)": "0001662970",  # 미 재무장관, Key Square Capital
    "Vivek Ramaswamy (Strive)": "0001954109",  # Strive Asset Management
}

#: 대형 은행 13F (#1098). **확신 포트폴리오가 아니다** — 마켓메이킹·수탁·인덱스가
#: 섞여 있고 분기 공시라 45일 지연된다. 버핏의 NEW 와 JPM 의 NEW 는 같은 뜻이 아니므로
#: 읽는 쪽에 반드시 그 단서를 붙인다.
#:
#: CIK 는 2026-08-18 EDGAR `company_tickers.json` + `submissions` API 로 **직접 확인**했다
#: (넷 다 13F-HR 실적 있음). 한 분기 포지션 수 실측: JPM 34,064 · BAC 18,318 ·
#: GS 14,070 · Citi 11,343 — 그래서 `dealer` 로 격리하고 universe 로 좁혀 저장한다.
BANK_13F = {
    "JPMorgan Chase": "0000019617",
    "Bank of America": "0000070858",
    "Goldman Sachs": "0000886982",
    "Citigroup": "0000831001",
}

#: `superinvestors.investor_class` 값. `conviction` 이 기본이라 기존 행과 기존 수집기가
#: 전부 자동으로 옳은 쪽에 앉는다.
CONVICTION = "conviction"
DEALER = "dealer"

# edgartools User-Agent (SEC 정책 준수)
EDGAR_IDENTITY = "Nuri-Quant research@nuri-quant.dev"


class SuperinvestorCollector(BaseCollector):
    """SEC EDGAR 13F로 슈퍼투자자 포트폴리오 수집."""

    #: 수집 대상. **`None` 이면 호출 시점에 `SUPERINVESTORS` 를 읽는다** — 클래스 속성에
    #: 상수를 바로 박으면 정의 시점 바인딩이라 모듈 상수를 갈아끼워도 반영되지 않는다
    #: (테스트 18곳이 그 방식으로 레지스트리를 좁힌다. 조용히 8명 전체를 돌면서 통과한다).
    #: 서브클래스는 명시로 덮는다.
    investors: Optional[dict] = None
    investor_class: str = CONVICTION
    #: `None` 이면 전량 저장. set 이면 그 티커만 — 은행 13F 전량 미러를 막는다.
    universe: Optional[set] = None

    def __init__(self, name: str = "superinvestors"):
        super().__init__(name)

    def collect(self, **kwargs) -> list[dict]:
        """전체 슈퍼투자자의 13F 수집.

        Args (via kwargs):
            quarters: 수집할 분기 수 (기본 8, 최대 20)
        """
        from edgar import Company, set_identity
        from tqdm import tqdm

        set_identity(EDGAR_IDENTITY)

        num_quarters = kwargs.get("quarters", 8)
        results = []
        succeeded: list[str] = []
        failed: list[str] = []

        investors_list = list((self.investors if self.investors is not None else SUPERINVESTORS).items())
        self.logger.info(
            f"13F 수집({self.investor_class}): {len(investors_list)}곳, 최근 {num_quarters}분기"
            + (f", universe {len(self.universe)}종목으로 제한" if self.universe is not None else "")
        )
        iterator = tqdm(investors_list, desc="  superinvestors", unit="inv", disable=len(investors_list) < 5)

        for investor_name, cik in iterator:
            try:
                self.logger.debug(f"{investor_name} ({cik}) 13F 수집 중...")
                company = Company(cik)
                filings = company.get_filings(form="13F-HR")

                if not filings or len(filings) == 0:
                    self.logger.warning(f"{investor_name}: 13F 공시 없음")
                    continue

                count = 0
                for filing in filings[:num_quarters]:
                    filing_date = str(filing.filing_date)
                    try:
                        filing_obj = filing.obj()
                        infotable = filing_obj.infotable
                    except Exception as e:
                        self.logger.warning(f"{investor_name} {filing_date}: 파싱 실패 — {e}")
                        continue

                    if infotable is None or infotable.empty:
                        self.logger.warning(f"{investor_name} {filing_date}: 보유종목 데이터 없음")
                        continue

                    # 티커별 합산 (같은 종목이 여러 줄로 나옴)
                    grouped = (
                        infotable.groupby("Ticker")
                        .agg(
                            {
                                "Value": "sum",
                                "SharesPrnAmount": "sum",
                                "Issuer": "first",
                            }
                        )
                        .reset_index()
                    )

                    total_value = grouped["Value"].sum()
                    if total_value == 0:
                        continue

                    kept = 0
                    for _, row in grouped.iterrows():
                        ticker = row["Ticker"]
                        if not ticker or pd.isna(ticker):
                            continue
                        # universe 필터는 **비중 계산 뒤**다. 먼저 걸러 버리면 분모가
                        # 우리 유니버스 합이 되어 `portfolio_pct` 가 실제 비중보다
                        # 부풀고, 화면에서 "JPM 포트폴리오의 12%" 같은 거짓이 된다.
                        if self.universe is not None and ticker not in self.universe:
                            continue

                        pct = row["Value"] / total_value * 100

                        results.append(
                            {
                                "investor": investor_name,
                                "filing_date": filing_date,
                                "ticker": ticker,
                                "shares": float(row["SharesPrnAmount"]),
                                "market_value": float(row["Value"]),
                                "portfolio_pct": round(pct, 4),
                                "issuer_name": row["Issuer"],
                                "investor_class": self.investor_class,
                            }
                        )
                        kept += 1

                    count += 1
                    self.logger.info(
                        f"  {investor_name} {filing_date}: {len(grouped)}종목 중 {kept}건 저장, 총 ${total_value:,.0f}"
                    )

                self.logger.debug(f"{investor_name}: {count}분기 수집 완료")
                succeeded.append(investor_name)

            except Exception as e:
                failed.append(investor_name)
                self.logger.debug(f"{investor_name}: 수집 실패 — {e}")
                continue

        if len(investors_list) >= 5:
            sample = ", ".join(failed[:3]) + (f" 외 {len(failed) - 3}명" if len(failed) > 3 else "")
            self.logger.info(
                "📊 슈퍼투자자 13F: ✅ %d 성공 / ❌ %d 실패 — total %d filings — failed: %s",
                len(succeeded),
                len(failed),
                len(results),
                sample or "없음",
            )

        return results

    def save(self, data: Any) -> int:
        """슈퍼투자자 데이터 DB 저장."""
        if not data:
            return 0
        return _upsert_superinvestors(data)


def _upsert_superinvestors(records: list[dict], db_path=None) -> int:
    """superinvestors 테이블에 upsert.

    ⚠️ `investor_class` 를 **반드시** 함께 쓴다. `INSERT OR REPLACE` 는 충돌 시 기존 행을
    지우고 새로 넣으므로, 컬럼을 빼면 재수집 때마다 `dealer` 행이 컬럼 기본값인
    `conviction` 으로 조용히 되돌아간다 — 그러면 은행 보유가 확신 신호에 섞인다.
    """
    if not records:
        return 0
    with get_db(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO superinvestors
               (investor, filing_date, ticker, shares, market_value,
                portfolio_pct, issuer_name, investor_class)
               VALUES (:investor, :filing_date, :ticker, :shares, :market_value,
                       :portfolio_pct, :issuer_name, :investor_class)""",
            [{"investor_class": CONVICTION, **r} for r in records],
        )
        return len(records)


class Bank13FCollector(SuperinvestorCollector):
    """대형 은행 4곳 13F — `dealer` 로 격리 저장 (#1098).

    같은 테이블에 넣되 `investor_class='dealer'` 라 `smart_money` / `min_superinvestors`
    같은 확신 신호는 이 행을 보지 못한다. 그 분리가 이 클래스의 존재 이유다 — 섞으면
    거의 모든 티커가 "슈퍼투자자 4명 보유" 가 되어 그 항의 변별력이 0이 된다.

    universe 로 좁히는 이유: 한 분기 77,795 포지션 중 대부분은 우리가 판단하지 않는
    종목·채권·옵션이다. 전량 미러는 8분기에 622K 행을 쌓고 어떤 질문에도 답하지 않는다.
    """

    investors = BANK_13F
    investor_class = DEALER

    def __init__(self):
        super().__init__("bank_13f")
        from nuri.core.coverage import _load_universe

        self.universe = _load_universe()["us"]


def detect_changes(investor: str, db_path=None) -> pd.DataFrame:
    """분기 간 포지션 변화 감지 (NEW/INCREASED/DECREASED/CLOSED/UNCHANGED).

    Returns:
        DataFrame with columns: investor, filing_date, prev_filing_date, ticker,
                                 change_type, shares, prev_shares, issuer_name
    """
    quarters = query(
        "SELECT DISTINCT filing_date FROM superinvestors WHERE investor = ? ORDER BY filing_date",
        (investor,),
        db_path=db_path,
    )
    if len(quarters) < 2:
        return pd.DataFrame()

    all_changes = []

    for i in range(1, len(quarters)):
        prev_date = quarters[i - 1]["filing_date"]
        curr_date = quarters[i]["filing_date"]

        prev_rows = query(
            "SELECT ticker, shares, issuer_name FROM superinvestors WHERE investor = ? AND filing_date = ?",
            (investor, prev_date),
            db_path=db_path,
        )
        curr_rows = query(
            "SELECT ticker, shares, issuer_name FROM superinvestors WHERE investor = ? AND filing_date = ?",
            (investor, curr_date),
            db_path=db_path,
        )

        prev_map = {r["ticker"]: r for r in prev_rows}
        curr_map = {r["ticker"]: r for r in curr_rows}

        prev_tickers = set(prev_map.keys())
        curr_tickers = set(curr_map.keys())

        # NEW: 이번 분기 신규
        for t in curr_tickers - prev_tickers:
            all_changes.append(
                {
                    "investor": investor,
                    "filing_date": curr_date,
                    "prev_filing_date": prev_date,
                    "ticker": t,
                    "change_type": "NEW",
                    "shares": curr_map[t]["shares"],
                    "prev_shares": 0,
                    "issuer_name": curr_map[t]["issuer_name"],
                }
            )

        # CLOSED: 이번 분기 청산
        for t in prev_tickers - curr_tickers:
            all_changes.append(
                {
                    "investor": investor,
                    "filing_date": curr_date,
                    "prev_filing_date": prev_date,
                    "ticker": t,
                    "change_type": "CLOSED",
                    "shares": 0,
                    "prev_shares": prev_map[t]["shares"],
                    "issuer_name": prev_map[t]["issuer_name"],
                }
            )

        # 기존 보유 비교
        for t in curr_tickers & prev_tickers:
            curr_shares = curr_map[t]["shares"]
            prev_shares = prev_map[t]["shares"]
            if prev_shares == 0:
                change = "INCREASED"
            elif curr_shares > prev_shares * 1.05:
                change = "INCREASED"
            elif curr_shares < prev_shares * 0.95:
                change = "DECREASED"
            else:
                change = "UNCHANGED"

            all_changes.append(
                {
                    "investor": investor,
                    "filing_date": curr_date,
                    "prev_filing_date": prev_date,
                    "ticker": t,
                    "change_type": change,
                    "shares": curr_shares,
                    "prev_shares": prev_shares,
                    "issuer_name": curr_map[t]["issuer_name"],
                }
            )

    return pd.DataFrame(all_changes) if all_changes else pd.DataFrame()


def print_summary():
    """슈퍼투자자 보유 현황 출력."""
    investors = query(
        "SELECT DISTINCT investor FROM superinvestors WHERE investor_class = 'conviction' ORDER BY investor"
    )
    if not investors:
        print("슈퍼투자자 데이터가 없습니다.")
        return

    # 내 보유종목
    my_tickers = set(r["ticker"] for r in query("SELECT DISTINCT ticker FROM portfolio"))

    print(f"\n{'=' * 70}")
    print("  슈퍼투자자 포트폴리오 (SEC 13F)")
    print(f"{'=' * 70}")

    for inv in investors:
        name = inv["investor"]
        rows = query(
            """SELECT ticker, issuer_name, portfolio_pct, market_value, filing_date
               FROM superinvestors
               WHERE investor = ?
               ORDER BY portfolio_pct DESC LIMIT 10""",
            (name,),
        )
        if not rows:
            continue

        filing_date = rows[0]["filing_date"]
        total = sum(
            r["market_value"] for r in query("SELECT market_value FROM superinvestors WHERE investor = ?", (name,))
        )

        print(f"\n  {name} (공시일: {filing_date}, 총 ${total:,.0f})")
        print(f"  {'Ticker':<10} {'종목명':<25} {'비중%':>8} {'내보유':>6}")
        print(f"  {'-' * 52}")

        for r in rows:
            mine = " *" if r["ticker"] in my_tickers else ""
            print(f"  {r['ticker']:<10} {r['issuer_name'][:24]:<25} {r['portfolio_pct']:>7.1f}%{mine}")

    # 내 보유종목 중 슈퍼투자자도 보유한 종목
    overlap = query(
        """SELECT s.ticker, GROUP_CONCAT(DISTINCT s.investor) as investors
           FROM superinvestors s
           WHERE s.ticker IN (SELECT DISTINCT ticker FROM portfolio)
             AND s.investor_class = 'conviction'
           GROUP BY s.ticker
           ORDER BY s.ticker"""
    )
    if overlap:
        print(f"\n  {'=' * 50}")
        print("  내 보유종목 중 슈퍼투자자도 보유:")
        for r in overlap:
            print(f"    {r['ticker']}: {r['investors']}")

    print()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    collector = SuperinvestorCollector()
    collector.run()
    print_summary()
