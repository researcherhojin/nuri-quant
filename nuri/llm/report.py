"""
Ollama 기반 LLM 리포트 생성기 — SIEGE Certification 패턴 적용.

1. Gate 검증 → 데이터 완성도 확인
2. 전체 데이터 소스 수집 → 구조화된 컨텍스트
3. LLM 생성 → 자연어 리포트
4. Output Validation → 환각 검증 (입력에 없는 숫자/티커 감지)
5. 면책 조항 + 데이터 완성도 경고 자동 첨부

사용법:
    python -m nuri.llm.report
"""
import logging
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5")
# llama.cpp GGUF 모델 경로 (설정 시 Ollama 대신 직접 실행)
LLAMA_MODEL_PATH = os.getenv("LLAMA_MODEL_PATH", "")

DISCLAIMER = (
    "⚠️ 본 리포트는 Nuri-Quant 시스템이 수집한 데이터와 AI(LLM)가 생성한 분석입니다. "
    "투자 조언이 아니며, 모든 투자 결정과 그에 따른 책임은 투자자 본인에게 있습니다. "
    "과거 성과는 미래 수익을 보장하지 않습니다."
)

SYSTEM_PROMPT = """당신은 Nuri-Quant 투자 분석 리포트 작성 전문가입니다.
한국어로 작성하세요. /no_think

규칙:
1. [DATA]에 있는 수치만 사용. 없는 숫자 생성 금지.
2. "~할 것으로 보입니다" 같은 예측 표현 금지. 사실 기반만.
3. drift: critical/degrading 시그널은 ⚠️ 경고.
4. 충돌(conflict) 종목은 "관망 권장".

리포트 구조 (이 구조를 정확히 따르세요):

## 1. 데이터 완성도
Gate 상태 1~2문장.

## 2. 시장 환경
레짐 + VIX + Fear&Greed + 매크로 스코어. 2~3문장.

## 3. 리스크 현황
Sharpe, VaR, MDD, 손절 경고. 2~3문장.

## 4. 시그널 신뢰도
drift 상태별 시그널 정리. 최근 부진한 시그널 경고.

## 5. 매매 후보
상위 3~5건. 충돌 종목 표시. 외부 데이터(TipRanks/Dataroma) 반영.

## 6. 리밸런스 필요 사항
규칙 위반 종목 + 매도 수량 + 회수 금액.

## 7. 전략 요약
포지션 사이징, 추천/회피 시그널, 방어 섹터.

## 8. 주의사항
충돌, drift, 데이터 부족 경고."""


@dataclass
class ReportContext:
    """LLM에 전달하는 구조화된 컨텍스트."""
    gate_summary: str
    gate_score: float           # 0~1
    regime_section: str
    macro_section: str
    risk_section: str
    candidates_section: str
    conflicts_section: str
    drift_section: str
    consensus_section: str
    strategy_section: str
    external_section: str = ""  # 외부 데이터 요약
    rebalance_section: str = "" # 리밸런스 어드바이저 요약
    known_tickers: set[str] = None
    known_numbers: set[str] = None

    def __post_init__(self):
        if self.known_tickers is None:
            self.known_tickers = set()
        if self.known_numbers is None:
            self.known_numbers = set()


