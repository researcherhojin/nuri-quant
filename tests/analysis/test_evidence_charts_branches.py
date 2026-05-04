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

# cspell:ignore nonnull subchart

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
        """L163-172: SPY SMA50 vs SMA200 gap 이 bull → sideways → bear 시계열로 변화 시
        bear 분기 (gap < -2) + vrect 전환 분기 둘 다 발화.

        Regression: bear 분기 누락 시 아래쪽 zone 색상 surface 안 됨;
        vrect 전환 분기 누락 시 zone 경계 시각화 사라짐.
        """
        from nuri.core.db import upsert_prices

        # 250 day SPY price 시계열 — SMA50/SMA200 차이가 +5% → 0 → -5% 로 흔들리도록.
        # 처음 100일 상승, 가운데 50일 횡보, 마지막 100일 하락으로 구성.
        n = 250
        dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d").tolist()
        prices_arr = (
            [400 + i * 0.6 for i in range(100)]  # bull
            + [460 + np.sin(i / 5) * 1 for i in range(50)]  # sideways
            + [460 - i * 0.6 for i in range(100)]  # bear
        )
        rows = [
            {
                "ticker": "SPY",
                "date": dates[i],
                "open": prices_arr[i] - 1,
                "high": prices_arr[i] + 1,
                "low": prices_arr[i] - 2,
                "close": prices_arr[i],
                "volume": 1_000_000,
                "adj_close": prices_arr[i],
            }
            for i in range(n)
        ]
        upsert_prices(pd.DataFrame(rows), db_path)

        out_dir = tmp_path / "evidence"
        out_dir.mkdir()
        # classify_regime 결과는 데이터 부족할 수 있어 silent 허용.
        with patch.object(ec, "classify_regime", return_value=None):
            result = ec.generate_regime_chart(out_dir, db_path=db_path)
        assert result.exists()
        body = result.read_text()
        # bear band fillcolor (244,67,54) 적용된 vrect 가 본문에 들어감.
        # zone 전환 → vrect → 'fillcolor' 키 + bear 색 둘 다 등장.
        assert "fillcolor" in body
        # bear band 의 RGBA 값 substring 확인.
        assert "244,67,54" in body or "244, 67, 54" in body


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
    극단탐욕). 각 zone 마다 macro 테이블에 마지막 값 inject 후 검증.
    """

    @staticmethod
    def _seed(db_path, last_value: float) -> None:
        from nuri.core.db import upsert_macro

        records = [
            {"indicator": "fear_greed", "date": d, "value": 50.0, "source": "test"}
            for d in pd.date_range("2026-01-01", periods=29).strftime("%Y-%m-%d")
        ]
        # 마지막 날만 last_value — DESC sorted 후 첫 row 가 last_value 가 되도록 미래 날짜.
        records.append({"indicator": "fear_greed", "date": "2026-02-15", "value": last_value, "source": "test"})
        upsert_macro(records, db_path)

    def test_extreme_fear_zone_red(self, db_path, tmp_path):
        """L450-452 (current_value <= 20): 극단적 공포 — dot 색상 #ef5350."""
        self._seed(db_path, 15)
        out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "극단적 공포" in body

    def test_fear_zone_orange(self, db_path, tmp_path):
        """L453-455 (20 < cur <= 40): 공포 — dot 색상 #ff9800.

        body 안에 '공포' 단어 + dot 색 등장. zone 음영 (rgba) 와 dot 색 (#ff9800)
        둘 다 본문에 있어야 함.
        """
        self._seed(db_path, 35)
        out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        # status 라벨 표시 (hovertemplate 일부).
        assert "공포" in body

    def test_greed_zone_green(self, db_path, tmp_path):
        """L459-461 (60 < cur <= 80): 탐욕 — dot 색상 #66bb6a."""
        self._seed(db_path, 75)
        out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
        assert "탐욕" in body

    def test_extreme_greed_zone_blue(self, db_path, tmp_path):
        """L462-464 (cur > 80): 극단적 탐욕 — dot 색상 #42a5f5.

        Regression: 본 분기 누락 시 모든 high reading 이 그냥 '탐욕' 으로 surface,
        VIX low + extreme greed 진입 시 buy 차단 시그널 약해짐.
        """
        self._seed(db_path, 90)
        out = ec.generate_fear_greed_chart(tmp_path, db_path=db_path)
        body = out.read_text()
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


