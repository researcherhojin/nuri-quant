"""기업 브리핑은 공급자 신원·보고 기간·결측값을 보존한다."""

import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock
from urllib.parse import parse_qsl, urlparse

import pandas as pd
import pytest
import requests

import nuri.collectors.company_research as research_module
from nuri.collectors.company_research import CompanyResearchCollector
from nuri.core.db import OperationalError, get_db
from nuri.core.timezone import kst_now, today_kst

# autouse 스텁이 모듈 속성을 바꾸기 전에 원본을 잡아 둔다 (검색 URL 구성 자체를 검사).
real_collect_recent_news = research_module._collect_recent_news


@pytest.fixture(autouse=True)
def news_feed_stub(monkeypatch):
    monkeypatch.setattr(
        "nuri.collectors.company_research.collect_briefing_sources",
        lambda profile, news: {"sources": [], "failed_sources": [], "official_registered": False},
    )
    monkeypatch.setattr("nuri.collectors.company_research._collect_recent_news", lambda ticker, name: [])
    monkeypatch.setattr("nuri.collectors.company_research.enrich_news", lambda records, name, symbol: records)


@pytest.fixture
def provider(monkeypatch):
    import yfinance

    stock = MagicMock()
    stock.info = {
        "symbol": "DEMO",
        "longName": "Demo Company",
        "longBusinessSummary": "Makes sample products.",
        "financialCurrency": "USD",
    }
    stock.get_income_stmt.return_value = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [1000, 0, -20], pd.Timestamp("2024-12-31"): [800, 40, 30]},
        index=["TotalRevenue", "OperatingIncome", "NetIncome"],
    )
    stock.get_cashflow.return_value = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [0, float("nan")]}, index=["OperatingCashFlow", "FreeCashFlow"]
    )
    stock.get_balance_sheet.return_value = pd.DataFrame()
    stock.history.return_value = pd.DataFrame(
        {"Open": [10.0], "High": [12.0], "Low": [9.0], "Close": [11.0], "Volume": [100.0]},
        index=[pd.Timestamp("2026-01-02", tz="America/New_York")],
    )
    stock.get_news.return_value = []
    monkeypatch.setattr(yfinance, "Ticker", lambda ticker: stock)
    return stock


def test_collect_preserves_dates_zero_and_missing(provider):
    collector = CompanyResearchCollector()
    data = collector.collect(ticker="demo")
    assert data[0]["profile"]["name"] == "Demo Company"
    assert data[0]["statements"]["income"][0]["period"] == "2025-12-31"
    assert data[0]["statements"]["income"][0]["operating_income"] == 0
    assert data[0]["statements"]["cashflow"][0]["free_cashflow"] is None
    assert collector.save(data) == 1
    assert collector.save([]) == 0


def test_mismatched_identity_is_not_saved(provider):
    provider.info["symbol"] = "OTHER"
    assert CompanyResearchCollector().collect(ticker="DEMO") == []


def test_partial_statement_failure_is_exposed(provider):
    provider.get_cashflow.side_effect = RuntimeError("source unavailable")
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert result["unavailable"] == ["cashflow", "balance"]
    assert result["statements"]["cashflow"] == []
    assert result["statements"]["income"]


def test_read_is_mounted_and_empty_is_explicit(client):
    result = client.get("/api/ticker/DEMO/research")
    assert result.status_code == 200
    assert result.json()["dossier"] is None
    assert result.json()["news"] == []


def test_refresh_then_read_preserves_news_source_and_ticker_filter(client, provider):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO news(ticker,date,title,url,source) VALUES(?,?,?,?,?)",
            ("DEMO", "2026-01-01", "Sample announcement", "https://example.com/news", "Example Publisher"),
        )
        conn.execute(
            "INSERT INTO news(ticker,date,title,url,source) VALUES(?,?,?,?,?)",
            ("OTHER", "2026-01-02", "Other company", "https://example.com/other", "Other Publisher"),
        )
    assert client.post("/api/ticker/DEMO/research/refresh").json()["saved"] == 1
    data = client.get("/api/ticker/demo/research").json()
    assert data["dossier"]["profile"]["name"] == "Demo Company"
    assert data["news_count"] == 1
    assert data["news"][0]["source"] == "Example Publisher"
    with get_db() as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_refresh_errors_are_generic_and_missing_symbol_is_404(client, provider):
    provider.info = {}
    assert client.post("/api/ticker/DEMO/research/refresh").status_code == 404
    provider.get_income_stmt.side_effect = None
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            CompanyResearchCollector,
            "collect",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private internal error")),
        )
        response = client.post("/api/ticker/DEMO/research/refresh")
    assert response.status_code == 502
    assert "private" not in response.text


def test_malformed_or_mismatched_stored_payload_is_not_a_profile(client):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO external_analysis(date,source,ticker,data_type,details) VALUES(?,?,?,?,?)",
            ("2026-01-01", "yahoo_finance", "DEMO", "company_research", json.dumps({"ticker": "OTHER"})),
        )
    assert client.get("/api/ticker/DEMO/research").json()["dossier"] is None
    with get_db() as conn:
        conn.execute("UPDATE external_analysis SET details='invalid json'")
    assert client.get("/api/ticker/DEMO/research").json()["dossier"] is None


