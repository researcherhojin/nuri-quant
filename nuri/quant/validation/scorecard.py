"""
C-4: 통합 스코어카드 — C-1/C-2/C-3 결과를 단일 HTML로 통합.

C-1 (시그널 백테스트)과 C-2 (슈퍼투자자 추종)가 완료된 후 실행.

사용법:
    python -m nuri.quant.validation.scorecard
"""
import logging
from datetime import datetime
from pathlib import Path

from nuri.db import query

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"


def generate_validation_report(output_dir: Path | None = None) -> Path | None:
    """C-1/C-2/C-3 결과를 통합 Plotly HTML로 생성.

    구현 순서:
    1. signal_scorecard.csv 로드 (C-1)
    2. superinvestor_scorecard.csv 로드 (C-2)
    3. analyst results 로드 (C-3, 데이터 있으면)
    4. Plotly로 대시보드 HTML 생성:
       - 시그널 랭킹 바차트 (승률/PF 기준)
       - 슈퍼투자자 랭킹 바차트
       - 현재 활성 시그널 테이블 (오늘 발생 + 과거 승률)
    5. validation_report.html 저장
    """
    if output_dir is None:
        today = datetime.now().strftime("%Y-%m-%d")
        output_dir = REPORT_DIR / today

    # 필수 입력 파일 확인
    signal_csv = output_dir / "signal_scorecard.csv"
    si_csv = output_dir / "superinvestor_scorecard.csv"

    missing = []
    if not signal_csv.exists():
        missing.append("signal_scorecard.csv (C-1 먼저 실행)")
    if not si_csv.exists():
        missing.append("superinvestor_scorecard.csv (C-2 먼저 실행)")

    if missing:
        logger.warning(f"통합 스코어카드 생성 불가. 누락 파일:\n  " + "\n  ".join(missing))
        return None

    # TODO: Plotly 대시보드 생성
    # import plotly.graph_objects as go
    # from plotly.subplots import make_subplots
    #
    # 섹션 1: 시그널 랭킹 (horizontal bar chart, PF 기준 정렬)
    # 섹션 2: 슈퍼투자자 랭킹 (horizontal bar chart, 초과수익 기준)
    # 섹션 3: 현재 활성 시그널 (오늘 기준 발생 시그널 + 해당 시그널 승률)
    # 섹션 4: 애널리스트 적중률 (C-3 데이터 있으면)

    raise NotImplementedError("C-4: generate_validation_report 구현 필요")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    path = generate_validation_report()
    if path:
        print(f"통합 리포트: {path}")
