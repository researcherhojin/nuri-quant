"""2026-03-28 외부 데이터 분석 결과 저장.

이 스크립트는 오늘 세션에서 수집한 6개 사이트 데이터를 DB에 저장한다.
향후에는 자동화된 collector로 대체할 예정.
"""
from nuri.collectors.external import save_external, save_superinvestor, save_tipranks

# ═══════════════════════════════════════════════════════
# TipRanks 데이터 (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
tipranks_data = [
    ("TSLA", "Hold", 393.51, 30, -1.3),
    ("OKLO", "Moderate Buy", 96.23, 13, 37.0),
    ("HOOD", "Strong Buy", 123.85, 16, 33.0),
    ("IONQ", "Moderate Buy", 64.40, 11, 47.0),
    ("ORCL", "Strong Buy", 312.34, 31, 60.0),
    ("FIG", "Moderate Buy", 40.25, 10, 91.0),
    ("LLY", "Strong Buy", 1252.26, 21, 38.0),
    ("NVDA", "Strong Buy", 273.61, 39, 52.0),
    ("GOOGL", "Strong Buy", 376.57, 32, 23.0),
    ("TEM", "Moderate Buy", 78.69, 14, 55.0),
    ("RKLB", "Moderate Buy", 89.36, 13, 30.0),
    ("PLTR", "Moderate Buy", 194.61, 20, 49.0),
    ("AMD", "Strong Buy", 283.03, 38, 32.0),
    ("BULL", "Strong Buy", 11.67, 3, 113.0),
    ("NBIS", "Strong Buy", 168.13, 8, 87.0),
]

for ticker, consensus, target, analysts, upside in tipranks_data:
    save_tipranks(ticker, consensus, target, analysts, upside)

# ═══════════════════════════════════════════════════════
# Dataroma 슈퍼투자자 (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
superinvestor_data = [
    ("GOOGL", 32, "mixed_sell", "Ackman -86%, Viking new buy, Buffett $5.6B"),
    ("NVDA", 14, "mixed_buy", "Duan Yongping +1110%, Maverick +39%"),
    ("ORCL", 9, "selling", "Polen -22.6%, First Eagle -6.2%"),
    ("TSLA", 5, "selling", "Viking adding, others reducing"),
    ("LLY", 5, "selling", "Jensen -46%, insiders buying"),
    ("FIG", 3, "mixed", "Viking new buy, Durable Capital -68%"),
    ("AMD", 3, "heavy_selling", "Tepper -66%, Meridian -54%, Viking -10%"),
    ("TEM", 3, "mixed", "Duan Yongping new buy, Polen -78%"),
    ("RKLB", 2, "neutral", "Polen new buy (tiny)"),
    ("PLTR", 1, "negligible", "Matrix $411K only"),
    ("BULL", 1, "selling", "Tiger Global -43%"),
    ("HOOD", 0, "none", "No superinvestor ownership"),
    ("IONQ", 0, "none", "No superinvestor ownership"),
    ("OKLO", 0, "none", "Not in dataroma DB"),
    ("NBIS", 0, "none", "Not in dataroma DB"),
]

for ticker, count, trend, details in superinvestor_data:
    save_superinvestor(ticker, count, trend, details)

# ═══════════════════════════════════════════════════════
# Macrotrends 밸류에이션 (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
valuations = [
    ("TSLA", "pe_ratio", "327", 327.0, "significantly_overvalued"),
    ("NVDA", "pe_ratio", "37", 37.0, "fairly_valued (forward PE 21)"),
    ("ORCL", "pe_ratio", "28", 28.0, "fairly_valued (10yr avg)"),
    ("HOOD", "pe_ratio", "37", 37.0, "moderate (growth fintech)"),
    ("LLY", "pe_ratio", "43", 43.0, "moderately_overvalued"),
    ("OKLO", "revenue", "0", 0.0, "pre_revenue (2028+ first revenue)"),
    ("IONQ", "pe_ratio", "-13.6", -13.6, "unprofitable (P/S 91x)"),
]

for ticker, data_type, value, numeric, details in valuations:
    save_external("macrotrends", ticker, data_type, value, numeric, details)

# ═══════════════════════════════════════════════════════
# ARK Invest (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
ark_data = [
    ("TSLA", "ark_action", "hold", None, "#1 holding, target $2600"),
    ("TEM", "ark_action", "strong_buy", None, "Only buy on $84M sell day (3/26)"),
    ("HOOD", "ark_action", "buy", None, "$32.7M bought Feb 2026"),
    ("NVDA", "ark_action", "sell", None, "155K shares sold 3/26 ($27.8M)"),
    ("AMD", "ark_action", "sell", None, "38K shares sold 3/26 ($8.4M)"),
    ("RKLB", "ark_action", "sell", None, "76K shares trimmed"),
    ("BULL", "ark_action", "sold", None, "Position exited"),
]

for ticker, data_type, value, numeric, details in ark_data:
    save_external("ark", ticker, data_type, value, numeric, details)

# ═══════════════════════════════════════════════════════
# TradingEconomics 매크로 (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
macro_data = [
    ("macro", "gdp_growth", "0.7", 0.7, "Q4 2025, weakest quarter"),
    ("macro", "unemployment", "4.4", 4.4, "Feb 2026"),
    ("macro", "cpi", "2.4", 2.4, "Feb 2026, moderating"),
    ("macro", "core_cpi", "2.5", 2.5, "Lowest since Mar 2021"),
    ("macro", "fed_rate", "3.625", 3.625, "3.50-3.75%, held steady"),
    ("macro", "consumer_confidence", "55.5", 55.5, "3-month low"),
    ("macro", "manufacturing_pmi", "52.4", 52.4, "Expansion"),
    ("macro", "sahm_rule", "0.30", 0.30, "Below 0.50 threshold"),
]

for ticker, data_type, value, numeric, details in macro_data:
    save_external("tradingeconomics", ticker, data_type, value, numeric, details)

# ═══════════════════════════════════════════════════════
# ETF.com 펀드 플로우 (2026-03-28 조사)
# ═══════════════════════════════════════════════════════
flow_data = [
    ("SPY", "fund_flow", "bearish", None, "S&P 500 -6.8% from ATH, 4 weeks down"),
    ("QQQ", "fund_flow", "bearish", None, "Nasdaq -6.95% 1-month, tech underperforming"),
    ("US_EQUITY", "fund_flow", "-1.34B", -1.34, "Domestic equity outflows"),
    ("INTL_EQUITY", "fund_flow", "+6.78B", 6.78, "International equity inflows"),
    ("BONDS", "fund_flow", "+15.62B", 15.62, "Bond inflows 3x equity"),
    ("GOLD", "fund_flow", "$4337/oz", 4337.0, "All-time high, safe haven"),
]

for ticker, data_type, value, numeric, details in flow_data:
    save_external("etf_flows", ticker, data_type, value, numeric, details)

print("✅ 외부 데이터 저장 완료 (6개 사이트)")

# 요약 출력
from nuri.collectors.external import print_summary
print_summary()