TEMA_SAMPLE = """
<h1>NASA<br>Tema Space Innovators ETF</h1>
<div class="inner-left-part"><div class="details-box"><h3>Fund Details</h3></div><h6>As of January 02, 2026</h6>
<div class="box"><div class="col-specification">Ticker</div><div class="col-details">NASA</div></div>
<div class="box"><div class="col-specification">Total Expense Ratio</div><div class="col-details">0.50%</div></div>
<div class="box"><div class="col-specification">AUM</div><div class="col-details">$1,000,000</div></div>
</div>
<div class="summary-block"><div class="summary">An actively managed portfolio of space exploration, rockets, propulsion systems and satellite technology.</div></div>
<div class="inner-box"><h3>Top 10 Holdings</h3><h6>As of January 01, 2026</h6><div class="outer-wrap">
<div class="box"><div class="col-specification">Sample Aerospace</div><div class="col-details">20%</div></div>
<div class="box"><div class="col-specification">Sample Satellite</div><div class="col-details">10%</div></div>
</div></div>
<p><strong>Space Risk:</strong> Technology setbacks can affect development.</p>
"""


def test_official_fund_parsing_keeps_independent_dates_and_missing_values():
    from nuri.collectors.company_research import parse_tema_fund

    fund = parse_tema_fund(TEMA_SAMPLE, "NASA")
    assert fund["details_as_of"] == "2026-01-02"
    assert fund["holdings_as_of"] == "2026-01-01"
    assert fund["expense_pct"] == 0.5
    assert fund["aum"] == 1_000_000
    assert fund["holding_count"] is None
    assert fund["holdings"][0]["weight_pct"] == 20
    assert "액티브" in fund["strategy_text"]
    assert fund["risks"][0]["title"] == "Space Risk"
    with pytest.raises(ValueError):
        parse_tema_fund(TEMA_SAMPLE.replace(">NASA</div>", ">OTHER</div>"), "NASA")
    without_date = parse_tema_fund(TEMA_SAMPLE.replace("As of January 01, 2026", "Unknown"), "NASA")
    assert without_date["holdings_as_of"] is None


def test_official_business_and_investment_structure_are_source_bound():
    from nuri.collectors.company_research import parse_tema_fund

    extra = """<div class="three-column-block-text"><p>Demo Space (DEMO) designs rockets and operates Starlink.</p></div>
    <div class="faq-title"><h2>FAQ<span>As of January 03, 2026</span></h2></div>
    <div class="faq-accordion-dropdown-section-v2"><h4>How does NASA invest in SpaceX?</h4><div class="faq-accordion-content-text">Exposure through a special purpose vehicle.</div></div>"""
    fund = parse_tema_fund(TEMA_SAMPLE + extra, "NASA")
    assert fund["highlights"][0]["symbol"] == "DEMO"
    assert "로켓" in fund["highlights"][0]["explanation"]
    assert fund["faq_as_of"] == "2026-01-03"
    assert "SPV" in fund["exposure_text"]
    empty = parse_tema_fund(TEMA_SAMPLE, "NASA")
    assert empty["highlights"] == []
    assert empty["exposure_text"] is None
    assert empty["faq_as_of"] is None


def test_previous_payload_version_is_refreshed_even_if_saved_today(client, provider):
    client.post("/api/ticker/DEMO/research/refresh")
    with get_db() as conn:
        payload = json.loads(conn.execute("SELECT details FROM external_analysis").fetchone()[0])
        payload["schema_version"] = 3
        conn.execute("UPDATE external_analysis SET details=?", (json.dumps(payload),))
    assert client.get("/api/ticker/DEMO/research").json()["collected_today"] is False
    assert client.post("/api/ticker/DEMO/research/refresh").json()["saved"] == 1
    assert provider.history.call_count == 2


def test_etf_uses_official_data_without_requesting_company_statements(provider, monkeypatch):
    import nuri.collectors.company_research as module

    provider.info = {"symbol": "NASA", "longName": "Source Fund", "quoteType": "ETF"}
    monkeypatch.setattr(module, "_collect_tema_fund", lambda symbol: module.parse_tema_fund(TEMA_SAMPLE, symbol))
    data = CompanyResearchCollector().collect(ticker="NASA")[0]
    assert data["profile"]["name"] == "Tema Space Innovators ETF"
    assert data["fund"]["holdings_as_of"] == "2026-01-01"
    assert data["statements"] == {"income": [], "cashflow": [], "balance": []}
    assert data["price_history"][0]["date"] == "2026-01-02"
    provider.get_income_stmt.assert_not_called()
    provider.get_cashflow.assert_not_called()


def test_daily_refresh_reuses_today_and_force_fetches_again(client, provider):
    assert client.get("/api/ticker/DEMO/research").json()["collected_today"] is False
    assert client.post("/api/ticker/DEMO/research/refresh").json()["saved"] == 1
    assert client.get("/api/ticker/DEMO/research").json()["collected_today"] is True
    assert client.post("/api/ticker/DEMO/research/refresh").json()["reused"] is True
    assert provider.history.call_count == 1
    assert client.post("/api/ticker/DEMO/research/refresh?force=true").json()["saved"] == 1
    assert provider.history.call_count == 2


