/**
 * Centralized Korean UI strings — single source of truth (#226).
 *
 * Components and tests import from here instead of inlining Korean.
 * Not a full i18n solution (next-intl) — just constants extraction.
 */

/* ── Dashboard Hero ─────────────────────────────────────────── */
export const HERO = {
  TOTAL_ASSET: "총 자산",
  TODAY_PNL: "오늘 P&L",
  CUMULATIVE_RETURN: "누적 수익률",
  CUMULATIVE_SUB: "실현 미실현 합계",
  WIN_RATE: "승률",
  FLAT: "보합",
  HOLDINGS_BASIS: "보유 종목 기준",
  HOLDINGS_PREFIX: "보유",
  CASH_PREFIX: "현금",
} as const;

/* ── Composition Section ────────────────────────────────────── */
export const COMPOSITION = {
  TAB_TICKER: "자산",
  TAB_SECTOR: "섹터",
  TAB_ACCOUNT: "계좌",
  TOTAL_ASSET: "총 자산",
  EMPTY: "표시할 데이터가 없습니다.",
  NO_DATA: "— 데이터 없음",
  NO_LOSERS: "손실 없음",
  CONCENTRATION: "집중도 (HHI)",
} as const;

/* ── Verdict / Trend / Market Context ───────────────────────── */
export const VERDICT = {
  AGGRESSIVE: "공격",
  NEUTRAL: "관망",
  CAUTIOUS: "주의",
  DEFENSIVE: "방어",
  STALE: "데이터 낡음", // 판단 입력 stale — verdict 보류 (#1180)
} as const;

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

/* ── Holding Row Statuses ───────────────────────────────────── */
export const HOLDING_STATUS = {
  STOP_LOSS: "손절",
  VIOLATION: "⚠ 위반",
  SELL: "매도",
  TP2: "✓ 익절₂",
  TP1: "✓ 익절₁",
  BUY: "매수",
  HOLD: "보유",
  REACHED: "✓ 도달",
} as const;

/* ── Holding Row ARIA / Column Headers ──────────────────────── */
export const HOLDING_LABEL = {
  CURRENT_AVG: "현재가/평단가",
  DAILY_DELTA: "일변",
  STOP_LOSS: "손절가",
  TARGET_1: "1차 익절가",
  TARGET_2: "2차 익절가",
  SECTOR: "섹터",
  POSITION_PCT: "비중",
  SUMMARY_ARIA: "보유 종목 요약",
} as const;

/* ── Column Headers (Holdings Table) ────────────────────────── */
export const COL = {
  ACCOUNT: "계좌",
  TICKER: "종목",
  CURRENT: "현재/",
  AVG: "평단",
  PNL: "손익",
  DAILY: "일변",
  STATUS: "상태",
  STOP: "손절",
  TP1: "1차익절",
  TP2: "2차익절",
  TREND: "추세",
  SECTOR: "섹터",
  WEIGHT: "비중",
} as const;

/* ── Dashboard Sections ─────────────────────────────────────── */
export const SECTION = {
  HOLDINGS: "보유 종목",
  WINNERS: "수익",
  LOSERS: "손실",
  COLLAPSE: "접기",
  VIEW_ALL: "전체",
  VIEW_SUFFIX: "보기",
  DETAIL: "상세",
  PENSION: "연금",
  PENSION_HIDDEN_SUFFIX: "건 숨김",
  PENSION_MONTH_END_WAIT: "월말 대기",
  PENSION_MONTH_END_BUY_WAIT: "월말 매수 대기",
} as const;

/* ── Dashboard Strips ───────────────────────────────────────── */
export const STRIP = {
  ALERTS_TITLE: "알림",
  ALERTS_EMPTY: "위험 요소 없음",
  ALERTS_PREFIX: "⚠ 주의",
  EVENTS_TITLE: "이벤트",
  EVENTS_EMPTY: "예정된 이벤트 없음",
  EVENTS_PREFIX: "📅 다음 이벤트",
  EVENTS_FALLBACK: "이벤트",
  CANDIDATES_TITLE: "신규 후보",
  CANDIDATES_EMPTY: "신규 매수 후보 없음",
  CANDIDATES_PREFIX: "🎯 신규 후보",
} as const;

