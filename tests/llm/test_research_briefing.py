"""공개 브리핑은 근거·시점·법인·단위 및 송신 허용 목록을 검사한다."""

import json
from unittest.mock import MagicMock

import pytest

from nuri.core.timezone import kst_now
from nuri.llm.research_briefing import generate_briefing, public_bundle, validate_claims, validate_report


@pytest.fixture
def dossier():
    now = kst_now().isoformat()
    return {
        "collected_at": now,
        "profile": {"name": "Demo Company", "symbol": "DEMO", "quote_type": "EQUITY"},
        "holdings": {"account": "Brokerage Alpha", "private_marker": "secret-token"},
        "briefing_evidence": {
            "sources": [
                {
                    "source_id": "official",
                    "url": "https://example.com/release",
                    "title": "Release",
                    "published_at": now[:10],
                    "collected_at": now,
                    "entity": "Demo Company",
                    "kind": "official",
                    "text": "Demo Company plans to expand production by 20%. Demo Company reported revenue growth of 10%.",
                }
            ]
        },
    }


def claim_data():
    return {
        "claims": [
            {
                "claim_id": "plan",
                "source_id": "official",
                "quote": "Demo Company plans to expand production by 20%.",
                "statement": "생산 확대 계획의 목표는 20%입니다.",
                "kind": "plan",
                "entity": "Demo Company",
                "period": None,
            },
            {
                "claim_id": "revenue",
                "source_id": "official",
                "quote": "Demo Company reported revenue growth of 10%.",
                "statement": "매출 증가율은 10%였습니다.",
                "kind": "fact",
                "entity": "Demo Company",
                "period": None,
            },
        ]
    }


def report_data():
    passage = {"text": "생산 확대 계획은 실현 시 성장에 기여하지만 실행 여부를 확인해야 합니다.", "claim_ids": ["plan"]}
    return {
        "summary": passage,
        "business": passage,
        "changes": passage,
        "financials": passage,
        "schedule": passage,
        "arguments": [
            {
                "title": "생산 확대",
                **{key: passage for key in ("fact", "impact", "counterpoint", "checkpoint", "timing")},
            }
        ],
    }


def test_public_allowlist_excludes_private_fields_and_future_sources(dossier):
    dossier["briefing_evidence"]["sources"].append(
        {**dossier["briefing_evidence"]["sources"][0], "published_at": "9999-01-01"}
    )
    bundle = public_bundle(dossier)
    assert len(bundle["sources"]) == 1
    assert "secret-token" not in str(bundle)
    assert "Brokerage Alpha" not in str(bundle)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "fact"},
        {"entity": "Other Company"},
        {"quote": "Demo Company plans to expand production by 40%."},
        {"statement": "생산 확대 계획의 목표는 20억입니다."},
        {"statement": "매수하세요."},
        {"source_id": "unknown"},
    ],
)
def test_invalid_claims_fail_closed(dossier, change):
    raw = claim_data()
    raw["claims"][0].update(change)
    with pytest.raises(ValueError):
        validate_claims(raw, public_bundle(dossier))


@pytest.mark.parametrize(
    "text,refs",
    [
        ("확정된 성장률은 90%입니다.", ["plan"]),
        ("분할매수하세요.", ["plan"]),
        ("매출 증가율은 10%였습니다.", ["plan"]),
        ("계획입니다.", ["unknown"]),
    ],
)
def test_report_cannot_introduce_numbers_trades_or_foreign_claims(dossier, text, refs):
    raw = report_data()
    raw["summary"] = {"text": text, "claim_ids": refs}
    with pytest.raises(ValueError):
        validate_report(raw, validate_claims(claim_data(), public_bundle(dossier)))


def test_generate_uses_gateway_and_never_returns_article_quotes(dossier, monkeypatch):
    client = MagicMock()
    raw = claim_data()
    for index, claim in enumerate(raw["claims"]):
        claim.pop("quote")
        claim.pop("source_id")
        claim["unit_id"] = f"official:{index}"
    client.chat_json.side_effect = [
        raw,
        report_data(),
        {"valid": True, "errors": [], "invalid_claim_ids": [], "reason": ""},
    ]
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    result = generate_briefing(dossier)
    assert result["status"] == "ready"
    assert client.chat_json.call_count == 3
    assert "secret-token" not in str(client.chat_json.call_args_list)
    assert all("quote" not in item for item in result["claims"])
    assert all("text" not in item for item in result["sources"])
    from nuri.llm.research_briefing import WRITE_EXAMPLES

    writer_input = json.loads(client.chat_json.call_args_list[1].kwargs["user"])
    assert writer_input["style_examples"] == WRITE_EXAMPLES
    assert {item["claim_id"] for item in writer_input["claims"]} == {"plan", "revenue"}
    assert "style_examples" not in json.loads(client.chat_json.call_args_list[0].kwargs["user"])