def test_failed_refresh_keeps_prior_source_date_and_does_not_claim_today(client, provider, monkeypatch):
    import nuri.api.routes.ticker_research as route

    client.post("/api/ticker/DEMO/research/refresh")
    with get_db() as conn:
        row = conn.execute("SELECT details FROM external_analysis").fetchone()
        payload = json.loads(row[0])
        payload["collected_at"] = "2000-01-01T09:00:00+09:00"
        conn.execute("UPDATE external_analysis SET details=?", (json.dumps(payload),))
    monkeypatch.setattr(
        CompanyResearchCollector,
        "collect",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("source failed")),
    )
    assert client.post("/api/ticker/DEMO/research/refresh").status_code == 502
    response = client.get("/api/ticker/DEMO/research").json()
    assert response["collected_today"] is False
    assert response["dossier"]["collected_at"].startswith("2000-01-01")
    assert route._collection_lock.acquire(blocking=False)
    try:
        busy = client.post("/api/ticker/DEMO/research/refresh")
        assert busy.status_code == 503
        assert busy.headers["Retry-After"] == "5"
    finally:
        route._collection_lock.release()


def test_preview_reads_saved_judgments_without_running_live_strategy(client, monkeypatch):
    import nuri.api.routes.ticker as route

    def unexpected(*args, **kwargs):
        raise AssertionError("Preview must not compute live strategy")

    monkeypatch.setattr(route, "_get_consensus", unexpected)
    monkeypatch.setattr(route, "_get_signals", unexpected)
    monkeypatch.setattr("nuri.core.ticker_names.get_ticker_name", MagicMock(side_effect=unexpected))
    response = client.get("/api/ticker/DEMO?stored_only=true")
    assert response.status_code == 200
    assert response.json()["consensus"] is None
    assert response.json()["signals"] == []


def test_news_without_valid_publication_date_is_not_labelled_as_today_and_duplicates_are_removed(provider):
    from nuri.core.timezone import today_kst

    article = {
        "content": {
            "title": "Sample report",
            "canonicalUrl": {"url": "https://example.com/article"},
            "provider": {"displayName": "Publisher"},
            "pubDate": f"{today_kst()}T00:00:00Z",
        }
    }
    provider.get_news.return_value = [
        article,
        article,
        {
            "content": {
                "title": "Unknown date",
                "canonicalUrl": {"url": "https://example.com/unknown"},
                "pubDate": "invalid",
            }
        },
    ]
    news = CompanyResearchCollector().collect(ticker="DEMO")[0]["news"]
    assert len(news) == 1
    assert news[0]["date"] == today_kst()
    assert news[0]["title"] == "Sample report"


def test_recent_news_excludes_old_future_and_duplicate_headlines(provider, monkeypatch):
    from datetime import timedelta

    from nuri.core.timezone import kst_now, today_kst

    current = {
        "date": today_kst(),
        "title": "New sample report",
        "url": "https://example.com/current",
        "source": "Publisher",
    }
    records = [
        current,
        {**current, "title": "NEW SAMPLE REPORT"},
        {**current, "date": "2000-01-01", "title": "Old report"},
        {**current, "date": (kst_now() + timedelta(days=1)).date().isoformat(), "title": "Future report"},
    ]
    monkeypatch.setattr("nuri.collectors.company_research._collect_recent_news", lambda ticker, name: records)
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert result["news"] == [current]
    assert result["news_check"]["failed_sources"] == []


def test_news_feed_preserves_publication_timezone_and_rejects_invalid_payload():
    from nuri.collectors.company_research import parse_news_feed

    xml = "<rss><channel><item><title>Sample report - Publisher</title><link>https://example.com/report</link><source>Publisher</source><pubDate>Mon, 05 Jan 2026 23:00:00 GMT</pubDate></item><item><title>Missing date</title><link>https://example.com/missing</link></item></channel></rss>"
    records = parse_news_feed(xml, "DEMO")
    assert len(records) == 1
    assert records[0]["date"] == "2026-01-06"
    assert records[0]["title"] == "Sample report"
    assert records[0]["source"] == "Publisher"
    with pytest.raises(ValueError):
        parse_news_feed("<html>Unavailable</html>", "DEMO")


def test_news_failure_is_not_a_successful_empty_search(provider, monkeypatch):
    def failed(*args):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr("nuri.collectors.company_research._collect_recent_news", failed)
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert result["news"] == []
    assert result["news_check"]["failed_sources"] == ["Google News"]
    assert "news" in result["unavailable"]


def test_public_response_does_not_republish_article_body(client, provider):
    collector = CompanyResearchCollector()
    dossier = collector.collect(ticker="DEMO")[0]
    dossier["holdings"] = {"account": "PRIVATE ACCOUNT FIELD"}
    dossier["profile"]["private_marker"] = "PRIVATE PROFILE FIELD"
    dossier["news"] = [{"date": "2026-01-01", "title": "Sample", "analysis_text": "PRIVATE ARTICLE BODY"}]
    dossier["briefing_evidence"] = {"sources": [{"text": "PRIVATE OFFICIAL BODY"}]}
    collector.save([dossier])
    body = client.get("/api/ticker/DEMO/research").text
    assert "PRIVATE ARTICLE BODY" not in body
    assert "PRIVATE OFFICIAL BODY" not in body
    assert "PRIVATE ACCOUNT FIELD" not in body
    assert "PRIVATE PROFILE FIELD" not in body
    external_body = client.get("/api/external/DEMO").text
    assert "PRIVATE ARTICLE BODY" not in external_body
    assert "PRIVATE OFFICIAL BODY" not in external_body
    assert "PRIVATE ACCOUNT FIELD" not in external_body
    assert "PRIVATE PROFILE FIELD" not in external_body


