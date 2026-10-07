/**
 * Centralized Korean UI strings — single source of truth (#226).
 *
 * Components and tests import from here instead of inlining Korean.
 * Not a full i18n solution (next-intl) — just constants extraction.
 */

/* ── Trend / Market Context ─────────────────────────────────── */
export const TREND = {
  BULL: "상승",
  BEAR: "하락",
  SIDEWAYS: "횡보",
} as const;

export const VIX_ZONE = {
  CALM: "안정",
  LOW: "낮음",
  NORMAL: "보통",
  CAUTION: "주의",
  DANGER: "위험",
} as const;

export const FEAR_GREED = {
  EXTREME_FEAR: "극도 공포",
  FEAR: "공포",
  NEUTRAL: "중립",
  GREED: "탐욕",
  EXTREME_GREED: "극도 탐욕",
} as const;

export const MACRO_LEVEL = {
  GOOD: "양호",
  NORMAL: "보통",
  WEAK: "부진",
  FRAGILE: "취약",
} as const;

/* ── Signal Translations (alert → Korean) ───────────────────── */
export const SIGNAL = {
  BB_BOUNCE: "볼린저밴드 반등",
  MACD_BULLISH_TURN: "MACD 상승전환",
  MACD_BEARISH_TURN: "MACD 하락전환",
  MACD_GOLDEN: "MACD 골든크로스",
  MACD_DEAD: "MACD 데드크로스",
  RSI_OVERSOLD: "RSI 과매도",
  RSI_OVERBOUGHT: "RSI 과매수",
  SMA_GOLDEN: "이동평균 골든크로스",
  SMA_DEAD: "이동평균 데드크로스",
  VOLUME_SPIKE: "거래량 급증",
  GAP_UP: "갭 상승",
  GAP_DOWN: "갭 하락",
  BB_SQUEEZE_BREAKOUT: "볼린저밴드 돌파",
  NEAR_52W_LOW_BOUNCE: "52주 저점 반등",
  VOLUME_PROFILE_RESISTANCE: "거래량 저항선",
  /** Drift alert rewrite */
  DRIFT_REPLACE: "매매 신호 성과 하락:",
  DRIFT_SOURCE: "시그널 성과 급락:",
  CONFLICT_REPLACE: "매수·매도 신호 충돌",
  STOP_SUFFIX: "손절",
  NEAR_SUFFIX: "근접",
  CONFLICT_SHORT: "충돌",
} as const;

/* ── Consensus Page ─────────────────────────────────────────── */
export const CONSENSUS = {
  // 자리표시자 셀 (#1436) — 확신도 숫자를 찍으면 의견처럼 읽힌다. 백엔드가 이미 동의율·
  // 패널 커버리지에서 빼고 있으므로, 숫자를 보이면 같은 화면이 자기 자신과 모순된다.
  CELL_DEGRADED: "×",
  CELL_ABSTAINED: "·",
  PLACEHOLDER_DEGRADED: "의견 미산출",
  PLACEHOLDER_ABSTAINED: "의견 없음",
  VIX_BLOCKED: "신규 매수 차단",
  VIX_CAUTION: "반포지션 적용 중",
  VIX_BLOCKED_SUB: "win rate 붕괴 구간, 모든 BUY 차단",
  VIX_CAUTION_SUB: "BUY 종목 confidence ×0.5, 수량 절반만 진입",
} as const;

/* ── Targets Page ───────────────────────────────────────────── */
export const TARGETS = {
  ALL: "전체 종목",
  GROWTH: "성장주",
  VALUE: "가치주",
  TP_TRIGGERED: "익절 도달",
  TS_TRIGGERED: "트레일링 스톱",
  SELL_NEEDED: "매도 필요",
  SELL_IMMEDIATE: "즉시 매도",
  COUNT_SUFFIX: "개",
  DESCRIPTION: "가격 타겟 — rules.yaml 기반 (O'Neil + Minervini)",
  SUBTITLE: "전 종목 매수가 · 손절가 · 익절가 · 트레일링 스톱 · 애널리스트 목표가",
} as const;

/* ── Rebalance Page (#1227 U5c — /advisor 통합) ─────────────── */
export const REBALANCE = {
  SECTION_VIOLATIONS: "규칙 위반 — 매도 우선순위",
  SECTION_WEIGHTS: "비중 리밸런싱 — Risk Parity",
} as const;

/* ── Advisor Page ───────────────────────────────────────────── */
export const ADVISOR = {
  TOTAL_VIOLATIONS: "총 위반",
  TOTAL_RECOVERABLE: "총 회수 가능",
  NO_VIOLATIONS: "모든 투자 규칙 준수 중. 위반 사항 없음.",
  CRITICAL_PREFIX: "⚠ CRITICAL 위반",
  CRITICAL_SUFFIX: "즉시 조치 필요",
  DESCRIPTION: "Rebalance Advisor — 매도 우선순위 순 (rules.yaml 기반)",
  SUBTITLE: "투자 규칙 위반 감지 · 매도 수량 계산 · 회수 금액 · 우선순위 정렬",
  VIOLATION_DIST: "위반 유형별 분포",
} as const;

/* ── Evidence Page ──────────────────────────────────────────── */
export const EVIDENCE = {
  TITLE: "Evidence Charts",
  LOAD_FAILED: "증거 차트 로드 실패. API 서버 확인 필요.",
  SUBTITLE: "투자 결정 근거 시각화 — 레짐, 포트폴리오, 시그널, 공포·탐욕, 매도 근거",
  // #1225: iframe → 네이티브 차트. 데이터는 DB 라이브 — 빈 상태는 1줄 룰.
  NO_DATA: "데이터 없음 — 파이프라인 수집 후 표시됩니다.",
  NO_VIOLATIONS: "위반 없음 — 손절선·비중 한도 모두 정상.",
  LIVE: "LIVE",
  TITLE_REGIME: "레짐 증거 (SPY + SMA + VIX)",
  TITLE_HEATMAP: "포트폴리오 히트맵",
  TITLE_SIGNALS: "시그널 성과 (승률 + PF + drift)",
  TITLE_FEAR_GREED: "공포·탐욕 지수 90일 추이",
  TITLE_SELL: "매도 근거 (위반 항목별 심각도)",
} as const;

/* ── Command Palette (#1226 U5b) ────────────────────────────── */
export const PALETTE = {
  PLACEHOLDER: "페이지 이동 또는 티커 검색…",
  HINT: "검색",
  SECTION_ROUTES: "페이지",
  SECTION_TICKERS: "티커",
  NO_RESULTS: "결과 없음",
  FOOTER: "↑↓ 이동 · Enter 열기 · Esc 닫기",
  ARIA: "커맨드 팔레트",
} as const;

/* ── Portfolio Page ─────────────────────────────────────────── */
export const PORTFOLIO = {
  QTY_ERROR: "수량은 0보다 커야 합니다",
  PRICE_ERROR: "평균가는 0보다 커야 합니다",
  TICKER_ERROR: "Ticker를 입력하세요",
  ADD_FAILED: "추가 실패",
  EDIT_FAILED: "수정 실패",
} as const;

/* ── Report Page ────────────────────────────────────────────── */
export const REPORT = {
  PLACEHOLDER: "Generate Report 버튼을 눌러 AI 투자 리포트를 생성하세요.",
  OLLAMA_REQUIRED: "Ollama가 실행 중이어야 합니다 (ollama serve)",
} as const;

