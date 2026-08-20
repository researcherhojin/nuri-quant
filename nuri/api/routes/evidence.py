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