def test_generation_is_explicit_cached_and_read_is_side_effect_free(client, provider, monkeypatch):
    from nuri.api.routes import ticker_research as route
    from nuri.llm import research_briefing as generator

    assert client.post("/api/ticker/DEMO/research/briefing").status_code == 409
    client.post("/api/ticker/DEMO/research/refresh")
    generated = MagicMock(
        return_value={
            "status": "ready",
            "evidence_hash": generator.evidence_hash(generator.public_bundle(route._stored_dossier("DEMO"))),
            "prompt_version": generator.VERSION,
            "model": generator.MODEL,
        }
    )
    monkeypatch.setattr(generator, "generate_briefing", generated)
    monkeypatch.setattr(route._briefing_worker, "submit", lambda fn, *args: fn(*args))
    client.get("/api/ticker/DEMO/research")
    generated.assert_not_called()
    response = client.post("/api/ticker/DEMO/research/briefing")
    assert response.status_code == 202
    generated.assert_called_once()
    assert client.get("/api/ticker/DEMO/research").json()["public_briefing"]["status"] == "ready"
    assert client.post("/api/ticker/DEMO/research/briefing").json()["reused"] is True
    generated.assert_called_once()
    provider.info["longBusinessSummary"] = "Changed public description."
    client.post("/api/ticker/DEMO/research/refresh?force=true")
    assert client.get("/api/ticker/DEMO/research").json()["public_briefing"]["status"] == "stale"


def test_generation_single_flight_sheds_second_request(client, provider):
    from nuri.api.routes import ticker_research as route

    client.post("/api/ticker/DEMO/research/refresh")
    route._briefing_lock.acquire()
    try:
        assert client.post("/api/ticker/DEMO/research/briefing").status_code == 503
    finally:
        route._briefing_lock.release()


def test_cross_process_pending_lease_prevents_duplicate_generation(client, provider):
    from nuri.api.routes import ticker_research as route
    from nuri.core.timezone import kst_now

    client.post("/api/ticker/DEMO/research/refresh")
    route._save_briefing("OTHER", {"status": "pending", "started_at": kst_now().isoformat()})
    assert not route._briefing_lock.locked()
    assert client.post("/api/ticker/DEMO/research/briefing").status_code == 503
    assert not route._briefing_lock.locked()


@pytest.mark.parametrize("failure", ["generator", "submission"])
def test_failed_background_job_releases_durable_lease(client, provider, monkeypatch, failure):
    from nuri.api.routes import ticker_research as route
    from nuri.llm import research_briefing as generator

    client.post("/api/ticker/DEMO/research/refresh")
    monkeypatch.setattr(route._briefing_worker, "submit", lambda fn, *args: fn(*args))
    monkeypatch.setattr(generator, "generate_briefing", MagicMock(side_effect=RuntimeError("synthetic error")))
    if failure == "submission":
        monkeypatch.setattr(
            route._briefing_worker, "submit", MagicMock(side_effect=RuntimeError("synthetic submit error"))
        )
    first = client.post("/api/ticker/DEMO/research/briefing")
    assert first.status_code == (502 if failure == "submission" else 202)
    assert not route._briefing_lock.locked()
    assert client.get("/api/ticker/DEMO/research").json()["public_briefing"]["status"] == "unavailable"
    monkeypatch.setattr(route._briefing_worker, "submit", lambda fn, *args: fn(*args))
    monkeypatch.setattr(generator, "generate_briefing", lambda dossier: {"status": "insufficient"})
    assert client.post("/api/ticker/DEMO/research/briefing").status_code == 202


def test_real_collector_stamps_cutoff_after_source_collection(provider, monkeypatch):
    from nuri.core.timezone import kst_now
    from nuri.llm.research_briefing import public_bundle

    def sources(profile, news):
        now = kst_now().isoformat()
        return {
            "sources": [
                {
                    "source_id": "official",
                    "url": "https://example.com/release",
                    "title": "Release",
                    "kind": "official",
                    "entity": profile["name"],
                    "published_at": now[:10],
                    "collected_at": now,
                    "text": "Demo Company production plan.",
                }
            ]
        }

    monkeypatch.setattr("nuri.collectors.company_research.collect_briefing_sources", sources)
    dossier = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert any(source["source_id"] == "official" for source in public_bundle(dossier)["sources"])


# ── 갱신·브리핑 라우트의 경합과 손상 상태 ─────────────────────────────────────


def _save_today_dossier():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO external_analysis(date,source,ticker,data_type,details,collected_at) VALUES(?,?,?,?,?,?)",
            (
                today_kst(),
                "yahoo_finance",
                "DEMO",
                "company_research",
                json.dumps(
                    {
                        "ticker": "DEMO",
                        "schema_version": 6,
                        "collected_at": kst_now().isoformat(),
                        "profile": {"name": "Demo Company", "symbol": "DEMO"},
                    }
                ),
                kst_now().isoformat(),
            ),
        )


