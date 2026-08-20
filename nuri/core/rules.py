"""투자 규칙 로더 — config/rules.yaml에서 규칙을 로드.

사용법:
    from nuri.core.rules import RULES
    max_pos = RULES["position_limits"]["max_single_position"]
"""

from pathlib import Path

import yaml

_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "rules.yaml"


def _load_rules() -> dict:
    if _RULES_PATH.exists():
        with open(_RULES_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    # 폴백 (파일 없을 때)
    return {
        "position_limits": {"max_single_position": 0.15, "max_sector_exposure": 0.35},
        "stop_loss": {"per_stock": -20, "portfolio": -10},
        "leverage": {"banned_etfs": ["TSLL", "TQQQ", "SQQQ", "UPRO", "SPXU"]},
    }


RULES = _load_rules()

# ─── 포지션 한도 ───
MAX_SINGLE_POSITION = RULES["position_limits"]["max_single_position"]
MAX_SECTOR_EXPOSURE = RULES["position_limits"]["max_sector_exposure"]
MIN_CASH_RESERVE = RULES.get("position_limits", {}).get("min_cash_reserve", 0.20)

# ─── 손절 ───
STOCK_STOP_LOSS = RULES["stop_loss"]["per_stock"]
# ─── Brief 표시 임계 (#571) — 매매 룰 아님, 카드 심각도 표기용 ───
_brief = RULES.get("brief", {})
BRIEF_SEVERITY_GAP_PCT = _brief.get("severity_gap_pct", -10)
BRIEF_BENCHMARK = _brief.get("benchmark", {"us": "SPY", "kr": "069500.KS"})
BRIEF_EARNINGS_WINDOW_DAYS = _brief.get("earnings_window_days", 14)
BRIEF_TRAILING_MIN_PEAK_GAIN_PCT = _brief.get("trailing_min_peak_gain_pct", 10)
STOCK_STOP_LOSS_VALUE = RULES.get("stop_loss", {}).get("per_stock_value", -10)
PORTFOLIO_STOP = RULES["stop_loss"]["portfolio"]

# ─── 익절 ───
_tp = RULES.get("take_profit", {})
TAKE_PROFIT_GROWTH = _tp.get("growth", {"target_1": 20, "target_2": 40})
TAKE_PROFIT_VALUE = _tp.get("value", {"target_1": 15, "target_2": 30})
TAKE_PROFIT_SWING = _tp.get("swing", {"target_1": 5, "target_2": 10})
SWING_STOP_LOSS = TAKE_PROFIT_SWING.get("stop_loss", -5)
SWING_MAX_HOLD_DAYS = TAKE_PROFIT_SWING.get("max_hold_days", 7)
SWING_MIN_SCAN_SCORE = TAKE_PROFIT_SWING.get("min_scan_score", 20)
SWING_MIN_AGENT_CONFIDENCE = TAKE_PROFIT_SWING.get("min_agent_confidence", 50)
# Leader exception (8주 룰 운영화): 성장주는 고정 익절 대신 trail_ma 이동평균 이탈로 청산
# (승자 run). value/swing 은 위 ladder 유지. config/rules.yaml take_profit.leader.
TAKE_PROFIT_LEADER = _tp.get("leader", {"enabled": False, "trail_ma": 50})

# ─── ARK 매매 파생 (#1143) ───
# 보유 스냅샷 → Buy/Sell 파생 임계. smart_money 의 ARK 항목 발화 여부를 결정한다.
ARK_MIN_TRADE_PCT = RULES.get("ark", {}).get("min_trade_pct", 1.0)
# 펀드별 CSV 발행 지연 허용치 — 200 인 채로 내용만 어는 소스를 잡는다 (#1145).
ARK_MAX_SOURCE_LAG_DAYS = RULES.get("ark", {}).get("max_source_lag_days", 7)

# ─── 트레일링 스톱 ───
_ts = RULES.get("trailing_stop", {})
TRAILING_STOP_GROWTH = _ts.get("growth", -15)
TRAILING_STOP_VALUE = _ts.get("value", -15)
TRAILING_STOP_VOLATILE = _ts.get("volatile", -20)

# ─── DecisionCompiler 의사결정 임계값 (#529, carry-over audit N1) ───
# emit/HOLD 를 가르는 게이트라 투자 룰이다 — 코드 하드코딩 금지 조항 대상.
_dc = RULES.get("decision_compiler", {})
CONVICTION_EMIT_CUTOFF = _dc.get("conviction_emit_cutoff", 0.70)
CONVICTION_HOLD_CUTOFF = _dc.get("conviction_hold_cutoff", 0.50)
REGIME_FAVOR_PROB = _dc.get("regime_favor_prob", 0.60)

# ─── Forward outcome tracking 임계값 (#529, carry-over audit N2) ───
# PyYAML 은 bare `7:` 를 int 로 파싱하지만 `"7":` 로 인용하면 str 이 된다. 키 타입이
# 갈리면 `WINDOW_THRESHOLDS[window]`(window 는 int)가 KeyError 를 내고 actor 가 죽는다.
# 정규화는 여기 한 곳에 둔다 — 소비자마다 방어하게 만들지 않는다.
# 값도 list → tuple 로 굳힌다. 어노테이션이 tuple 이고, 원소 단위 변형을 막는다.
_ot = RULES.get("outcome_tracking", {})
OUTCOME_WINDOW_THRESHOLDS: dict[int, tuple[float, float]] = {
    int(w): (float(p[0]), float(p[1]))
    for w, p in (_ot.get("window_thresholds") or {7: [0.05, -0.05], 14: [0.07, -0.07], 30: [0.10, -0.10]}).items()
}

# ─── 매수 진입 조건 ───
_entry = RULES.get("entry_rules", {})
VIX_BLOCK_ABOVE = _entry.get("vix_gate", {}).get("block_above", 30)
VIX_CAUTION_ABOVE = _entry.get("vix_gate", {}).get("caution_above", 25)
# 이보다 오래된 VIX 는 '미상'으로 본다 — 미상은 caution 과 동일 취급(절반 포지션).
# **영업일** 기준 (휴장일 오탐 방지 — `nuri/trading/recommend/vix_gate.py` 참조).
VIX_MAX_AGE_BUSINESS_DAYS = _entry.get("vix_gate", {}).get("max_age_business_days", 2)
REGIME_CASH = _entry.get(
    "regime_cash",
    {
        "extreme_fear": 0.60,
        "fear": 0.40,
        "neutral": 0.25,
        "greed": 0.20,
        "extreme_greed": 0.40,
    },
)
MAX_TRANCHES = _entry.get("scaling_in", {}).get("max_tranches", 3)
TRANCHE_INTERVAL_DAYS = _entry.get("scaling_in", {}).get("tranche_interval_days", 5)

# ─── 매크로 종합 점수 ───
MACRO_MIN_COVERAGE = RULES.get("macro", {}).get("min_coverage", 0.6)

# ─── 멀티팩터 합성 ───
FACTOR_RULES = RULES.get("factors", {})

# ─── 매수 체크리스트 ───
_chk = RULES.get("buy_checklist", {})
MIN_TIPRANKS_CONSENSUS = _chk.get("min_tipranks_consensus", "moderate_buy")
MIN_SUPERINVESTORS = _chk.get("min_superinvestors", 3)
MAX_PE_RATIO = _chk.get("max_pe_ratio", 100)
MIN_REVENUE_GROWTH = _chk.get("min_revenue_growth", 0)
REQUIRE_FACTOR_TOP50 = _chk.get("require_factor_top50pct", True)

# ─── 매도 우선순위 ───
SELL_PRIORITY = RULES.get(
    "sell_priority",
    [
        "leverage_etf",
        "stop_loss_exceeded",
        "no_superinvestor",
        "position_limit_exceeded",
        "sector_limit_exceeded",
    ],
)

# ─── 레버리지 제한 ───
LEVERAGE_ETFS = set(RULES["leverage"]["banned_etfs"])
LEVERAGE_MAX_DAYS = RULES.get("leverage", {}).get("max_holding_days", 5)

# ─── 계좌별 전략 프로파일 ───
ACCOUNT_STRATEGIES = RULES.get(
    "account_strategies",
    {
        "core": {"stop_loss": -7, "max_single_position": 0.15, "max_sector_exposure": 0.35},
    },
)
_DEFAULT_STRATEGY = ACCOUNT_STRATEGIES.get(
    "core", {"stop_loss": -7, "max_single_position": 0.15, "max_sector_exposure": 0.35}
)


PORTFOLIO_PATH = Path(__file__).parent.parent.parent / "config" / "portfolio.yaml"


def _resolve_account_key(accounts: dict, account: str | None) -> str | None:
    """계좌 **id · label · name** 중 무엇이 와도 yaml 의 계좌 키로 정규화한다 (#994).

    yaml 은 id 로 키잉하는데(`toss`), DB/API 는 label 을 들고 다닌다(`Toss`). 매칭
    실패가 예외가 아니라 조용한 폴백(`core`, stop_loss -7)이라 **전 계좌가 -7 로
    평가**됐고, `actions.py` 의 "하드코딩 -7 제거" 주석과 정반대로 동작했다.
    2026-08-03 실측: Toss(long_term, -20) 보유가 -19.6% 에서 urgent SELL 로 떴다.
    """
    if not account:
        return None
    if account in accounts:
        return account
    needle = str(account).strip().casefold()
    for key, info in accounts.items():
        if not isinstance(info, dict):
            continue
        for cand in (key, info.get("label"), info.get("name")):
            if cand and str(cand).strip().casefold() == needle:
                return key
    return None


def _load_accounts() -> dict:
    import yaml

    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("accounts", {}) or {}
    except Exception:
        return {}


def get_account_strategy(account: str) -> dict:
    """계좌명 → 전략 프로파일 반환. portfolio.yaml의 strategy 필드 기준.

    id 뿐 아니라 label / name 으로도 조회된다 (#994).
    """
    accounts = _load_accounts()
    key = _resolve_account_key(accounts, account)
    if key is None:
        return _DEFAULT_STRATEGY
    strategy_name = (accounts.get(key) or {}).get("strategy") or "core"
    return ACCOUNT_STRATEGIES.get(strategy_name, _DEFAULT_STRATEGY)


def get_account_strategy_name(account: str | None) -> str:
    """계좌명 → 전략 이름 반환 ('core'|'swing'|'pension'|...). 매칭 실패 → 'core'.

    `get_account_strategy()` 는 rules dict(stop_loss/max_position/...)만 반환해
    이름이 소실된다 — pension 판별(daily action 제외)엔 이름이 authoritative 하므로
    yaml 의 strategy 필드를 직접 노출.

    `get_account_strategy()` 와 동일하게 id / label / name 을 모두 받는다 (#994).
    label 로 조회하면 'core' 가 나오던 탓에, 연금 제외가 label 경로에서 무력했다.
    """
    if not account:
        return "core"
    accounts = _load_accounts()
    key = _resolve_account_key(accounts, account)
    if key is None:
        return "core"
    return (accounts.get(key) or {}).get("strategy") or "core"


_REAL_ACCOUNT_KEYS = ("broker", "name", "label", "strategy", "balance")


def is_real_account(info: dict | None) -> bool:
    """계좌 블록 하나가 실계좌인지 — **이미 파싱된 dict 로** 판정한다.

    `get_real_accounts()` 와 달리 파일을 다시 읽지 않는다. 다른 yaml 을 로드한
    호출자(`import_portfolio.load_holdings_by_account(config_path=...)`)가 기본 경로를
    재독해 **엉뚱한 파일 기준으로 판정하는 사고**를 막는다.
    """
    return any((info or {}).get(k) for k in _REAL_ACCOUNT_KEYS)


def get_real_accounts() -> set[str]:
    """실제 증권계좌만 — `portfolio.yaml` 의 픽스처/stub 계좌를 배제한다.

    판별은 **계좌를 설명하는 메타데이터**(`broker`/`name`/`label`/`strategy`/`balance`)
    선언 여부다. 픽스처(`test`/`sample`/`main`)는 `currency` + `holdings` 뿐이다.

    이전 기준은 여기에 **`holdings` 가 포함돼 있었고, 그래서 픽스처도 전부 통과했다** —
    "test/sample stub 차단" 이라 적힌 방어선이 실제로는 열려 있었다 (#527 의도 무산).
    2026-07-29 실측: 8개 계좌 전부가 real 로 판정됐고, import 가 픽스처 9행을
    프로덕션에 넣었다.

    ⚠️ 기준을 더 좁히지 말 것 (예: `broker` 만). `strategy` 만 선언한 실계좌를 조용히
    누락시키면 **보유가 통째로 사라진다** — 픽스처가 섞이는 것보다 나쁜 실패다.
    지운 건 `holdings` 하나뿐이고, 그 하나가 구멍이었다.

    호출자는 DB row 를 이 집합으로 걸러 stale 픽스처 행이 집계를 오염시키지 않게 한다.
    """
    import yaml

    _portfolio_path = Path(__file__).parent.parent.parent / "config" / "portfolio.yaml"
    try:
        with open(_portfolio_path, encoding="utf-8") as f:
            portfolio = yaml.safe_load(f) or {}
    except Exception:
        return set()
    return {acc for acc, info in (portfolio.get("accounts") or {}).items() if is_real_account(info)}


def get_stop_loss_for_account(account: str | None) -> int:
    """계좌명 → stop_loss threshold (정수 %). 계좌 미지정/매칭 실패 → global fallback.

    A-3 unified sell engine (§2.2 mechanical execution). `certification.py` 가 이미
    per-row 로 `get_account_strategy(account)["stop_loss"]` 를 쓰는 패턴을 그대로
    노출 — risk_agent/actions.py 도 동일하게 rows 의 `account` 기준으로 threshold
    조회해야 PnL 이 그 row 의 cost basis 에서 계산된 것과 일치 (mismatch 방지).
    """
    if not account:
        return int(STOCK_STOP_LOSS)
    strategy = get_account_strategy(account)
    return int(strategy.get("stop_loss", STOCK_STOP_LOSS))
