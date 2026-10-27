"""TradingAgents 프롬프트 문구 — 원본 `tradingagents/agents/{researchers,managers,analysts}/*.py` (e8f5503).

바꾼 점 (Modified) — 기록이 곧 원본과의 차이표다:
- 강세/약세 연구원의 "Key points" 와 Research Manager 의 등급 척도 · 판단 지침은 **글자 그대로** 옮겼다.
  등급 척도는 원본처럼 포지션 언어(늘리기 · 줄이기)로 쓰여 있다 — 우리 쪽 의미는 알파 방향의 강도이며
  수량 · 배분은 정하지 않는다(채점 팔은 Research Manager 등급에서 끝난다).
- Research Manager 의 출력 절 "Strategic Actions"(트레이더용 규모 지시)는 뺐다 — 포트폴리오 축.
- 분석가 역할 설명은 원본 첫 문장을 바탕으로 하되 도구 이름 · 도구 사용 지시 · "Markdown table" 지시는 뺐다.
  분석가는 도구 대신 근거 묶음의 자기 몫을 받고, 산문 보고서 대신 근거 ID 를 가리키는 주장으로 답한다.
- 시장(기술) 분석가 원본은 지표 목록(10일 지수이동평균 · 거래량 가중 이동평균 등)을 고르게 하는데, 우리 묶음에는 그 지표가 없어
  목록을 뺐다. 감성 분석가는 원본의 StockTwits · Reddit 대신 보유와 무관한 시장 심리 지표를 받는다 — 두 소스는
  약관상 제외했다(#1967: Reddit Data API Terms §2.4 · §2.8 · §3.1, StockTwits 신규 등록 중단).
- reflection(`memory/reflection.py`)은 원본 지시를 따르되 "cite the figure" 대신 **숫자를 쓰지 말라** 고 한다 —
  수익률 · 알파는 코드가 기억 항목 옆에 렌더한다(다른 단계와 같은 숫자 규칙). 보유 창은 원본의 "분석일 다음 첫
  종가" 대신 "기준 시점 이후 첫 개장" 에서 센다 — A 와 B 가 같은 진입을 갖게(#1966).
- 언어 지시(`get_language_instruction`)는 원본 기본값 English 와 같아 생략했다.
"""

from __future__ import annotations

# 원본 bull_researcher.py — "Key points to focus on" 블록 그대로
BULL_KEY_POINTS = """You are a Bull Analyst advocating for investing in the stock. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data."""

# 원본 bear_researcher.py — 같은 블록 그대로
BEAR_KEY_POINTS = """You are a Bear Analyst making the case against investing in the stock. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts."""

# 원본 research_manager.py — 등급 척도 + 판단 지침 그대로. A(1회 호출)와 B(Research Manager)가 **같은 글**을 받는다:
# 등급의 정의가 팔마다 다르면 B−A 가 방법이 아니라 지시문의 차이를 잰다.
RATING_SCALE = """**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

The debate always contains conflicting arguments; deciding which side is stronger is the job, so conflict alone is not a reason to Hold. Commit to the side with the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not manufacture a direction to appear decisive. Weigh the bull and bear cases on their merits, independent of which side spoke first or last."""

MANAGER_ROLE = (
    "As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate "
    "and deliver a clear investment recommendation."
)

# 원본 각 분석가 system_message 의 첫 문장을 바탕으로 (위 "바꾼 점" 참고)
ANALYST_ROLES = {
    "market": (
        "You are a trading assistant tasked with analyzing financial markets: price trend, momentum and "
        "volume from the technical indicators provided."
    ),
    "fundamentals": (
        "You are a researcher tasked with analyzing fundamental information about a company: valuation, "
        "profitability, growth, balance sheet, analyst estimates and earnings surprises."
    ),
    "news": (
        "You are a news researcher tasked with analyzing recent news and trends over the past week: news "
        "about the company and the macroeconomic state relevant for trading."
    ),
    "sentiment": (
        "You are a financial market sentiment analyst: company headlines, institutional ownership filings, "
        "fund flows and market-wide sentiment gauges."
    ),
}


def reflection_prompt(holding_days: int) -> str:
    """원본 `Reflector._system_prompt` — 숫자 인용 지시만 바꿨다(위 "바꾼 점")."""
    return (
        "You are a trading analyst reviewing your own past decision now that the outcome is known.\n"
        f"The outcome covers {holding_days} trading days from the first open after the analysis cutoff, "
        "which may be shorter than the horizon the decision was written for.\n"
        "Write exactly 2-4 sentences of plain prose (no bullets, no headers, no markdown).\n\n"
        "Cover in order:\n"
        f"1. What the {holding_days}-day alpha shows about the directional call (describe it in words; do not "
        "write numbers, the figures are shown beside your lesson), and say so plainly if the window is too short "
        "to judge the thesis.\n"
        "2. Which part of the investment thesis this window supports or undercuts.\n"
        "3. One concrete lesson to apply to the next similar analysis.\n\n"
        "Be specific and terse. Your output will be stored verbatim in a memory log "
        "and re-read by future analysts, so every word must earn its place."
    )