def test_collection_finished_by_another_request_is_reused_after_taking_the_lock(client, provider, monkeypatch):
    import nuri.api.routes.ticker_research as route

    class LockAfterPeer:
        """첫 확인과 락 획득 사이에 다른 요청이 오늘 자료 저장을 마친 상황."""

        released = False

        def acquire(self, blocking=True):
            _save_today_dossier()
            return True

        def release(self):
            self.released = True

    lock = LockAfterPeer()
    monkeypatch.setattr(route, "_collection_lock", lock)
    assert client.post("/api/ticker/DEMO/research/refresh").json() == {"saved": 0, "ticker": "DEMO", "reused": True}
    assert lock.released
    provider.history.assert_not_called()


def _pending(route, generator, **fields):
    return {
        "status": "pending",
        "evidence_hash": generator.evidence_hash(generator.public_bundle(route._stored_dossier("DEMO"))),
        "prompt_version": generator.VERSION,
        "model": generator.MODEL,
        **fields,
    }


@pytest.mark.parametrize(
    "started_at,status",
    [
        ("now", "pending"),
        ("31 minutes ago", "unavailable"),
        ("future", "unavailable"),
        ("naive", "unavailable"),
        ("malformed", "unavailable"),
        ("missing", "unavailable"),
    ],
)
def test_pending_briefing_is_shown_only_while_its_lease_is_alive(client, provider, started_at, status):
    from nuri.api.routes import ticker_research as route
    from nuri.llm import research_briefing as generator

    client.post("/api/ticker/DEMO/research/refresh")
    now = kst_now()
    stamps = {
        "now": now.isoformat(),
        "31 minutes ago": (now - timedelta(minutes=31)).isoformat(),
        "future": (now + timedelta(minutes=5)).isoformat(),
        "naive": now.replace(tzinfo=None).isoformat(),
        "malformed": "yesterday",
    }
    fields = {"started_at": stamps[started_at]} if started_at in stamps else {}
    route._save_briefing("DEMO", _pending(route, generator, **fields))
    assert client.get("/api/ticker/DEMO/research").json()["public_briefing"]["status"] == status


@pytest.mark.parametrize("details", ["{broken", None])
def test_corrupt_stored_briefing_is_hidden_without_breaking_the_page(client, provider, details):
    client.post("/api/ticker/DEMO/research/refresh")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO external_analysis(date,source,ticker,data_type,value,details) VALUES(?,?,?,?,?,?)",
            (today_kst(), "source_backed_briefing", "DEMO", "public_briefing", "ready", details),
        )
    response = client.get("/api/ticker/DEMO/research")
    assert response.status_code == 200
    assert response.json()["public_briefing"] is None
    assert response.json()["dossier"]["profile"]["name"] == "Demo Company"


@pytest.mark.parametrize("lease", ["expired", "corrupt"])
def test_dead_or_corrupt_lease_of_another_ticker_does_not_block_generation(client, provider, monkeypatch, lease):
    from nuri.api.routes import ticker_research as route
    from nuri.llm import research_briefing as generator

    client.post("/api/ticker/DEMO/research/refresh")
    details = (
        json.dumps({"status": "pending", "started_at": (kst_now() - timedelta(hours=2)).isoformat()})
        if lease == "expired"
        else "{broken"
    )
    with get_db() as conn:
        conn.execute(
            "INSERT INTO external_analysis(date,source,ticker,data_type,value,details) VALUES(?,?,?,?,?,?)",
            (today_kst(), "source_backed_briefing", "OTHER", "public_briefing", "pending", details),
        )
    generated = MagicMock(return_value={"status": "insufficient"})
    monkeypatch.setattr(generator, "generate_briefing", generated)
    monkeypatch.setattr(route._briefing_worker, "submit", lambda fn, *args: fn(*args))
    assert client.post("/api/ticker/DEMO/research/briefing").status_code == 202
    generated.assert_called_once()
    assert not route._briefing_lock.locked()


def test_background_failure_releases_the_lock_even_if_its_state_cannot_be_saved(monkeypatch, caplog):
    from nuri.api.routes import ticker_research as route
    from nuri.llm import research_briefing as generator

    def locked_database(ticker, result):
        raise OperationalError("database is locked")

    monkeypatch.setattr(generator, "generate_briefing", MagicMock(side_effect=RuntimeError("generator failed")))
    monkeypatch.setattr(route, "_save_briefing", locked_database)
    assert route._briefing_lock.acquire(blocking=False)
    with caplog.at_level(logging.ERROR, logger=route.__name__):
        route._build_briefing("DEMO", {"ticker": "DEMO"}, {"status": "pending"})
    assert not route._briefing_lock.locked()
    assert "브리핑 실패 상태 저장 오류" in caplog.text


# ── 수집기: 뉴스 피드 ────────────────────────────────────────────────────────


def _feed_item(
    title="Sample report", link="https://example.com/report", pub="Mon, 05 Jan 2026 23:00:00 GMT", source=""
):
    source_tag = f"<source>{source}</source>" if source else ""
    return f"<item><title>{title}</title><link>{link}</link>{source_tag}<pubDate>{pub}</pubDate></item>"


@pytest.mark.parametrize(
    "rejected",
    [
        _feed_item(pub="Mon, 05 Jan 2026 23:00:00 -0000"),  # RFC 2822 의 시간대 미상
        _feed_item(link="http://example.com/report"),
        _feed_item(title=""),
    ],
)
def test_news_feed_drops_items_without_timezone_https_link_or_title(rejected):
    from nuri.collectors.company_research import parse_news_feed

    kept = _feed_item(title="Kept report", link="https://example.com/kept")
    records = parse_news_feed(f"<rss><channel>{rejected}{kept}</channel></rss>", "DEMO")
    assert [record["title"] for record in records] == ["Kept report"]


