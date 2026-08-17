"""
매크로 이벤트 헤드라인 분류기 — OpenAI gpt-5.4-nano (primary) + keyword regex (fallback).

Phase A 단독 모듈 — macro_score / classifier 의 의사결정 로직은 일절 안 건드림.
출력만 produce, 사용은 Phase B에서.

입력: headline (str)
출력: {category, sentiment, confidence, regime_hint}

LLM 경로는 STRATEGY.md §4.4.3 외부 LLM Egress Policy 하에서만 작동한다.
이 분류기가 wrapper에 보내는 데이터는 **공개 RSS 헤드라인 한정 (Tier 0)** —
사용자 narrative나 portfolio 데이터는 절대 이 함수를 통해 외부로 나가지 않는다.

#152 Step 2 — 이전에는 Ollama Qwen3.5 (primary) + regex (fallback) 였으나,
Mac mini production hardware에서 Ollama가 hang되는 문제 (Phase A 실측에서 확인)
+ regex의 nuance 손실 (Iran 키워드가 Fed 헤드라인 흡수 등) 때문에 LLM 경로를
OpenAI gpt-5.4-nano로 교체. regex는 per-headline graceful degradation으로 유지
(wrapper raise / opt-out / offline 시 단일 헤드라인은 regex로, 나머지는 정상).

사용법:
    from nuri.llm.event_classifier import classify_event
    result = classify_event("Iran and Israel agree to ceasefire after 2 weeks of strikes")
    # → {'category': 'geopolitical_de_escalation', 'sentiment': 0.5, ...}
"""

import logging
import re

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# 카테고리 — 새 카테고리 추가 시 REGIME_HINT 매핑도 반드시 함께 추가.
CATEGORIES: tuple[str, ...] = (
    "geopolitical_escalation",  # war, sanctions, missile strike, invasion
    "geopolitical_de_escalation",  # ceasefire, treaty, peace talks
    "fed_dovish",  # rate cut, dovish, pause, easing
    "fed_hawkish",  # rate hike, hawkish, tightening
    "oil_supply_shock",  # opec cut, sanctions on oil, refinery shutdown
    "oil_demand_drop",  # oil oversupply, recession-driven demand fall
    "earnings_beat",  # beat estimates, raised guidance
    "earnings_miss",  # missed, cut guidance, profit warning
    "sector_rally",  # broad sector surge / rotation
    "sector_selloff",  # sector plunge / crash
    "trade_war",  # tariff, retaliation, trade deal collapse
    "export_surge",  # Korea/global export boom, trade surplus, shipment growth
    "currency_shift",  # FX major move (USD/KRW, yen carry unwind, DXY)
    "demand_growth",  # semiconductor demand, chip shortage, AI capex, global PMI up
    "neutral",  # default — no actionable signal
)

# 카테고리 → 레짐 힌트 (Phase B에서 special_regime promotion 후보로 사용 예정).
# Phase A에서는 단순히 DB에 저장만, 의사결정 로직은 안 건드림.
REGIME_HINT_BY_CATEGORY: dict[str, str | None] = {
    "geopolitical_escalation": "bear_high_vol",
    "geopolitical_de_escalation": "recovery",
    "fed_dovish": "bull_low_vol",
    "fed_hawkish": "sideways_high_vol",
    "oil_supply_shock": "stagflation",
    "oil_demand_drop": "recovery",
    "earnings_beat": "bull_low_vol",
    "earnings_miss": "bear_high_vol",
    "sector_rally": "sector_rotation",
    "sector_selloff": "bear_high_vol",
    "trade_war": "bear_high_vol",
    "export_surge": "recovery",
    "currency_shift": "sideways_high_vol",
    "demand_growth": "bull_low_vol",
    "neutral": None,
}