/* ── Decisions Page ─────────────────────────────────────────── */
export const DECISIONS = {
  EMPTY: "아직 기록된 의사결정 없음.",
  EMPTY_FILTERED: "필터에 해당하는 의사결정 없음.", // #1216: 필터 적용 중 0건은 데이터 부재와 구분
  SUBTITLE: "의사결정 저널 — 모든 BUY/SELL 판단의 근거와 결과를 추적합니다.",
  // #1216 U3: outcome 필터·라벨. 판정 규칙은 90일 경과 시 pnl_90d
  // (nuri/trading/engine/decisions.py) — 표기는 그 규칙의 미러다.
  FILTER_ALL: "전체",
  OUTCOME_PENDING: "대기",
  OUTCOME_SUCCESS: "성공",
  OUTCOME_FAILURE: "실패",
  OUTCOME_NEUTRAL: "중립",
  ADJ_DONE: "판정", // 판정 완료 행: "판정 YYYY-MM-DD"
  ADJ_DUE_PREFIX: "D-", // pending: 판정 예정까지 남은 일수 (D-1 이 마지막 대기일)
  // 판정일 도래(elapsed>=90)부터는 백엔드가 즉시 판정 가능 — 그날 이후에도 pending 이면
  // 추적기 미실행/가격 부재다 (codex R1 P1: D-0 을 대기로 두면 규칙과 하루 어긋난다)
  ADJ_DUE: "판정일 도래 · 미판정",
  FILTER_OUTCOME_LABEL: "결과",
  FILTER_ACTION_LABEL: "액션",
  FILTERED_NOTE_SUFFIX: "건 표시 · 요약 카드는 전체 기준", // 필터 중 전역 요약과의 혼동 방지 (codex R1 P2)
  RAIL_CONTEXT: "결정 시점 컨텍스트 (frozen)",
  // #1303: regime 에 결정 시점 증거 행이 없을 때의 표식.
  //
  // ⚠️ **"백필됨" 이라고 말하지 않는다.** 원인을 단정할 수 없기 때문이다 (codex P2):
  // `record_decision` 은 컬럼과 evidence 행을 **다른 트랜잭션**으로 쓰므로
  // (`upsert_decision` → `upsert_decision_evidence`, 각자 커밋), 그 사이에서 프로세스가
  // 죽으면 **정상 기록된 행**도 같은 모양이 된다. 백필(#1264)과 구분할 방법이 없다.
  // 그래서 관측한 사실만 말한다 — 원인이 무엇이든 사용자에게 중요한 뜻은 같다:
  // **이 regime 은 결정 시점 증거로 검증할 수 없다.**
  REGIME_NO_EVIDENCE: "당시 증거 행 없음",
  REGIME_NO_EVIDENCE_FULL: "이 regime 을 뒷받침하는 결정 시점 증거 행이 없습니다 — 사후 보완이거나 기록이 중단된 경우입니다",
  // 목록의 좁은 칸용 축약 — 전체 문구는 title 로 붙는다.
  REGIME_NO_EVIDENCE_TAG: "증거없음",
  RAIL_PRICES: "가격 레벨",
  RAIL_PNL: "실현 결과 (forward PnL %)",
  // #1257 판정 경로 히어로 — 판정 소스(final_action_source)별 3변형. 일상어 원칙:
  // "합의 불성립"/"mechanical rung" 같은 시스템 은어 금지 (와이어프레임 v2 codex 검토).
  HERO_VETO_TITLE: "의견은 갈렸지만, 손실 관리 규칙이 이 판정을 자동 확정했습니다",
  // 엔진은 확신도가 아니라 **판정(액션)을 보수적으로 강등**한다 (scoring.py divergence
  // penalty — codex ship review P2: "확신도를 낮췄다" 는 SSoT 불일치)
  HERO_PENALTY_TITLE: "에이전트 의견이 크게 갈려 판정을 보수적으로 강등했습니다",
  HERO_WEIGHTED_TITLE: "에이전트 가중 합의가 이 판정을 만들었습니다",
  HERO_UNKNOWN_TITLE: "판정 경로를 해석할 수 없습니다 — 화면이 모르는 새 판정 메커니즘",
  HERO_CONSENSUS_REF: "에이전트 합의 — 참고용 (최종 판정에 미반영)",
  HERO_DECIDER_VETO: "최종 판정을 확정한 것 — 손실 관리 규칙 (리스크 거부권)",
  HERO_CONF_NOTE: "확신도는 규칙의 확신도 — 에이전트 일치율과 다른 수치인 이유",
  HERO_AGREEMENT_LABEL: "일치율",
  // 판정 후 새 사실 슬롯 — P1(이벤트 수집기) 전까지는 부재를 정직하게 표시
  NEW_FACTS_TITLE: "판정 이후 새로 생긴 사실",
  NEW_FACTS_EMPTY: "공시·기업 이벤트 자동 반영은 아직 없습니다 — 새 정보가 있다면 아래 재검토 체크로 판단하세요.",
  // 재검토 체크 — 사실 확인이지 매매 권고가 아니다 (invariants: no ad-hoc calls)
  RECHECK_TITLE: "이 판단을 재검토하려면 확인할 것",
  RECHECK_NOTE: "사실 체크 — 매매 권고 아님",
  RECHECK_STOP: "가격이 손절 기준선 위로 복귀했는가",
  RECHECK_VOL: "판정 근거의 리스크 조건이 해소됐는가",
  RECHECK_THESIS: "새 정보가 투자 논지를 무효화하는가",
  RECHECK_PIT: "기준값은 현재 규칙 기준 재구성 — 판정 당시 규칙 스냅샷이 아님",
  // SELL 은 매수 사다리(Entry/T1/T2)를 렌더하지 않는다 — 액션별 별도 템플릿
  SELL_PRICE_NOTE: "SELL 판정 — 매수 사다리(Target)는 적용되지 않습니다",
  PRICE_AT_DECISION: "결정 시점 가격",
  // 에이전트 2단 — "데이터 없음 ≠ 중립" (#1028 semantics 를 UI 로)
  AGENTS_LIVE_TITLE: "에이전트 판정 — 유효 의견",
  AGENTS_COVERAGE_LABEL: "패널 커버리지",
  AGENTS_DEGRADED_SUMMARY: "의견 미산출",
  AGENTS_DEGRADED_NOTE: "가중치 0 — 합의에 미반영",
  // 기권은 degraded 와 다르다 (#1436): 정상 실행됐고, **가중 투표에는 반영된다**
  // (smart_money 는 37.5 로 기여 — #1437). 동의율·커버리지에서만 빠진다.
  AGENTS_ABSTAINED_SUMMARY: "의견 없음",
  AGENTS_ABSTAINED_NOTE: "동의율·커버리지에서 제외 — 가중 투표에는 반영",
  // 규칙 판정(veto)인데 논지가 없으면 자동 논지 렌더 — 채점 기준의 공백 방지
  AUTO_THESIS_TITLE: "자동 논지 (손절 규율 집행)",
  AUTO_THESIS_BODY:
    "손절 규칙에 따른 기계적 청산. 맞으면 — 청산 후 추가 하락을 피한다. 틀리면 — 반등분을 놓친다. 판정일에 실현 결과로 채점.",
} as const;

/* ── Pipeline Page ──────────────────────────────────────────── */
export const PIPELINE = {
  RUNNING_SUFFIX: "개 실행 중",
  AUTO_REFRESH: "10초 자동 갱신",
  LEGEND_OK: "정상",
  LEGEND_WARN: "경고 / 대기",
  LEGEND_ERROR: "에러",
  LEGEND_RUNNING: "실행 중",
  EVENT_TIMELINE: "이벤트 타임라인",
  NO_EVENTS: "아직 이벤트 없음",
  RUN_STEP_HINT: "파이프라인 스텝을 실행하세요",
  // design-review F-008: 형제 헤더(이벤트 타임라인)와 언어 일치 + SSoT 로 이동
  GATE_CONDITIONS: "게이트 조건",
  GATE_LOADING: "게이트 조건 로딩 중...",
  // #1250: 로딩 · 없음 · 실패를 서로 다른 화면으로 가른다. 이전엔 셋이 한 화면이라
  // "백엔드 죽음" 과 "이벤트 없음" 이 구분되지 않았다.
  TIMELINE_LOADING: "이벤트 불러오는 중...",
  GATE_EMPTY: "게이트 조건 없음 — 파이프라인 실행 후 표시됩니다",
  // #1252: 페이지 타이틀 · 실행 버튼 · 노드 카피가 SSoT 밖에 있었다.
  TITLE: "Pipeline",
  RUN: "실행",
  RUNNING: "실행 중...",
  NODE_COLLECT: "Collect",
  NODE_COLLECT_SUB: "15 collectors + 6 sites",
  NODE_VALIDATE: "Validate",
  NODE_VALIDATE_SUB: "Signal backtest + scorecard",
  NODE_CLASSIFY: "Classify",
  NODE_CLASSIFY_SUB: "6-regime classifier",
  NODE_DIAGNOSE: "Diagnose",
  NODE_DIAGNOSE_SUB: "10 agents consensus",
  NODE_RECOMMEND: "Recommend",
  NODE_RECOMMEND_SUB: "Buy/sell + price targets",
  NODE_TRACK: "Track",
  NODE_TRACK_SUB: "30/60/90d outcomes",
} as const;