def gather_context(db_path=None) -> ReportContext:
    """모든 데이터 소스를 수집하여 구조화된 컨텍스트 생성."""
    known_tickers = set()
    known_numbers = set()

    def _track(text: str) -> str:
        """텍스트에서 티커와 숫자를 추출하여 검증용 세트에 추가."""
        # 숫자 추출 (소수점 포함)
        for m in re.findall(r'\d+\.?\d*', text):
            known_numbers.add(m)
        return text

    # ── 1. Gate ──
    gate_summary = "Gate 정보 없음"
    gate_score = 0.0
    try:
        from nuri.trading.engine.gate import check_all_gates
        gates = check_all_gates(db_path)
        lines = []
        total_pass = total_all = 0
        for phase, result in gates.items():
            status = "READY" if result.ready else "BLOCKED"
            lines.append(f"  {phase}: {status} ({result.passed}/{result.total})")
            total_pass += result.passed
            total_all += result.total
            for c in result.conditions:
                if not c.passed:
                    lines.append(f"    - FAIL: {c.description} → {c.detail}")
        gate_score = total_pass / total_all if total_all > 0 else 0
        gate_summary = _track(f"데이터 완성도: {total_pass}/{total_all} ({gate_score:.0%})\n" + "\n".join(lines))
    except Exception as e:
        gate_summary = f"Gate 검증 실패: {e}"

    # ── 2. Regime ──
    regime_section = "레짐 데이터 없음"
    try:
        from nuri.quant.regime.classifier import classify_regime
        regime = classify_regime(db_path=db_path)
        if regime:
            d = regime.details
            th = d.get("thresholds", {})
            regime_section = _track(
                f"레짐: {regime.regime} (신뢰도 {regime.confidence:.0%})\n"
                f"SPY: ${d['spy_close']:,.2f}, SMA50: ${d['sma50']:,.2f}, SMA200: ${d['sma200']:,.2f}\n"
                f"SMA Gap: {d['sma_diff_pct']:+.1f}%\n"
                f"VIX: {d.get('vix', 'N/A')}, Fear&Greed: {d.get('fear_greed', 'N/A')}, RSI: {d.get('rsi', 'N/A')}\n"
                f"동적 임계값 — VIX th: {th.get('vix_threshold', 'N/A')}, "
                f"Sideways: ±{th.get('sideways_pct', 'N/A')}%, BB Width th: {th.get('bb_width_threshold', 'N/A')}"
            )
    except Exception:
        pass

    # ── 3. Macro ──
    macro_section = "매크로 데이터 없음"
    try:
        from nuri.quant.regime.macro_score import compute_macro_score
        macro = compute_macro_score(db_path=db_path)
        det = macro.details
        macro_section = _track(
            f"매크로 스코어: {macro.total_score:.0f}/100 ({macro.interpretation})\n"
            f"  수익률곡선: {macro.yield_curve_score:.0f} (spread: {det.get('spread', 'N/A')})\n"
            f"  VIX: {macro.vix_score:.0f} ({det.get('vix', 'N/A')})\n"
            f"  심리: {macro.sentiment_score:.0f} (F&G: {det.get('fear_greed', 'N/A')})\n"
            f"  고용: {macro.employment_score:.0f} (실업률: {det.get('unemployment', 'N/A')})\n"
            f"  물가: {macro.inflation_score:.0f} (CPI: {det.get('cpi_yoy', 'N/A')})\n"
            f"  통화: {macro.monetary_score:.0f} (FFR: {det.get('fed_funds', 'N/A')})"
        )
    except Exception:
        pass

    # ── 4. Risk ──
    risk_section = "리스크 데이터 없음"
    try:
        from nuri.analysis.risk import analyze_risk
        metrics = analyze_risk()
        if metrics:
            sharpe = metrics.get("sharpe_ratio", "N/A")
            mdd = metrics.get("max_drawdown_pct", "N/A")
            var95 = metrics.get("var_95_daily_pct", "N/A")
            cvar95 = metrics.get("cvar_95_daily_pct", "N/A")
            risk_section = _track(
                f"Sharpe: {sharpe}, MDD: {mdd}%\n"
                f"VaR(95%): {var95}%, CVaR(95%): {cvar95}%"
            )
            alerts = metrics.get("stop_loss_alerts", [])
            if alerts:
                for a in alerts:
                    known_tickers.add(a["ticker"])
                    risk_section += _track(f"\n  손절선 경고: {a['ticker']} {a['pnl_pct']:+.1f}%")
    except Exception:
        pass

    # ── 5. Candidates (drift + conflict 이미 반영됨) ──
    candidates_section = "매매 후보 없음"
    try:
        from nuri.trading.recommend.candidates import screen_candidates
        candidates = screen_candidates(lookback_days=5, db_path=db_path)
        buys = [c for c in candidates if c.direction == "BUY" and c.regime_fit]
        sells = [c for c in candidates if c.direction == "SELL" and c.regime_fit]
        lines = [f"BUY {len(buys)}건, SELL {len(sells)}건"]
        for c in (buys + sells)[:10]:
            known_tickers.add(c.ticker)
            flags = []
            if c.drift_status in ("critical", "degrading"):
                flags.append(f"drift:{c.drift_status}")
            if c.conflict:
                flags.append("충돌")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  {c.direction} {c.ticker}: {c.signal_id} "
                f"(신뢰도 {c.confidence:.0f}, 승률 {c.win_rate:.0%}, PF {c.profit_factor:.1f}){flag_str}"
            )
        candidates_section = _track("\n".join(lines))
    except Exception:
        pass

    # ── 6. Conflicts ──
    conflicts_section = "충돌 없음"
    try:
        from nuri.trading.engine.conflicts import detect_conflicts
        conflicts = detect_conflicts(db_path=db_path)
        if conflicts:
            lines = [f"시그널 충돌 {len(conflicts)}건:"]
            for cf in conflicts:
                known_tickers.add(cf.ticker)
                lines.append(
                    f"  {cf.ticker}: {cf.conflict_type} ({cf.severity}) "
                    f"— BUY({','.join(cf.buy_signals)}) vs SELL({','.join(cf.sell_signals)})"
                    f"\n    → {cf.recommendation}"
                )
            conflicts_section = _track("\n".join(lines))
    except Exception:
        pass

    # ── 7. Learning Memory Drift ──
    drift_section = "성과 변화 데이터 없음"
    try:
        from nuri.trading.engine.memory import detect_drift
        drifts = detect_drift(db_path=db_path)
        if drifts:
            lines = ["시그널 성과 변화 (전체 기간 vs 최근 90일):"]
            for d in drifts:
                lines.append(
                    f"  {d.signal_id}: {d.status} "
                    f"(전체 {d.all_time_wr:.0%} → 최근 {d.recent_wr:.0%}, {d.drift_pct:+.1f}%)"
                )
            critical = [d for d in drifts if d.status in ("critical", "degrading")]
            if critical:
                lines.append(f"  ⚠ 성과 급락 시그널: {', '.join(d.signal_id for d in critical)}")
            drift_section = _track("\n".join(lines))
    except Exception:
        pass

    # ── 8. Multi-Agent Consensus ──
    consensus_section = "에이전트 합의 데이터 없음"
    try:
        from nuri.trading.agents.consensus import analyze_portfolio as agent_analyze
        results = agent_analyze(db_path=db_path)
        if results:
            lines = [f"멀티 에이전트 합의 ({len(results)}종목):"]
            for r in sorted(results, key=lambda x: x.final_confidence, reverse=True)[:10]:
                known_tickers.add(r.ticker)
                agent_summary = ", ".join(
                    f"{v.agent_name}={v.action}" for v in r.verdicts
                )
                lines.append(
                    f"  {r.ticker}: {r.final_action} (신뢰도 {r.final_confidence:.0f}, "
                    f"동의율 {r.agreement_rate:.0%}) [{agent_summary}]"
                )
                if r.dissent:
                    for d in r.dissent[:1]:
                        lines.append(f"    반대: {d}")
            consensus_section = _track("\n".join(lines))
    except Exception:
        pass

    # ── 9. Strategy ──
    strategy_section = "전략 데이터 없음"
    try:
        from nuri.quant.regime.strategy_map import map_regime_to_strategy
        rec = map_regime_to_strategy(db_path=db_path)
        if rec:
            strategy_section = _track(
                f"포지션: {rec.position_sizing}\n"
                f"추천 시그널: {', '.join(rec.recommended_signals) or '없음'}\n"
                f"회피 시그널: {', '.join(rec.avoid_signals) or '없음'}\n"
                f"선호 섹터: {', '.join(rec.sector_preference)}\n"
                f"근거: {rec.notes}"
            )
    except Exception:
        pass

    # ── 10. 외부 데이터 요약 ──
    external_section = "외부 데이터 없음"
    try:
        from nuri.collectors.external import get_external_summary
        ext_summary = get_external_summary(db_path)
        if ext_summary["total_records"] > 0:
            lines = [f"총 {ext_summary['total_records']}건 ({len(ext_summary['sources'])}개 소스)"]
            for s in ext_summary["sources"]:
                lines.append(f"  {s['source']}: {s['tickers']}종목 {s['records']}건 ({s['latest_date']})")
            external_section = _track("\n".join(lines))
    except Exception:
        pass

    # ── 11. 리밸런스 어드바이저 ──
    rebalance_section = "리밸런스 데이터 없음"
    try:
        from nuri.analysis.rebalance_advisor import generate_advisor_report
        report = generate_advisor_report(db_path)
        if report["total_violations"] > 0:
            lines = [f"위반 {report['total_violations']}건 (critical {report['violations_by_severity'].get('critical', 0)}건)"]
            lines.append(f"총 회수 가능: ${report['total_recovery_usd']:,.0f}")
            for a in report["actions"][:5]:
                lines.append(f"  {a['ticker']}: {a['reason']} (${a['sell_value_usd']:,.0f})")
            rebalance_section = _track("\n".join(lines))
    except Exception:
        pass

    return ReportContext(
        gate_summary=gate_summary,
        gate_score=gate_score,
        regime_section=regime_section,
        macro_section=macro_section,
        risk_section=risk_section,
        candidates_section=candidates_section,
        conflicts_section=conflicts_section,
        drift_section=drift_section,
        consensus_section=consensus_section,
        strategy_section=strategy_section,
        external_section=external_section,
        rebalance_section=rebalance_section,
        known_tickers=known_tickers,
        known_numbers=known_numbers,
    )