# Regex 폴백 — Ollama 다운/네트워크 차단 시 결정론적으로 동작.
# (regex_pattern, category, sentiment_default)
# 패턴은 case-insensitive, 학습이 아닌 키워드 매칭 — false positive 있을 수 있음.
_KEYWORD_PATTERNS: list[tuple[str, str, float]] = [
    (
        r"\b(ceasefire|truce|peace deal|treaty signed|de[- ]?escalat\w*|talks resume)\b",
        "geopolitical_de_escalation",
        0.5,
    ),
    (
        r"\b(missile strike|invasion|attack|escalat\w*|sanctions imposed|retaliat\w*|airstrike|war)\b",
        "geopolitical_escalation",
        -0.6,
    ),
    (r"\b(rate cut|dovish|fed pause|easing cycle|cut rates)\b", "fed_dovish", 0.4),
    (r"\b(rate hike|hawkish|tightening|raise rates|hike rates)\b", "fed_hawkish", -0.3),
    (r"\b(opec[+]? cut|oil supply|refinery shut|crude shortage)\b", "oil_supply_shock", -0.4),
    (r"\b(oil price drop|crude plunge|oil oversupply|wti tumbl)\b", "oil_demand_drop", 0.2),
    (r"\b(beat estimates|earnings beat|raised guidance|crushed estimates|tops forecast)\b", "earnings_beat", 0.5),
    (r"\b(earnings miss|missed estimates|cut guidance|profit warn|guidance lower)\b", "earnings_miss", -0.5),
    # 한국/글로벌 수출 + 반도체 수요 (#137) — sector_rally보다 먼저 매칭되어야 함 (구체적 패턴 우선)
    (r"(export[s ].*surge|export[s ].*boom|export[s ].*jump|trade surplus|shipment.*grow)", "export_surge", 0.6),
    (r"(Korea.*export|Korean.*export|KR.*export|KOSPI.*export)", "export_surge", 0.5),
    (r"(semiconductor.*demand|chip.*demand|AI.*capex|chip.*shortage|fab.*expansion|HBM.*demand)", "demand_growth", 0.5),
    (r"(TSMC.*revenue|TSMC.*record|chip.*boom|foundry.*demand)", "demand_growth", 0.5),
    (r"\b(won.*weak|dollar.*strong|USD.*KRW.*rise|yen.*carry|DXY.*surge|currency.*depreciat)", "currency_shift", -0.3),
    (r"\b(won.*strong|dollar.*weak|USD.*KRW.*fall|DXY.*drop|currency.*appreciat)", "currency_shift", 0.3),
    # 일반 섹터 랠리/셀오프 — 위의 구체적 패턴에 안 걸린 경우만
    (r"\b(rall(y|ies|ied)|surges?|jumps?|soars?|rebounds?|sector rotation)\b", "sector_rally", 0.3),
    (r"\b(plunges?|sell[- ]?off|crash(es)?|tumbles?|sinks?|rout)\b", "sector_selloff", -0.4),
    (r"\b(tariff|trade war|trade deal|retaliatory)\b", "trade_war", -0.3),
]


def classify_event(headline: str, *, use_llm: bool = True) -> dict:
    """헤드라인 → 구조화된 분류 결과.

    use_llm=True (기본): OpenAI gpt-5.4-nano 시도 → 실패 시 regex 폴백.
    use_llm=False: regex만 사용 (테스트/CI/오프라인용).

    LLM 경로는 wrapper(`nuri.llm.openai_client`)를 통해 호출되며 audit log
    + opt-out + 비용 logging이 자동 적용된다. 단일 헤드라인 호출 실패는
    조용히 regex로 폴백한다 (collector 100건 batch 중 일부 실패가 전체를
    죽이지 않게). wrapper 자체의 예외(Disabled/Unavailable/ResponseError)는
    여기서 흡수되며 caller가 알 필요 없다.

    반환:
        {
            "category": str (CATEGORIES 중 하나),
            "sentiment": float in [-1.0, 1.0],
            "confidence": float in [0.0, 1.0],
            "regime_hint": str | None,
        }
    """
    if not headline or not headline.strip():
        return _neutral_result()

    if use_llm:
        try:
            return _classify_with_openai(headline)
        except Exception as e:  # noqa: BLE001 — wrapper 예외 → 조용히 regex 폴백
            logger.debug("OpenAI 분류 실패 (%s) → regex 폴백", type(e).__name__)

    return _classify_with_regex(headline)


