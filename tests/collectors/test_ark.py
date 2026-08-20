"""ARK 수집기 테스트 (#1143).

이 수집기에는 테스트가 없었다. 그래서 CSV 소스 2개가 죽고 폴백이 매매 아닌
보유 스냅샷을 `direction="Hold"` 로 쓰는 상태가 몇 달간 아무 신호 없이 지나갔다.
"""

from unittest.mock import MagicMock, patch

import pytest

from nuri.core.db import get_db, query

# 실제 CSV 형태 — 소문자 컬럼, 콤마 섞인 숫자, `weight (%)`, 마지막 면책 문구 행,
# 그리고 비상장 보유분(ticker 빈 칸)까지 그대로 재현한다.
ARKK_CSV = (
    "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
    '08/20/2026,ARKK,TESLA INC,TSLA,88160R101,"1,713,664","$601,701,703.70",9.36%\n'
    '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"434,775","$202,777,545.00",3.15%\n'
    '08/20/2026,ARKK,NOT HELD BY US,ZZZZ,111111111,"1,000","$1,000.00",0.01%\n'
    '08/20/2026,ARKK,BRERA HOLDINGS PLC-CL B,,G13311132,"268,782","$1,135,603.95",0.02%\n'
    '"Investors should carefully consider the investment objectives and risks."\n'
)