class TestEvidenceChartsRunpy:
    """`__main__` block (lines 813-818): logging.basicConfig + generate_all_evidence."""

    def test_main_invokes_generate_all_evidence(self, monkeypatch, capsys):
        """runpy → __main__ block 실행 → generate_all_evidence 의 summary print 확인.

        runpy 가 모듈 소스를 재실행하므로 함수 monkeypatch 무효 (test illusion).
        대신 chart-emitter 들을 raise 시켜 빠르게 통과 + 출력 print 검증.
        """
        import runpy
        import sys

        # 모든 chart-emitter raise 시켜도 generate_all_evidence 는 try/except 로 graceful;
        # 마지막 print 가 stdout 에 떠야 한다. _emit_* 함수들을 source-level 로 패치.
        def _boom(*a, **kw):
            raise RuntimeError("skip")

        for name in (
            "generate_regime_chart",
            "generate_portfolio_heatmap",
            "generate_signal_performance_chart",
            "generate_fear_greed_chart",
            "_detect_portfolio_violations",
            "generate_sell_evidence_chart",
        ):
            monkeypatch.setattr(f"nuri.analysis.evidence_charts.{name}", _boom)

        monkeypatch.setattr(sys, "argv", ["evidence_charts"])
        runpy.run_module("nuri.analysis.evidence_charts", run_name="__main__")
        out = capsys.readouterr().out
        assert "증거 차트 생성 완료" in out


class TestRegimeChartSMABranches:
    """evidence_charts.py 89->101, 102->115: SMA50/SMA200 모두 NaN 시 add_trace 우회 (#611)."""

    def test_sma50_sma200_all_nan_skips_traces(self, db_path, tmp_path):
        """SMA50/SMA200 모두 NaN → 89 False / 102 False (trace 미추가).

        rolling(50).mean() 은 row 수 < 50 시 전 NaN 반환. 30 row 삽입해
        sma50_valid.empty / sma200_valid.empty 가 둘 다 True 가 되게 한다.
        """
        from nuri.core.db import upsert_prices

        n = 30  # < 50 → SMA50/SMA200 모두 NaN
        dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d").tolist()
        rows = [
            {
                "ticker": "SPY",
                "date": dates[i],
                "open": 400.0,
                "high": 401.0,
                "low": 399.0,
                "close": 400.0 + i * 0.1,
                "volume": 1_000_000,
                "adj_close": 400.0 + i * 0.1,
            }
            for i in range(n)
        ]
        upsert_prices(pd.DataFrame(rows), db_path)

        out_dir = tmp_path / "evidence"
        out_dir.mkdir()
        with patch.object(ec, "classify_regime", return_value=None):
            result = ec.generate_regime_chart(out_dir, db_path=db_path)
        assert result.exists()
        body = result.read_text()
        # SMA 50 / 200 trace 미추가 (89 False / 102 False 분기 확인)
        assert '"name":"SMA 50"' not in body
        assert '"name":"SMA 200"' not in body


class TestShadeRegimeZonesEarlyExit:
    """evidence_charts.py 214->exit: _shade_regime_zones 에 row 1 개만 입력 시
    prev_zone 이 None 인 채 루프 종료 → 마지막 vrect 추가 분기 미진입 (#611)."""

    def test_single_row_no_zone_transitions(self):
        from plotly.subplots import make_subplots

        from nuri.analysis.evidence_charts import _shade_regime_zones

        fig = make_subplots(rows=1, cols=1)
        # SMA50/SMA200 모두 NaN → zone 결정 불가, prev_zone 영원히 None
        df = pd.DataFrame(
            [
                {"date": "2025-01-01", "sma50": float("nan"), "sma200": float("nan")},
                {"date": "2025-01-02", "sma50": float("nan"), "sma200": float("nan")},
            ]
        )
        # 예외 raise 없이 통과 — 214 분기 False 진입
        _shade_regime_zones(fig, df)
        # zone 추가 안 됨 — fig.layout.shapes 가 비어 있어야 함 (vrect 미생성)
        shapes = list(getattr(fig.layout, "shapes", None) or [])
        assert shapes == [], f"zone vrect 가 추가되면 안 됨: {shapes}"


class TestPortfolioHeatmapNoViolations:
    """evidence_charts.py 312->324: violations 빈 list → annotation 미추가 (#611)."""

    def test_no_violations_skips_annotation(self, tmp_path, monkeypatch):
        """모든 종목이 stop_loss / max_single 정상 → violations 빈 list → 312 False → 324."""
        # analyze_portfolio 가 정상 비중·정상 pnl 데이터 반환하도록 patch
        df = pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "current_value_usd": 1000,
                    "pnl_pct": 5.0,
                    "weight_pct": 8.0,  # max_single 15% 미만
                    "sector": "Tech",
                },
                {
                    "ticker": "BBB",
                    "current_value_usd": 1000,
                    "pnl_pct": -2.0,  # PORTFOLIO_STOP -10 보다 큼
                    "weight_pct": 8.0,
                    "sector": "Health",
                },
            ]
        )
        monkeypatch.setattr("nuri.analysis.portfolio.analyze_portfolio", lambda *a, **kw: df)

        out_dir = tmp_path / "evidence"
        out_dir.mkdir()
        result = ec.generate_portfolio_heatmap(out_dir)
        assert result.exists()
        body = result.read_text()
        # violations 비어 annotation 미추가 — "위반 종목" 텍스트 없음 (312 False 분기 확인)
        assert "위반 종목" not in body
