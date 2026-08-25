"""스마트머니 에이전트 — 슈퍼투자자 + ARK + 애널리스트 컨센서스 기반 판정."""

from datetime import timedelta

from nuri.core.agent_config import AGENT_CONFIG
from nuri.core.timezone import kst_now
from nuri.trading.agents.base import AgentVerdict, BaseAgent

_CFG = AGENT_CONFIG.get("smart_money", {})
_CONF = _CFG.get("confidence", {})
_FRESH = _CFG.get("freshness", {})


def _cutoff(days: int) -> str:
    """max-age 일수 → 'YYYY-MM-DD' 컷오프 (문자열 비교용, DB 날짜 포맷과 동일)."""
    return (kst_now() - timedelta(days=days)).strftime("%Y-%m-%d")


class SmartMoneyAgent(BaseAgent):
    def __init__(self):
        super().__init__("smart_money")

    def _source_is_fresh(self, probe_sql: str, cutoff: str, db_path) -> bool:
        """소스 **전체**의 최신 날짜가 컷오프 안인지 — 티커 행 나이와 구분한다 (#1187 Codex P2).

        티커의 행만 낡은 것은 소스 staleness 가 아니다: 13F 에서 팔린 종목, ARK 가
        보유만 유지한 종목은 소스가 멀쩡해도 그 티커의 매매/보유 행이 늙는다. 그건
        정상 부재라 조용히 제외하고, 소스 자체가 낡았을 때만 "낡음 — 제외" 를 낸다.
        프로브 실패/빈 결과는 미상 = 신선 아님 (ark COUNT(*)=5 원칙과 같은 방향).
        """
        rows = self._safe_query(probe_sql, (), db_path)
        if not rows:
            return False
        latest = list(rows[0].values())[0]
        return bool(latest) and str(latest) >= cutoff

    def analyze(self, ticker: str, db_path=None) -> AgentVerdict:
        score = 0
        reasons = []
        # source 별 신선도 억제 (#1187): 낡은 행은 점수에서 빼되, "소스가 낡아 제외" 는
        # 소스-레벨 프로브가 낡음을 확인했을 때만 명시한다 (Surface rung). 소스가
        # 신선한데 티커 행만 늙었으면 정상 부재로 조용히 제외한다 (Codex P2 ×2).
        # 임계는 config/agents.yaml smart_money.freshness (config-over-code).
        stale_sources: list[str] = []

        pct_high = _CFG.get("portfolio_pct_high", 5)
        upside_th = _CFG.get("upside_threshold", 20)
        downside_th = _CFG.get("downside_threshold", -10)
        si_cutoff = _cutoff(_FRESH.get("superinvestors_max_age_days", 200))
        est_cutoff = _cutoff(_FRESH.get("estimates_max_age_days", 45))
        ark_cutoff = _cutoff(_FRESH.get("ark_max_age_days", 14))

        # 1. 슈퍼투자자 보유 여부
        si_all = self._safe_query(
            "SELECT investor, portfolio_pct, filing_date FROM superinvestors "
            "WHERE ticker = ? AND investor_class = 'conviction' ORDER BY portfolio_pct DESC",
            (ticker,),
            db_path,
        )
        si_rows = [r for r in si_all if (r.get("filing_date") or "") >= si_cutoff]
        if (
            si_all
            and not si_rows
            and not self._source_is_fresh(
                # investor_class 필터는 잠금 테스트 의무이자 의미상 정확 — 이 에이전트의
                # universe 는 conviction 이므로 소스 신선도도 conviction 제출분으로 잰다
                "SELECT MAX(filing_date) FROM superinvestors WHERE investor_class = 'conviction'",
                si_cutoff,
                db_path,
            )
        ):
            latest = max(r.get("filing_date") or "?" for r in si_all)
            stale_sources.append("superinvestors")
            reasons.append(f"슈퍼투자자 13F 낡음(최신 {latest}) — 제외")
        if si_rows:
            investors = [r["investor"] for r in si_rows[:3]]
            max_pct = si_rows[0]["portfolio_pct"]
            score += min(2, len(si_rows))
            reasons.append(f"슈퍼투자자 {len(si_rows)}명 보유 ({', '.join(investors[:2])})")
            if max_pct > pct_high:
                score += 1
                reasons.append(f"최대 비중 {max_pct:.1f}%")

        # 2. 슈퍼투자자 포지션 변화 (NEW/INCREASED) — 같은 13F 컷오프 적용 (#1187):
        # "최근 신규 매수" 가 두 분기 전 제출분이면 최근이 아니다
        change_rows = self._safe_query(
            "SELECT DISTINCT investor FROM superinvestors s1 "
            "WHERE ticker = ? AND investor_class = 'conviction' AND filing_date >= ? AND filing_date = ("
            "  SELECT MAX(filing_date) FROM superinvestors WHERE investor = s1.investor"
            ") AND NOT EXISTS ("
            "  SELECT 1 FROM superinvestors s2 "
            "  WHERE s2.investor = s1.investor AND s2.ticker = s1.ticker "
            "  AND s2.filing_date < s1.filing_date"
            ")",
            (ticker, si_cutoff),
            db_path,
        )
        if change_rows:
            score += 1
            reasons.append(f"최근 신규 매수: {', '.join(r['investor'] for r in change_rows)}")

        # 3. 애널리스트 컨센서스 — 최신 1행이라도 컷오프보다 낡으면 제외 (#1187):
        # LIMIT 1 은 나이를 안 본다. 낡은 목표가/등급이 점수에 들어가면 안 된다.
        est_rows = self._safe_query(
            "SELECT recommendation, target_mean, current_price, num_analysts, date "
            "FROM estimates WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            (ticker,),
            db_path,
        )
        if est_rows and (est_rows[0].get("date") or "") < est_cutoff:
            if not self._source_is_fresh("SELECT MAX(date) FROM estimates", est_cutoff, db_path):
                stale_sources.append("estimates")
                reasons.append(f"애널리스트 컨센서스 낡음(최신 {est_rows[0].get('date') or '?'}) — 제외")
            est_rows = []
        if est_rows:
            est = est_rows[0]
            rec = est.get("recommendation", "")
            target = est.get("target_mean")
            current = est.get("current_price")

            if rec in ("buy", "strong_buy"):
                score += 1
                reasons.append(f"애널리스트: {rec} ({est.get('num_analysts', '?')}명)")
            elif rec in ("sell", "strong_sell"):
                score -= 1
                reasons.append(f"애널리스트: {rec}")

            if target and current and current > 0:
                upside = (target - current) / current * 100
                if upside > upside_th:
                    score += 1
                    reasons.append(f"목표가 괴리 +{upside:.0f}%")
                elif upside < downside_th:
                    score -= 1
                    reasons.append(f"목표가 하회 {upside:.0f}%")

        # 4. ARK 최근 매매
        # `direction` 은 Buy / Sell / Hold 세 값을 갖는다. 예전에는 sells 를
        # `len(rows) - buys` 로 구해서 **Hold 가 전부 매도로 집계**됐다 (#1143). ark
        # 테이블이 한동안 Hold 만 담고 있었으므로 (죽은 CSV 소스 → 보유 스냅샷 폴백)
        # 거기 있는 티커는 예외 없이 score -1 과 "ARK 최근 매도 N건" 이라는 거짓 근거를
        # 받았다. 데이터 결손이 아니라 틀린 신호였다. Buy/Sell 을 각각 세고, 쿼리에서도
        # 걸러 LIMIT 5 창을 Hold 가 잡아먹지 않게 한다.
        # 컷오프 (#1187): ARK "최근 매매" 는 진짜로 최근이어야 한다 — 235일 전 Buy 가
        # "ARK 최근 매수" 로 표면화된 게 이 조항의 기원. 임계는 config/freshness.yaml
        # ark fail(336h=14d) 과 정렬. 창(LIMIT 5) 안에 낡은 행이 섞이지 않게 SQL 에서 거른다.
        ark_all = self._safe_query(
            "SELECT direction, shares, date FROM ark WHERE ticker = ? "
            "AND direction IN ('Buy', 'Sell') ORDER BY date DESC LIMIT 5",
            (ticker,),
            db_path,
        )
        ark_rows = [r for r in ark_all if (r.get("date") or "") >= ark_cutoff]
        if ark_all and not ark_rows:
            # 소스 프로브는 `ark` 테이블이 아니라 `ark_source_dates` 다 (#1147): ark 는
            # 보유 교집합 + Hold 스냅샷이라 "보유만 유지한 종목" 도 매매 행이 늙는다.
            # 수집기가 필터 이전 사실을 기록하는 곳이 소스 신선도의 정본이다.
            if not self._source_is_fresh("SELECT MAX(csv_date) FROM ark_source_dates", ark_cutoff, db_path):
                latest = max(r.get("date") or "?" for r in ark_all)
                stale_sources.append("ark")
                reasons.append(f"ARK 매매 낡음(최신 {latest}) — 제외")
        if ark_rows:
            buys = sum(1 for r in ark_rows if r["direction"] == "Buy")
            sells = sum(1 for r in ark_rows if r["direction"] == "Sell")
            if buys > sells:
                score += 1
                reasons.append(f"ARK 최근 매수 {buys}건")
            elif sells > buys:
                score -= 1
                reasons.append(f"ARK 최근 매도 {sells}건")

        if not reasons:
            return AgentVerdict(self.name, ticker, "HOLD", _CONF.get("no_data", 30), "스마트머니 데이터 없음")

        score_buy = _CFG.get("score_buy", 2)
        score_sell = _CFG.get("score_sell", -1)

        if score >= score_buy:
            action, confidence = (
                "BUY",
                min(
                    _CONF.get("buy_cap", 80),
                    _CONF.get("buy_base", 40) + score * _CONF.get("buy_multiplier", 12),
                ),
            )
        elif score <= score_sell:
            action, confidence = (
                "SELL",
                min(
                    _CONF.get("sell_cap", 70),
                    _CONF.get("sell_base", 40) + abs(score) * _CONF.get("sell_multiplier", 12),
                ),
            )
        else:
            action, confidence = "HOLD", _CONF.get("hold_base", 35) + abs(score) * _CONF.get("hold_multiplier", 8)

        return AgentVerdict(
            self.name,
            ticker,
            action,
            round(self.normalize_confidence(confidence), 1),
            "; ".join(reasons),
            {"score": score, "n_superinvestors": len(si_rows), "stale_sources": stale_sources},
        )