def test_news_feed_keeps_a_title_that_does_not_end_with_the_source_name():
    from nuri.collectors.company_research import parse_news_feed

    item = _feed_item(title="Publisher reports demand", source="Publisher")
    (record,) = parse_news_feed(f"<rss><channel>{item}</channel></rss>", "DEMO")
    assert (record["title"], record["source"]) == ("Publisher reports demand", "Publisher")


@pytest.mark.parametrize(
    "ticker,locale",
    [
        ("DEMO", {"hl": "en-US", "gl": "US", "ceid": "US:en"}),
        ("000001.KS", {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}),
        ("000001.KQ", {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}),
    ],
)
def test_recent_news_search_quotes_the_verified_name_in_the_market_locale(monkeypatch, ticker, locale):
    requested = []
    feed = f"<rss><channel>{_feed_item(title='Sample report - Publisher', source='Publisher')}</channel></rss>"

    def get(url, **kwargs):
        requested.append((url, kwargs))
        return SimpleNamespace(text=feed, raise_for_status=lambda: None)

    monkeypatch.setattr(requests, "get", get)
    records = real_collect_recent_news(ticker, 'Demo "Quoted" Company')
    ((url, kwargs),) = requested
    assert kwargs == {"timeout": 15}
    parsed = urlparse(url)
    assert (parsed.netloc, parsed.path) == ("news.google.com", "/rss/search")
    query = f'"Demo Quoted Company" when:{research_module.NEWS_LOOKBACK_DAYS}d'
    assert dict(parse_qsl(parsed.query)) == {"q": query, **locale}
    assert [(record["ticker"], record["title"]) for record in records] == [(ticker, "Sample report")]


# ── 수집기: 공식 ETF 페이지 어댑터 ──────────────────────────────────────────


def test_fund_page_without_details_section_is_not_an_identity_match():
    with pytest.raises(ValueError, match="identity"):
        research_module.parse_tema_fund(TEMA_SAMPLE.replace("<h3>Fund Details</h3>", "<h3>Overview</h3>"), "NASA")


def test_incomplete_fund_detail_row_does_not_hide_the_others():
    row = '<div class="box"><div class="col-specification">Inception Date</div></div>'
    html = TEMA_SAMPLE.replace("<h6>As of January 02, 2026</h6>", "<h6>As of January 02, 2026</h6>" + row)
    fund = research_module.parse_tema_fund(html, "NASA")
    assert fund["inception"] is None
    assert (fund["expense_pct"], fund["aum"]) == (0.5, 1_000_000)


def test_fund_valuation_skips_unlabelled_or_unparseable_ratios():
    characteristics = """<div class="characteristics"><h3>ETF Characteristics</h3><h6>As of January 03, 2026</h6>
    <div class="box"><div class="col-specification"><span>Price-to-Earnings (P/E)</span></div><div class="col-details">25.5x</div></div>
    <div class="box"><div class="col-specification"><span>Price-to-Book Value (P/BV)</span></div><div class="col-details">n/a</div></div>
    <div class="box"><div class="col-specification">Price-to-Sales (P/S)</div><div class="col-details">3.1x</div></div>
    </div>"""
    fund = research_module.parse_tema_fund(TEMA_SAMPLE + characteristics, "NASA")
    assert (fund["pe"], fund["pb"], fund["ps"]) == (25.5, None, None)
    assert fund["valuation_as_of"] == "2026-01-03"


def test_fund_without_holdings_section_has_no_holdings_or_holdings_date():
    fund = research_module.parse_tema_fund(
        TEMA_SAMPLE.replace("<h3>Top 10 Holdings</h3>", "<h3>Portfolio</h3>"), "NASA"
    )
    assert fund["holdings"] == []
    assert fund["holdings_as_of"] is None


def test_fund_holdings_without_a_valid_percentage_are_dropped():
    rows = (
        '<div class="box"><div class="col-specification">Unknown Weight</div><div class="col-details">N/A</div></div>'
        '<div class="box"><div class="col-specification">Overweight</div><div class="col-details">150%</div></div>'
        '<div class="box"><div class="col-specification">No Weight</div></div>'
    )
    html = TEMA_SAMPLE.replace('<div class="outer-wrap">', '<div class="outer-wrap">' + rows)
    fund = research_module.parse_tema_fund(html, "NASA")
    assert fund["holdings"] == [
        {"name": "Sample Aerospace", "weight_pct": 20},
        {"name": "Sample Satellite", "weight_pct": 10},
    ]


def test_fund_strategy_is_not_written_without_a_recognised_theme():
    summary = (
        "An actively managed portfolio of space exploration, rockets, propulsion systems and satellite technology."
    )
    fund = research_module.parse_tema_fund(TEMA_SAMPLE.replace(summary, "A diversified portfolio."), "NASA")
    assert fund["strategy_text"] is None


