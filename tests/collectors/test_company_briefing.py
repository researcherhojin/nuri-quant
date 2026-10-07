"""기업별 고정 문장 없이 공급자 사업 문구를 한국어로 읽는다."""

import pytest

from nuri.collectors.company_briefing import describe_business
from nuri.collectors.korean_research import parse_korean_profile


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