/* ── Market Context Labels ──────────────────────────────────── */
export const MARKET = {
  SENTIMENT: "심리",
  ECONOMY: "경제",
  ACTUAL: "실제",
  INVEST: "투자",
  CASH: "현금",
  TARGET: "권장",
} as const;

/* ── Dashboard Footer ───────────────────────────────────────── */
export const FOOTER = {
  QUALITY: "품질",
  QUALITY_FAIL: "품질 미통과",
  RULE_VIOLATION: "규칙 위반",
  COUNT_SUFFIX: "건",
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

/* ── Sparkline ──────────────────────────────────────────────── */
export const SPARKLINE = {
  TREND_30D: "30일 추세",
  TREND_UP: "상승",
  TREND_DOWN: "하락",
  PERIOD_LABEL: "추세",
  PERIOD_SUFFIX: "일",
} as const;

/* ── Collapsible Strip ──────────────────────────────────────── */
export const COLLAPSIBLE = {
  EXPAND_SUFFIX: "펼치기",
  HIDE: "숨기기",
  HIDE_SUFFIX: "숨기기",
} as const;

/* ── Consensus Page ─────────────────────────────────────────── */
export const CONSENSUS = {
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
  NOT_GENERATED: "차트 미생성.",
  MAKE_EVIDENCE: "make evidence",
  MAKE_FULLSCAN: "make full-scan",
  RUN_REQUIRED: "실행 필요",
  OR: "또는",
  LOAD_FAILED: "증거 차트 로드 실패. API 서버 확인 필요.",
  NO_CHARTS: "증거 차트 없음.",
  SUBTITLE: "투자 결정 근거 시각화 — 레짐, 포트폴리오, 시그널, 공포·탐욕, 매도 근거",
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
  SUBTITLE: "의사결정 저널 — 모든 BUY/SELL 판단의 근거와 결과를 추적합니다.",
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
  GATE_LOADING: "게이트 조건 로딩 중...",
} as const;

/* ── Ticker Detail Page ─────────────────────────────────────── */
export const TICKER_DETAIL = {
  STOP_LOSS: "손절가",
  TARGET_1: "1차 익절",
  TARGET_2: "2차 익절",
  TRAILING: "트레일링",
  ANALYST: "애널리스트",
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

export const REGIME_GUIDE: Record<string, string> = {
  bull: "추세 매수 유리 — 시그널 매수 진입 가능",
  bear: "방어 자세 — 신규 매수 자제, 손절 엄수",
  sideways: "방향성 불명확 — 소량 분할 매수 또는 관망",
};

/* ── Common ─────────────────────────────────────────────────── */
export const COMMON = {
  API_ERROR: "API 연결 실패. make api 실행 필요.",
  COUNT_SUFFIX: "건",
  UNIT_SUFFIX: "개",
  RUN_REQUIRED: "실행 필요",
} as const;

/* ── Action-First Dashboard ────────────────────────────────── */
export const ACTION = {
  TITLE: "오늘의 액션",
  URGENT: "즉시 실행",
  CHECK: "오늘 확인",
  HOLD: "유지",
  HOLD_SUMMARY: "유지 종목",
  PORTFOLIO: "포트폴리오 리밸런스",
  DETAIL: "상세 근거",
  DISMISS: "무시하기",
  EMPTY: "오늘 실행할 액션이 없습니다.",
  CONF: "확신도",
  AGREE: "합의",
  PNL: "손익",
  WEIGHT: "비중",
  EVIDENCE: "증거 체인", // #1182: 카드 → /decisions/[id]
} as const;

export const OPPORTUNITY = {
  TITLE: "기회 탐색",
  SUBTITLE: "뉴스·이슈 종목",
  PROS: "찬성",
  CONS: "반대",
  VERDICT: "판정",
  ANALYZE: "10-Agent 분석",
  CHART: "차트 보기",
  EMPTY: "현재 감지된 기회가 없습니다.",
  POSITIVE: "매수 고려",
  NEUTRAL: "관망",
  DANGER: "매수 금지",
  MUTED: "데이터 부족",
} as const;

export const CONTEXT = {
  TITLE: "시장 컨텍스트",
  SYSTEM_HEALTH: "시스템 건강",
  SIEGE: "Certification",
  REGIME: "레짐",
  MACRO: "매크로",
  FRESHNESS: "데이터",
  CERTIFIED: "인증",
  REJECTED: "미인증",
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
