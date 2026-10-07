"""공급자 사업 설명을 한국어 구조로 읽는다. 종목별 고정 브리핑은 사용하지 않는다."""

import json
import re
from pathlib import Path

# 공급자 분류·문구의 번역 사전이다. 투자 규칙이나 성장 전망이 아니다.
INDUSTRIES = {
    "Auto Manufacturers": "자동차 제조",
    "Auto Parts": "자동차 부품",
    "Semiconductors": "반도체",
    "Semiconductor Equipment & Materials": "반도체 장비·소재",
    "Consumer Electronics": "소비자 전자제품",
    "Software - Infrastructure": "소프트웨어 인프라",
    "Software - Application": "응용 소프트웨어",
    "Internet Content & Information": "인터넷 콘텐츠·정보",
    "Internet Retail": "온라인 유통",
    "Aerospace & Defense": "항공우주·방위",
    "Communication Equipment": "통신 장비",
    "Telecom Services": "통신 서비스",
    "Biotechnology": "바이오 기술",
    "Drug Manufacturers - General": "의약품 제조",
    "Drug Manufacturers - Specialty & Generic": "전문·복제 의약품",
    "Medical Devices": "의료 기기",
    "Banks - Regional": "지역 은행",
    "Banks - Diversified": "종합 은행",
    "Credit Services": "신용·결제 서비스",
    "Insurance - Diversified": "종합 보험",
    "Asset Management": "자산 운용",
    "Oil & Gas Integrated": "종합 석유·가스",
    "Solar": "태양광",
    "Utilities - Regulated Electric": "전력 공급",
    "Specialty Industrial Machinery": "산업 기계",
    "Real Estate Services": "부동산 서비스",
}

SECTORS = {
    "Consumer Cyclical": "경기소비재",
    "Consumer Defensive": "필수소비재",
    "Technology": "기술",
    "Financial Services": "금융",
    "Healthcare": "헬스케어",
    "Industrials": "산업재",
    "Energy": "에너지",
    "Utilities": "유틸리티",
    "Real Estate": "부동산",
    "Basic Materials": "소재",
    "Communication Services": "통신·미디어",
}