def test_highlight_explanations_follow_the_described_business():
    block = """<div class="three-column-block-text">
    <p>Overview of selected holdings</p>
    <p>Demo Phone (DPHN) builds a space-based network for unmodified smartphones.</p>
    <p>Demo Radio (DRAD) supplies RF components for satellite ground stations.</p>
    <p>Demo Furniture (DFUR) makes office chairs.</p></div>"""
    highlights = research_module.parse_tema_fund(TEMA_SAMPLE + block, "NASA")["highlights"]
    assert [item["symbol"] for item in highlights] == ["DPHN", "DRAD", "DFUR"]
    phone, radio, furniture = (item["explanation"] for item in highlights)
    assert "스마트폰" in phone and "로켓" not in phone
    assert "고주파" in radio and "스마트폰" not in radio
    assert furniture is None


def test_faq_entry_without_an_answer_is_not_published():
    faq = """<div class="faq-accordion-dropdown-section-v2"><h4>Question without an answer?</h4></div>
    <div class="faq-accordion-dropdown-section-v2"><h4>How does NASA invest in SpaceX?</h4><div class="faq-accordion-content-text">Exposure through a special purpose vehicle.</div></div>"""
    fund = research_module.parse_tema_fund(TEMA_SAMPLE + faq, "NASA")
    assert fund["faq"] == [
        {"question": "How does NASA invest in SpaceX?", "answer": "Exposure through a special purpose vehicle."}
    ]


def test_official_fund_page_is_fetched_from_the_registered_url(monkeypatch):
    requested = []

    def get(url, **kwargs):
        requested.append((url, kwargs))
        return SimpleNamespace(text=TEMA_SAMPLE, raise_for_status=lambda: None)

    monkeypatch.setattr(requests, "get", get)
    fund = research_module._collect_tema_fund("NASA")
    assert requested == [(research_module.TEMA_URL, {"timeout": 20})]
    assert fund["holdings_as_of"] == "2026-01-01"


# ── 수집기: 가격·신원·펀드·뉴스 결손 ────────────────────────────────────────


def test_absent_price_frame_is_an_empty_history():
    assert research_module._prices(None) == []


@pytest.mark.parametrize("history", [pd.DataFrame(), RuntimeError("timeout")])
def test_missing_price_history_is_reported_as_unavailable(provider, history):
    if isinstance(history, Exception):
        provider.history.side_effect = history
    else:
        provider.history.return_value = history
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert result["price_history"] == []
    assert "prices" in result["unavailable"]


def test_price_rows_with_missing_values_are_dropped(provider):
    index = pd.DatetimeIndex(["2026-01-02", "2026-01-05"]).tz_localize("America/New_York")
    provider.history.return_value = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [12.0, 12.5],
            "Low": [9.0, 10.5],
            "Close": [float("nan"), 12.0],
            "Volume": [100.0, 120.0],
        },
        index=index,
    )
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert [row["date"] for row in result["price_history"]] == ["2026-01-05"]


KOREAN_PROFILE = {
    "name": "샘플기업",
    "quote_type": "EQUITY",
    "source_url": "https://stock.naver.com/domestic/stock/000001",
    "description": "샘플 사업 설명",
    "exchange": "KS",
    "fund": None,
}


def test_korean_provider_supplies_identity_when_yahoo_profile_fails(provider, monkeypatch):
    requested = []
    monkeypatch.setattr(
        research_module, "collect_korean_profile", lambda symbol: (requested.append(symbol), KOREAN_PROFILE)[1]
    )
    monkeypatch.setattr(type(provider), "info", PropertyMock(side_effect=RuntimeError("provider down")), raising=False)
    result = CompanyResearchCollector().collect(ticker="000001.ks")[0]
    assert requested == ["000001.KS"]
    profile = result["profile"]
    assert (profile["name"], profile["display_name"], profile["description"]) == (
        "샘플기업",
        "샘플기업",
        "샘플 사업 설명",
    )
    assert (profile["country"], profile["currency"], profile["exchange"]) == ("South Korea", "KRW", "KS")
    assert profile["identity_source_url"] == KOREAN_PROFILE["source_url"]
    assert "profile" in result["unavailable"]


def test_yahoo_profile_for_another_symbol_is_discarded_for_a_korean_listing(provider, monkeypatch):
    monkeypatch.setattr(research_module, "collect_korean_profile", lambda symbol: KOREAN_PROFILE)
    provider.info = {
        "symbol": "OTHER",
        "longName": "Other Corporation",
        "sector": "Technology",
        "longBusinessSummary": "Other business.",
    }
    profile = CompanyResearchCollector().collect(ticker="000001.KS")[0]["profile"]
    assert (profile["name"], profile["description"], profile["sector"]) == ("샘플기업", "샘플 사업 설명", None)


def test_korean_provider_failure_is_recorded_and_public_name_drives_news_search(provider, monkeypatch):
    def unavailable(symbol):
        raise RuntimeError("provider down")

    names, searched = [], []
    monkeypatch.setattr(research_module, "collect_korean_profile", unavailable)
    monkeypatch.setattr(research_module, "public_display_name", lambda symbol: (names.append(symbol), "샘플기업")[1])
    monkeypatch.setattr(
        research_module, "_collect_recent_news", lambda ticker, name: (searched.append((ticker, name)), [])[1]
    )
    provider.info = {"symbol": "000001.KS", "longName": "Sample Corporation"}
    result = CompanyResearchCollector().collect(ticker="000001.KS")[0]
    assert "korean_profile" in result["unavailable"]
    assert (result["profile"]["name"], result["profile"]["display_name"]) == ("Sample Corporation", "샘플기업")
    assert result["profile"]["country"] is None
    assert names == ["000001.KS"]
    assert searched == [("000001.KS", "샘플기업")]