def test_style_example_citations_cannot_become_actual_evidence(dossier):
    from nuri.llm.research_briefing import WRITE_EXAMPLES

    with pytest.raises(ValueError, match="Unknown reference"):
        validate_report(WRITE_EXAMPLES[0]["report"], validate_claims(claim_data(), public_bundle(dossier)))


def test_style_examples_obey_report_and_argument_contracts():
    from nuri.llm.research_briefing import WRITE_EXAMPLES, Argument, Claim

    example = WRITE_EXAMPLES[0]
    claims = [
        Claim(
            **item,
            source_id="example",
            statement="가상의 설명 예시입니다.",
            entity=example["identity"]["name"],
            period=None,
        )
        for item in example["claims"]
    ]
    validate_report(example["report"], claims)
    Argument.model_validate(WRITE_EXAMPLES[1]["argument"])


def test_bad_generation_is_not_displayed(dossier, monkeypatch):
    client = MagicMock()
    client.chat_json.return_value = {"claims": []}
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    result = generate_briefing(dossier)
    assert result["status"] == "invalid"
    assert "report" not in result


def test_incomplete_evidence_never_calls_llm(dossier, monkeypatch):
    dossier["briefing_evidence"]["sources"] = []
    client = MagicMock()
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    assert generate_briefing(dossier)["status"] == "insufficient"
    client.chat_json.assert_not_called()


@pytest.mark.parametrize(
    "original,changed", [("25억원", "25억 달러"), ("3%p", "3%"), ("-10%", "10%"), ("△10억", "10억")]
)
def test_currency_points_and_sign_cannot_change(original, changed):
    from nuri.llm.research_briefing import _numbers

    assert not _numbers(changed).issubset(_numbers(original))


def test_group_fact_cannot_be_attributed_to_issuer(dossier):
    raw = claim_data()
    raw["claims"][0]["quote"] = "Demo Company subsidiary posted revenue growth of 20%."
    dossier["briefing_evidence"]["sources"][0]["text"] += " " + raw["claims"][0]["quote"]
    with pytest.raises(ValueError, match="attribution"):
        validate_claims(raw, public_bundle(dossier))


def _extraction_fixture():
    raw = claim_data()
    for index, claim in enumerate(raw["claims"]):
        claim.pop("quote")
        claim.pop("source_id")
        claim["unit_id"] = f"official:{index}"
    return raw


def test_numeric_repair_is_bounded_and_preserves_verified_facts(dossier, monkeypatch):
    bad = report_data()
    bad["summary"] = {"text": "근거 없는 99% 증가입니다.", "claim_ids": ["plan"]}
    client = MagicMock()
    client.chat_json.side_effect = [
        _extraction_fixture(),
        bad,
        report_data(),
        {"valid": True, "errors": [], "invalid_claim_ids": [], "reason": ""},
    ]
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    result = generate_briefing(dossier)
    assert result["status"] == "ready"
    assert result["numeric_narrative_fallback"] is True
    assert client.chat_json.call_count == 4
    assert "20%" in result["claims"][0]["statement"]


def test_semantic_review_rejects_reversed_or_invented_claims(dossier, monkeypatch):
    client = MagicMock()
    client.chat_json.side_effect = [
        _extraction_fixture(),
        report_data(),
        {"valid": False, "errors": ["direction"], "invalid_claim_ids": [], "reason": "Direction inconsistent."},
        report_data(),
        {"valid": False, "errors": ["direction"], "invalid_claim_ids": [], "reason": "Direction inconsistent."},
    ]
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    result = generate_briefing(dossier)
    assert result["status"] == "invalid"
    assert result["failure_stage"] == "semantic_review"
    assert "report" not in result


@pytest.mark.parametrize(
    "symbol,asset_type", [("DEMO", "EQUITY"), ("111111.KS", "EQUITY"), ("111111.KQ", "EQUITY"), ("FUND", "ETF")]
)
def test_shared_public_contract_handles_markets_without_private_position_input(dossier, symbol, asset_type):
    dossier["profile"].update(symbol=symbol, quote_type=asset_type)
    bundle = public_bundle(dossier)
    assert bundle["ticker"] == symbol
    assert bundle["asset_type"] == asset_type
    assert "holdings" not in bundle


@pytest.mark.parametrize("term", ["subsidiaries", "affiliate", "affiliates", "계열사"])
def test_affiliate_results_cannot_become_issuer_results(dossier, term):
    raw = claim_data()
    raw["claims"][0]["quote"] = f"Demo Company {term} posted revenue growth of 20%."
    dossier["briefing_evidence"]["sources"][0]["text"] += " " + raw["claims"][0]["quote"]
    with pytest.raises(ValueError, match="attribution"):
        validate_claims(raw, public_bundle(dossier))


