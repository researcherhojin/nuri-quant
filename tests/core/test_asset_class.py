"""`nuri/core/asset_class.py` — 자산군 분류 (#248 에서 도입, #1619 PR 2 에서 core 로 이동).

`tests/trading/engine/test_certification.py::TestAssetClassification` 과 e2 branch-coverage 의
분류 테스트를 옮겨 왔다 — 인증기 테스트가 삭제돼도 분류 잠금은 남아야 한다.
"""

from __future__ import annotations

from nuri.core.asset_class import classify_asset_class
from nuri.core.rules import RULES


class TestRealRules:
    """config/rules.yaml 의 실제 규칙으로 — 순서(sector_prefix 가 ticker_suffix 보다 먼저)를 잠근다."""

    def test_sector_prefix_beats_suffix(self):
        """KR 상장 US 추종 ETF 는 ticker 가 .KS 여도 기초자산 기준 us_equity."""
        rules = RULES["asset_class_rules"]
        assert classify_asset_class("448300.KS", "ETF/USIndex", rules) == "us_equity"
        assert classify_asset_class("132030.KS", "ETF/Commodity", rules) == "commodity"
        assert classify_asset_class("447660.KS", "ETF/Bond", rules) == "bond"
        assert classify_asset_class("292160.KS", "ETF/KRIndex", rules) == "kr_index"
        assert classify_asset_class("381170.KS", "ETF/USTech", rules) == "us_equity"

    def test_ks_suffix_without_sector_prefix(self):
        rules = RULES["asset_class_rules"]
        assert classify_asset_class("005930.KS", "Semiconductor", rules) == "kr_equity"
        assert classify_asset_class("000660.KS", "Semiconductor", rules) == "kr_equity"

    def test_kq_suffix(self):
        assert classify_asset_class("068760.KQ", "Biotech", RULES["asset_class_rules"]) == "kr_equity"

    def test_us_default(self):
        rules = RULES["asset_class_rules"]
        assert classify_asset_class("AAPL", "Technology", rules) == "us_equity"
        assert classify_asset_class("UNKNOWN", "", rules) == "us_equity"


class TestMatchBranches:
    def test_safety_net_without_default_rule(self):
        rules = [{"match": {"ticker_suffix": ".KS"}, "asset_class": "kr_equity"}]
        assert classify_asset_class("AAPL", "Technology", rules) == "us_equity"

    def test_sector_exact_match(self):
        rules = [
            {"match": {"sector": "Treasury"}, "asset_class": "bond"},
            {"match": {"default": True}, "asset_class": "us_equity"},
        ]
        assert classify_asset_class("TLT", "Treasury", rules) == "bond"