/* ── Ticker Detail Page ─────────────────────────────────────── */
export const TICKER_PREVIEW = {
  BUSINESS_CORE: "사업 핵심", BUSINESS_AREAS: "주요 사업과 확인할 조건", BUSINESS_METHOD: "공급자의 사업 분류와 원문에 확인된 사업만 한국어로 정리했습니다. 전망과 매매 판단은 포함하지 않습니다.", BUSINESS_PARTIAL: "현재 원자료에서 한국어 사업 요약을 구성하지 못했습니다. 사업 설명 원문과 회사 공시를 확인하세요.",
  FINANCIAL_READING: "실적을 읽는 관점", GROWTH_QUALITY: "매출과 수익성", CASH_QUALITY: "이익과 현금흐름", FUNDING_STRUCTURE: "자금 구조", FINANCING_CONTEXT: "금융 사업이 있는 연결 재무자료입니다. 대출·리스 자산 확대와 자금 조달이 부채·현금흐름에 포함될 수 있으므로 제조·서비스 부문만의 현금흐름으로 해석하지 마세요.",
  PROFIT_CHANGE: (period: string, revenue: string, profit: string) => `${period} 매출은 이전 결산 대비 ${revenue}, 영업이익은 ${profit} 변화했습니다.`,
  GROWTH_DIVERGENCE: "매출이 늘어도 영업이익은 줄었습니다. 판매 구성·가격·원가·일회성 비용 중 어떤 요인이 영향을 줬는지 사업보고서에서 확인해야 합니다.", GROWTH_TOGETHER: "매출과 영업이익이 함께 증가했습니다. 이익 증가의 지속성과 비용·일회성 요인을 확인해야 합니다.", PROFITABILITY_CHANGE: (before: string, after: string) => `영업이익률은 ${before}에서 ${after}로 변했습니다. 매출 규모와 수익성의 변화를 나누어 볼 수 있습니다.`,
  PROFIT_CASH_DIVERGENCE: "같은 결산 기간에 순이익은 양수지만 영업현금흐름은 음수입니다. 이익이 현금 유입으로 이어졌는지, 운전자본과 금융 자산의 변화를 공시에서 대조해야 합니다.",
  COUNTRY_KR: "대한민국", FUND_SOURCE: "운용 자료 출처", BENCHMARK: "추종 지수", ISSUER: "운용사", NAV: "주당 순자산가치", DEVIATION: "공급자 발표 괴리율", FUND_STRUCTURE: "상품 구조와 주의점", FUND_SNAPSHOT_NOTE: "공급자가 원자료 기준일을 제공하지 않아 조회 시점의 값으로 표시합니다. 종목 시가총액을 운용자산으로 바꾸지 않습니다.",
  FUND_BENCHMARK: (benchmark: string) => `이 상품은 ${benchmark}의 성과를 추종하는 것을 목표로 합니다. ETF 가격·순자산가치·기초지수의 움직임을 구분해 확인하세요.`, FUND_HOLDINGS_UNAVAILABLE: "이 공급자 응답에는 구성 자산·비중·구성 기준일이 없습니다. 실제 구성은 운용사 최신 자료에서 확인해야 합니다.",
  BRIEF: "종목 브리핑", COMPANY: "종목 소개", BUSINESS_EXCERPT: "사업 설명 · 원문 발췌", BUSINESS_ORIGINAL: "사업 설명 · 공급자 원문 전체", IDENTITY_NOTE: "공급자가 확인한 회사명과 심볼입니다. 보유 목록의 표시 이름과 다를 수 있습니다.",
  NO_PROFILE: "회사 소개가 아직 없습니다. 기업 자료를 수집하면 확인된 회사명·사업 설명·연간 재무자료를 볼 수 있습니다.",
  BRIEFING_KINDS: { fact: "확인된 사실", plan: "회사 계획", forecast: "외부 전망" }, BRIEFING_EVIDENCE: "근거 확인",
  BRIEFING_UNDATED: (collected: string) => `발표일 미확인 / 수집 ${collected}`, BRIEFING_TITLE: "출처 기반 기업 분석",
  BRIEFING_INTRO: "공개 기업 자료를 바탕으로 사업·최근 변화·기회와 위험을 설명합니다. 개인 보유 정보는 생성기에 전달하지 않습니다.",
  BRIEFING_TIMES: (collected: string, generated: string) => `자료 수집 · ${collected} · 생성 · ${generated}`,
  BRIEFING_COVERAGE: (official: number, news: number, snapshot: number) => `공식 자료 ${official}건 · 기사 본문 ${news}건 · 공급자 스냅샷 ${snapshot}건`,
  BRIEFING_NO_IR: " · 공식 IR 미확보, 뉴스 중심 분석", BRIEFING_REJECTED: (count: number) => `근거 검사에서 ${count}개 문장을 제외했습니다. `,
  BRIEFING_CHECKED: "출처 연결과 수치 검사를 거친 설명입니다. 기존 시스템의 매매 판정은 별도로 표시합니다.",
  BRIEFING_IMPACT: "실적에 미치는 경로", BRIEFING_COUNTER: "반대 근거와 불확실성", BRIEFING_CHECKPOINT: "확인할 지표", BRIEFING_TIMING: "예상 시기",
  BRIEFING_FOOTER: (model?: string) => `분석 모델 · ${model ?? ""} · 가격·재무·판정 기준일은 각각의 자료에 표시됩니다.`,
  BRIEFING_GENERATE: "기업 분석 생성", BRIEFING_GENERATING: "기업 분석 작성 중…", BRIEFING_DONE: "기업 분석 생성 완료",
  BRIEFING_SLOW: "생성 작업이 계속되고 있습니다. 잠시 후 페이지를 새로고침하세요.", BRIEFING_STALE_DATA: "먼저 최신 자료를 갱신하세요.",
  BRIEFING_BUSY: "다른 브리핑을 생성 중입니다. 잠시 후 다시 실행하세요.", BRIEFING_START_FAILED: "브리핑 생성을 시작하지 못했습니다.",
  COLLECT: "최신 자료 갱신", COLLECTING: "오늘 자료 수집 중…", COLLECT_FAILED: "수집 결과를 확인하지 못했습니다. 잠시 후 다시 조회하세요.", COLLECT_UNKNOWN: "이 심볼의 회사 정보를 공급자에서 확인하지 못했습니다. 종목 코드를 확인하세요.", COLLECT_AUTH: "기업 자료 수집 권한이 필요합니다.",
  SECTOR: "업종", INDUSTRY: "사업 분류", COUNTRY: "국가", EXCHANGE: "거래소", WEBSITE: "회사 홈페이지", MARKET_CAP: "시가총액",
  BRIEF_FACTS: "실적 요약", RECENT: "최신 소식", NEWS_EMPTY: "저장된 종목 뉴스가 없습니다.", EVENTS_EMPTY: "저장된 종목 일정이 없습니다.", NEWS_NOTE: "최근 30일 발행 기사를 검색해 날짜순으로 표시합니다. 기사 제목을 눌러 원문을 확인하세요.",
  FINANCIAL_TREND: "실적·현금흐름", FINANCIAL_NOTE: "회계연도 말 기준의 연간 원자료입니다. 단위는 표시된 보고 통화이며, 수집 시점과 결산일을 구분합니다.",
  REVENUE: "매출", OPERATING_INCOME: "영업이익", NET_INCOME: "순이익", OCF: "영업현금흐름", FCF: "잉여현금흐름", CASH: "현금·단기투자", DEBT: "총부채", FINANCIAL_CURRENCY: "보고 통화", CURRENCY_UNKNOWN: "보고 통화 미확인 · 원자료 수치", NO_FINANCIALS: "연간 재무 원자료가 아직 없습니다.",
  VALUATION: "가치 지표", VALUATION_NOTE: "후행 PER·선행 PER·PBR은 서로 다른 기준입니다. 과거 저장 시점과 비교하며, 동종 기업 비교 자료 없이 저평가·고평가를 단정하지 않습니다.",
  FORWARD_PE: "선행 PER", PBR: "PBR", MEASURED: "자료 기준 요약", CHECKPOINTS: "확인할 조건", RISK_FACTS: "주의할 점",
  QUESTIONS: ["최근 성장률이 일회성 요인인지, 사업 자체의 변화인지 공시에서 확인했나요?", "회계상 이익이 실제 영업현금흐름과 함께 움직이고 있나요?", "최근 가격과 실적·판정의 기준일이 서로 맞나요?"],
  SOURCE: "자료 출처", COLLECTED: "수집 시각", YAHOO: "Yahoo Finance", READING_GUIDE: "저장된 사실을 읽는 브리핑입니다. 시스템의 매매 판단은 별도 영역에서 확인하세요.",
  SUMMARY_REVENUE: (period: string, value: string, change: string | null) => `${period} 결산 매출은 ${value}입니다.${change ? ` 이전 결산 대비 ${change} 변화했습니다.` : " 이전 결산 비교값이 없어 증감률은 계산하지 않았습니다."}`,
  SUMMARY_PROFIT: (period: string, value: string) => `${period} 결산 순이익은 ${value}입니다.`,
  SUMMARY_CASHFLOW: (period: string, ocf: string, fcf: string) => `${period} 결산 영업현금흐름은 ${ocf}, 잉여현금흐름은 ${fcf}입니다.`,
  LOSS_FACT: "최근 연간 순이익이 음수로 기록됐습니다. 손실 발생 원인은 공시에서 추가 확인해야 합니다.",
  CASHFLOW_FACT: "최근 연간 영업현금흐름이 음수로 기록됐습니다. 현금 유출 원인과 지속성을 확인해야 합니다.",
  NO_RISK_FACT: "현재 자료만으로 기업 고유의 위험 요인을 확정하기 어렵습니다. 반대 의견과 원문 자료를 함께 확인하세요.",
  NO_PEERS: "동종 기업 비교 자료 미제공", DATE_SNAPSHOTS: "저장 시점 비교 · 결산 추이와 별개",
  TODAY: "수집 기준", DAILY_CURRENT: "오늘 수집 완료", DAILY_STALE: "이전 자료 · 갱신 필요", DAILY_NOTE: "매일 첫 조회 때 최신 자료를 수집합니다. 가격은 거래일, 구성 종목은 운용사 발표일을 따릅니다.",
  PARTIAL: "일부 자료 수집 실패 · 각 항목의 기준일을 확인하세요.", FRESH_SOURCE_NOTE: "수집 시각은 자료의 발생 시각과 다릅니다. 아래에 원자료 기준일을 각각 표시합니다.",
  READING_ORDER: "이 페이지에서",
  DOCUMENT_TITLE: "종목 분석 브리핑", DOCUMENT_BASIS: "분석 기준", DOCUMENT_INDEX: "브리핑 목차",
  DOCUMENT_SECTIONS: { summary: "핵심 요약", business: "사업과 수익 구조", changes: "최근 변화", financials: "실적과 가치 지표", outlook: "성장 요인과 위험", schedule: "확인 일정", judgment: "시스템 판단과 가격" },
  DOCUMENT_NO_SCHEDULE: "확인된 종목 일정이 없습니다.",
  RISK_ORIGINAL: "위험 고지 원문",
  NEWS_CHECKED: "최신 검색",
  NEWS_NONE_RECENT: "최근 30일 검색에서 관련 기사를 찾지 못했습니다.",
  NEWS_NOT_CHECKED: "최신 기사를 조회 중입니다. 자료 갱신 후 검색 결과가 표시됩니다.",
  NEWS_SEARCH_FAILED: "뉴스 검색에 실패했습니다. 최신 자료 갱신으로 다시 시도하세요.",
  NEWS_SOURCE_FAILED: (sources: string) => `일부 뉴스 소스 조회 실패 · ${sources}`,
  PRICE_TREND: (start: string, end: string) => `${start}부터 ${end}까지 수집된 종가 흐름`,
  READING_NOTES: "자료 해석 안내",
  JUDGMENT_GUIDE: "확신도와 판단 기준 읽기",
  FUND_CONCENTRATION: (count: number, weight: string) => `상위 ${count}개가 ${weight}%`,
  FUND_CONCENTRATION_EXPLAIN: "상위 자산의 움직임이 ETF 성과에 큰 영향을 줄 수 있습니다.",
  FUND_COST_EXPLAIN: "장기 보유 시 누적되는 운용 비용입니다. 같은 투자 대상의 다른 상품과 비교하세요.",
  MORE_NEWS: (count: number) => `관련 소식 ${count}개 더 보기`,
  DATA_DATES: "자료 기준일 안내",
  DAILY_PARTIAL: "오늘 수집 · 일부 자료 확인 필요",
  MISSING_SOURCES: "확인하지 못한 자료",
  SOURCE_FIELDS: { fund_official: "운용사 공식 자료", fund: "ETF 운용 자료", korean_profile: "국내 종목·상품 정보", profile: "기업 소개", income: "손익계산서", cashflow: "현금흐름표", balance: "재무상태표", prices: "가격 이력", news: "뉴스 검색" },
  PRICE_BASIS: "가격 · 최근 거래일", FINANCIAL_BASIS: "연간 재무 · 결산일", FUND_VALUATION_BASIS: "구성 자산 가치 지표", NEWS_BASIS: "뉴스 · 검색 시각", PROFILE_BASIS: "사업 소개 · 조회 시각",
  CASHFLOW_BASIS: "현금흐름 · 결산일", BALANCE_BASIS: "재무상태 · 결산일",
  BASIS_NOTE: "수집 완료는 오늘 조회했다는 뜻입니다. 거래일·공시 결산일·운용사 발표일이 오늘이라는 뜻은 아닙니다.",
  HIGHLIGHT_BUSINESSES: "구성 기업과 사업", HIGHLIGHT_NOTE: "운용사가 별도로 소개한 기업입니다. 현재 비중 순위와 다를 수 있으며, 설명 기준일은 별도로 제공되지 않았습니다.",
  EXPOSURE: "투자 구조", FAQ_ORIGINAL: "투자 구조 · 공식 설명 원문", FAQ_DATE: "공식 설명 기준",
  SOURCE_CONSISTENCY: "공식 페이지의 티커 표기와 비상장 평가 설명이 함께 남아 있습니다. 이 자료만으로 현재 상장 여부나 유동성을 확정할 수 없어 최신 공시 확인이 필요합니다.",
  MARGIN_EXPLAIN: (period: string, value: string) => `${period} 매출 대비 순이익은 ${value}입니다. 매출 증가와 이익 창출은 별개이므로 비용 변화도 함께 확인해야 합니다.`,
  CASH_CONVERSION: (period: string, value: string) => `${period} 영업현금흐름은 순이익의 ${value}배입니다. 회계상 이익과 실제 현금 유입의 차이를 보여주며, 일회성 운전자본 변화는 공시에서 확인해야 합니다.`,
  CASH_COMPARE: (period: string, cash: string, debt: string) => `${period} 현금·단기투자는 ${cash}, 총부채는 ${debt}입니다. 현금 규모만으로 상환 능력을 판단할 수 없어 부채 만기와 현금 사용 계획을 함께 확인해야 합니다.`,
  NEWS_EXCERPT: "기사 핵심 · 원문 발췌", NEWS_READING: "확인할 변화", NEWS_CONTENT_UNAVAILABLE: "본문을 확인하지 못해 내용 요약과 영향 해석을 제공하지 않습니다.", NEWS_CONTENT_NOT_CHECKED: "제목 검색 결과 · 본문 미조회",
  NEWS_INTERPRETATION_NOTE: "본문에서 확인한 주제에 따른 점검 질문입니다. 호재·악재나 매매 신호를 뜻하지 않습니다.",
  NEWS_TOPICS: { earnings: "실적 변화가 지속 가능한지, 비교 기간과 일회성 항목을 확인하세요.", holdings: "구성 자산·비중과 투자 구조가 최신 운용 공시에서도 같은지 확인하세요.", capital: "자금 조달 조건과 부채·희석 영향이 공시에 명시됐는지 확인하세요.", operations: "발사·계약·생산 일정이 실제 매출이나 서비스 개시로 이어졌는지 확인하세요." },
  LANDING_TITLE: "종목 브리핑", LANDING_DESCRIPTION: "검토할 종목을 선택해 사업·가격·시스템 판단의 근거를 확인하세요.",
  SEARCH_LABEL: "종목 코드 또는 이름", SEARCH_PLACEHOLDER: "티커·종목명 검색", SEARCH_OPEN: "브리핑 열기", SEARCH_LOADING: "종목 검색 중…", SEARCH_FAILED: "검색 결과를 조회하지 못했습니다. 종목 코드를 직접 입력해 열 수 있습니다.", SEARCH_EMPTY: "검색 결과가 없습니다. 정확한 종목 코드를 입력해 열 수 있습니다.", SEARCH_INVALID: "종목명은 검색 결과에서 선택하세요. 직접 열려면 유효한 종목 코드를 입력하세요.", SEARCH_HELP: "종목명은 결과에서 선택하고, 정확한 티커는 Enter로 바로 열 수 있습니다.", LANDING_HOLDINGS: "보유 종목에서 선택", LANDING_NO_HOLDINGS: "불러올 수 있는 보유 종목이 없습니다. 위에서 종목을 검색하세요.",
  FUND_INTRO: "ETF 소개", FUND_NOTE: "ETF는 여러 자산을 담는 상품입니다. 기업 자체의 매출·EPS 대신 구성 자산과 운용 정보를 확인합니다.",
  FUND_DATA_MISSING: "운용 자료를 확인하지 못했습니다. 구성·비용·집중도 해설은 자료 수집 후 표시됩니다.",
  AUM: "운용자산", EXPENSE: "연간 총보수", INCEPTION: "출시일", HOLDING_COUNT: "구성 종목 수", HOLDINGS: "주요 구성", ASSET_NAME: "자산", FUND_DETAILS_DATE: "상품 정보 기준", HOLDINGS_DATE: "구성 기준", POINTS: "투자 포인트", PROSPECTUS: "투자설명서", OFFICIAL: "운용사 공식 자료",
  EXPENSE_NOTE: "총보수는 연간 운용 비용 비율이며 매매 수수료와는 별개입니다. 운용자산 규모만으로 안전성을 판단하지 않습니다.",
  CONCENTRATION_NOTE: "상위 비중은 분산 정도를 보여줍니다. ETF라는 이름만으로 위험이 작다고 볼 수 없습니다.",
  FUND_TOP: (names: string, weight: string, count: number) => `공개된 구성에서 ${names} 등 상위 ${count}개가 ${weight}%를 차지합니다. 이 자산들의 움직임이 상품 성과에 큰 영향을 줄 수 있습니다.`,
  FUND_TOTAL: (count: number, value: string) => `공개된 ${count}개 자산의 비중 합계는 ${value}%입니다. 나머지 구성과 현금은 이 목록에 포함되지 않을 수 있습니다.`,
  FUND_FEE: (value: string) => `연간 총보수는 ${value}%입니다. 장기 보유 시 비용이 누적되므로 동일한 투자 대상의 다른 상품과 비교할 항목입니다.`,
  FUND_LARGEST: (name: string, weight: string) => `가장 큰 구성 자산은 ${name}이며 비중은 ${weight}%입니다. 해당 자산의 사업·가격 변화가 이 ETF에 미치는 영향을 함께 확인하세요.`,
  FUND_UNKNOWN_DATE: "공급자가 구성 기준일을 제공하지 않았습니다. 수집일을 구성 기준일로 대신 표시하지 않습니다.",
  RISK_GLOSSARY: {
    "Sector Focus Risk": { title: "산업 집중", text: "특정 산업에 투자하므로 그 산업의 경기·규제 변화가 여러 구성 자산에 동시에 영향을 줄 수 있습니다." },
    "Aerospace and Defense Industry Risk": { title: "정부 예산·정책", text: "항공우주·방위 기업의 수요는 정부 지출과 규제에 영향을 받습니다. 예산 축소와 정책 변화를 확인해야 합니다." },
    "Space Risk": { title: "기술·개발 불확실성", text: "우주산업은 기술 개발과 상용화 과정에서 지연·실패가 발생할 수 있어 예상 성장이 실현되지 않을 수 있습니다." },
    "Special Purpose Vehicles and Private Company Risk": { title: "비상장 자산·SPV", text: "비상장 자산이나 특수목적기구(SPV)는 즉시 처분하기 어렵고 가격 평가도 불확실할 수 있습니다. ETF 거래가격과 내부 자산 평가를 구분하세요." },
  },
  ACTION_LABELS: { BUY: "매수", SELL: "매도", HOLD: "유지", WATCH: "관찰", LONG: "상승 기대", SHORT: "하락 기대", FLAT: "중립·위험 제한", REBALANCE: "비중 재조정", TRIM: "비중 축소", HEDGE: "위험 헤지", NONE: "조정 없음" },
  CURRENT_JUDGMENT: "현재 판단", JUDGMENT_SOURCE: "사용자 시스템의 저장된 판정을 설명합니다. 자료 갱신이 매매 판정을 새로 실행하지는 않습니다.",
  CONFIDENCE_NOTE: "확신도는 시스템 내부의 합의 지표이며 수익이나 적중 확률을 뜻하지 않습니다.",
  ACTION_MEANING: { BUY: "시스템 합의는 매수입니다. 찬성 근거와 반대 의견을 함께 읽고 판정 기준일을 확인하세요.", SELL: "시스템 합의는 매도입니다. 매매 판단 탭에서 기록된 사유와 보유 점검의 규칙 위반을 대조하세요.", HOLD: "시스템 합의는 유지입니다. 현재 기록에는 매수·매도로 변경할 합의가 없습니다.", WATCH: "시스템 합의는 관찰입니다. 거래 결론보다 추가 근거 확인이 필요한 상태입니다." },
  AXIS_NOTE: "기대수익 판단과 비중·위험 조정은 별도 신호입니다. 비중 조정만으로 긴급 매도를 뜻하지 않습니다.",
  PRO_REASONS: "판정 이유", NO_VALID_REASON: "이 판정을 뒷받침하는 유효 의견의 설명이 아직 없습니다.",
  PSR: "PSR", FUND_VALUATION_NOTE: "운용사가 발표한 구성 자산의 집계 지표입니다. 미제공 PER은 저평가나 고평가의 증거가 아닙니다. 집계 방식과 예상 이익·장부가치·매출의 기준을 원문에서 확인하세요.",
  STORED_PRICE_SOURCE: "기존 시스템의 저장 가격입니다. 최신 수집 가격이 없을 때 사용하며 가격 기준일을 확인하세요.",
  PRICE_RANGE: "가격 요약", PRICE_RANGE_NOTE: "수집된 기간의 일봉으로 계산했습니다. 장중에는 최근 일봉이 미확정일 수 있습니다. 미래 목표가·배당 포함 총수익률과는 다릅니다.",
  RANGE_START: "관측 시작", RANGE_END: "최근 거래일", RANGE_HIGH: "기간 최고", RANGE_LOW: "기간 최저", RANGE_CHANGE: "첫 종가 대비", RANGE_DRAWDOWN: "기간 최고 대비", VOLUME: "거래량",
  PRICE_EXPLAIN: (start: string, end: string, change: string) => `${start} 첫 종가부터 ${end} 최근 종가까지 ${change} 변화했습니다. 이 기간의 움직임은 사업·구성 자산 변화와 함께 해석해야 합니다.`,
  PRICE_NOT_CHEAP: "고점에서 내려왔다는 사실만으로 저평가를 뜻하지 않습니다. 가격 하락의 원인과 자산 가치 변화를 확인해야 합니다.",
  HISTORY_EXPLAIN: "판정은 당시 자료로 내려진 기록입니다. 이후 수익률은 결과 추적이며 현재의 매수·매도 근거로 자동 적용되지 않습니다.",
  HISTORY_CHANGE: (previous: string, latest: string) => `최근 두 기록의 판정은 ${previous} → ${latest}입니다. 변경 이유는 각 기록의 당시 근거에서 확인하세요.`,
  OUTCOMES: { pending: "추적 중", success: "성공으로 기록", failure: "실패로 기록", neutral: "중립으로 기록" },
  SELECT: "종목 선택",
  PREVIEW: "종목 상세 미리보기", BACK: "Overview로 돌아가기", ORIGINAL: "기존 화면 비교",
  EYEBROW: "종목 검토", PRICE: "최근 일봉 가격", PRICE_DATE: "가격 기준일", AS_OF: "합의 기준일",
  CONSENSUS: "현재 시스템 합의", CONFIDENCE: "합의 확신도", CONFIDENCE_DENOMINATOR: " / 100", AGREEMENT: "의견 일치율",
  UNKNOWN_DATE: "기준일 미제공", UNAVAILABLE: "조회할 수 없습니다. 잠시 후 다시 확인해 주세요.",
  NO_CONSENSUS: "확인 가능한 합의가 없습니다.", NO_DATA: "저장된 자료가 없습니다.",
  TIME_NOTE: "가격·합의·보유 점검은 기준일이 다를 수 있습니다. 당시 판단의 근거는 판정 이력에서 확인하세요.",
  HOLDING: "보유 종목 점검", NO_REVIEW: "현재 점검 목록에 이 종목이 없습니다. 보유 여부는 포트폴리오에서 확인하세요.",
  PORTFOLIO: "포트폴리오 보기", ACCOUNT: "점검 기준 계좌", POSITION: "종목 비중", PNL: "계좌 평가손익",
  ALPHA: "기대수익 판단", PORTFOLIO_AXIS: "포트폴리오 판단", NOT_PROVIDED: "미제공",
  REVIEW_DATE: "점검 판정 기준일", GENERATED: "점검 목록 생성", LEDGER: "연결된 판정 근거",
  NO_LEDGER: "이 점검에 연결된 판정 기록이 없습니다.", NO_REASON: "제공된 근거가 없습니다.",
  ACCOUNT_NOTE: "여러 계좌 보유 시 보유 점검에서 선택한 계좌의 손익입니다. 종목 비중은 전체 보유 기준입니다.",
  EVIDENCE: "매매 판단", RESEARCH: "가격·자료", HISTORY: "판단 기록", DETAIL_TABS: "종목 상세 탐색",
  AGENTS: "에이전트 의견", AGENT_NOTE: "현재 합의의 구성 의견입니다. 자료 부족·기권은 유효 의견과 구분합니다.",
  DISSENT: "다른 의견", NO_DISSENT: "제공된 반대 의견이 없습니다.",
  PRICE_HISTORY: "가격 흐름", PRICE_NOTE: "저장된 종가·거래량과 이동평균입니다.",
  FUNDAMENTALS: "기업 지표", FUND_LABELS: { pe_ratio: "PER", roe: "ROE", revenue_growth: "매출 성장률", debt_to_equity: "부채 / 자기자본", profit_margin: "순이익률", beta: "베타" },
  LEGACY_CALCULATION_NOTE: "이전 계산 기준으로 저장된 판정입니다. 부채비율 단위·보유 비중 산식 수정은 새 판정부터 적용되며, 아래 사유는 당시 기록 원문입니다.",
  DECISION_MECHANISMS: { risk_veto: "위험 에이전트 거부권", weighted_sum: "에이전트 가중 투표", divergence_penalty: "기술적 반대에 따른 유보" },
  DECISION_MECHANISM_UNKNOWN: "저장된 결정 경로를 확인할 수 없습니다.",
  VETO_CONFIDENCE_NOTE: "위험 규칙이 최종 판정을 결정했습니다. 확신도 100이 전체 에이전트의 만장일치를 뜻하지 않습니다.",
  RATINGS: "애널리스트 의견", EARNINGS: "분기 실적", INSIDERS: "내부자 거래", INVESTORS: "주요 투자자 공시",
  FIRM: "기관", GRADE: "등급 / 변경", TARGET: "외부 목표가", PERIOD: "결산일", ACTUAL: "실제 EPS", ESTIMATE: "예상 EPS",
  DATE: "기준일", PERSON: "이름", TRANSACTION: "거래 구분", SHARES: "주식 수", WEIGHT: "공시 비중",
  HISTORY_NOTE: "최근 12건의 저장된 판정입니다. 현재 합의와 별개이며, 각 행에서 당시 근거를 확인할 수 있습니다.",
  ACTION: "판정", OUTCOME: "추적 결과", RETURN_7D: "7일 수익률", RETURN_30D: "30일 수익률", OPEN: "근거 보기",
  SOURCE_NOTE: "각 자료에 저장된 기준일을 표시합니다. 외부 의견은 시스템 판정과 별개입니다.",
  LOADING: "종목 자료를 불러오고 있습니다.", RETRY: "다시 조회",
} as const;

