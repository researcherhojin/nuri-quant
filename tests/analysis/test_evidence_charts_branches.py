"""Branch coverage tests for nuri.analysis.evidence_charts.

Targets residual branches uncovered by test_evidence_charts.py:
- L166 (regime zone='bear'): gap_pct < -2 분기.
- L172 (vrect transition): zone change 가 prev_zone 있는 상태에서 발화 → vrect 추가.
- L314 (signal_performance fallback): scorecard 의 ticker 행이 모두 nan-rows
  none → head(20) fallback path.
- L329 (drift status='degrading'): 색상 주황 분기.
- L451-455 / L463-464 (fear_greed 색상 zones): 5 zone 색상 결정 분기 — 극단공포 /
  공포 / 중립 / 탐욕 / 극단탐욕.
- L600-601, L606-607, L612-613, L618-619, L625-626 (generate_all_evidence 의 5
  try/except): 각 sub-chart 생성기 raise 시 logger.error 후 다음 chart 진행.
- L663-664 (_load_drift_map exception swallow): detect_drift raise → {} 반환.

Privacy: synthetic ticker TST_*. No broker/PnL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from nuri.analysis import evidence_charts as ec
from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ec.db"
    init_db(path)
    return path


# ════════════════════════════════════════════════════════════
# L166 / L172 — regime zones (bear band + zone transition vrect)
# ════════════════════════════════════════════════════════════


class TestRegimeChartZones:
    def test_bear_zone_and_transition_recorded(self, db_path, tmp_path):
        """L163-172: gap_pct 시계열이 bull→sideways→bear→sideways 같은 다중 전환을
        가질 때 모든 zone 분기 (특히 bear / 전환 vrect) 가 발화.

        Regression: bear 분기 누락 시 아래쪽 zone 색상 surface 안 됨; vrect 분기
        누락 시 zone 경계 시각화 사라짐.
        """
        # gap_pct 가 +5 (bull) → 0 (sideways) → -5 (bear) → 0 (sideways) 로 변화하는
        # 데이터 직접 inject — generate_regime_chart 가 _build_regime_df 를 부르지 않게
        # 그쪽 reader 만 patch 한다.
        dates = pd.date_range("2026-01-01", periods=12)
        gap = [5, 5, 5, 0, 0, 0, -5, -5, -5, 0, 0, 0]
        synthetic = pd.DataFrame(
            {
                "date": dates,
                "spy_close": np.linspace(450, 470, 12),
                "ma200": np.linspace(440, 445, 12),
                "gap_pct": gap,
            }
        )
        # _build_regime_df 가 위 df 반환하도록 patch.
        with patch.object(ec, "_build_regime_df", return_value=synthetic):
            out_dir = tmp_path / "evidence"
            out_dir.mkdir()
            result = ec.generate_regime_chart(out_dir, db_path=db_path)
        assert result.exists()
        # HTML 안에 vrect 가 최소 1개 (전환 시 추가). plotly 는 shape attribute 로
        # vrect 표현 → 'shapes' or fillcolor 단어 검색.
        body = result.read_text()
        assert "fillcolor" in body  # zone color 적용된 vrect 존재


# ════════════════════════════════════════════════════════════
# L314 — signal_performance fallback head(20)
# ════════════════════════════════════════════════════════════


class TestSignalPerformanceFallback:
    def test_ticker_all_nonnull_uses_head20_fallback(self, tmp_path):
        """L312-314: scorecard 가 ticker NaN row 가 없을 때 head(20) fallback.

        Regression: total 빈 채로 다음 라인 → KeyError on win_rate sort.
        """
        # 모든 row 의 ticker 가 non-NaN 인 scorecard.
        df = pd.DataFrame(
            {
                "signal_id": [f"sig_{i}" for i in range(5)],
                "ticker": [f"TST_{i}" for i in range(5)],
                "win_rate": [0.5 + i * 0.05 for i in range(5)],
                "profit_factor": [1.0 + i * 0.1 for i in range(5)],
            }
        )
        with patch.object(ec, "_load_latest_scorecard", return_value=df):
            out = ec.generate_signal_performance_chart(tmp_path)
        assert out.exists()
        # 차트 본문에 signal_id 들 포함됨 — total empty 가 아니라 head(20) path 가 발화.
        body = out.read_text()
        assert "sig_0" in body or "sig_1" in body


# ════════════════════════════════════════════════════════════
# L329 — drift 'degrading' 색상 분기
# ════════════════════════════════════════════════════════════


class TestSignalPerformanceDriftColor:
    def test_degrading_drift_yields_orange(self, tmp_path):
        """L328-329: drift_map status='degrading' → 주황 (#ff9800).

        Regression: 분기 누락 시 degrading 도 stable 색상 (파랑) 으로 surface.
        """
        df = pd.DataFrame(
            {
                "signal_id": ["sig_a", "sig_b"],
                "ticker": [pd.NA, pd.NA],  # all NaN — 정상 path
                "win_rate": [0.55, 0.60],
                "profit_factor": [1.1, 1.2],
            }
        )
        drift_map = {
            "sig_a": {"status": "degrading", "drift_pct": -0.3},
            "sig_b": {"status": "stable", "drift_pct": 0.05},
        }
        with (
            patch.object(ec, "_load_latest_scorecard", return_value=df),
            patch.object(ec, "_load_drift_map", return_value=drift_map),
        ):
            out = ec.generate_signal_performance_chart(tmp_path)
        body = out.read_text()
        # degrading 색상 (#ff9800) 본문에 등장.
        assert "ff9800" in body.lower()


# ════════════════════════════════════════════════════════════
# L451-455 / L463-464 — fear_greed 색상 zone 5 분기
# ════════════════════════════════════════════════════════════


class TestFearGreedZoneColors:
    """fear_greed 차트는 현재 값에 따라 5 zone 색상 (극단공포 / 공포 / 중립 / 탐욕 /
    극단탐욕). 각 zone 마다 개별 fixture 로 트리거.
    """

    @pytest.fixture
    def patched_fg(self, db_path):
        """fg 데이터 series 를 마지막 값만 control 가능하도록 헬퍼."""

        def _make(last_value: float) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "date": pd.date_range("2026-04-01", periods=10),
                    "value": [50] * 9 + [last_value],
                }
            )

        return _make

    def test_extreme_fear_zone_red(self, patched_fg, tmp_path, db_path):
        """L450-452 (current_value <= 20): 극단적 공포 — #ef5350 빨강."""
        df = patched_fg(15)
        with patch.object(ec, "_load_fear_greed", return_value=df):
            out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "ef5350" in body.lower()
        assert "극단적 공포" in body

    def test_fear_zone_orange(self, patched_fg, tmp_path, db_path):
        """L453-455 (20 < cur <= 40): 공포 — #ff9800 주황."""
        df = patched_fg(35)
        with patch.object(ec, "_load_fear_greed", return_value=df):
            out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "ff9800" in body.lower()
        assert "공포" in body

    def test_greed_zone_green(self, patched_fg, tmp_path, db_path):
        """L459-461 (60 < cur <= 80): 탐욕 — #66bb6a 녹색."""
        df = patched_fg(75)
        with patch.object(ec, "_load_fear_greed", return_value=df):
            out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "66bb6a" in body.lower()
        assert "탐욕" in body

    def test_extreme_greed_zone_blue(self, patched_fg, tmp_path, db_path):
        """L462-464 (cur > 80): 극단적 탐욕 — #42a5f5 파랑.

        Regression: 본 분기 누락 시 모든 high reading 이 그냥 '탐욕' 으로 surface,
        VIX low + extreme greed 진입 시 buy 차단 시그널 약해짐.
        """
        df = patched_fg(90)
        with patch.object(ec, "_load_fear_greed", return_value=df):
            out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "42a5f5" in body.lower()
        assert "극단적 탐욕" in body


# ════════════════════════════════════════════════════════════
# L600-601 / L606-607 / L612-613 / L618-619 / L625-626
# generate_all_evidence sub-chart raise → logger.error 흡수
# ════════════════════════════════════════════════════════════


class TestGenerateAllEvidenceErrorSwallow:
    def test_each_subchart_failure_logged_not_aborted(self, db_path, tmp_path, caplog, monkeypatch):
        """L598-626: 5 sub-chart 가 raise 해도 logger.error 후 진행 — 결과 paths=[].

        Regression: 분기 누락 시 첫 chart 실패가 전체 함수 abort, 나머지 chart 미생성.
        """
        # REPORT_DIR 을 tmp_path 로 redirect — production 디렉토리 오염 방지.
        monkeypatch.setattr(ec, "REPORT_DIR", tmp_path / "reports")

        caplog.set_level(logging.ERROR)
        with (
            patch.object(ec, "generate_regime_chart", side_effect=RuntimeError("regime fail")),
            patch.object(ec, "generate_portfolio_heatmap", side_effect=RuntimeError("heat fail")),
            patch.object(ec, "generate_signal_performance_chart", side_effect=RuntimeError("sig fail")),
            patch.object(ec, "generate_fear_greed_chart", side_effect=RuntimeError("fg fail")),
            patch.object(ec, "_detect_portfolio_violations", side_effect=RuntimeError("violations fail")),
        ):
            paths = ec.generate_all_evidence(db_path=db_path)

        assert paths == []  # 모든 chart 실패 → 빈 리스트
        # 5 종류 error 모두 logger 에 기록.
        msgs = " ".join(rec.message for rec in caplog.records)
        assert "레짐 차트" in msgs
        assert "포트폴리오 히트맵" in msgs
        assert "시그널 성과" in msgs
        assert "공포·탐욕" in msgs
        assert "매도 근거" in msgs


# ════════════════════════════════════════════════════════════
# L663-664 — _load_drift_map exception swallow
# ════════════════════════════════════════════════════════════


class TestLoadDriftMapSwallow:
    def test_detect_drift_raise_returns_empty_dict(self, db_path):
        """L663-664: detect_drift import 또는 호출 raise → {} 반환.

        Regression: 분기 누락 시 drift_map 로드 실패가 signal_performance 차트
        전체 abort.
        """
        with patch(
            "nuri.trading.engine.memory.detect_drift",
            side_effect=RuntimeError("memory db missing"),
        ):
            out = ec._load_drift_map(db_path=db_path)
        assert out == {}