ACTIVITIES = [
    (
        r"invests in",
        "기업·사업 투자",
        "기업이나 사업에 투자하는 회사로 설명됩니다.",
        "피투자기업의 가치·배당과 지분법·처분 손익을 구분해 확인해야 합니다. 업종 분류만으로 직접 제조하는 기업과 같은 방식으로 평가하지 마세요.",
    ),
    (
        r"manufactures and distributes motor vehicles",
        "차량 제조·판매",
        "자동차와 부품을 생산하고 유통합니다.",
        "판매량·차종 구성·판매가격과 제조 원가가 수익성에 어떻게 반영되는지 확인해야 합니다.",
    ),
    (
        r"(?:electric vehicles|eco vehicles|battery electric|hybrid)",
        "전동화 제품",
        "사업 설명에 전기차·친환경차 또는 하이브리드 제품이 포함됩니다.",
        "제품별 판매 비중과 가격 경쟁, 개발·생산 투자가 이익과 현금흐름에 미치는 영향을 확인해야 합니다.",
    ),
    (
        r"(?:vehicle financing|automotive financing)",
        "자동차 금융",
        "차량 구매를 지원하는 금융 사업도 운영합니다.",
        "금융 사업의 대출·리스 자산과 자금 조달이 연결 부채·현금흐름에 포함될 수 있습니다. 제조 부문의 현금흐름과 구분해 공시를 읽어야 합니다.",
    ),
    (
        r"(?:graphics processing|graphics and compute|graphics processing units|GPUs)",
        "그래픽·연산 반도체",
        "사업 설명에 그래픽 처리와 연산용 반도체가 포함됩니다.",
        "고객 수요와 제품 공급, 데이터센터 투자 및 경쟁 제품의 변화를 함께 확인해야 합니다.",
    ),
    (
        r"(?:memory chips|memory semiconductors|dynamic random access memory|DRAM)",
        "메모리 반도체",
        "메모리 반도체를 사업 대상으로 설명합니다.",
        "제품 가격·재고·설비 투자가 매출과 현금흐름에 어떻게 반영되는지 확인해야 합니다.",
    ),
    (
        r"(?:foundry|wafer fabrication)",
        "반도체 생산",
        "반도체 위탁생산 또는 웨이퍼 제조 사업이 포함됩니다.",
        "고객 주문·가동률·공정 투자와 실제 수익성을 함께 확인해야 합니다.",
    ),
    (
        r"(?:cloud services|cloud computing|cloud infrastructure)",
        "클라우드",
        "클라우드 서비스나 컴퓨팅 인프라를 제공합니다.",
        "서비스 매출 증가와 인프라 투자·운영 비용의 변화를 대조해야 합니다.",
    ),
    (
        r"(?:digital advertising|online advertising|advertising services)",
        "광고",
        "디지털·온라인 광고 서비스가 사업 설명에 포함됩니다.",
        "광고 수요와 이용자 활동, 서비스별 수익성이 함께 개선되는지 확인해야 합니다.",
    ),
    (
        r"(?:e-commerce|online retail|online stores)",
        "온라인 유통",
        "온라인 유통·전자상거래 서비스를 운영합니다.",
        "판매 규모와 물류·판매 비용의 변화가 영업이익으로 이어지는지 확인해야 합니다.",
    ),
    (
        r"(?:smartphones|smartphone|mobile phones)",
        "스마트폰",
        "스마트폰 또는 휴대전화 관련 제품·서비스가 포함됩니다.",
        "제품 수요·교체 주기와 서비스 매출, 경쟁 및 공급망 변화를 확인해야 합니다.",
    ),
    (
        r"(?:subscription|subscriptions)",
        "구독 서비스",
        "구독 방식의 제품·서비스가 사업 설명에 포함됩니다.",
        "가입자·계약 유지와 매출 증가가 비용 증가를 상쇄하는지 확인해야 합니다.",
    ),
    (
        r"(?:launch vehicles|launch services|space launch)",
        "우주 발사",
        "발사체 또는 우주 발사 서비스를 사업 대상으로 설명합니다.",
        "개발·발사 일정과 계약 이행, 현금 소요가 실제 실적과 함께 개선되는지 확인해야 합니다.",
    ),
    (
        r"(?:satellite|satellites)",
        "위성",
        "위성 관련 제품·서비스가 포함됩니다.",
        "위성 배치·계약·서비스 개시와 투자 비용을 함께 확인해야 합니다.",
    ),
    (
        r"(?:clinical.stage|clinical trials|therapeutics)",
        "치료제 개발",
        "임상 또는 치료제 개발을 사업 대상으로 설명합니다.",
        "임상 결과·승인 절차와 연구비·보유 현금의 변화를 공시에서 확인해야 합니다.",
    ),
    (
        r"(?:deposit products|accepts deposits|deposit services)",
        "예금·은행 서비스",
        "예금 관련 금융 서비스를 운영합니다.",
        "금리·예금 조달과 대출 자산의 건전성, 금융업에 맞는 자본 지표를 확인해야 합니다.",
    ),
    (
        r"(?:insurance products|insurance services|insurance coverage)",
        "보험",
        "보험 관련 상품·서비스가 포함됩니다.",
        "보험 손익과 자산 운용 성과, 지급 부담과 자본 여력을 함께 확인해야 합니다.",
    ),
    (
        r"(?:payment processing|payment services|payment network)",
        "결제",
        "결제 처리·네트워크 서비스를 제공합니다.",
        "거래량 증가와 수수료·운영 비용, 규제의 변화를 확인해야 합니다.",
    ),
    (
        r"(?:crude oil|natural gas)",
        "석유·가스",
        "원유 또는 천연가스 관련 사업이 포함됩니다.",
        "원자재 가격과 생산·투자 비용이 현금흐름에 미치는 영향을 확인해야 합니다.",
    ),
    (
        r"(?:solar energy|solar power|solar modules)",
        "태양광",
        "태양광 에너지·발전 또는 모듈 사업이 포함됩니다.",
        "수요·제품 가격·설비 투자와 정책 지원의 변화를 함께 확인해야 합니다.",
    ),
]


def public_display_name(symbol: str) -> str | None:
    """보유 여부와 무관하게 공개 KRX 이름 맵만 읽는다. 개인 별칭은 뉴스 검색에 쓰지 않는다."""
    if not symbol.endswith((".KS", ".KQ")):
        return None
    try:
        names = json.loads((Path(__file__).resolve().parents[2] / "config" / "kr_ticker_names.json").read_text())
        name = names.get(symbol)
        return name if isinstance(name, str) and name.strip() else None
    except (OSError, ValueError):
        return None


def describe_business(profile: dict) -> dict:
    description = profile.get("description") or ""
    activities = []
    for pattern, title, explanation, checkpoint in ACTIVITIES:
        match = re.search(pattern, description, re.I)
        if match:
            activities.append(
                {"title": title, "explanation": explanation, "checkpoint": checkpoint, "source_phrase": match.group()}
            )
    industry_name = profile.get("industry")
    sector_name = profile.get("sector")
    industry = INDUSTRIES.get(industry_name) if isinstance(industry_name, str) else None
    sector = SECTORS.get(sector_name) if isinstance(sector_name, str) else None
    name = profile.get("display_name") or profile.get("name")
    summary = f"{name}의 공급자 사업 분류는 {industry}입니다." if industry else None
    if activities:
        summary = " ".join(
            filter(
                None, [summary, f"사업 설명에서 {'·'.join(item['title'] for item in activities)} 사업이 확인됩니다."]
            )
        )
    return {
        "summary": summary,
        "industry_label": industry,
        "sector_label": sector,
        "activities": activities,
        "has_financing": bool(
            re.search(r"vehicle financing|automotive financing|banking|accepts deposits", description, re.I)
        ),
        "source_name": "Yahoo Finance",
        "source_url": f"https://finance.yahoo.com/quote/{profile['symbol']}/profile/",
    }