export const TICKER_DETAIL = {
  STOP_LOSS: "손절가",
  TARGET_1: "1차 익절",
  TARGET_2: "2차 익절",
  TRAILING: "트레일링",
  ANALYST: "애널리스트",
  // #1218 U4a: 빈 패널 접기 — 데이터 없는 카드는 렌더하지 않고 한 줄로 병합
  MISSING_PREFIX: "미수집 데이터:",
  MISSING_KR_HINT: "(KR 종목은 yfinance/EDGAR 소스 미지원 항목이 정상적으로 비어 있음)",
  PANEL_RATINGS: "Analyst Ratings",
  PANEL_EARNINGS: "Earnings",
  PANEL_INSIDERS: "Insider Activity",
  PANEL_FUNDAMENTALS: "Fundamentals",
  PANEL_SMART_MONEY: "Smart Money",
  PANEL_TARGETS: "Price Targets",
  PANEL_EXTERNAL: "External Data",
} as const;

/* ── Scan Page (#1219 U4b) ──────────────────────────────────── */
export const SCAN = {
  TITLE: "Market Scanner",
  // 병합 테이블 헤더: 시그널 수 + 스윙 승인/거절 집계
  HEADER_SIGNALS: "시그널",
  HEADER_APPROVED: "승인",
  HEADER_REJECTED: "거절",
  EMPTY: "스캔 결과 없음 — make quick-scan 실행 필요",
  TAG_APPROVED: "승인",
  TAG_REJECTED: "미승인",
  TAG_NO_EVAL: "—", // 스윙 평가 없음 (스캔 전용 행)
  REJECTED_FOLD: "미승인 사유",
} as const;

