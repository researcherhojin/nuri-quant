"""
Wall Street 에이전트 — 애널리스트 등급 변경 + Earnings Surprise + Insider 매매 기반 판정.

yfinance에서 직접 데이터를 가져오며 별도 API 키 불필요.

분석 항목:
1. 최근 90일 Upgrade/Downgrade 추세
2. 최근 Earnings Surprise (실적 vs 예상)
3. Insider 매매 패턴 (순매수 vs 순매도)
4. 애널리스트 컨센서스 분포 (strongBuy~strongSell)
"""
import logging
from datetime import timedelta

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.timezone import kst_now
from nuri.trading.agents.base import AgentVerdict, BaseAgent

logger = logging.getLogger(__name__)

_CFG = AGENT_CONFIG.get("wallstreet", {})
_CONF = _CFG.get("confidence", {})


# yfinance에서 데이터가 없는 종목 (ETF, 한국주, 레버리지) — 스킵하여 속도 개선
SKIP_TICKERS = {
    "VOO", "SH", "SDS", "PSQ", "IWM", "EFA", "EEM", "ARKK",  # ETFs
    "TSLL", "TQQQ", "SQQQ", "UPRO", "SPXU", "BULL",           # Leveraged
    "SPY", "QQQ",                                                # Index ETFs
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",  # Sector ETFs
}