def _resp(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.raise_for_status.return_value = None
    return r


@pytest.fixture
def held(db_path):
    """보유 종목 2개를 심는다 (공개 레포 — 임의 값)."""
    with get_db(db_path) as c:
        for t in ("TSLA", "AMD"):
            c.execute(
                "INSERT INTO portfolio (ticker, quantity, avg_price, account) VALUES (?,?,?,?)",
                (t, 10, 100.0, "Brokerage Alpha"),
            )
    return db_path


class TestArkCsvParsing:
    def test_parses_current_lowercase_columns(self, held):
        """`ticker` / `shares` / `weight (%)` — 예전 파서는 `% of ETF` 만 봤다."""
        from nuri.collectors.ark import ARKCollector

        with patch("nuri.collectors.ark.requests.get", return_value=_resp(ARKK_CSV)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        by_ticker = {r["ticker"]: r for r in rows}
        assert set(by_ticker) == {"TSLA", "AMD"}
        assert by_ticker["TSLA"]["shares"] == 1713664.0  # 콤마 제거
        assert by_ticker["TSLA"]["weight"] == 9.36  # '%' 제거
        assert by_ticker["TSLA"]["date"] == "2026-08-20"  # MM/DD/YYYY → ISO
        assert by_ticker["TSLA"]["fund"] == "ARKK"

    def test_skips_disclaimer_row_and_unlisted_holdings(self, held):
        """면책 문구 행과 ticker 없는 비상장 보유분은 ticker 가 비어 걸러진다."""
        from nuri.collectors.ark import ARKCollector

        with patch("nuri.collectors.ark.requests.get", return_value=_resp(ARKK_CSV)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert all(r["ticker"] for r in rows)
        assert "ZZZZ" not in {r["ticker"] for r in rows}  # 보유 종목 필터


class TestArkDirectionDerivation:
    """ARK 는 매매가 아니라 보유 스냅샷을 낸다 — 방향은 직전 보유분 대비 증감이다."""

    def _derive(self, db_path, prev_shares, now_shares, prev_date="2026-08-19"):
        from nuri.collectors.ark import ARKCollector

        if prev_shares is not None:
            with get_db(db_path) as c:
                c.execute(
                    "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                    (prev_date, "TSLA", "Hold", prev_shares, 1.0, "ARKK"),
                )
        return ARKCollector()._derive_direction("TSLA", "ARKK", "2026-08-20", now_shares, db_path)

    def test_increase_is_a_buy(self, db_path):
        assert self._derive(db_path, 1000.0, 1100.0) == "Buy"

    def test_decrease_is_a_sell(self, db_path):
        assert self._derive(db_path, 1000.0, 900.0) == "Sell"

    def test_noise_below_threshold_is_hold(self, db_path):
        """ARK 는 매일 소수점 수준으로 리밸런싱한다 — 0 이 아닌 모든 변화를 매매라 부르면
        전 종목이 매일 신호를 낸다."""
        assert self._derive(db_path, 1000.0, 1005.0) == "Hold"

    def test_first_observation_claims_no_direction(self, db_path):
        """비교 대상이 없으면 방향을 주장하지 않는다 — 첫 관측은 Hold."""
        assert self._derive(db_path, None, 1000.0) == "Hold"

    def test_zero_share_snapshot_is_not_a_baseline(self, db_path):
        """폴백이 남긴 `shares=0.0` 행을 기준선으로 잡으면 다음 수집분이 통째로 Buy 가 된다.

        기준선 쿼리에서 `shares > 0` 을 빼면 이 테스트가 Buy 를 보고 실패한다.
        """
        assert self._derive(db_path, 0.0, 1000.0) == "Hold"

    def test_a_real_prior_wins_over_a_newer_zero_snapshot(self, db_path):
        """0 스냅샷이 더 최신이어도 진짜 보유분을 기준선으로 삼아야 한다."""
        with get_db(db_path) as c:
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                ("2026-08-10", "TSLA", "Hold", 1000.0, 1.0, "ARKK"),
            )
        assert self._derive(db_path, 0.0, 900.0) == "Sell"


class TestArkFailureIsNotEmptyCollection:
    """#1043 규약 — 전면 실패는 raise, 겹치는 종목 없음은 NO_DATA."""

    def test_total_failure_raises_instead_of_returning_empty(self, held):
        from nuri.collectors.ark import ARKCollector

        with patch("nuri.collectors.ark.requests.get", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                ARKCollector().collect(db_path=held)

    def test_first_error_is_raised_not_the_last(self, held):
        """마지막 것만 올리면 첫 펀드의 원인이 알림 문구에서 사라진다."""
        from nuri.collectors.ark import ARKCollector

        errs = [RuntimeError(f"err{i}") for i in range(5)]
        with patch("nuri.collectors.ark.requests.get", side_effect=errs):
            with pytest.raises(RuntimeError, match="err0"):
                ARKCollector().collect(db_path=held)

    def test_partial_failure_still_returns_what_worked(self, held):
        """한 펀드가 죽어도 나머지는 수집된다 — raise 조건이 `errors` 뿐이면 여기서 터진다."""
        from nuri.collectors.ark import ARKCollector

        seq = [RuntimeError("one fund down")] + [_resp(ARKK_CSV)] * 4
        with patch("nuri.collectors.ark.requests.get", side_effect=seq):
            rows = ARKCollector().collect(db_path=held)

        assert rows
        assert {r["ticker"] for r in rows} == {"TSLA", "AMD"}

    def test_no_overlap_is_no_data_not_failure(self, held):
        """200 인데 우리 보유 종목과 겹치는 게 없으면 예외가 아니라 빈 수집이다."""
        from nuri.collectors.ark import ARKCollector

        csv_no_overlap = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '08/20/2026,ARKK,SOMETHING ELSE,QQQQ,111,"1,000","$1,000.00",0.01%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(csv_no_overlap)):
            assert ARKCollector().collect(db_path=held) == []


class TestArkNoNetworkFallback:
    def test_yfinance_is_not_imported(self):
        """폴백은 top-10 보유 스냅샷을 `shares=0.0` 으로 써서 델타 기준선을 오염시켰다.
        지금은 소스가 살아 있으므로 제거했다 — 되살아나면 이 테스트가 잡는다.

        문자열 grep 이 아니라 AST 로 본다. 소스에 'yfinance' 가 등장하는 곳은 왜 뺐는지
        적어둔 주석·docstring 이라, grep 은 그 설명 자체에 걸려 영영 빨갛다.
        """
        import ast
        import inspect

        import nuri.collectors.ark as ark_mod

        tree = ast.parse(inspect.getsource(ark_mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert "yfinance" not in imported
        assert not hasattr(ark_mod.ARKCollector, "_collect_yfinance")


class TestArkSave:
    def test_save_persists_direction(self, held):
        from nuri.collectors.ark import ARKCollector

        with patch("nuri.collectors.ark.requests.get", return_value=_resp(ARKK_CSV)):
            rows = ARKCollector().collect(db_path=held)
        assert ARKCollector().save(rows) == len(rows)
        stored = query("SELECT ticker, direction, shares FROM ark ORDER BY ticker", db_path=held)
        assert {r["ticker"] for r in stored} == {"AMD", "TSLA"}


class TestArkMalformedInput:
    def test_unparseable_date_row_is_skipped(self, held):
        """날짜를 못 읽으면 그 행만 버린다 — parse_date 가 None 을 주는 경우."""
        from nuri.collectors.ark import ARKCollector

        bad = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '조만간,ARKK,TESLA INC,TSLA,88160R101,"1,000","$1,000.00",1.00%\n'
            '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"2,000","$2,000.00",2.00%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(bad)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert {r["ticker"] for r in rows} == {"AMD"}

    def test_amount_parsing(self):
        from nuri.collectors.ark import _to_float_or_none

        assert _to_float_or_none("1,713,664") == 1713664.0
        assert _to_float_or_none("$601,701,703.70") == 601701703.70
        assert _to_float_or_none("9.36%") == 9.36

    def test_unparseable_shares_is_none_not_zero(self):
        """0.0 으로 눕히면 방향 파생이 그걸 전량 청산으로 읽는다 — 포맷 드리프트가
        매도 신호로 둔갑한다 (#1143 codex P2)."""
        from nuri.collectors.ark import _to_float_or_none

        assert _to_float_or_none("N/A") is None
        assert _to_float_or_none(None) is None
        assert _to_float_or_none("") is None

    def test_row_with_unparseable_shares_is_dropped_not_zeroed(self, held):
        """shares 를 못 읽은 행은 버린다. 남겨서 0 으로 적으면 매도가 된다."""
        from nuri.collectors.ark import ARKCollector

        bad = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '08/20/2026,ARKK,TESLA INC,TSLA,88160R101,N/A,"$1,000.00",1.00%\n'
            '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"2,000","$2,000.00",2.00%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(bad)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert {r["ticker"] for r in rows} == {"AMD"}
        assert all(r["direction"] != "Sell" for r in rows)


class TestArkExits:
    """전량 청산과 펀드 간 이동 — 부재는 CSV 에 행으로 나타나지 않는다 (#1143 codex P1)."""

    def _seed_prior(self, db_path, fund="ARKK", ticker="TSLA", shares=1000.0, date="2026-08-19"):
        with get_db(db_path) as c:
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                (date, ticker, "Hold", shares, 1.0, fund),
            )

    def test_disappearing_ticker_becomes_a_sell(self, held):
        """어제 ARKK 가 TSLA 를 들고 있었는데 오늘 CSV 에 없다 → 전량 청산."""
        from nuri.collectors.ark import ARKCollector

        self._seed_prior(held)
        only_amd = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"2,000","$2,000.00",2.00%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(only_amd)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        exits = [r for r in rows if r["ticker"] == "TSLA"]
        assert len(exits) == 1
        assert exits[0]["direction"] == "Sell"
        assert exits[0]["shares"] == 0.0
        assert exits[0]["date"] == "2026-08-20"

    def test_exit_is_emitted_once_not_every_day(self, held):
        """어제 이미 0 으로 적힌 종목은 '보유 중이었다' 가 아니다 — 매일 Sell 을 다시 내면
        smart_money 의 LIMIT 5 창이 같은 청산으로 영원히 채워진다."""
        from nuri.collectors.ark import ARKCollector

        with get_db(held) as c:
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                ("2026-08-19", "TSLA", "Sell", 0.0, 0.0, "ARKK"),
            )
        only_amd = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"2,000","$2,000.00",2.00%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(only_amd)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert not [r for r in rows if r["ticker"] == "TSLA"]

    def test_reentry_after_exit_is_a_fresh_position_not_a_sell(self, held):
        """청산 뒤 더 작게 재진입한 것을 pre-exit 규모와 비교하면 Sell 로 뒤집힌다."""
        from nuri.collectors.ark import ARKCollector

        with get_db(held) as c:
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                ("2026-08-10", "TSLA", "Hold", 5000.0, 5.0, "ARKK"),
            )
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                ("2026-08-19", "TSLA", "Sell", 0.0, 0.0, "ARKK"),
            )
        assert ARKCollector()._derive_direction("TSLA", "ARKK", "2026-08-20", 100.0, held) == "Hold"

    def test_exit_only_covers_the_fund_that_lost_it(self, held):
        """ARKK 에서 빠져도 ARKW 는 별개 — 펀드별로 판단한다."""
        from nuri.collectors.ark import ARKCollector

        self._seed_prior(held, fund="ARKW")
        only_amd = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '08/20/2026,ARKK,ADVANCED MICRO DEVICES,AMD,007903107,"2,000","$2,000.00",2.00%\n'
        )
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(only_amd)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert not [r for r in rows if r["ticker"] == "TSLA"]

    def test_no_exit_rows_when_the_fetch_yielded_nothing(self, held):
        """CSV 가 비었거나 전부 걸러졌으면 청산이라 단정하지 않는다 — 그건 소스 문제다."""
        from nuri.collectors.ark import ARKCollector

        self._seed_prior(held)
        empty = "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(empty)):
            rows = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert rows == []
