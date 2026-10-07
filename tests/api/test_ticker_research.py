"""기업 브리핑은 공급자 신원·보고 기간·결측값을 보존한다."""

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from nuri.collectors.company_research import CompanyResearchCollector
from nuri.core.db import get_db


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