def test_profile_failure_without_another_identity_source_propagates(provider, monkeypatch):
    monkeypatch.setattr(type(provider), "info", PropertyMock(side_effect=RuntimeError("provider down")), raising=False)
    with pytest.raises(RuntimeError, match="provider down"):
        CompanyResearchCollector().collect(ticker="DEMO")


def test_official_fund_page_failure_is_logged_and_yahoo_holdings_are_used(provider, monkeypatch, caplog):
    """공식 운용사 페이지가 실패하면 경고를 남기고 Yahoo 보유 종목으로 채운다.

    `unavailable` 의 키는 단정하지 않는다 — 지금은 Yahoo 가 채운 뒤에도 일반 "fund" 가 남아
    화면이 ETF 운용 자료를 없는 것으로 읽는다(프런트 라벨에는 `fund_official` 이 따로 있다).
    결함 후보라 정답으로 박지 않는다 (#1756).
    """
    requested = []

    def unreachable(url, **kwargs):
        requested.append(url)
        raise requests.ConnectionError("unreachable")

    monkeypatch.setattr(requests, "get", unreachable)
    provider.info = {"symbol": "NASA", "longName": "Source Fund", "quoteType": "ETF"}
    provider.funds_data.top_holdings = pd.DataFrame(
        {"Name": ["Sample Holding"], "Holding Percent": [0.25]}, index=pd.Index(["AAA"])
    )
    with caplog.at_level(logging.WARNING, logger="nuri.collectors.company_research"):
        data = CompanyResearchCollector().collect(ticker="NASA")[0]
    assert requested == [research_module.TEMA_URL]
    assert "공식 ETF 자료 조회 실패: NASA" in caplog.text
    assert (data["fund"]["source_name"], data["fund"]["source_url"]) == (
        "Yahoo Finance",
        "https://finance.yahoo.com/quote/NASA/holdings/",
    )
    assert data["fund"]["holdings"] == [{"name": "Sample Holding", "weight_pct": 25.0}]
    assert data["profile"]["name"] == "Source Fund"


def test_etf_without_an_official_adapter_uses_yahoo_top_holdings(provider):
    provider.info = {
        "symbol": "FUND",
        "longName": "Sample Fund",
        "quoteType": "ETF",
        "currency": "USD",
        "totalAssets": 5_000_000,
    }
    provider.funds_data.top_holdings = pd.DataFrame(
        {"Name": ["Sample Holding", None, "Unparsed Weight"], "Holding Percent": [0.25, 0.125, "n/a"]},
        index=pd.Index(["AAA", "BBB", "CCC"]),
    )
    data = CompanyResearchCollector().collect(ticker="FUND")[0]
    fund = data["fund"]
    assert (fund["source_name"], fund["source_url"]) == (
        "Yahoo Finance",
        "https://finance.yahoo.com/quote/FUND/holdings/",
    )
    assert (fund["aum"], fund["currency"]) == (5_000_000, "USD")
    assert fund["holdings"] == [{"name": "Sample Holding", "weight_pct": 25.0}, {"name": "BBB", "weight_pct": 12.5}]
    assert data["statements"] == {"income": [], "cashflow": [], "balance": []}
    assert data["business"] is None
    assert data["unavailable"] == []
    provider.get_income_stmt.assert_not_called()


def test_fund_holdings_failure_is_reported_as_unavailable(provider):
    class NoHoldings:
        @property
        def top_holdings(self):
            raise RuntimeError("holdings unavailable")

    provider.info = {"symbol": "FUND", "longName": "Sample Fund", "quoteType": "ETF"}
    provider.funds_data = NoHoldings()
    data = CompanyResearchCollector().collect(ticker="FUND")[0]
    assert data["fund"] is None
    assert data["unavailable"] == ["fund"]


def test_yahoo_news_accepts_epoch_dates_and_skips_malformed_items(provider):
    flat = {
        "title": "Flat report",
        "link": "https://example.com/flat",
        "publisher": "Publisher",
        "providerPublishTime": int(kst_now().timestamp()),
    }
    provider.get_news.return_value = [
        "not a news item",
        flat,
        {**flat, "title": "Zero epoch", "providerPublishTime": 0},
        {**flat, "title": "Missing epoch", "providerPublishTime": None},
        {**flat, "title": "Infinite epoch", "providerPublishTime": float("inf")},
    ]
    news = CompanyResearchCollector().collect(ticker="DEMO")[0]["news"]
    # 발행 시각이 없거나 잘못된 기사에 오늘 날짜를 붙이지 않는다.
    assert [(item["title"], item["date"]) for item in news] == [("Flat report", today_kst())]


def test_yahoo_news_failure_is_reported_while_search_results_are_kept(provider, monkeypatch):
    provider.get_news.side_effect = RuntimeError("rate limited")
    current = {
        "date": today_kst(),
        "title": "Search result",
        "url": "https://example.com/current",
        "source": "Publisher",
    }
    monkeypatch.setattr(research_module, "_collect_recent_news", lambda ticker, name: [current])
    result = CompanyResearchCollector().collect(ticker="DEMO")[0]
    assert result["news"] == [current]
    assert result["news_check"]["failed_sources"] == ["Yahoo Finance"]
    assert "news" in result["unavailable"]
