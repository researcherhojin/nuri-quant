"""은행 13F(`dealer`)가 확신 신호에 섞이지 않는지 (#1098).

## 왜 필터가 규율이 아니라 **기계 검사**여야 하나

은행 4곳은 마켓메이킹·수탁·인덱스로 사실상 미국 유니버스 전체를 들고 있다(2026-08-18
EDGAR 실측: JPM 34,064 · BAC 18,318 · GS 14,070 · Citi 11,343 포지션). 그래서 필터를 한
군데만 빠뜨려도 그 소비자는 **거의 모든 티커에서 같은 값**을 내고, 그건 틀린 값이 아니라
**변별력이 0인 값**이라 화면에서 정상으로 보인다. `smart_money` 의 `min(2, 보유 수)` 가
정확히 그 모양이다 — 상수 2가 되어도 아무도 모른다.

그래서 두 층으로 잠근다:
- **동작** — 딜러 행을 심어도 점수·표시·커버리지가 변하지 않는다
- **구조** — `superinvestors` 를 읽는 모든 SQL 리터럴이 `investor_class` 를 걸거나
  allowlist 에 사유와 함께 등재. 양방향이라 낡은 항목도 FAIL

⚠️ 구조 스윕의 한계를 알고 쓴다: 테이블명이 f-string 변수인 쿼리는 리터럴에
`superinvestors` 가 없어 **보이지 않는다**(`coverage.py::_table_tickers`). 그래서 그쪽은
`_COVERAGE_FILTERS` 로 명시 처리하고 동작 테스트로 따로 잠갔다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nuri.collectors.superinvestors import CONVICTION, DEALER, _upsert_superinvestors
from nuri.core.db import get_db, init_db, query

NURI = Path(__file__).resolve().parents[2] / "nuri"

#: `investor_class` 를 안 거는 것이 옳은 쿼리. **사유 필수**.
ALLOWED: dict[tuple[str, str], str] = {
    (
        "collectors/superinvestors.py",
        "INSERT OR REPLACE INTO superinvestors",
    ): "writer — 컬럼을 직접 쓴다",
    (
        "collectors/superinvestors.py",
        "SELECT DISTINCT filing_date FROM superinvestors WHERE investor = ?",
    ): "detect_changes — investor 이름으로 이미 좁혀져 class 가 중복",
    (
        "collectors/superinvestors.py",
        "SELECT ticker, shares, issuer_name FROM superinvestors WHERE investor = ? AND filing_date = ?",
    ): "detect_changes — 위와 같은 이유",
    (
        "collectors/superinvestors.py",
        "SELECT ticker, issuer_name, portfolio_pct, market_value, filing_date FROM superinvestors WHERE investor = ?",
    ): "print_summary — 구동 쿼리가 conviction 만 뽑아 넘긴 이름으로 좁혀진다",
    (
        "collectors/superinvestors.py",
        "SELECT market_value FROM superinvestors WHERE investor = ?",
    ): "print_summary — 위와 같은 이유",
}


def _sql_literals() -> list[tuple[str, str]]:
    """`nuri/` 안의 SQL 문자열 리터럴 중 superinvestors 를 건드리는 것.

    파이썬은 인접 문자열 리터럴을 **파싱 시점에 하나로 접으므로** 여러 줄로 쪼갠 SQL 도
    하나의 `Constant` 로 잡힌다 — 조각마다 따로 검사해 놓치는 일이 없다.
    """
    found = []
    for path in sorted(NURI.rglob("*.py")):
        rel = str(path.relative_to(NURI))
        if rel == "core/db_migrations.py":  # 스키마 정의 자체
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            sql = " ".join(node.value.split())
            if "superinvestors" not in sql:
                continue
            if not any(v in sql.upper() for v in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                continue
            found.append((rel, sql))
    return found


class TestEveryQueryDecides:
    def test_the_sweep_actually_finds_queries(self):
        """스윕이 0건을 찾고도 통과하면 이 파일 전체가 장식이다."""
        assert len(_sql_literals()) >= 5

    def test_every_superinvestor_query_filters_or_is_allowlisted(self):
        offenders = []
        for rel, sql in _sql_literals():
            if "investor_class" in sql:
                continue
            if any(rel == a_rel and sql.startswith(a_sql) for a_rel, a_sql in ALLOWED):
                continue
            offenders.append(f"{rel}: {sql[:110]}")
        assert not offenders, (
            "`superinvestors` 를 읽는데 investor_class 를 안 건 쿼리:\n  "
            + "\n  ".join(offenders)
            + "\n확신 신호면 investor_class='conviction' 을 걸고, 아니면 ALLOWED 에 사유와 함께 등재."
        )

    def test_allowlist_has_no_stale_entries(self):
        """해소된 항목이 남아 있으면 다음 위반을 조용히 통과시킨다."""
        live = {(rel, sql) for rel, sql in _sql_literals()}
        stale = [
            f"{rel}: {sql[:80]}"
            for rel, sql in ALLOWED
            if not any(a_rel == rel and a_sql.startswith(sql) for a_rel, a_sql in live)
        ]
        assert not stale, "ALLOWED 에 더 이상 존재하지 않는 쿼리:\n  " + "\n  ".join(stale)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _seed(db_path, ticker="ZZZZ"):
    """확신 1명 + 딜러 4곳. 딜러가 신호를 오염시키면 아래 단언들이 깨진다."""
    _upsert_superinvestors(
        [
            {
                "investor": "Conviction One",
                "filing_date": "2026-05-15",
                "ticker": ticker,
                "shares": 1000.0,
                "market_value": 1_000_000.0,
                "portfolio_pct": 8.0,
                "issuer_name": "Example Corp",
                "investor_class": CONVICTION,
            }
        ]
        + [
            {
                "investor": f"Dealer {i}",
                "filing_date": "2026-05-15",
                "ticker": ticker,
                "shares": 500.0,
                "market_value": 500_000.0,
                "portfolio_pct": 0.01,
                "issuer_name": "Example Corp",
                "investor_class": DEALER,
            }
            for i in range(4)
        ],
        db_path=db_path,
    )


class TestDealerRowsDoNotReachConvictionSignals:
    def test_smart_money_counts_only_conviction_holders(self, db_path):
        """`min(2, 보유 수)` 항이 딜러로 채워지면 거의 모든 티커에서 상수가 된다."""
        from nuri.trading.agents.smart_money import SmartMoneyAgent

        _seed(db_path)
        verdict = SmartMoneyAgent().analyze("ZZZZ", db_path=db_path)

        assert verdict.data_points["n_superinvestors"] == 1, "딜러 4곳이 확신 보유로 세어졌다"

    def test_coverage_counts_only_conviction_tickers(self, db_path):
        """딜러는 유니버스 전체를 들고 있어, 세면 커버리지가 자동으로 임계를 넘는다."""
        from nuri.core.coverage import _table_tickers

        _upsert_superinvestors(
            [
                {
                    "investor": "Dealer One",
                    "filing_date": "2026-05-15",
                    "ticker": t,
                    "shares": 1.0,
                    "market_value": 1.0,
                    "portfolio_pct": 0.0,
                    "issuer_name": t,
                    "investor_class": DEALER,
                }
                for t in ("AAAA", "BBBB", "CCCC")
            ],
            db_path=db_path,
        )
        _seed(db_path, ticker="DDDD")

        assert _table_tickers("superinvestors", db_path=db_path) == {"DDDD"}


class TestUpsertKeepsTheClass:
    def test_reupserting_a_dealer_row_does_not_reset_it(self, db_path):
        """`INSERT OR REPLACE` 는 행을 지우고 새로 넣는다 — 컬럼을 빼면 기본값으로 되돌아간다.

        그러면 재수집 때마다 은행 보유가 조용히 확신 신호로 승격된다.
        """
        _seed(db_path)
        _seed(db_path)  # 같은 (investor, filing_date, ticker) → REPLACE 경로

        rows = query(
            "SELECT investor_class, COUNT(*) AS n FROM superinvestors GROUP BY investor_class",
            db_path=db_path,
        )
        assert {r["investor_class"]: r["n"] for r in rows} == {CONVICTION: 1, DEALER: 4}

    def test_a_record_without_a_class_defaults_to_conviction(self, db_path):
        """기존 수집기는 이 키를 안 보낸다 — 기본값이 틀리면 15,600 행이 오분류된다."""
        _upsert_superinvestors(
            [
                {
                    "investor": "Legacy",
                    "filing_date": "2026-05-15",
                    "ticker": "EEEE",
                    "shares": 1.0,
                    "market_value": 1.0,
                    "portfolio_pct": 1.0,
                    "issuer_name": "E",
                }
            ],
            db_path=db_path,
        )

        assert query("SELECT investor_class FROM superinvestors", db_path=db_path)[0]["investor_class"] == CONVICTION


class TestBankRegistry:
    def test_banks_are_not_in_the_conviction_registry(self):
        """한 dict 에 섞이면 기존 수집기가 은행을 확신으로 저장한다."""
        from nuri.collectors.superinvestors import BANK_13F, SUPERINVESTORS

        assert not set(BANK_13F) & set(SUPERINVESTORS)

    def test_bank_collector_is_a_dealer_and_is_universe_bounded(self):
        """universe 를 안 걸면 한 분기 77,795 포지션이 그대로 들어온다."""
        from nuri.collectors.superinvestors import Bank13FCollector

        c = Bank13FCollector()
        assert c.investor_class == DEALER
        assert c.universe, "universe 필터가 비어 있다 — 전량 미러가 된다"

    def test_ciks_are_ten_digit_strings(self):
        """EDGAR 는 0 패딩 10자리를 쓴다 — 잘리면 조용히 다른 회사이거나 404 다."""
        from nuri.collectors.superinvestors import BANK_13F

        for name, cik in BANK_13F.items():
            assert len(cik) == 10 and cik.isdigit(), f"{name}: {cik!r}"


class TestDealerRowsAreStillReachable:
    def test_a_dealer_row_can_be_read_back(self, db_path):
        """격리가 은닉이 되면 안 된다 — 은행 보유는 전용 경로로 읽을 수 있어야 한다."""
        _seed(db_path)

        with get_db(db_path) as conn:
            n = conn.execute("SELECT COUNT(*) FROM superinvestors WHERE investor_class = ?", (DEALER,)).fetchone()[0]
        assert n == 4


class TestRegistryResolvesAtRuntime:
    """`investors` 는 호출 시점에 읽는다 — 클래스 속성에 상수를 박으면 안 된다 (Codex P1).

    `investors: dict = SUPERINVESTORS` 는 **클래스 정의 시점** 바인딩이라 모듈 상수를
    갈아끼워도 `collect()` 가 못 본다. 레지스트리를 좁히는 테스트 18곳이 그러면 조용히
    8명 전체를 돌면서 **통과**한다 — 틀린 결과가 아니라 무의미한 결과라 눈에 안 띈다.
    """

    def test_patching_the_module_constant_narrows_collect(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from nuri.collectors.superinvestors import SuperinvestorCollector

        monkeypatch.setattr("nuri.collectors.superinvestors.SUPERINVESTORS", {"Only One": "0000000001"})
        seen = []

        def _company(cik):
            seen.append(cik)
            m = MagicMock()
            m.get_filings.return_value = []
            return m

        with patch("edgar.set_identity"), patch("edgar.Company", side_effect=_company):
            SuperinvestorCollector().collect(quarters=1)

        assert seen == ["0000000001"], f"레지스트리가 안 좁혀졌다 — {len(seen)}곳을 돌았다"

    def test_the_bank_collector_still_overrides_it(self):
        from nuri.collectors.superinvestors import BANK_13F, Bank13FCollector

        assert Bank13FCollector().investors == BANK_13F


class TestUniverseFilterRunsAfterTheWeight:
    """universe 로 좁히되 `portfolio_pct` 는 **실제 포트폴리오 대비** 비중이어야 한다.

    필터를 비중 계산 **앞**에 두면 분모가 우리 유니버스 합이 되어 비중이 부풀고, 화면에
    "JPM 포트폴리오의 12%" 같은 거짓이 실린다. 실제로는 0.3% 인데 말이다. 그 오류는
    숫자가 그럴듯해서 검토로는 절대 안 걸린다.
    """

    def _collect(self, universe):
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from nuri.collectors.superinvestors import Bank13FCollector

        infotable = pd.DataFrame(
            {
                "Ticker": ["AAAA", "BBBB", "CCCC"],
                "Value": [10e6, 30e6, 60e6],
                "SharesPrnAmount": [100.0, 300.0, 600.0],
                "Issuer": ["A Corp", "B Corp", "C Corp"],
            }
        )
        filing = MagicMock()
        filing.filing_date = "2026-05-15"
        filing.obj.return_value = MagicMock(infotable=infotable)
        filings = MagicMock()
        filings.__len__ = lambda self: 1
        filings.__getitem__ = lambda self, i: [filing][i]
        filings.__bool__ = lambda self: True
        company = MagicMock()
        company.get_filings.return_value = filings

        collector = Bank13FCollector()
        collector.investors = {"Test Bank": "0000000001"}
        collector.universe = universe
        with patch("edgar.set_identity"), patch("edgar.Company", return_value=company):
            return collector.collect(quarters=1)

    def test_out_of_universe_tickers_are_dropped(self):
        got = self._collect({"AAAA"})

        assert [r["ticker"] for r in got] == ["AAAA"]

    def test_the_kept_weight_is_of_the_whole_portfolio(self):
        """AAAA 는 전체 1억 중 1천만 = 10%. 유니버스만 세면 100% 로 부푼다."""
        got = self._collect({"AAAA"})

        assert got[0]["portfolio_pct"] == pytest.approx(10.0)
        assert got[0]["investor_class"] == DEALER

    def test_no_universe_keeps_everything(self):
        assert len(self._collect(None)) == 3


class TestSchedulerRunsTheBankCollector:
    """잡을 등록만 하고 dispatcher 분기가 없으면 조용히 안 돈다 — 분기를 실행해서 본다."""

    def test_dispatch_reaches_the_bank_collector(self):
        from unittest.mock import patch

        import nuri.scheduler as sch

        with patch("nuri.collectors.superinvestors.Bank13FCollector.run") as run:
            sch._dispatch_collector("bank_13f")

        run.assert_called_once()
        assert run.call_args.kwargs.get("quarters"), "분기 수를 안 넘기면 기본 8분기가 돈다"

    def test_the_job_is_registered_and_staged(self):
        import nuri.scheduler as sch

        assert sch._STAGE_OF_JOB["bank_13f"] == "collect"
        scheduled = {j["args"][0] for j in sch.SCHEDULES if j.get("func") is sch._run_collector and j.get("args")}
        assert "bank_13f" in scheduled

    def test_the_bank_job_is_separate_from_the_conviction_job(self):
        """한 잡에 합치면 은행 쪽 EDGAR 실패가 확신 13F 수집까지 같이 죽인다."""
        import nuri.scheduler as sch

        jobs = {j["args"][0]: j["cron"] for j in sch.SCHEDULES if j.get("func") is sch._run_collector and j.get("args")}
        assert jobs["bank_13f"] != jobs["superinvestors"]