def test_short_issuer_name_does_not_match_inside_another_word(dossier):
    dossier["profile"]["name"] = "Arm"
    dossier["briefing_evidence"]["sources"][0]["kind"] = "news"
    raw = claim_data()
    raw["claims"][0].update(entity="Arm", quote="The farm plans to expand production by 20%.")
    dossier["briefing_evidence"]["sources"][0]["text"] += " " + raw["claims"][0]["quote"]
    with pytest.raises(ValueError, match="not present"):
        validate_claims(raw, public_bundle(dossier))


def test_verified_official_document_establishes_company_pronoun(dossier):
    raw = claim_data()
    raw["claims"][0]["quote"] = "The company plans to expand production by 20%."
    dossier["briefing_evidence"]["sources"][0]["text"] += " " + raw["claims"][0]["quote"]
    assert validate_claims(raw, public_bundle(dossier))[0].kind == "plan"


def test_official_document_does_not_reassign_named_peer_result(dossier):
    raw = claim_data()
    raw["claims"][0]["quote"] = "Other Company plans to expand production by 20%."
    dossier["briefing_evidence"]["sources"][0]["text"] += " " + raw["claims"][0]["quote"]
    with pytest.raises(ValueError, match="Different named"):
        validate_claims(raw, public_bundle(dossier))


def test_percent_and_korean_calendar_year_are_equivalent_formats():
    from nuri.llm.research_briefing import _numbers

    assert _numbers("35 percent by 2030") == _numbers("35% 2030년")


def test_quantity_conversion_is_exact_and_currency_stays_distinct():
    from nuri.llm.research_briefing import _numbers

    assert _numbers("5.55 million") == _numbers("555만")
    assert _numbers("1.2 billion USD") == _numbers("12억 달러")
    assert _numbers("1,000.0 KRW") == _numbers("1000원")
    assert _numbers("12억 달러") != _numbers("12억원")
    assert _numbers("5.55 million") != _numbers("550만")


def test_business_sales_words_are_not_trading_advice():
    from nuri.llm.research_briefing import _no_trade

    _no_trade("자동차 판매도 회복될 수 있지만 구매수요를 확인해야 합니다.")
    for text in ("추가매수 권고", "매도하세요", "분할매수 전략"):
        with pytest.raises(ValueError, match="Trading recommendation"):
            _no_trade(text)


@pytest.mark.parametrize(
    "quote",
    [
        "다른기업은 매출 10% 증가를 기록했다.",
        "Customers reported growth of 10%.",
        "Our customers reported growth of 10%.",
        "고객 회사는 매출 10% 증가를 기록했다.",
        "경쟁 회사가 매출 10% 증가를 기록했다.",
        "계약 당사자는 매출 10% 증가를 기록했다.",
    ],
)
def test_official_document_requires_issuer_or_issuer_pronoun(dossier, quote):
    dossier["briefing_evidence"]["sources"][0]["text"] = quote
    claim = claim_data()["claims"][1]
    claim["quote"] = quote
    with pytest.raises(ValueError, match="Legal entity"):
        validate_claims({"claims": [claim]}, public_bundle(dossier))


def test_compound_units_abbreviations_and_unknown_suffixes_fail_closed():
    from nuri.llm.research_briefing import _numbers

    assert _numbers("3천억원") == _numbers("300 billion KRW")
    assert _numbers("3천억원") != _numbers("3천만원")
    assert _numbers("$5.2B") != _numbers("5.2달러")
    assert _numbers("40 mn") == _numbers("40 million")
    assert _numbers("3K") == _numbers("3 thousand")
    assert _numbers("5foo") != _numbers("5")
    assert _numbers("-$25") == _numbers("$-25")
    assert _numbers("-$25") != _numbers("$25")


def test_semantic_review_cannot_approve_flagged_claim(dossier, monkeypatch):
    client = MagicMock()
    client.chat_json.side_effect = [
        _extraction_fixture(),
        report_data(),
        {"valid": True, "errors": [], "invalid_claim_ids": ["plan"], "reason": "Flagged claim"},
    ]
    monkeypatch.setattr("nuri.llm.research_briefing.get_client", lambda: client)
    assert generate_briefing(dossier)["status"] == "invalid"


def test_extraction_pool_excludes_ambiguous_subjects_before_model(dossier):
    from nuri.llm.research_briefing import eligible_units

    dossier["briefing_evidence"]["sources"][0]["text"] += (
        " Our customers reported growth of 10%. The company plans to expand production by 20%."
    )
    units = eligible_units(public_bundle(dossier))
    assert len(units) == 3
    assert not any("Our customers" in unit["quote"] for unit in units)
    assert any("The company plans" in unit["quote"] for unit in units)
