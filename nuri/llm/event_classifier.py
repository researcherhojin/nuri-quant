"""
매크로 이벤트 헤드라인 분류기 — Ollama Qwen3.5 (primary) + keyword regex (fallback).

Phase A 단독 모듈 — macro_score / classifier 의 의사결정 로직은 일절 안 건드림.
출력만 produce, 사용은 Phase B에서.

입력: headline (str)
출력: {category, sentiment, confidence, regime_hint}

사용법:
    from nuri.llm.event_classifier import classify_event
    result = classify_event("Iran and Israel agree to ceasefire after 2 weeks of strikes")
    # → {'category': 'geopolitical_de_escalation', 'sentiment': 0.5, ...}
"""
import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5")
OLLAMA_TIMEOUT_SEC = 15  # collector를 블로킹하지 않도록 짧게


# 카테고리 — 새 카테고리 추가 시 REGIME_HINT 매핑도 반드시 함께 추가.
CATEGORIES: tuple[str, ...] = (
    "geopolitical_escalation",     # war, sanctions, missile strike, invasion
    "geopolitical_de_escalation",  # ceasefire, treaty, peace talks
    "fed_dovish",                  # rate cut, dovish, pause, easing
    "fed_hawkish",                 # rate hike, hawkish, tightening
    "oil_supply_shock",            # opec cut, sanctions on oil, refinery shutdown
    "oil_demand_drop",             # oil oversupply, recession-driven demand fall
    "earnings_beat",               # beat estimates, raised guidance
    "earnings_miss",               # missed, cut guidance, profit warning
    "sector_rally",                # broad sector surge / rotation
    "sector_selloff",              # sector plunge / crash
    "trade_war",                   # tariff, retaliation, trade deal collapse
    "neutral",                     # default — no actionable signal
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
    "neutral": None,
}

# Regex 폴백 — Ollama 다운/네트워크 차단 시 결정론적으로 동작.
# (regex_pattern, category, sentiment_default)
# 패턴은 case-insensitive, 학습이 아닌 키워드 매칭 — false positive 있을 수 있음.
_KEYWORD_PATTERNS: list[tuple[str, str, float]] = [
    (r"\b(ceasefire|truce|peace deal|treaty signed|de[- ]?escalat\w*|talks resume)\b",
     "geopolitical_de_escalation", 0.5),
    (r"\b(missile strike|invasion|attack|escalat\w*|sanctions imposed|retaliat\w*|airstrike|war)\b",
     "geopolitical_escalation", -0.6),
    (r"\b(rate cut|dovish|fed pause|easing cycle|cut rates)\b",
     "fed_dovish", 0.4),
    (r"\b(rate hike|hawkish|tightening|raise rates|hike rates)\b",
     "fed_hawkish", -0.3),
    (r"\b(opec[+]? cut|oil supply|refinery shut|crude shortage)\b",
     "oil_supply_shock", -0.4),
    (r"\b(oil price drop|crude plunge|oil oversupply|wti tumbl)\b",
     "oil_demand_drop", 0.2),
    (r"\b(beat estimates|earnings beat|raised guidance|crushed estimates|tops forecast)\b",
     "earnings_beat", 0.5),
    (r"\b(earnings miss|missed estimates|cut guidance|profit warn|guidance lower)\b",
     "earnings_miss", -0.5),
    (r"\b(rall(y|ies|ied)|surges?|jumps?|soars?|rebounds?|sector rotation)\b",
     "sector_rally", 0.3),
    (r"\b(plunges?|sell[- ]?off|crash(es)?|tumbles?|sinks?|rout)\b",
     "sector_selloff", -0.4),
    (r"\b(tariff|trade war|trade deal|retaliatory)\b",
     "trade_war", -0.3),
]


def classify_event(headline: str, *, use_llm: bool = True) -> dict:
    """헤드라인 → 구조화된 분류 결과.

    use_llm=True (기본): Ollama Qwen3.5 시도 후 실패 시 regex 폴백.
    use_llm=False: regex만 사용 (테스트/CI/오프라인용).

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
            return _classify_with_ollama(headline)
        except Exception as e:  # noqa: BLE001 — Ollama 다운 시 묵묵히 폴백
            logger.debug("Ollama 분류 실패 (%s) → regex 폴백", type(e).__name__)

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
            }
    return _neutral_result()


def _classify_with_ollama(headline: str) -> dict:
    """Ollama HTTP API 호출 — JSON 모드. 실패 시 caller가 폴백."""
    import requests  # lazy import: 모듈 import 시 네트워크 의존 안 가지게

    prompt = (
        "You are a financial news classifier. Classify this market headline.\n"
        f'Headline: "{headline}"\n\n'
        f"Categories: {', '.join(CATEGORIES)}\n\n"
        "Output ONLY this JSON format, no thinking, no explanation:\n"
        '{"category": "<one of categories>", "sentiment": <float -1.0 to 1.0>, '
        '"confidence": <float 0.0 to 1.0>}\n'
    )

    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 200},
        },
        timeout=OLLAMA_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # JSON 모드인데 깨진 응답 → fallback 트리거
        raise ValueError(f"Ollama returned non-JSON: {raw[:100]!r}") from None

    return _normalize(parsed)


def _normalize(parsed: dict) -> dict:
    """LLM 출력을 검증·클램프하여 안전한 dict 반환."""
    category = parsed.get("category", "neutral")
    if category not in CATEGORIES:
        # 미지의 카테고리 → neutral로 강제 (신뢰도 낮춤)
        return {**_neutral_result(), "confidence": 0.2}

    sentiment = float(parsed.get("sentiment", 0.0))
    sentiment = max(-1.0, min(1.0, sentiment))

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    return {
        "category": category,
        "sentiment": sentiment,
        "confidence": confidence,
        "regime_hint": REGIME_HINT_BY_CATEGORY[category],
    }


def _neutral_result() -> dict:
    return {
        "category": "neutral",
        "sentiment": 0.0,
        "confidence": 0.3,
        "regime_hint": None,
    }
