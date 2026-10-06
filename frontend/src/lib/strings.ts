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
  HOLDINGS_PREFIX: "보유",
  CASH_PREFIX: "현금",
  // #1185: 출처 분리 — 히어로 4지표는 전부 포트폴리오 스냅샷이지 판정 원장이 아니다 (§3.11).
  // 출처는 보유 DB(portfolio 테이블)+최신 종가다 — yaml 은 sync 지연/실패 시 어긋난다 (Codex P2).
  // 범위도 갈린다: 총 자산=전 계좌+현금, 오늘·누적·승률=연금 제외 보유분 (page.tsx 필터).
  PROVENANCE_SNAPSHOT: "지표 출처: 포트폴리오 스냅샷 (보유 DB + 최신 종가, 미실현 포함)",
  PROVENANCE_SCOPE: "총 자산=전 계좌+현금 · 오늘·누적·승률=연금 제외 보유분",
  PROVENANCE_LEDGER_LINK: "시스템 판정 성과는 판정 원장",
  WIN_RATE_SCOPE: "보유 미실현 기준 — 시스템 판정 성과 아님",
} as const;

/* ── Composition Section ────────────────────────────────────── */
export const COMPOSITION = {
  TAB_TICKER: "자산",
  TAB_SECTOR: "섹터",
  TAB_ACCOUNT: "계좌",
  TOTAL_ASSET: "총 자산",
  OTHER: "기타", // #1210: 스택 바 상위 5 밖 슬라이스 병합 라벨
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
  ALLOCATION: "배분",
  SENTIMENT: "심리",
  ACTUAL: "실제",
  INVEST: "투자",
  CASH: "현금",
  TARGET: "권장",
} as const;

