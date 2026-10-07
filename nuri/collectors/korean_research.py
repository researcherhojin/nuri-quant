"""국내 종목 신원·ETF 설명의 공개 공급자 보완. 계좌 정보는 읽지 않는다."""

import math
import re


def _number(value):
    try:
        result = float(str(value).replace(",", "").replace("%", ""))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def parse_korean_profile(symbol: str, basic: dict, integration: dict) -> dict:
    code, market = symbol.rsplit(".", 1)
    if (
        basic.get("itemCode") != code
        or integration.get("itemCode") != code
        or basic.get("stockExchangeType", {}).get("code") != market
        or not basic.get("stockName")
    ):
        raise ValueError("Korean provider identity mismatch")
    if basic.get("stockEndType") != integration.get("stockEndType"):
        raise ValueError("Korean provider asset type mismatch")
    fund = None
    source = f"https://stock.naver.com/domestic/stock/{code}"
    if basic.get("stockEndType") == "etf":
        metrics = {item["code"]: item.get("value") for item in integration.get("totalInfos", []) if item.get("code")}
        key = integration.get("etfKeyIndicator") or {}
        description = integration.get("description")
        fund = {
            "name": basic["stockName"],
            "description": description,
            "strategy_text": description,
            "source_name": "네이버페이 증권",
            "source_url": source,
            "details_as_of": None,
            "holdings_as_of": None,
            "valuation_as_of": None,
            "expense_pct": _number(key.get("totalFee", metrics.get("fundPay"))),
            "currency": "KRW",
            "aum": None,
            "holding_count": None,
            "inception": None,
            "holdings": [],
            "risks": [],
            "prospectus_url": None,
            "benchmark": metrics.get("etfBaseIdx"),
            "issuer": key.get("issuerName") or metrics.get("issueName"),
            "nav": _number(key.get("nav")),
            "deviation_pct": _number(key.get("deviationRate")),
        }
        # 설명에 실제 표기된 투자 구조에 대해서만 해설한다.
        fund["structure_notes"] = [
            text
            for phrase, text in [
                (
                    "선물",
                    "선물 기반 상품은 현물 가격뿐 아니라 계약 교체 비용과 선물 만기의 영향을 받습니다. 기초지수의 산출 방식과 롤오버를 확인해야 합니다.",
                ),
                (
                    "환헤지",
                    "환헤지는 환율 영향을 줄이는 구조입니다. 헤지 비용과 실제 헤지 비율을 확인해야 하며 환율 위험이 완전히 없어지는 것은 아닙니다.",
                ),
                (
                    "레버리지",
                    "레버리지 상품은 일간 목표 배수를 추종할 수 있습니다. 장기 수익률이 같은 배수가 되는 것은 아니므로 투자설명서의 추종 기간을 확인해야 합니다.",
                ),
                (
                    "커버드콜",
                    "커버드콜 구조는 옵션 매도로 분배 재원을 확보할 수 있지만 상승 참여가 제한될 수 있습니다. 분배율과 총수익률을 구분해야 합니다.",
                ),
            ]
            if description and phrase in description
        ]
    return {
        "name": basic["stockName"],
        "quote_type": "ETF" if fund else "EQUITY",
        "source_url": source,
        "description": integration.get("description"),
        "exchange": market,
        "fund": fund,
    }


def collect_korean_profile(symbol: str) -> dict:
    import requests

    if not re.fullmatch(r"[A-Z0-9]{6}\.(KS|KQ)", symbol):
        raise ValueError("Unsupported Korean symbol")
    code = symbol.split(".")[0]
    records = []
    for endpoint in ("basic", "integration"):
        response = requests.get(f"https://m.stock.naver.com/api/stock/{code}/{endpoint}", timeout=8)
        response.raise_for_status()
        records.append(response.json())
    return parse_korean_profile(symbol, *records)