def _classify_with_regex(headline: str) -> dict:
    """결정론적 키워드 매칭. 네트워크/LLM 무관 — 항상 동작."""
    text = headline.lower()
    for pattern, category, sentiment in _KEYWORD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {
                "category": category,
                "sentiment": sentiment,
                "confidence": 0.5,  # regex는 신뢰도 mid — LLM보다 낮음
                "regime_hint": REGIME_HINT_BY_CATEGORY[category],
                "classification_method": "regex",
            }
    return _neutral_result()


def _classify_with_openai(headline: str) -> dict:
    """OpenAI gpt-5.4-nano 분류 — wrapper 경유.

    실패 시 wrapper가 ExternalLLMDisabled / ExternalLLMUnavailable /
    ExternalLLMResponseError 중 하나를 raise하며, 상위 classify_event가
    이를 흡수해 regex 폴백한다. 이 함수는 wrapper 예외를 직접 처리하지 않는다.

    데이터 클래스: 이 함수가 wrapper에 보내는 user 메시지는 **공개 RSS 헤드라인**
    뿐이며 사용자 portfolio/narrative는 절대 포함하지 않는다 (STRATEGY.md §4.4.3
    Tier 0 한정).
    """
    from nuri.llm.openai_client import get_client

    system_prompt = (
        "You classify financial news headlines for a quant investment system. "
        "Return ONLY a JSON object with these fields:\n"
        f"- category: one of {list(CATEGORIES)}\n"
        "- sentiment: float -1.0 (very bearish) to 1.0 (very bullish)\n"
        "- confidence: float 0.0 to 1.0\n\n"
        "RULES:\n"
        "1. If a headline mentions multiple topics, classify by the PRIMARY topic.\n"
        "   Example: 'Fed holds rates steady amid Iran war' → fed_dovish\n"
        "2. MACRO vs SECTOR distinction:\n"
        "   - sector_rally: single sector rotation (e.g., 'XLK rallies 2%')\n"
        "   - export_surge: country-level export growth (e.g., 'Korea exports surge 36.7%')\n"
        "   - demand_growth: industry demand expansion (e.g., 'semiconductor demand TSMC record')\n"
        "3. KOREAN CONTEXT: Korea is a major semiconductor/auto/steel exporter.\n"
        "   'Korea exports surge' = export_surge (NOT sector_rally or neutral).\n"
        "   'Korean semiconductor shipments grow' = demand_growth.\n"
        "4. CONFIDENCE: headline with specific data (%, $, YoY) → 0.7-0.9.\n"
        "   Vague headline ('reports suggest') → 0.4-0.6.\n"
        "5. currency_shift: major FX moves (USD/KRW, yen carry, DXY)."
    )

    parsed = get_client().chat_json(
        system=system_prompt,
        user=f"Headline: {headline}",
    )
    return _normalize(parsed)


def _normalize(parsed: dict) -> dict:
    """LLM 출력을 검증·클램프하여 안전한 dict 반환."""
    category = parsed.get("category", "neutral")
    if category not in CATEGORIES:
        # 미지의 카테고리 → neutral로 강제 (신뢰도 낮춤)
        return {**_neutral_result(), "confidence": 0.2, "classification_method": "normalized_invalid"}

    sentiment = float(parsed.get("sentiment", 0.0))
    sentiment = max(-1.0, min(1.0, sentiment))

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    return {
        "category": category,
        "sentiment": sentiment,
        "confidence": confidence,
        "regime_hint": REGIME_HINT_BY_CATEGORY[category],
        "classification_method": "openai",
    }


def _neutral_result() -> dict:
    return {
        "category": "neutral",
        "sentiment": 0.0,
        "confidence": 0.3,
        "regime_hint": None,
        "classification_method": "neutral_default",
    }