/* ── Dashboard Footer ───────────────────────────────────────── */
export const FOOTER = {
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

/* ── Action-First Dashboard ────────────────────────────────── */
export const ACTION = {
  TITLE: "오늘의 액션",
  URGENT: "즉시 실행",
  CHECK: "오늘 확인",
  HOLD: "유지",
  HOLD_SUMMARY: "유지 종목",
  PORTFOLIO: "포트폴리오 리밸런스",
  EMPTY: "오늘 실행할 액션이 없습니다.",
  EVIDENCE: "증거 체인", // #1182: 카드 → /decisions/[id]
  NEW: "NEW", // #1212: 미확인 행 배지 (localStorage seen-state)
  ACK: "확인", // #1212: quick-peek ack 버튼 — NEW 해제, 판정일 갱신 시 재표시
  // #1251: 행 자체가 disclosure 였는데 시맨틱은 테이블 행이라 스크린리더가
  // 컨트롤로 announce 하지 못했다. 실제 버튼의 접근명 — 종목명을 붙여 행마다 구분된다.
  PEEK_EXPAND: "상세 펼치기",
  PEEK_COLLAPSE: "상세 접기",
  // design-review F-001: 숫자 3개(수익률/비중/확신도)가 무라벨이라 추측을 요구했다
  COL_TICKER: "종목",
  COL_ACCOUNT: "계좌",
  COL_ACTION: "액션",
  COL_REASON: "근거",
  COL_PNL: "수익률",
  COL_WEIGHT: "비중",
  COL_CONF: "확신도",
  // #1279: 시세 없는 보유(비상장)의 손익은 측정 불가다. 0.0% 로 렌더하면 "보합" 으로
  // 읽힌다 — 지어낸 숫자를 사용자 카피로 내보내지 않는다 (STRATEGY §2.6 과 같은 원칙).
  PNL_UNKNOWN: "미상",
  // #1252: quick-peek 라벨. 계좌는 COL_ACCOUNT 를 재사용한다 — 같은 뜻에 키를 둘 두지 않는다.
  PEEK_CURRENT: "현재가",
  PEEK_STOP: "손절",
  PEEK_TP1: "1차익절",
  PEEK_TP2: "2차익절",
  PEEK_AS_OF: "판정",
  // DETAIL/CONF/AGREE/PNL/WEIGHT/DISMISS 는 U2b-2 (#1208) 카드→행 전환으로 제거
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
  // #1252: "전체 {n}건 →" — 숫자를 사이에 끼우므로 접두/접미로 나눈다
  // (`PIPELINE.RUNNING_SUFFIX` 와 같은 관례).
  ALL_PREFIX: "전체",
  ALL_SUFFIX: "건 →",
  // #1652: 카드 → 32px 행 + quick-peek. 열 머리글과 펼침 접근명.
  COL_TICKER: "종목",
  COL_PRICE: "가격",
  COL_SIGNAL: "시그널",
  COL_METRICS: "지표",
  PEEK_EXPAND: "상세 펼치기",
  PEEK_COLLAPSE: "상세 접기",
  AGREEMENT_SUFFIX: "% 합의",
  ANALYZING: "분석 중...",
} as const;

export const CONTEXT = {
  TITLE: "시장 컨텍스트",
  SYSTEM_HEALTH: "시스템 건강",
  RAIL_TITLE: "시스템 상태",
  REGIME: "레짐",
  MACRO: "매크로",
  FRESHNESS: "데이터",
  // #1212: FAIL 행의 다음 행동 카피 (레일 sub — 상태만 말하지 말 것)
  CHECK_PIPELINE: "파이프라인 확인 →",
  // #1252: 레짐 전환 배너 카피
  REGIME_SHIFT: "Regime 전환 신호",
  REGIME_SHIFT_NOW: "현재",
  REGIME_SHIFT_CONF: "신뢰도",
  REGIME_SHIFT_ADVICE: "% — 다음 행동 보류 권고",
  ATTENTION: "ATTENTION",
  FAIL_SUFFIX: "건 실패",
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
  ROUTE_DASHBOARD: "Dashboard",
  ROUTE_DASHBOARD_NEXT: "Overview Preview",
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


/* ── 백엔드 분류 → 한국어 라벨 (대시보드 · Overview Preview 공용) ──────────── */
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

/* ── Overview Preview (/dashboard-next, #1658) ──────────────────────────────── */
// 화면의 모든 사용자 노출 문구. 컴포넌트와 테스트는 여기서 읽는다 (#1252 — 리터럴은 e2e 무신호 회귀의 경로).
export const DASHBOARD_NEXT = {
  TITLE: "Overview",
  SUBTITLE: "시장과 포트폴리오의 현재 상태",
  PREVIEW_TAG: "PREVIEW",
  COMPARE: "기존 대시보드와 비교",
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
    GUIDE_CAVEAT: "시스템 신뢰도는 수익 확률이 아닙니다. 목록 생성 시각과 판정 기준일도 다릅니다. 오래된 입력이나 연결된 원장이 없는 항목은 근거를 추가 확인하세요.",
    LEDGER: "판정 원장",
    FILTER_ARIA: "판단 목록 필터",
    BUCKETS: { urgent: "우선 확인", check: "검토", portfolio: "포트폴리오 규칙", hold: "유지" },
    BUCKET_EMPTY: (bucket: string) => `${bucket} 목록에 현재 표시할 항목이 없습니다.`,
    QUEUE_ARIA: (bucket: string) => `${bucket} 종목 선택`,
    EVIDENCE_ARIA: "선택한 판단 근거",
    TICKER_DETAIL: "종목 상세",
    AS_OF: "판정 기준일 · ",
    NO_REASONS: "판단 근거 미제공",
    POSITION: "보유 비중",
    PNL: "평가 손익률",
    CONFIDENCE: "시스템 신뢰도",
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
    PROS: "긍정 근거",
    CONS: "유의점",
    NO_PROS: "제공된 근거 없음",
    NO_CONS: "제공된 유의점 없음",
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
    COMPARE_GUIDE: "화면 비교 안내",
    COMPARE_TITLE: "기존 화면과 비교",
    COMPARE_INTRO: "동일한 백엔드를 사용하는 별도 화면입니다. 조회 시점에 따라 값이 다를 수 있습니다.",
    COMPARE_POINTS: [
      "시장 요약·판단·자산 배분·수집 상태를 한 화면에서 확인합니다.",
      "판단을 선택하면 근거와 보유 영향이 옆에 표시됩니다.",
      "추가 근거와 전체 소스는 팝업 또는 상세 화면에서 확인합니다.",
    ],
    OPEN_LEGACY: "기존 화면을 새 탭에서 열기",
  },
  DIALOG: { CLOSE: "닫기", ESC: "ESC" },
  TIME_UNKNOWN: "기준 시각 미제공",
} as const;