/* ── Engine Page (#1218 U4a) ────────────────────────────────── */
export const ENGINE = {
  CONFLICTS_EMPTY: "시그널 충돌 없음",
  DRIFT_EMPTY: "드리프트 데이터 없음 — make validate 실행 필요",
  // BLOCKED 게이트의 다음 행동 (phase id = pipeline step id, /api/gate 실측)
  NEXT_ACTION_PREFIX: "다음 행동:",
  NEXT_ACTION_RUN: "파이프라인에서 실행 →",
  NEXT_ACTION_GENERIC: "파이프라인 확인 →", // 매핑 밖 phase — 실행 불가 이름을 광고하지 않는다
} as const;

/* ── Explore Page ───────────────────────────────────────────── */
export const EXPLORE = {
  SEARCH_PLACEHOLDER: "종목 검색 (NVDA, 삼성전자, 005930...)",
  US_POPULAR: "US 인기 종목",
  KR_POPULAR: "KR 인기 종목",
  MARKET_CONTEXT: "시장 현황",
  MARKET_NO_DATA: "시장 데이터 없음 — make collect 실행 후 표시됩니다",
  RECENT_SIGNALS: "최근 시그널",
  SIGNALS_NO_DATA: "시그널 데이터 없음 — make full-scan 실행 후 표시됩니다",
  QUICK_START: "빠른 시작",
  LOAD_SAMPLE: "sample portfolio 로드",
  LOAD_SAMPLE_DESC: "대시보드 바로 체험",
  NO_RESULTS: "일치하는 종목이 없습니다",
  SEARCH_HINT: "ticker 코드 또는 종목명을 입력하세요",
  LOADING: "검색 중...",
  NO_PRICE: "미수집",
  COLLECT_HINT: "make scan-extended로 전체 종목 수집",
} as const;