def format_prompt(ctx: ReportContext) -> str:
    """컨텍스트를 LLM 프롬프트로 조립."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"[DATA]\n"
        f"## 1. 데이터 완성도\n{ctx.gate_summary}\n\n"
        f"## 2. 시장 레짐\n{ctx.regime_section}\n\n"
        f"## 3. 매크로\n{ctx.macro_section}\n\n"
        f"## 4. 리스크\n{ctx.risk_section}\n\n"
        f"## 5. 시그널 성과 변화 (Learning Memory)\n{ctx.drift_section}\n\n"
        f"## 6. 매매 후보\n{ctx.candidates_section}\n\n"
        f"## 7. 시그널 충돌\n{ctx.conflicts_section}\n\n"
        f"## 8. 멀티 에이전트 합의\n{ctx.consensus_section}\n\n"
        f"## 9. 전략\n{ctx.strategy_section}\n\n"
        f"## 10. 외부 데이터 (TipRanks, Dataroma, ARK 등)\n{ctx.external_section}\n\n"
        f"## 11. 리밸런스 어드바이저\n{ctx.rebalance_section}\n"
        f"[/DATA]\n\n"
        f"위 [DATA]만을 근거로 오늘의 투자 리포트를 작성하세요. "
        f"외부 데이터(섹션 10)와 리밸런스(섹션 11)도 반드시 반영하세요."
    )


# ═══════════════════════════════════════════════════════
# Output Validation (SIEGE Certification 패턴)
# ═══════════════════════════════════════════════════════


@dataclass
class ValidationResult:
    """LLM 출력 검증 결과."""
    passed: bool
    hallucinated_tickers: list[str]  # 입력에 없는 티커 언급
    warnings: list[str]


def validate_output(text: str, ctx: ReportContext) -> ValidationResult:
    """LLM 출력을 입력 데이터 대비 검증.

    검증 항목:
    1. 티커 환각: 입력에 없는 티커 언급
    2. 숫자 환각: "승률 XX%", "PF X.X" 등이 입력 데이터와 불일치
    3. 데이터 완성도 경고
    4. 구조 검증: 7단 섹션 구조 준수 여부
    """
    warnings = []
    hallucinated = []

    # ── 1. 티커 환각 검증 ──
    mentioned_tickers = set(re.findall(r'(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])', text))
    common_words = {
        "BUY", "SELL", "HOLD", "RSI", "MACD", "SMA", "VIX", "ETF",
        "PF", "MDD", "PE", "ROE", "CPI", "GDP", "FOMC", "USD", "KRW",
        "VOL", "OK", "ALL", "TOP", "MAX", "MIN", "AVG", "SPY",
        "THE", "AND", "FOR", "NOT", "ARE", "BUT", "HAS", "WAS",
        "BB", "EMA", "READY", "BLOCKED", "FAIL",
        "DATA", "GATE", "PASS", "WARN", "NOTE", "CVaR", "VaR",
    }
    suspicious = mentioned_tickers - ctx.known_tickers - common_words
    for t in suspicious:
        if len(t) <= 5 and t.isalpha():
            hallucinated.append(t)
    if hallucinated:
        warnings.append(
            f"입력 데이터에 없는 티커 언급: {', '.join(hallucinated)}. "
            f"LLM 환각 가능성."
        )

    # ── 2. 숫자 환각 검증 ──
    # "승률 XX%" 패턴 추출 후 입력 데이터와 비교
    wr_claims = re.findall(r'승률\s*(\d+)%', text)
    pf_claims = re.findall(r'PF\s*(\d+\.?\d*)', text)
    fabricated_numbers = []

    for wr in wr_claims:
        # 입력에 해당 승률이 존재하는지 확인 (±2% 허용)
        wr_val = int(wr)
        found = False
        for known in ctx.known_numbers:
            try:
                # 입력에서 0.XX 형태의 승률을 100배한 값과 비교
                kv = float(known)
                if abs(kv * 100 - wr_val) <= 2 or abs(kv - wr_val) <= 2:
                    found = True
                    break
            except ValueError:
                continue
        if not found and wr_val not in (0, 100):
            fabricated_numbers.append(f"승률 {wr}%")

    for pf in pf_claims:
        pf_val = float(pf)
        found = any(
            abs(float(k) - pf_val) < 0.15
            for k in ctx.known_numbers
            if k.replace(".", "").isdigit()
        )
        if not found and pf_val > 0:
            fabricated_numbers.append(f"PF {pf}")

    if fabricated_numbers:
        warnings.append(
            f"입력 데이터와 불일치하는 수치: {', '.join(fabricated_numbers)}. "
            f"LLM 숫자 환각 의심."
        )

    # ── 3. 데이터 완성도 경고 ──
    if ctx.gate_score < 0.5:
        warnings.append(
            f"데이터 완성도 {ctx.gate_score:.0%}로 낮음. "
            f"리포트 신뢰도 제한적."
        )

    # ── 4. 구조 검증: 7단 섹션 키워드 존재 확인 ──
    required_topics = ["완성도", "시장", "리스크", "시그널", "후보", "전략", "주의"]
    missing_topics = [t for t in required_topics if t not in text]
    if len(missing_topics) >= 4:
        warnings.append(
            f"리포트 구조 불완전: {', '.join(missing_topics)} 섹션 누락."
        )

    passed = len(hallucinated) == 0 and len(fabricated_numbers) == 0 and ctx.gate_score >= 0.3
    return ValidationResult(passed=passed, hallucinated_tickers=hallucinated, warnings=warnings)


# ═══════════════════════════════════════════════════════
# Report Generation
# ═══════════════════════════════════════════════════════


def _generate_llamacpp(prompt: str) -> str:
    """llama.cpp로 직접 생성 (GGUF 모델 필요)."""
    if not LLAMA_MODEL_PATH:
        return ""
    try:
        from llama_cpp import Llama
        llm = Llama(model_path=LLAMA_MODEL_PATH, n_ctx=4096, n_gpu_layers=-1, verbose=False)
        output = llm(prompt, max_tokens=1024, temperature=0.3, stop=["[/DATA]"])
        return output["choices"][0]["text"].strip()
    except ImportError:
        logger.warning("llama-cpp-python 미설치")
        return ""
    except Exception as e:
        logger.warning(f"llama.cpp 실패: {e}")
        return ""


def _generate_ollama(prompt: str) -> str:
    """Ollama HTTP API로 생성. Qwen3.5 thinking 모델 호환."""
    import requests as _requests
    try:
        resp = _requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 2000},
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response", "")

        # Qwen3.5 thinking 모델 처리:
        # 1. response가 있으면 그대로 사용 (thinking 제외)
        # 2. response가 비어있으면 thinking에서 실제 리포트 부분만 추출
        if response.strip():
            # thinking 잔여물 제거: "## 1." 이전 내용 필터링
            for marker in ["## 1.", "# 1. "]:
                idx = response.find(marker)
                if idx > 0:
                    response = response[idx:]
                    break
            # "*   **## " 형식의 thinking indent 제거
            import re
            response = re.sub(r"\s*\*\s*\*\*", "\n", response)
            response = re.sub(r"\*\*\s*$", "", response, flags=re.MULTILINE)
        elif data.get("thinking"):
            thinking = data["thinking"]
            for marker in ["## 1.", "# 1."]:
                idx = thinking.find(marker)
                if idx >= 0:
                    response = thinking[idx:]
                    break
            if not response:
                response = thinking

        return response
    except _requests.ConnectionError:
        return (
            f"[LLM 연결 실패]\n"
            f"방법 1: LLAMA_MODEL_PATH=모델.gguf 설정 (llama.cpp 직접)\n"
            f"방법 2: ollama serve 실행 후 ollama pull {OLLAMA_MODEL}"
        )
    except Exception as e:
        return f"[LLM 오류] {e}"


def generate_llm_report(db_path=None) -> dict:
    """LLM 리포트 생성 (Gate → Context → Generate → Validate).

    Returns:
        dict with keys: report, context, validation, disclaimer, gate_blocked
    """

    ctx = gather_context(db_path)

    # Gate 차단: score < 30%면 리포트 생성 거부
    if ctx.gate_score < 0.3:
        return {
            "report": None,
            "context": ctx.gate_summary,
            "validation": {"passed": False, "warnings": ["데이터 완성도 30% 미만으로 리포트 생성 불가"]},
            "disclaimer": DISCLAIMER,
            "gate_blocked": True,
        }

    prompt = format_prompt(ctx)

    # llama.cpp 우선 → Ollama 폴백
    raw_report = ""
    if LLAMA_MODEL_PATH:
        raw_report = _generate_llamacpp(prompt)

    if not raw_report:
        raw_report = _generate_ollama(prompt)

    # Output Validation
    validation = validate_output(raw_report, ctx)

    # 최종 리포트 조립: 면책 조항 + 검증 결과 + LLM 출력
    final_parts = []

    # 데이터 완성도 경고
    if ctx.gate_score < 0.7:
        final_parts.append(f"📊 데이터 완성도: {ctx.gate_score:.0%} — 일부 지표 미수집")

    # LLM 출력
    final_parts.append(raw_report)

    # 검증 경고
    if validation.warnings:
        final_parts.append("\n---\n⚠️ 검증 경고:")
        for w in validation.warnings:
            final_parts.append(f"  - {w}")

    if validation.hallucinated_tickers:
        final_parts.append(f"  - 환각 의심 티커: {', '.join(validation.hallucinated_tickers)}")

    # 면책 조항 (항상 마지막)
    final_parts.append(f"\n---\n{DISCLAIMER}")

    return {
        "report": "\n".join(final_parts),
        "context": format_prompt(ctx),
        "validation": {
            "passed": validation.passed,
            "hallucinated_tickers": validation.hallucinated_tickers,
            "warnings": validation.warnings,
        },
        "disclaimer": DISCLAIMER,
        "gate_blocked": False,
    }


def generate_llm_report_sync(db_path=None) -> dict:
    """동기 버전 (CLI용). generate_llm_report가 이미 동기이므로 직접 호출."""
    return generate_llm_report(db_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    result = generate_llm_report_sync()

    if result["gate_blocked"]:
        print("❌ Gate 차단: 데이터 부족으로 리포트 생성 불가")
        print(result["context"])
    else:
        print("=== LLM 리포트 ===")
        print(result["report"])

        # 자동 저장
        from datetime import date
        from pathlib import Path
        report_dir = Path("data/reports") / str(date.today())
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / "llm_report.md"
        out_path.write_text(result["report"], encoding="utf-8")
        print(f"\n📄 리포트 저장: {out_path}")

    if result["validation"]["warnings"]:
        print("\n=== 검증 결과 ===")
        for w in result["validation"]["warnings"]:
            print(f"  {w}")
