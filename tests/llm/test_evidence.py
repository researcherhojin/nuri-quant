"""근거 묶음 (#1955) — 상태 5종 · 커버리지 게이트 · 공통 기준일 · 한 스냅샷 · 해시 · 보유 비접근."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

import nuri.core.db as db_mod
from nuri.core.db import get_db, init_db
from nuri.llm import evidence as ev

KST = timezone(timedelta(hours=9))
CUTOFF = datetime(2026, 3, 10, 9, 0, tzinfo=KST)  # 고정 cutoff 를 넘기므로 now-창 시한폭탄이 없다
D = "2026-03-09"
D_NEXT = "2026-03-10"
UNIVERSE = {"us": {f"T{i}" for i in range(10)}, "kr": set()}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def cfg():
    return copy.deepcopy(ev.load_config())


def _rows(db_path, sql, rows):
    with get_db(db_path) as conn:
        conn.executemany(sql, rows)


def _prices(db_path, tickers, day, close=100.0):
    _rows(
        db_path,
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(t, day, close, close, close, close, 1000) for t in tickers],
    )


def _factors(db_path, tickers, day):
    _rows(
        db_path,
        "INSERT INTO factors (ticker, date, momentum_score, composite_score) VALUES (?, ?, 0.5, 0.5)",
        [(t, day) for t in tickers],
    )


def _build(db_path, cfg, ticker="T0", **kw):
    return ev.build_packet(ticker, cutoff=kw.pop("cutoff", CUTOFF), db_path=db_path, config=cfg, universe=UNIVERSE)


class TestCoverageGate:
    def test_a_source_covering_few_tickers_is_excluded_for_everyone(self, db_path, cfg):
        """보유 위주로 모이는 소스는 '있음' 자체가 보유를 드러낸다 — 유니버스 대부분을 덮지 못하면 뺀다."""
        _prices(db_path, UNIVERSE["us"], D)
        _rows(
            db_path,
            "INSERT INTO fundamentals (ticker, date, pe_ratio) VALUES (?, ?, 20.0)",
            [("T0", D), ("T1", D)],
        )
        p = _build(db_path, cfg)
        assert p["sources"]["fundamentals"]["status"] == "excluded"
        assert p["sources"]["fundamentals"]["coverage"] == 0.2
        assert not [i for i in p["items"] if i["source"] == "fundamentals"]
        assert p["sources"]["prices"]["status"] == "ok"

    def test_a_ticker_with_fresher_rows_than_its_market_is_cut_to_the_market_date(self, db_path, cfg):
        """보유 종목만 하루 더 신선한 가격을 받는다 — 그 날짜가 보이면 보유가 새어 나간다."""
        _prices(db_path, UNIVERSE["us"], D)
        _prices(db_path, ["T0"], D_NEXT, close=120.0)
        p = _build(db_path, cfg)
        item = next(i for i in p["items"] if i["source"] == "prices")
        assert p["sources"]["prices"]["as_of"] == D
        assert item["observed"] == D
        assert item["fields"]["last_close"] == 100.0

    def test_a_holdings_independent_source_skips_the_gate(self, db_path, cfg):
        _rows(
            db_path,
            "INSERT INTO superinvestors (investor, filing_date, ticker, shares, investor_class) VALUES (?, ?, ?, ?, ?)",
            [("fund-a", D, "T0", 10.0, "conviction"), ("bank-b", D, "T0", 99.0, "dealer")],
        )
        p = _build(db_path, cfg)
        got = [i for i in p["items"] if i["source"] == "superinvestors"]
        assert p["sources"]["superinvestors"]["status"] == "ok"
        assert [i["fields"]["investor"] for i in got] == ["fund-a"]  # 은행 13F 는 세지 않는다


class TestStatuses:
    def test_missing_when_the_source_passes_but_the_ticker_has_no_rows(self, db_path, cfg):
        _prices(db_path, UNIVERSE["us"], D)
        _factors(db_path, sorted(UNIVERSE["us"] - {"T0"}), D)  # 9/10 = 0.9 → 게이트 통과
        p = _build(db_path, cfg)
        assert p["sources"]["factors"]["status"] == "missing"

    def test_stale_and_ok_follow_the_configured_max_age(self, db_path, cfg):
        _prices(db_path, UNIVERSE["us"], D)
        later = CUTOFF + timedelta(days=10)
        cfg["sources"]["prices"]["max_age_days"] = 7
        assert _build(db_path, cfg, cutoff=later)["sources"]["prices"]["status"] == "stale"
        cfg["sources"]["prices"]["max_age_days"] = 30
        assert _build(db_path, cfg, cutoff=later)["sources"]["prices"]["status"] == "ok"

    def test_failed_when_the_query_raises_and_other_sources_still_build(self, db_path, cfg, monkeypatch):
        broken = ev.Source("ghost", "technical", "no_such_table", "date", "n/a", ("x",))
        monkeypatch.setattr(ev, "TICKER_SOURCES", (*ev.TICKER_SOURCES, broken))
        _prices(db_path, UNIVERSE["us"], D)
        p = _build(db_path, cfg)
        assert p["sources"]["ghost"] == {
            "role": "technical",
            "date_meaning": "n/a",
            "status": "failed",
            "reason": "OperationalError",
        }
        assert p["sources"]["prices"]["status"] == "ok"

    def test_every_item_carries_id_source_observed_and_age(self, db_path, cfg):
        _prices(db_path, UNIVERSE["us"], D)
        _factors(db_path, UNIVERSE["us"], D)
        p = _build(db_path, cfg)
        assert p["items"]
        for item in p["items"]:
            assert {"id", "source", "observed", "age_days", "fields"} <= item.keys()
            assert item["age_days"] == 1

    def test_a_source_without_a_date_has_no_age_and_is_never_stale(self, db_path, cfg):
        """earnings_surprises 는 발표일이 없다 — 나이를 지어내지 않는다."""
        _rows(
            db_path,
            "INSERT INTO earnings_surprises (ticker, quarter, eps_actual, eps_estimate, surprise_pct) VALUES (?, ?, 1, 1, 0)",
            [(t, q) for t in UNIVERSE["us"] for q in ("2025-12-31", "2025-06-30", "2025-09-30")],  # id 순서 ≠ 분기 순서
        )
        p = _build(db_path, cfg)
        got = [i for i in p["items"] if i["source"] == "earnings_surprises"]
        assert p["sources"]["earnings_surprises"]["status"] == "ok"
        assert [i["fields"]["quarter"] for i in got] == ["2025-12-31", "2025-09-30", "2025-06-30"]
        assert {i["age_days"] for i in got} == {None}

    def test_cutoff_must_be_timezone_aware(self, db_path, cfg):
        with pytest.raises(ValueError):
            _build(db_path, cfg, cutoff=datetime(2026, 3, 10, 9, 0))


class TestOneReadOnlySnapshot:
    def _spy(self, monkeypatch):
        calls, statements = [], []
        real = db_mod.get_connection

        def spy(db_path=None, readonly=False):
            conn = real(db_path, readonly=readonly)
            calls.append(readonly)
            conn.set_trace_callback(statements.append)
            return conn

        monkeypatch.setattr(db_mod, "get_connection", spy)
        return calls, statements

    def test_each_packet_opens_exactly_one_read_only_connection(self, db_path, cfg, monkeypatch):
        _prices(db_path, UNIVERSE["us"], D)
        calls, statements = self._spy(monkeypatch)
        _build(db_path, cfg)
        assert calls == [True]
        assert statements[0] == "BEGIN"
        ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        assert calls == [True, True]

    def test_no_statement_touches_a_portfolio_table(self, db_path, cfg, monkeypatch):
        _prices(db_path, UNIVERSE["us"], D)
        _rows(
            db_path,
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, sector) VALUES (?, ?, ?, ?, ?)",
            [("acct-a", "T0", 10, 90.0, "Tech")],
        )
        _, statements = self._spy(monkeypatch)
        p = _build(db_path, cfg)
        ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        assert statements
        assert not [s for s in statements if "portfolio" in s.lower()]
        assert "acct-a" not in ev._canonical(p)


class TestPacketHash:
    def test_hash_is_stable_and_moves_with_any_value(self, db_path, cfg):
        _prices(db_path, UNIVERSE["us"], D)
        first, second = _build(db_path, cfg), _build(db_path, cfg)
        assert first["packet_hash"] == second["packet_hash"]
        with get_db(db_path) as conn:
            conn.execute("UPDATE prices SET close = 101.0 WHERE ticker = 'T0'")
        assert _build(db_path, cfg)["packet_hash"] != first["packet_hash"]

    def test_hash_covers_the_whole_packet_except_itself(self, db_path, cfg):
        _prices(db_path, UNIVERSE["us"], D)
        p = _build(db_path, cfg)
        body = {k: v for k, v in p.items() if k != "packet_hash"}
        assert ev._seal(body)["packet_hash"] == p["packet_hash"]


class TestMarketPacket:
    def test_only_allowlisted_indicators_enter(self, db_path, cfg):
        _rows(
            db_path,
            "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
            [("vix", D, 18.0), ("vix", "2026-03-06", 20.0), ("wsb_held_mentions", D, 3.0)],
        )
        p = ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        vix = next(i for i in p["items"] if i["source"] == "macro.vix")
        assert vix["fields"]["latest"] == 18.0
        assert vix["fields"]["window_change"] == -2.0
        assert p["sources"]["macro.vix"]["status"] == "ok"
        assert not [i for i in p["items"] if "wsb" in i["source"]]

    def test_news_published_or_fetched_after_the_cutoff_is_left_out(self, db_path, cfg):
        before, after = "2026-03-09T12:00:00+00:00", "2026-03-10T03:00:00+00:00"  # cutoff = 03-10 00:00 UTC
        _rows(
            db_path,
            "INSERT INTO macro_events (fetched_at, published_at, source, headline, url, category) "
            "VALUES (?, ?, 'wire', ?, ?, 'trade_war')",
            [
                (before, before, "seen", "u1"),
                (before, after, "published later", "u2"),
                (after, before, "fetched later", "u3"),
            ],
        )
        p = ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        heads = [
            i["fields"]["headline"] for i in p["items"] if i["source"] == "macro_events" and "headline" in i["fields"]
        ]
        assert heads == ["seen"]
        counts = next(i for i in p["items"] if i["id"].startswith("macro_events:counts"))
        assert counts["fields"]["trade_war"] == 1

    def test_etf_flows_report_the_change_between_snapshots_and_go_stale(self, db_path, cfg):
        _rows(
            db_path,
            "INSERT INTO etf_flows (ticker, date, total_assets, volume_avg, nav_price) VALUES (?, ?, ?, 1, 1)",
            [("SPY", "2026-03-02", 100.0), ("SPY", D, 110.0), ("QQQ", D, 50.0)],
        )
        p = ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        flows = {i["source"]: i["fields"] for i in p["items"] if i["source"].startswith("etf_flows")}
        assert flows["etf_flows.SPY"]["total_assets_change_pct"] == 10.0
        assert flows["etf_flows.QQQ"]["total_assets_change_pct"] is None
        assert p["sources"]["etf_flows"]["status"] == "ok"
        cfg["market"]["etf_flows_max_age_days"] = 0
        assert (
            ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)["sources"]["etf_flows"]["status"]
            == "stale"
        )

    def test_empty_market_tables_are_missing_and_a_broken_one_is_failed(self, db_path, cfg):
        with get_db(db_path) as conn:
            conn.execute("DROP TABLE macro_events")
        p = ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        assert p["sources"]["macro_events"]["status"] == "failed"
        assert {p["sources"][k]["status"] for k in ("macro.vix", "calendar", "etf_flows")} == {"missing"}

    def test_calendar_keeps_market_events_and_drops_ticker_events(self, db_path, cfg):
        _rows(
            db_path,
            "INSERT INTO events (date, event_type, ticker, description) VALUES (?, ?, ?, ?)",
            [("2026-03-18", "fomc", None, "FOMC"), ("2026-03-12", "earnings", "T0", "T0 earnings")],
        )
        p = ev.build_market_packet(cutoff=CUTOFF, db_path=db_path, config=cfg)
        assert [i["fields"]["event_type"] for i in p["items"] if i["source"] == "calendar"] == ["fomc"]


def test_cli_prints_both_packets_and_exits_zero(db_path, capsys, monkeypatch):
    monkeypatch.setattr(ev, "_load_universe", lambda: UNIVERSE)
    _prices(db_path, UNIVERSE["us"], D)
    calls = []
    monkeypatch.setattr(ev.live_news, "fetch", lambda t: calls.append(t) or _news(t, fetched_at="2000-01-01 00:00:00"))
    assert ev.main(["--ticker", "T0", "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert '"kind": "ticker"' in out and '"kind": "market"' in out
    assert calls == ["T0"] and '"ticker_news"' in out


def test_cli_no_news_makes_no_fetch(db_path, capsys, monkeypatch):
    monkeypatch.setattr(ev, "_load_universe", lambda: UNIVERSE)
    monkeypatch.setattr(ev.live_news, "fetch", lambda t: pytest.fail("fetched"))
    assert ev.main(["--ticker", "T0", "--db", str(db_path), "--no-news"]) == 0
    assert '"not fetched"' in capsys.readouterr().out


UTC_CUTOFF = "2026-03-10 00:00:00"  # CUTOFF(KST 09:00) 의 UTC


def _article(link, pub, title="t"):
    return {"title": title, "summary": "s", "publisher": "wire", "link": link, "pub_date": pub}


def _news(ticker="T0", articles=(), status="ok", fetched_at="2026-03-09 23:59:00", **extra):
    return {"ticker": ticker, "status": status, "fetched_at": fetched_at, "articles": list(articles), **extra}


def _news_items(p):
    return [i for i in p["items"] if i["source"] == "ticker_news"]


class TestTickerNews:
    """실시간 종목 뉴스 (#1958) — 묶음은 넘겨받은 조회 결과만 거른다."""

    def test_only_articles_with_a_time_inside_the_window_and_before_the_cutoff_enter(self, db_path, cfg):
        news = _news(
            articles=[
                _article("u-in", "2026-03-09 12:00:00", "inside"),
                _article("u-late", "2026-03-10 00:00:01", "after cutoff"),
                _article("u-old", "2026-03-03 00:00:00", "outside lookback"),
                _article("u-none", None, "no time"),
                _article("u-in", "2026-03-09 12:00:00", "inside"),  # 같은 기사 두 번
            ]
        )
        p = ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=news)
        assert [i["fields"]["title"] for i in _news_items(p)] == ["inside"]
        assert _news_items(p)[0]["age_days"] == 0  # 12시간 전 — KST/UTC 날짜 차로 1 이 되면 안 된다
        assert p["sources"]["ticker_news"]["status"] == "ok"
        assert p["sources"]["ticker_news"]["fetched_at"] == news["fetched_at"]

    def test_newest_first_and_capped_by_config(self, db_path, cfg):
        cfg["sources"]["ticker_news"]["rows"] = 2
        news = _news(articles=[_article(f"u{h}", f"2026-03-09 {h:02d}:00:00", str(h)) for h in (1, 5, 3)])
        p = ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=news)
        assert [i["fields"]["title"] for i in _news_items(p)] == ["5", "3"]

    def test_the_item_id_is_stable_for_the_same_link(self, db_path, cfg):
        a = _article("https://x/1", "2026-03-09 12:00:00")
        p1 = ev.build_packet(
            "T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news(articles=[a])
        )
        b = {**a, "title": "edited"}
        p2 = ev.build_packet(
            "T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news(articles=[b])
        )
        assert _news_items(p1)[0]["id"] == _news_items(p2)[0]["id"]

    def test_zero_tagged_articles_is_ok_with_a_sample_note(self, db_path, cfg):
        p = ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news())
        info = p["sources"]["ticker_news"]
        assert info["status"] == "ok" and "not an absence" in info["note"]

    def test_failed_and_excluded_carry_no_items(self, db_path, cfg):
        failed = _news(status="failed", reason="no answer", articles=[_article("u", "2026-03-09 12:00:00")])
        p = ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=failed)
        assert (
            p["sources"]["ticker_news"]["status"] == "failed" and p["sources"]["ticker_news"]["reason"] == "no answer"
        )
        assert _news_items(p) == []
        p = ev.build_packet(
            "T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news(status="excluded")
        )
        assert p["sources"]["ticker_news"] == {
            "role": "news",
            "date_meaning": p["sources"]["ticker_news"]["date_meaning"],
            "status": "excluded",
            "fetched_at": "2026-03-09 23:59:00",
        }

    def test_no_fetch_is_missing(self, db_path, cfg):
        p = _build(db_path, cfg)
        assert p["sources"]["ticker_news"]["status"] == "missing"

    def test_a_fetch_that_finished_after_the_cutoff_is_refused(self, db_path, cfg):
        """그 결과에는 기준 시점 뒤에 나온 기사가 섞일 수 있다."""
        late = _news(fetched_at="2026-03-10 00:00:01")
        with pytest.raises(ValueError, match="after the cutoff"):
            ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=late)
        ok = _news(fetched_at=UTC_CUTOFF)
        ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=ok)

    def test_news_for_another_ticker_is_refused(self, db_path, cfg):
        with pytest.raises(ValueError, match="fetched for T1"):
            ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news("T1"))

    def test_the_news_is_inside_the_packet_hash(self, db_path, cfg):
        a = ev.build_packet("T0", cutoff=CUTOFF, db_path=db_path, config=cfg, universe=UNIVERSE, news=_news())
        b = ev.build_packet(
            "T0",
            cutoff=CUTOFF,
            db_path=db_path,
            config=cfg,
            universe=UNIVERSE,
            news=_news(articles=[_article("u", "2026-03-09 12:00:00")]),
        )
        assert a["packet_hash"] != b["packet_hash"]
