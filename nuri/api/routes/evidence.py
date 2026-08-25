"""증거 차트 API — Plotly HTML 차트 서빙 + 메타데이터."""

import logging
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from nuri.core.timezone import today_kst

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evidence"])

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"

# 사용 가능한 차트 목록
CHART_TYPES = {
    "regime": "레짐 증거 (SPY + SMA + VIX)",
    "portfolio_heatmap": "포트폴리오 히트맵",
    "signal_performance": "시그널 성과 (승률 + PF + drift)",
    "fear_greed": "공포·탐욕 지수 90일 추이",
    "sell_evidence": "매도 근거 (위반 항목별 심각도)",
}


_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _find_latest_report_dir() -> Path | None:
    """가장 최근 리포트 디렉토리 찾기.

    `data/reports/` 에는 날짜 디렉터리 말고도 `briefs` / `postmarket` /
    `buy_tracking` 이 섞여 있고, 잘못된 날짜로 생성된 **미래 디렉터리**도 남는다
    (실측 2026-08-20: `2026-11-08` · `2027-02-06` · `2027-09-14`). 이름을 그냥
    역순 정렬하면 그런 것들이 1등을 먹어서, 오늘 `make evidence` 를 돌려도
    화면에는 2027-09-14 자 차트가 뜬다. 이름이 ISO 날짜이고 **오늘 이하**인
    것만 후보로 본다.
    """
    if not REPORT_DIR.exists():
        return None
    today = today_kst()
    dated = [d for d in REPORT_DIR.iterdir() if d.is_dir() and _DATE_DIR_RE.match(d.name) and d.name <= today]
    for d in sorted(dated, key=lambda p: p.name, reverse=True):
        if (d / "evidence").exists():
            return d / "evidence"
    return None


@router.get("/evidence")
def list_evidence():
    """사용 가능한 증거 차트 목록."""
    evidence_dir = _find_latest_report_dir()
    if not evidence_dir:
        return {"charts": [], "message": "증거 차트 없음. make evidence 실행 필요"}

    available = []
    for chart_id, description in CHART_TYPES.items():
        candidates = [
            evidence_dir / f"{chart_id}.html",
            evidence_dir / f"{chart_id}_evidence.html",
        ]
        exists = any(p.exists() for p in candidates)
        available.append(
            {
                "id": chart_id,
                "description": description,
                "available": exists,
                "date": evidence_dir.parent.name,
            }
        )

    return {"charts": available, "date": evidence_dir.parent.name}


def _records(df) -> list[dict]:
    """DataFrame → JSON-안전 records (numpy 누수 방지 — 이 디렉터리 컨벤션).

    to_dict("records") 가 numpy 스칼라를 네이티브로 박싱하므로(pandas maybe_box_native)
    남는 비-JSON 값은 NaN/NaT/None 과 Timestamp 뿐이다.
    """
    import pandas as pd

    out = []
    for row in df.to_dict("records"):
        clean = {}
        for k, v in row.items():
            if pd.isna(v):
                clean[k] = None
            elif isinstance(v, pd.Timestamp):
                clean[k] = v.strftime("%Y-%m-%d")
            else:
                clean[k] = v
        out.append(clean)
    return out


# literal 세그먼트가 아래 `/evidence/{chart_id}` 와 겹치지 않도록 3-세그먼트 경로
# (이 파일의 `/evidence/report` 도달 불가 gotcha 참조 — nuri/api/CLAUDE.md).
@router.get("/evidence/data/{chart_id}")
def get_evidence_data(chart_id: str):
    """차트별 JSON 시리즈 — 네이티브(recharts) 렌더용 (#1224).

    Plotly 생성기와 evidence_data 공유 함수를 통해 단일 소스. 데이터 부재는
    빈 컬렉션으로 응답 (soft — 프론트가 빈 상태 1줄로 강등).
    """
    if chart_id not in CHART_TYPES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 차트: {chart_id}. 가능: {list(CHART_TYPES.keys())}")

    # 무거운 조립은 핸들러 안에서 lazy import (이 디렉터리 컨벤션)
    from nuri.analysis import evidence_data as ed

    if chart_id == "regime":
        spy = ed.load_spy_with_sma()
        vix = ed.load_vix_history()
        regime = None
        if not spy.empty:
            from nuri.quant.regime.classifier import classify_regime

            state = classify_regime()
            if state:
                regime = {
                    "regime": state.regime,
                    "trend": state.trend,
                    "volatility": state.volatility,
                    "confidence": state.confidence,
                }
        return {
            "spy": _records(spy) if not spy.empty else [],
            "vix": _records(vix) if not vix.empty else [],
            "regime": regime,
            "count": 0 if spy.empty else len(spy),
        }

    if chart_id == "portfolio_heatmap":
        grouped = ed.load_portfolio_grouped()
        items = _records(grouped) if not grouped.empty else []
        return {"items": items, "count": len(items)}

    if chart_id == "signal_performance":
        total = ed.load_signal_performance()
        if total is None or total.empty:
            return {"signals": [], "count": 0}
        cols = [
            c for c in ("signal_id", "win_rate", "profit_factor", "total_trades", "drift_status") if c in total.columns
        ]
        signals = _records(total[cols])
        return {"signals": signals, "count": len(signals)}

    if chart_id == "fear_greed":
        fg = ed.load_fear_greed_history()
        history = _records(fg) if not fg.empty else []
        return {"history": history, "count": len(history)}

    # sell_evidence
    violations = ed.detect_portfolio_violations()
    return {"violations": violations, "count": len(violations)}


@router.get("/evidence/{chart_id}")
def get_evidence_chart(chart_id: str):
    """증거 차트 HTML 반환."""
    if chart_id not in CHART_TYPES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 차트: {chart_id}. 가능: {list(CHART_TYPES.keys())}")

    evidence_dir = _find_latest_report_dir()
    if not evidence_dir:
        raise HTTPException(status_code=404, detail="증거 차트 없음. make evidence 실행 필요")

    # 파일명 후보
    candidates = [
        evidence_dir / f"{chart_id}.html",
        evidence_dir / f"{chart_id}_evidence.html",
    ]
    for path in candidates:
        if path.exists():
            html = path.read_text(encoding="utf-8")
            return HTMLResponse(content=html)

    raise HTTPException(status_code=404, detail=f"{chart_id} 차트 파일 미생성. make evidence 실행 필요")


@router.get("/evidence/report")
def get_evidence_report():
    """증거 리포트 (portfolio_action_plan.md) 반환."""
    today = str(date.today())
    report_dir = REPORT_DIR / today
    candidates = [
        report_dir / "portfolio_action_plan.md",
        report_dir / "llm_evidence_report.md",
    ]
    for path in candidates:
        if path.exists():
            return {"content": path.read_text(encoding="utf-8"), "file": path.name}

    # 최신 디렉토리에서 찾기
    latest = _find_latest_report_dir()
    if latest:
        for name in ["portfolio_action_plan.md", "llm_evidence_report.md"]:
            path = latest.parent / name
            if path.exists():
                return {"content": path.read_text(encoding="utf-8"), "file": name}

    raise HTTPException(status_code=404, detail="증거 리포트 없음. make full-scan 실행 필요")
