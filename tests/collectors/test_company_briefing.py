"""기업별 고정 문장 없이 공급자 사업 문구를 한국어로 읽는다."""

import json
from types import SimpleNamespace

import pytest
import requests

from nuri.collectors import company_briefing
from nuri.collectors.company_briefing import describe_business, public_display_name
from nuri.collectors.korean_research import collect_korean_profile, parse_korean_profile


def test_automotive_financing_context_depends_on_actual_description():
    result = describe_business(
        {
            "symbol": "DEMO",
            "name": "Demo Company",
            "industry": "Auto Manufacturers",
            "description": "Manufactures and distributes motor vehicles and offers vehicle financing and hybrid cars.",
        }
    )
    assert result["industry_label"] == "자동차 제조"
    assert result["has_financing"] is True
    assert [item["title"] for item in result["activities"]] == ["차량 제조·판매", "전동화 제품", "자동차 금융"]
    without = describe_business(
        {
            "symbol": "DEMO",
            "name": "Demo Company",
            "industry": "Auto Manufacturers",
            "description": "Manufactures and distributes motor vehicles.",
        }
    )
    assert without["has_financing"] is False
    assert len(without["activities"]) == 1


def test_unknown_business_is_not_invented_and_does_not_depend_on_holding():
    unknown = describe_business(
        {"symbol": "DEMO", "name": "Demo Company", "description": "No business details provided."}
    )
    assert unknown["summary"] is None
    assert unknown["activities"] == []
    semiconductor = describe_business(
        {
            "symbol": "OTHER",
            "name": "Other Company",
            "industry": "Semiconductors",
            "description": "Provides memory semiconductors and cloud services.",
        }
    )
    assert semiconductor["industry_label"] == "반도체"
    assert [item["title"] for item in semiconductor["activities"]] == ["메모리 반도체", "클라우드"]


def korean_sample():
    basic = {"itemCode": "000001", "stockName": "샘플 ETF", "stockEndType": "etf", "stockExchangeType": {"code": "KS"}}
    integration = {
        "itemCode": "000001",
        "stockEndType": "etf",
        "description": "선물에 투자하고 환헤지를 실시합니다.",
        "totalInfos": [{"code": "etfBaseIdx", "value": "Sample Index"}],
        "etfKeyIndicator": {"totalFee": 0, "nav": "1,000", "marketValueRaw": "1000000", "deviationRate": 0},
    }
    return basic, integration


def test_korean_etf_preserves_zero_unknown_dates_and_market_value_is_not_aum():
    result = parse_korean_profile("000001.KS", *korean_sample())
    assert result["quote_type"] == "ETF"
    assert result["fund"]["expense_pct"] == 0
    assert result["fund"]["nav"] == 1000
    assert result["fund"]["deviation_pct"] == 0
    assert result["fund"]["aum"] is None
    assert result["fund"]["holdings_as_of"] is None
    assert len(result["fund"]["structure_notes"]) == 2


@pytest.mark.parametrize("symbol", ["000002.KS", "000001.KQ"])
def test_korean_provider_must_match_code_and_exchange(symbol):
    with pytest.raises(ValueError):
        parse_korean_profile(symbol, *korean_sample())


def test_asset_type_mismatch_is_not_a_company():
    basic, integration = korean_sample()
    integration["stockEndType"] = "stock"
    with pytest.raises(ValueError):
        parse_korean_profile("000001.KS", basic, integration)


@pytest.fixture
def name_map(tmp_path, monkeypatch):
    """`config/kr_ticker_names.json` 은 gitignored 라 CI 에 없다 — 모듈 위치를 tmp 로 옮겨 픽스처 맵을 읽게 한다."""
    monkeypatch.setattr(company_briefing, "__file__", str(tmp_path / "nuri" / "collectors" / "company_briefing.py"))
    (tmp_path / "config").mkdir()
    return tmp_path / "config" / "kr_ticker_names.json"


def test_display_name_comes_only_from_a_non_blank_public_map_entry(name_map):
    name_map.write_text(
        json.dumps({"000001.KS": "샘플기업", "000002.KQ": "  ", "000003.KS": 3, "DEMO": "Demo Company"})
    )
    assert public_display_name("000001.KS") == "샘플기업"
    assert public_display_name("000002.KQ") is None
    assert public_display_name("000003.KS") is None
    assert public_display_name("000004.KS") is None
    assert public_display_name("DEMO") is None  # 맵에 있어도 국내 심볼이 아니면 읽지 않는다


@pytest.mark.parametrize("content", [None, "{broken"])
def test_missing_or_corrupt_name_map_yields_no_name(name_map, content):
    if content is not None:
        name_map.write_text(content)
    assert public_display_name("000001.KS") is None


def test_korean_equity_keeps_provider_identity_without_fund_fields():
    basic = {
        "itemCode": "000001",
        "stockName": "샘플기업",
        "stockEndType": "stock",
        "stockExchangeType": {"code": "KQ"},
    }
    integration = {"itemCode": "000001", "stockEndType": "stock", "description": "샘플 사업 설명"}
    assert parse_korean_profile("000001.KQ", basic, integration) == {
        "name": "샘플기업",
        "quote_type": "EQUITY",
        "source_url": "https://stock.naver.com/domestic/stock/000001",
        "description": "샘플 사업 설명",
        "exchange": "KQ",
        "fund": None,
    }


def test_unparseable_provider_numbers_stay_unknown_instead_of_zero():
    basic, integration = korean_sample()
    integration["etfKeyIndicator"] = {"totalFee": "-", "nav": None, "deviationRate": "0.25%"}
    fund = parse_korean_profile("000001.KS", basic, integration)["fund"]
    assert fund["expense_pct"] is None
    assert fund["nav"] is None
    assert fund["deviation_pct"] == 0.25


@pytest.mark.parametrize("symbol", ["5930.KS", "000001.KX", "000001", "00000/.KS"])
def test_unsupported_korean_symbol_is_refused_before_any_request(monkeypatch, symbol):
    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(requests, "get", unexpected)
    with pytest.raises(ValueError, match="Unsupported Korean symbol"):
        collect_korean_profile(symbol)


def test_korean_profile_reads_both_public_endpoints(monkeypatch):
    basic, integration = korean_sample()
    payloads = {"basic": basic, "integration": integration}
    requested = []

    def get(url, **kwargs):
        requested.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payloads[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(requests, "get", get)
    result = collect_korean_profile("000001.KS")
    assert (result["name"], result["quote_type"], result["exchange"]) == ("샘플 ETF", "ETF", "KS")
    assert requested == [
        ("https://m.stock.naver.com/api/stock/000001/basic", {"timeout": 8}),
        ("https://m.stock.naver.com/api/stock/000001/integration", {"timeout": 8}),
    ]