class WallStreetAgent(BaseAgent):
    def __init__(self):
        super().__init__("wallstreet")

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        # ETF, 한국주, 레버리지 종목은 yfinance Wall Street 데이터 없음 → 즉시 스킵
        if ticker in SKIP_TICKERS or ticker.endswith(".KS"):
            return AgentVerdict(self.name, ticker, "HOLD", 20, "Wall Street 데이터 미지원 종목")

        # DB에 캐시된 데이터 먼저 확인 (yfinance 호출 최소화)
        cached = self._check_cached(ticker, db_path)
        if cached:
            return cached

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
        except Exception:
            return AgentVerdict(self.name, ticker, "HOLD", 0, "yfinance 로드 실패")

        score = 0
        reasons = []
        data_points = {}

        # ── 1. Upgrades/Downgrades (최근 90일) ──
        try:
            ud = t.upgrades_downgrades
            if ud is not None and not ud.empty:
                cutoff = kst_now().replace(tzinfo=None) - timedelta(days=90)
                recent = ud[ud.index >= cutoff] if hasattr(ud.index[0], 'year') else ud.tail(10)

                upgrades = 0
                downgrades = 0
                for _, row in recent.iterrows():
                    action = str(row.get("Action", "")).lower()
                    if action in ("up", "upgrade"):
                        upgrades += 1
                    elif action in ("down", "downgrade"):
                        downgrades += 1
                    # init(신규), reit(재확인), main(유지) 등은 target price 변화로 판단
                    target_action = str(row.get("priceTargetAction", "")).lower()
                    if target_action == "raises":
                        upgrades += 1
                    elif target_action == "lowers":
                        downgrades += 1

                up_margin = _CFG.get("upgrade_margin", 2)
                if upgrades > downgrades + up_margin:
                    score += 2
                    reasons.append(f"최근 업그레이드 우세({upgrades}↑ vs {downgrades}↓)")
                elif downgrades > upgrades + up_margin:
                    score -= 2
                    reasons.append(f"최근 다운그레이드 우세({downgrades}↓ vs {upgrades}↑)")
                elif upgrades > 0 or downgrades > 0:
                    reasons.append(f"등급변경 혼조({upgrades}↑/{downgrades}↓)")

                data_points["upgrades_90d"] = upgrades
                data_points["downgrades_90d"] = downgrades

                # 최근 목표가
                targets = recent[recent["currentPriceTarget"].notna()]["currentPriceTarget"]
                if not targets.empty:
                    avg_target = float(targets.mean())
                    data_points["avg_target"] = round(avg_target, 2)
        except Exception:
            pass

        # ── 2. Earnings Surprise ──
        try:
            eh = t.earnings_history
            if eh is not None and not eh.empty:
                latest = eh.iloc[-1]
                surprise = latest.get("surprisePercent", 0) or 0

                earn_th = _CFG.get("earnings_surprise", 0.05)
                if surprise > earn_th:
                    score += 2
                    reasons.append(f"실적 서프라이즈 +{surprise*100:.0f}%")
                elif surprise < -earn_th:
                    score -= 2
                    reasons.append(f"실적 미스 {surprise*100:.0f}%")
                elif abs(surprise) <= earn_th:
                    reasons.append(f"실적 부합 ({surprise*100:+.1f}%)")

                data_points["earnings_surprise"] = round(float(surprise), 4)
                data_points["eps_actual"] = float(latest.get("epsActual", 0) or 0)
                data_points["eps_estimate"] = float(latest.get("epsEstimate", 0) or 0)
        except Exception:
            pass

        # ── 3. Insider 매매 ──
        try:
            ins = t.insider_transactions
            if ins is not None and not ins.empty:
                # 최근 10건
                recent_ins = ins.head(10)
                buys = 0
                sells = 0
                for _, row in recent_ins.iterrows():
                    text = str(row.get("Text", "")).lower()
                    if "purchase" in text or "buy" in text:
                        buys += 1
                    elif "sale" in text or "sell" in text:
                        sells += 1

                if buys > sells + _CFG.get("insider_buy_margin", 1):
                    score += 1
                    reasons.append(f"내부자 순매수({buys}B/{sells}S)")
                elif sells > buys + _CFG.get("insider_sell_margin", 3):
                    score -= 1
                    reasons.append(f"내부자 순매도({sells}S/{buys}B)")

                data_points["insider_buys"] = buys
                data_points["insider_sells"] = sells
        except Exception:
            pass

        # ── 4. 애널리스트 컨센서스 분포 ──
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty:
                latest = rec.iloc[0]
                strong_buy = int(latest.get("strongBuy", 0))
                buy = int(latest.get("buy", 0))
                hold = int(latest.get("hold", 0))
                sell = int(latest.get("sell", 0))
                strong_sell = int(latest.get("strongSell", 0))

                total = strong_buy + buy + hold + sell + strong_sell
                if total > 0:
                    bull_pct = (strong_buy + buy) / total
                    bear_pct = (sell + strong_sell) / total

                    if bull_pct > _CFG.get("consensus_bull", 0.60):
                        score += 1
                        reasons.append(f"컨센서스 매수 {bull_pct:.0%}({strong_buy+buy}/{total}명)")
                    elif bear_pct > _CFG.get("consensus_bear", 0.30):
                        score -= 1
                        reasons.append(f"컨센서스 매도 {bear_pct:.0%}({sell+strong_sell}/{total}명)")
                    else:
                        reasons.append(f"컨센서스 중립({strong_buy+buy}B/{hold}H/{sell+strong_sell}S)")

                    data_points["consensus"] = {
                        "strong_buy": strong_buy, "buy": buy, "hold": hold,
                        "sell": sell, "strong_sell": strong_sell,
                    }
        except Exception:
            pass

        if not reasons:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 20), "Wall Street 데이터 부족")

        # 판정
        if score >= _CFG.get("score_buy", 3):
            action, confidence = "BUY", min(
                _CONF.get("buy_cap", 85),
                _CONF.get("buy_base", 45) + score * _CONF.get("buy_multiplier", 10),
            )
        elif score <= _CFG.get("score_sell", -2):
            action, confidence = "SELL", min(
                _CONF.get("sell_cap", 80),
                _CONF.get("sell_base", 45) + abs(score) * _CONF.get("sell_multiplier", 10),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 35) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name, ticker, action, round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            data_points,
        )

    def _check_cached(self, ticker: str, db_path=None) -> AgentVerdict | None:
        """DB에 캐시된 Wall Street 데이터로 판정 (yfinance 호출 없이)."""
        ratings = self._safe_query(
            "SELECT action, target_price FROM analyst_ratings WHERE ticker=? ORDER BY date DESC LIMIT 10",
            (ticker,), db_path,
        )
        earnings = self._safe_query(
            "SELECT surprise_pct FROM earnings_surprises WHERE ticker=? ORDER BY quarter DESC LIMIT 1",
            (ticker,), db_path,
        )
        insiders = self._safe_query(
            "SELECT transaction_type FROM insider_trades WHERE ticker=? ORDER BY date DESC LIMIT 10",
            (ticker,), db_path,
        )

        if not ratings and not earnings and not insiders:
            return None  # 캐시 없음 → yfinance 호출 필요

        score = 0
        reasons = []

        earn_th = _CFG.get("earnings_surprise", 0.05)
        ins_sell_margin = _CFG.get("insider_sell_margin", 3)

        if ratings:
            ups = sum(1 for r in ratings if r.get("action") in ("up", "upgrade") or "raise" in str(r.get("action", "")).lower())
            downs = sum(1 for r in ratings if r.get("action") in ("down", "downgrade") or "lower" in str(r.get("action", "")).lower())
            if ups > downs + 1:
                score += 1
                reasons.append(f"등급↑({ups}↑/{downs}↓, cached)")
            elif downs > ups + 1:
                score -= 1
                reasons.append(f"등급↓({downs}↓/{ups}↑, cached)")

        if earnings:
            sp = earnings[0].get("surprise_pct")
            if sp and sp > earn_th:
                score += 1
                reasons.append(f"실적+{sp*100:.0f}%(cached)")
            elif sp and sp < -earn_th:
                score -= 1
                reasons.append(f"실적{sp*100:.0f}%(cached)")

        if insiders:
            sells = sum(1 for i in insiders if i.get("transaction_type") == "sale")
            buys = len(insiders) - sells
            if sells > buys + ins_sell_margin:
                score -= 1
                reasons.append(f"내부자매도({sells}S, cached)")

        if not reasons:
            return None

        if score >= 2:
            action, conf = "BUY", _CONF.get("cached_buy", 60)
        elif score <= -1:
            action, conf = "SELL", _CONF.get("cached_sell", 55)
        else:
            action, conf = "HOLD", _CONF.get("cached_hold", 40)

        return AgentVerdict(self.name, ticker, action, round(self.normalize_confidence(conf), 1),
                           "; ".join(reasons), {"cached": True})
