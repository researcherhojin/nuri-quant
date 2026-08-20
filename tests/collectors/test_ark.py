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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

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
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert not [r for r in rows if r["ticker"] == "TSLA"]

    def test_no_exit_rows_when_the_fetch_yielded_nothing(self, held):
        """CSV 가 비었거나 전부 걸러졌으면 청산이라 단정하지 않는다 — 그건 소스 문제다."""
        from nuri.collectors.ark import ARKCollector

        self._seed_prior(held)
        empty = "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
        with patch("nuri.collectors.ark.requests.get", return_value=_resp(empty)):
            rows, _ = ARKCollector()._collect_fund("http://x/y.csv", "ARKK", {"TSLA", "AMD"}, held)

        assert rows == []


class TestArkSourceStaleness:
    """소스가 200 인 채로 내용만 어는 경우 (#1145)."""

    def _csv(self, csv_date: str, fund: str = "ARKK") -> str:
        return (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            f'{csv_date},{fund},TESLA INC,TSLA,88160R101,"1,000","$1,000.00",1.00%\n'
        )

    def test_stale_fund_is_warned(self, held, caplog):
        """ARKF 는 7.5개월 전 보유를 담은 CSV 를 200 으로 정상 서빙하고 있었다.
        다운로드도 파싱도 성공하므로 이 경고가 없으면 아무 신호가 없다."""
        import logging

        from nuri.collectors.ark import ARKCollector

        with caplog.at_level(logging.WARNING):
            ARKCollector()._warn_stale_funds({"ARKF": "2026-01-02"})

        assert any("ARKF" in r.getMessage() for r in caplog.records)
        assert any("낡음" in (r.getMessage()) for r in caplog.records)

    def test_fresh_fund_is_silent(self, held, caplog):
        """정상 지연(전 영업일)에 경고를 내면 경고가 소음이 되어 아무도 안 본다."""
        import logging

        from nuri.collectors.ark import ARKCollector
        from nuri.core.timezone import today_kst

        with caplog.at_level(logging.WARNING):
            ARKCollector()._warn_stale_funds({"ARKK": today_kst()})

        assert not [r for r in caplog.records if "낡음" in (r.getMessage())]

    def test_a_stale_fund_does_not_hide_behind_fresh_ones(self, held, caplog):
        """펀드별로 본다 — 합쳐서 최신 하나만 보면 죽은 펀드가 멀쩡한 펀드 뒤로 숨는다."""
        import logging

        from nuri.collectors.ark import ARKCollector
        from nuri.core.timezone import today_kst

        with caplog.at_level(logging.WARNING):
            ARKCollector()._warn_stale_funds({"ARKK": today_kst(), "ARKG": today_kst(), "ARKF": "2026-01-02"})

        warned = [r.getMessage() for r in caplog.records if "낡음" in (r.getMessage())]
        assert len(warned) == 1
        assert "ARKF" in warned[0]

    def test_collect_wires_the_staleness_check(self, held, caplog):
        """`_warn_stale_funds` 를 직접 부르는 테스트만으로는 **호출 배선**이 안 잠긴다 —
        `collect()` 에서 그 한 줄을 지워도 초록이었다. 수집 경로 전체로 확인한다."""
        import logging

        from nuri.collectors.ark import ARK_HOLDINGS_FILES, ARKCollector
        from nuri.core.timezone import today_kst

        fresh = self._csv(f"{today_kst()[5:7]}/{today_kst()[8:10]}/{today_kst()[:4]}")
        stale = self._csv("01/02/2026")
        # 첫 펀드만 얼어 있고 나머지는 당일
        seq = [_resp(stale)] + [_resp(fresh)] * (len(ARK_HOLDINGS_FILES) - 1)

        with caplog.at_level(logging.WARNING):
            with patch("nuri.collectors.ark.requests.get", side_effect=seq):
                ARKCollector().collect(db_path=held)

        warned = [r.getMessage() for r in caplog.records if "낡음" in r.getMessage()]
        assert len(warned) == 1
        assert "2026-01-02" in warned[0]

    def test_a_stale_fund_we_hold_nothing_from_is_still_warned(self, held, caplog):
        """**소스 감시가 우리 포트폴리오 구성에 의존하면 안 된다** (#1145 codex P1).

        날짜를 보유 종목 필터 뒤에서 읽으면, 우리가 아무것도 안 겹치는 펀드는 records 가
        비어 fund_date 가 안 생기고 → 낡아도 경고가 없다. ARKF 가 그 상태로 미끄러지는 데
        필요한 건 우리가 ARKF 보유 종목을 하나도 안 들게 되는 것뿐이다.
        """
        import logging

        from nuri.collectors.ark import ARKCollector

        # CSV 는 낡았고, 담긴 종목은 우리 보유(TSLA/AMD)와 하나도 안 겹친다
        stale_no_overlap = (
            "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
            '01/02/2026,ARKF,SHOPIFY INC - CLASS A,SHOP,82509L107,"662,061","$1.00",9.65%\n'
        )
        with caplog.at_level(logging.WARNING):
            with patch("nuri.collectors.ark.requests.get", return_value=_resp(stale_no_overlap)):
                rows, csv_date = ARKCollector()._collect_fund("http://x/y.csv", "ARKF", {"TSLA", "AMD"}, held)

        assert rows == []  # 겹치는 보유 종목 없음
        assert csv_date == "2026-01-02"  # 그래도 날짜는 나온다

    def test_a_fund_with_no_usable_date_records_no_lag(self, held, caplog):
        """헤더만 있거나 날짜를 하나도 못 읽은 펀드는 지연 판정 대상이 아니다 —
        모르는 것을 0일 낡음으로도, 무한히 낡음으로도 단정하지 않는다."""
        import logging

        from nuri.collectors.ark import ARK_HOLDINGS_FILES, ARKCollector

        header_only = "date,fund,company,ticker,cusip,shares,market value ($),weight (%)\n"
        seq = [_resp(header_only)] * len(ARK_HOLDINGS_FILES)

        with caplog.at_level(logging.WARNING):
            with patch("nuri.collectors.ark.requests.get", side_effect=seq):
                assert ARKCollector().collect(db_path=held) == []

        assert not [r for r in caplog.records if "낡음" in r.getMessage()]