export const REGIME_GUIDE = {
  bull: "추세 매수 유리 — 시그널 매수 진입 가능",
  bear: "방어 자세 — 신규 매수 자제, 손절 엄수",
  sideways: "방향성 불명확 — 소량 분할 매수 또는 관망",
} satisfies Record<string, string>;

/* ── Common ─────────────────────────────────────────────────── */
export const COMMON = {
  // `make api` 지시는 prod(launchd)에서 틀린 조치라 카피에서 제거 (design-review F-002)
  API_ERROR: "API 연결에 실패했습니다 — 백엔드 서버 상태를 확인하세요.",
  // #1119: 슬롯 포화 503 은 의도된 shed — 페이지 전체 에러가 아니라 섹션 1줄로 강등
  DEGRADED: "데이터를 불러오지 못했습니다 — 잠시 후 새로고침하세요.",
  COUNT_SUFFIX: "건",
  UNIT_SUFFIX: "개",
  RUN_REQUIRED: "실행 필요",
} as const;

/* ── Rate 프리미티브 (#1429) ────────────────────────────────── */
// 비율 지표는 분모와 함께만 말한다. 문구가 "승률"/"적중률" 같은 성과 단어를 피하는
// 것은 의도적이다 — 표본이 안 닫힌 비율에 성과 이름을 붙이면 카드 자체가 주장이 된다.
export const RATE = {
  ADJUDICATED: "판정 완료",
  OPEN_SAMPLE: "표본 미완결 — 판정이 끝나지 않은 결정이 남아 있습니다",
} as const;

/* ── 에러 카피 (design-review F-002) ────────────────────────── */
// 원문 에러 문자열(영어 transport 텍스트)을 사용자 카피로 렌더하지 않는다.
// 사용자 카피 = 무엇이 실패했나 + 다음 행동. 원문은 title/콘솔로 강등.
export const ERRORS = {
  API_TITLE: "API 연결 실패",
  API_BODY: "백엔드 API가 응답하지 않습니다 — 서버 상태를 확인한 뒤 다시 시도하세요.",
  GENERIC_TITLE: "문제가 발생했습니다",
  RETRY: "다시 시도",
  REBALANCE_FAILED: "리밸런싱 계산에 실패했습니다 — 데이터 수집 후 다시 시도하세요.",
  SCORECARD_FAILED: "스코어카드를 불러오지 못했습니다 — make validate 실행 후 표시됩니다.",
  REPORT_FAILED: "리포트 생성에 실패했습니다 — Ollama·백엔드 상태를 확인한 뒤 다시 시도하세요.",
  COVERAGE_FAILED: "Coverage 확인 실패 — 파이프라인 상태를 확인하세요.",
  RUN_FAILED_PREFIX: "실행 실패: ",
  // #1250: 파이프라인 3개 fetch 는 실패를 삼켜 빈/로딩 화면으로 렌더했다.
  // 운영자 터미널에서 "백엔드 죽음" 과 "데이터 없음" 이 같은 화면이면 오판을 부른다.
  PIPELINE_STATUS_FAILED: "파이프라인 상태를 불러오지 못했습니다 — 아래 단계는 마지막으로 성공한 조회 기준입니다.",
  PIPELINE_TIMELINE_FAILED: "이벤트 타임라인을 불러오지 못했습니다 — 이벤트가 없는 것과 다릅니다.",
  PIPELINE_GATE_FAILED: "게이트 조건을 불러오지 못했습니다 — 조건이 없는 것과 다릅니다.",
} as const;

/**
 * #1683: 탐색 후보에 붙는 파이프라인 분류 문구. 점수·임계·차단 사유는 전부 API 값이다 —
 * 여기에는 숫자 임계를 두지 않는다. 매매 지시가 아니라 시스템의 분류다.
 */
export const SYSTEM_STANCE = {
  QUALIFIED: "후보 기준 통과",
  BELOW_THRESHOLD: "기준 미달",
  EXCLUDED: "제외",
  BLOCKED: "차단",
  NOT_SCORED: "미평가",
  REASON: {
    held: "보유 중",
    cooldown: "쿨다운",
    leverage_etf: "레버리지 ETF",
    no_factor: "팩터 데이터 없음",
    no_price: "가격 데이터 없음",
    evaluation_failed: "평가 실패",
  },
  NOTE: "BUY 후보 emitter 의 채점·게이트 분류입니다. 매매 지시가 아닙니다.",
} as const;

/* ── StatusBadge Korean keys ────────────────────────────────── */
export const STATUS_BADGE = {
  BUY: "\uB9E4\uC218",
  SELL: "\uB9E4\uB3C4",
  AGGRESSIVE: "\uACF5\uACA9",
  NEUTRAL: "\uAD00\uB9DD",
  CAUTIOUS: "\uC8FC\uC758",
  DEFENSIVE: "\uBC29\uC5B4",
} as const;

// \uC0AC\uC774\uB4DC\uBC14 5\uADF8\uB8F9 (#1200 U1b-2, docs/UX_REDESIGN_PLAN.md \u00A71)
export const NAV = {
  TODAY: "\uC624\uB298",
  DECISIONS: "\uC758\uC0AC\uACB0\uC815",
  PORTFOLIO: "\uD3EC\uD2B8\uD3F4\uB9AC\uC624",
  RESEARCH: "\uB9AC\uC11C\uCE58",
  SYSTEM: "\uC2DC\uC2A4\uD15C",
  // \uC544\uC774\uCF58 \uC804\uC6A9 \uC811\uAE30 \uD1A0\uAE00\uC758 \uC811\uADFC\uBA85 (codex design audit M5 / ship review P3 SSoT)
  SIDEBAR_EXPAND: "\uC0AC\uC774\uB4DC\uBC14 \uD3BC\uCE58\uAE30",
  SIDEBAR_COLLAPSE: "\uC0AC\uC774\uB4DC\uBC14 \uC811\uAE30",
  // 라우트 라벨 (#1252). 소비자는 사이드바 하나뿐이지만, SSoT 밖에 있으면 e2e 가
  // 문자열을 직접 박게 되고 그게 #1118 의 3.5개월 무신호 회귀를 만든 경로다.
  ROUTE_DASHBOARD: "Overview",
  ROUTE_DECISIONS: "Decisions",
  ROUTE_ENGINE: "Decision Engine",
  ROUTE_EVIDENCE: "Evidence",
  ROUTE_PORTFOLIO: "Portfolio",
  ROUTE_REBALANCE: "Rebalance",
  ROUTE_TARGETS: "Price Targets",
  ROUTE_EXPLORE: "Explore",
  ROUTE_SCANNER: "Scanner",
  ROUTE_SIGNALS: "Signals",
  ROUTE_STRATEGY: "Strategy",
  ROUTE_AGENTS: "Agents",
  ROUTE_PIPELINE: "Pipeline",
  ROUTE_REPORT: "AI Report",
  SYSTEM_ONLINE: "System Online",
} as const;


/* ── 백엔드 분류 → 한국어 라벨 (Overview · 다른 화면 공용) ──────────── */
// macro_score.py 의 interpretation 그대로가 키다. 점수로 라벨을 다시 지어내지 않는다 (#1652 Codex r1-r3).
export const MACRO_INTERPRETATION = {
  Favorable: MACRO_LEVEL.GOOD,
  Neutral: MACRO_LEVEL.NORMAL,
  Cautious: MACRO_LEVEL.WEAK,
  Adverse: MACRO_LEVEL.FRAGILE,
  Insufficient: "입력 부족",
  Unavailable: "산출 불가",
} satisfies Record<string, string>;

export const REGIME_LABEL = {
  bull_low_vol: "상승 · 저변동",
  bull_high_vol: "상승 · 고변동",
  bear_low_vol: "하락 · 저변동",
  bear_high_vol: "하락 · 고변동",
  sideways_low_vol: "횡보 · 저변동",
  sideways_high_vol: "횡보 · 고변동",
  // 특수 레짐 4종 (nuri/quant/regime/classifier.py SPECIAL_REGIMES) — 키가 없으면 화면이 원문 키를 낸다.
  // 키 집합은 tests/quant/regime/test_regime_label_coverage.py 가 ALL_REGIMES 와 대조한다.
  euphoria: "과열",
  stagflation: "스태그플레이션",
  recovery: "회복 초기",
  sector_rotation: "섹터 순환",
} satisfies Record<string, string>;

/* ── Overview (/, #1658 · #1698) ───────────────────────────────────────────── */
// 화면의 모든 사용자 노출 문구. 컴포넌트와 테스트는 여기서 읽는다 (#1252 — 리터럴은 e2e 무신호 회귀의 경로).
export const OVERVIEW = {
  TITLE: "Overview",
  SUBTITLE: "시장과 포트폴리오의 현재 상태",
  REFRESH: "새로고침",
  INBOX: "보유 종목 점검",
  RADAR: "시장 탐색",
  ALLOCATION: "내 포트폴리오",
  PIPELINE: "파이프라인 상태",
  TRUST: "데이터 업데이트",
  UNAVAILABLE: "정보를 불러올 수 없습니다. 잠시 후 새로고침해 주세요.",
  EMPTY: "현재 표시할 항목이 없습니다.",
  LOADING: "시장 환경과 시스템 판단을 불러오는 중입니다…",
  // 공통 상태 라벨 (파이프라인 이벤트 · 신선도)
  STATUS: { done: "완료", success: "완료", running: "실행 중", error: "오류", idle: "대기", PASS: "정상", WARN: "주의", FAIL: "지연" } satisfies Record<string, string>,
  SUMMARY: {
    ARIA: "오늘의 확인 순서",
    LABEL: "시스템 의견",
    PARTIAL: (missing: number, total: number) => `일부 정보를 불러오지 못했습니다 (${missing}/${total}).`,
    FRESHNESS_UNKNOWN: "신선도 확인 불가",
    FRESHNESS_FAIL: (n: number) => `지연된 데이터 ${n}개`,
    FRESHNESS_WARN: (n: number) => `주의할 데이터 ${n}개`,
    FRESHNESS_OK: "수집 데이터 정상",
  },
  METRICS: {
    ARIA: "현재 시장 환경",
    INDICES: "주요 지수",
    INDICES_UNAVAILABLE: "지수 정보를 불러올 수 없습니다.",
    INDEX_DATE_UNKNOWN: "기준일 없음",
    REGIME: "시스템 분류",
    REGIME_GUIDE_TITLE: "주요 지수와 시스템 분류",
    REGIME_GUIDE: [
      "주요 지수는 S&P 500·NASDAQ 종합·KOSPI·KOSDAQ 의 최근 저장값과 직전 관측 대비 변화율입니다. 수집이 빠진 날이나 휴장일이 끼면 며칠치 변화일 수 있습니다. 장중에는 확정 종가가 아닐 수 있고, 미국과 한국의 기준일이 다를 수 있습니다.",
      "시스템 분류는 시장 흐름(레짐)이며 목표 자산 배분에 쓰입니다. 기본 판정은 추세(상승·하락·횡보)와 변동성(저변동·고변동)입니다.",
      "특수 조건이 맞으면 기본 판정 대신 특수 분류가 표시됩니다 — 과열(VIX 12 미만이면서 공포·탐욕 지수 80 초과), 스태그플레이션(물가 상승률 4% 초과이면서 GDP 성장률 1% 미만), 회복 초기(장기 하락 뒤 50일 이동평균이 200일 이동평균을 다시 넘어섬), 섹터 순환(S&P 500 ETF 20일 수익률 ±2% 이내인데 섹터 ETF 하나 이상이 3% 이상 상승). 회복 초기·스태그플레이션·섹터 순환은 강한 경제 이벤트 신호로 지정되기도 합니다.",
      "검사 일치는 기본 판정을 점검하는 검사 중 통과한 비율입니다 — 추세 검사(공포·탐욕 지수, RSI, 50일 이동평균 기울기)와 변동성 교차 검사(VIX와 볼린저 밴드 폭이 같은 쪽을 가리키는지). 값이 없는 지표의 검사는 빠지므로 분모가 달라질 수 있습니다. 특수 분류의 신뢰도가 아니며, 앞으로 오를 확률이나 수익 확률도 아닙니다.",
    ],
    REGIME_BASE: (base: string) => `기본 판정 ${base}`,
    REGIME_AGREEMENT: (pct: string) => `검사 일치 ${pct}`,
    MACRO: "경제 여건 점수",
    MACRO_GUIDE_TITLE: "경제 여건 점수의 의미",
    MACRO_GUIDE: [
      "금리·수익률 곡선·고용·물가·시장 심리·경제 이벤트 등을 종합한 시스템 점수입니다. 높을수록 투자 환경에 우호적인 것으로 해석합니다.",
      "경제 성장률이나 수익 확률이 아닙니다. 입력이 부족하면 제공된 지표만으로 계산되므로 데이터 상태를 함께 확인해야 합니다.",
    ],
    MACRO_DENOMINATOR: " / 100",
    MACRO_UNAVAILABLE: "경제 지표 확인 필요",
    VIX: "변동성 지수",
    VIX_SUB: "VIX",
    VIX_GUIDE_TITLE: "변동성 지수(VIX)의 의미",
    VIX_GUIDE: [
      "S&P 500 옵션 가격에서 산출한 향후 30일 기대 변동성입니다. 높을수록 시장이 큰 가격 변동을 예상한다는 뜻이며, 방향(상승·하락)을 말해 주지는 않습니다.",
      "아래 출처와 기준일은 저장된 값 그대로입니다. 장중에는 확정 종가가 아닐 수 있습니다.",
    ],
    ACTIONS: "우선 점검 항목",
    ACTIONS_UNIT: " 우선 확인",
    ACTIONS_SUB: (check: string, portfolio: string) => `검토 ${check} · 규칙 ${portfolio}`,
    ACTIONS_GUIDE_TITLE: "우선 점검 항목의 의미",
    ACTIONS_GUIDE: [
      "보유 종목 점검에서 우선 확인으로 분류된 개수입니다. 검토와 포트폴리오 규칙 개수를 함께 표시합니다.",
      "시스템 판정 원장(에이전트 합의와 포트폴리오 규칙 점검)에서 만든 목록입니다. 매수·매도 지시가 아니라 점검 순서입니다.",
    ],
    ACTIONS_SOURCE: "시스템 판정",
    ACTIONS_JUDGED: "판정 기준일 (가장 최근)",
    ACTIONS_JUDGED_SHORT: (date: string) => `판정 ${date}`,
    // 카드 머리글·출처 (#1682) — 하단 패널과 같은 "아이콘 + 이름 + 읽는 법" 형식
    GUIDE: "읽는 법",
    SOURCE_HEADING: "출처와 기준일",
    SOURCE_COLUMNS: ["항목", "출처", "기준일"],
    SOURCE_UNKNOWN: "출처 미제공",
    SOURCE_EVENT_NOTE: "경제 이벤트 점수는 뉴스·경제 일정에서 따로 계산되어 이 목록에 없습니다. 기준금리 값이 없으면 2년물 금리로 대신 계산합니다.",
    SOURCE_LIST_GENERATED: (time: string) => `목록 생성 ${time}`,
    // 카드 우측 하단은 좁다 — 첫 출처 + 나머지 개수, 전체 목록은 모달에
    SOURCE_MORE: (first: string, rest: number) => (rest > 0 ? `${first} 외 ${rest}곳` : first),
  },
  // 저장된 source 코드 → 표시 이름. 모르는 코드는 그대로 보인다 (출처를 지어내지 않는다, #1682)
  SOURCE_NAME: {
    FRED: "FRED",
    yfinance: "Yahoo Finance",
    yfinance_SPY: "Yahoo Finance (SPY 옵션)",
    CNN: "CNN",
  } satisfies Record<string, string>,
  // 출처가 대용치일 때의 이름 — "키:source" (macro.py YFINANCE_SYMBOLS 의 대용 매핑)
  MACRO_INPUT_PROXY_LABEL: {
    "us_2y_yield:yfinance": "미국 13주물 금리 (2년물 대용)",
  } satisfies Record<string, string>,
  // 경제 여건 점수 입력 지표 (백엔드 MACRO_INPUTS 와 같은 키)
  MACRO_INPUT_LABEL: {
    us_10y_yield: "미국 10년물 금리",
    us_2y_yield: "미국 2년물 금리",
    us_3m_yield: "미국 3개월물 금리",
    vix: "VIX",
    put_call_ratio: "풋/콜 비율",
    fear_greed: "공포·탐욕 지수",
    unemployment: "실업률",
    cpi_yoy: "CPI 상승률",
    fed_funds_rate: "기준금리",
  } satisfies Record<string, string>,
  INBOX_PANEL: {
    GUIDE: "읽는 법",
    GUIDE_TITLE: "보유 종목 점검을 읽는 법",
    GUIDE_INTRO: "현재 보유 종목에 대해 백엔드가 생성한 점검 목록입니다. 종목을 선택하면 판정 기준일, 근거, 보유 비중과 두 종류의 신호를 확인할 수 있습니다.",
    GUIDE_BUCKETS: [
      "우선 확인: 시스템이 우선 점검 대상으로 분류한 항목입니다. 표시된 위험 근거를 먼저 확인하세요.",
      "검토: 추가 확인이 필요한 시스템 판단입니다.",
      "포트폴리오 규칙: 집중도·업종·레버리지 등 보유 구성의 점검입니다.",
      "유지: 시스템이 유지로 분류한 항목입니다.",
    ],
    GUIDE_AXES: "기대수익 신호(LONG·SHORT·FLAT)와 포트폴리오 신호(REBALANCE·TRIM·HEDGE·NONE)는 서로 다른 축입니다. 포트폴리오 규칙을 매도 판단으로 해석하지 마세요.",
    GUIDE_CAVEAT: "합의 확신도는 수익 확률이 아닙니다. 목록 생성 시각과 판정 기준일도 다릅니다. 오래된 입력이나 연결된 원장이 없는 항목은 근거를 추가 확인하세요.",
    LEDGER: "판정 원장",
    FILTER_ARIA: "판단 목록 필터",
    BUCKETS: { urgent: "우선 확인", check: "검토", portfolio: "포트폴리오 규칙", hold: "유지" },
    BUCKET_EMPTY: (bucket: string) => `${bucket} 목록에 현재 표시할 항목이 없습니다.`,
    QUEUE_ARIA: (bucket: string) => `${bucket} 종목 선택`,
    EVIDENCE_ARIA: "선택한 판단 근거",
    AS_OF: "판정 기준일 · ",
    NO_REASONS: "판단 근거 미제공",
    POSITION: "보유 비중",
    PNL: "평가 손익률",
    ALPHA_AXIS: "기대수익 신호",
    PORTFOLIO_AXIS: "포트폴리오 신호",
    NOT_PROVIDED: "미제공",
    LEDGER_LINK: "판정 원장에서 전체 근거 확인",
    NO_LEDGER: "연결된 판정 원장 기록이 없습니다.",
    GENERATED: "목록 생성 · ",
  },
  PORTFOLIO: {
    ARIA: "포트폴리오 구성",
    VIEW_ALL: "전체 보기",
    RULES_LINK: "포트폴리오 규칙",
    RULES_COUNT: (n: string) => `${n}건`,
    UNAVAILABLE: "포트폴리오를 불러오지 못했습니다.",
    GROUP_ARIA: "포트폴리오 구성 기준",
    GROUPS: { ticker: "종목별", sector: "업종별", account: "계좌별" },
    CHART_ARIA: "포트폴리오 구성 비중 도넛 차트",
    CHART_ARIA_UNKNOWN: "포트폴리오 비중 산출 불가",
    CHART_ARIA_EMPTY: "평가 자산 없음",
    TOTAL: "총 평가액",
    TOTAL_UNKNOWN: "산출 불가",
    TOTAL_UNIT: "USD · 현금 포함",
    LEGEND_ARIA: "전체 포트폴리오 비중 목록",
    COUNT: (n: number) => `전체 ${n}개 구성 · 목록을 스크롤해 확인`,
    INCOMPLETE: "가격·환율·현금 데이터 확인 필요 · 비중 산출 보류",
    BASIS: "평가 기준 · 전체 구성",
    BASIS_TITLE: "포트폴리오 구성과 평가 기준",
    BASIS_GUIDE: "저장된 최근 종가로 보유 수량을 평가하고 현금을 합산합니다. KRW 자산은 저장된 USD/KRW 환율로 환산합니다. 목표 비중이 아닌 현재 보유 구성입니다.",
    PRICE_DATE: "가격 기준일 · ",
    PRICE_DATE_NOTE: ". 실시간 시세가 아니며 종목별 기준일이 다를 수 있습니다.",
    NOT_PROVIDED: "미제공",
    WEIGHT_UNKNOWN: "비중 미상",
    UNCLASSIFIED: "미분류",
    CASH: "현금",
  },
  RADAR_PANEL: {
    ARIA: "시장 탐색 후보",
    SCANNER: "스캐너",
    CAPTION: "탐색 후보 가격 변화 · 목록 순서 상위 4개",
    COL_TICKER: "종목",
    COL_1D: "1일 변화",
    COL_5D: "5일 변화",
    COL_VERDICT: "시스템 판단",
    DETAIL_TITLE: (ticker: string) => `${ticker} · 탐색 근거`,
    // #1683: 스캐너 관측은 판정이 아니다 — 시스템 판단은 COL_VERDICT 자리의 파이프라인 분류다
    OBSERVATIONS: "스캐너 관측",
    NO_OBSERVATIONS: "스캐너 관측 없음",
    NOT_A_DECISION: "탐색 후보의 가격 변화입니다. 신규 판단이나 판단 변경을 의미하지 않습니다.",
    GENERATED: (time: string) => `목록 생성 · ${time} · 개별 가격 관측 시각은 제공되지 않습니다.`,
    TICKER_DETAIL: "종목 상세",
    FOOTER: "후보 가격 변화 · 판단 변경 이력 아님",
  },
  TRUST_PANEL: {
    ALL_SOURCES: "전체 소스",
    ALL_SOURCES_TITLE: "데이터 소스별 신선도",
    STALE_INPUTS: "종합 의견 보류 입력: ",
    PASS: "정상",
    WARN: "주의",
    FAIL: "지연",
    NONE_DELAYED: "주의·지연 항목 없음",
    MONITORED: (n: number) => `${n}개 소스 모니터링`,
    UNKNOWN: "신선도 확인 불가",
    REFRESH_DELAYED: "지연 데이터 갱신",
  },
  PIPELINE_PANEL: {
    ARIA: "파이프라인 실행 상태",
    DETAIL: "상세",
    RELOAD_ARIA: "파이프라인 상태 새로고침",
    RELOAD_TITLE: "상태만 조회 · 작업 재실행 아님",
    STAGES: { collect: "데이터 수집", analyze: "지표 분석", consensus: "의견 종합", decide: "판정 기록", track: "결과 추적" } satisfies Record<string, string>,
    EVENTS: { done: "성공 기록", success: "성공 기록", running: "실행 중", error: "오류", idle: "대기" } satisfies Record<string, string>,
    SCHEDULER: { ok: "스케줄러 정상", stale: "스케줄러 응답 지연", unknown: "스케줄러 확인 불가", error: "스케줄러 조회 오류", unavailable: "스케줄러 연결 실패" } satisfies Record<string, string>,
    SCHEDULER_OTHER: (status: string) => `스케줄러 ${status}`,
    SCHEDULER_PENDING: "스케줄러 확인 중",
    NO_LEDGER_DATE: "원장 미확인",
    NO_EVENT: "기록 없음",
    DECIDE_ERROR: "실행 오류",
    DECIDE_COUNT: (n: number) => `${n}건 기록`,
    DECIDE_CHECK: "확인 필요",
    DECIDE_TITLE: "판정 기록 상태",
    DECIDE_GUIDE: "판정 기록(Decide)은 별도 예약 작업이 없습니다. 의견 종합(Consensus) 작업 안에서 결과를 원장에 저장합니다.",
    DECIDE_LEDGER: (date: string, count: string) => `최근 원장 기준일: ${date} · 기록 ${count}건`,
    DECIDE_EVENT: (status: string, time: string) => `실행 이벤트: ${status} · ${time}`,
    DECIDE_CAVEAT: "기록이 있다는 사실이 최신 판단이나 품질을 보장하지 않습니다. 표시한 날짜는 현재 연결된 DB의 판정 기준일입니다. 개발 DB는 운영 원장의 읽기 복제본이므로 갱신·동기화 상태를 함께 확인하세요.",
    LEDGER_LINK: "판정 원장 확인",
    NOT_PROVIDED: "미확인",
    EMPTY: "실행 기록 없음",
    UNAVAILABLE: "실행 상태 확인 불가",
    STALE: "갱신 실패 · 이전 기록 표시",
    CHECKED_TITLE: (time: string) => `마지막 상태 조회 ${time} · 마지막 실행 결과는 데이터 신선도와 별개입니다.`,
    CHECKED_AT: (hhmm: string) => `조회 ${hhmm} KST`,
    CHECK_PENDING: "조회 대기",
    REFRESH: "데이터 갱신",
  },
  REFRESH_DIALOG: {
    TITLE: "데이터 갱신 작업",
    INTRO: "수집 또는 재계산할 작업을 선택하세요. 주가 → 지표 → 종합 분석 순서로 실행합니다. 기술 지표가 오래되었다면 주가도 함께 수집하세요.",
    SCOPE: "합의·판정·성과 기록은 예약 작업과 운영 원장에서 관리합니다. 이 갱신으로 새 투자 판단이 생성되지는 않습니다.",
    LOADING: "갱신 가능한 작업을 불러오는 중입니다.",
    JOB_STATUS: { queued: "대기", running: "진행 중", completed: "작업 완료", failed: "실패", skipped: "실행하지 않음" } satisfies Record<string, string>,
    UNSUPPORTED: "일부 지연 소스는 이 화면에서 직접 갱신하지 않습니다. 파이프라인 상세에서 예약 작업과 원본 소스를 확인하세요.",
    START: "선택한 데이터 갱신",
    SENDING: "요청 중…",
    IN_PROGRESS: "갱신 진행 중…",
    PIPELINE_LINK: "파이프라인 상세",
    LAST_REQUEST: "최근 요청 · ",
    RESULT: (pass: number, warn: number, fail: number) => `재확인: 정상 ${pass} · 주의 ${warn} · 지연 ${fail}. 작업 완료 후에도 원본 데이터가 오래되면 지연이 남습니다.`,
    ERROR_AUTH: "실행 권한이 필요합니다. API 인증 상태를 확인해 주세요.",
    ERROR_BUSY: "이미 갱신 작업이 실행 중입니다. 진행 상태를 확인하세요.",
    ERROR_REQUEST: "갱신 요청을 처리하지 못했습니다. 진행 상태를 확인한 후 다시 시도하세요.",
    ERROR_RESPONSE: "서버 응답을 확인하지 못했습니다. 중복 요청 전에 진행 상태를 확인하세요.",
    ERROR_POLL: "갱신 상태를 확인하지 못했습니다. 자동으로 다시 조회합니다. 요청한 작업은 서버에서 계속될 수 있습니다.",
    NOTE: "여러 분이 걸릴 수 있습니다. 진행 내역은 현재 API 프로세스 기준이며 재시작 시 초기화됩니다. 요약 수치는 서버 캐시 만료 후 반영될 수 있습니다.",
  },
  FOOTER: {
    SNAPSHOT: "현재 스냅샷 · ",
    ALERTS: (n: string) => `시스템 알림 ${n}`,
    ALERTS_TITLE: "시스템 알림",
  },
  DIALOG: { CLOSE: "닫기", ESC: "ESC" },
  TIME_UNKNOWN: "기준 시각 미제공",
} as const;
