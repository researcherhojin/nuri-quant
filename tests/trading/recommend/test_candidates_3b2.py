"""candidates.py helpers — Issue #616 Phase 3-B2.

`_load_scorecard` + `_get_regime_context` 의 4 partials/branch 닫음.
screen_candidates main flow + print_candidates 는 별도 PR (3-B3).

| line | branch | trigger |
|---|---|---|
| 81→120 | for-loop 자연 종료 (no csv found) | REPORT_DIR exists, 비어있거나 signal_scorecard.csv 없음 |
| 90-91 | `datetime.strptime` ValueError | 디렉토리명이 날짜 형식 아님 |
| 112-118 | stale_sells drop path | SELL 시그널이 PF>1.0 (pre-B-1 cache) |
| 154→157 | `strategy.signal_regime_stats` falsy | mock strategy with empty signal_regime_stats |
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ═══════════════════════════════════════════════════════
# 81→120, 90-91, 112-118: _load_scorecard
# ═══════════════════════════════════════════════════════


class TestLoadScorecardMissingBranches:
    def test_report_dir_exists_but_empty(self, tmp_path, monkeypatch):
        """81→120: REPORT_DIR 존재하지만 sub-dir 없음 → for 자연 종료 → ({}, None) 반환."""
        from nuri.trading.recommend import candidates as cand_mod

        empty_dir = tmp_path / "reports_empty"
        empty_dir.mkdir()
        monkeypatch.setattr(cand_mod, "REPORT_DIR", empty_dir)

        data, age = cand_mod._load_scorecard()
        assert data == {}
        assert age is None

    def test_invalid_dir_name_falls_back_to_none_age(self, tmp_path, monkeypatch):
        """90-91: 디렉토리명이 YYYY-MM-DD 아님 → ValueError → age_days = None 유지.

        그래도 csv 가 있으면 데이터는 정상 로드 (age_days 만 None).
        """
        from nuri.trading.recommend import candidates as cand_mod

        report_dir = tmp_path / "reports_bad_name"
        bad_dir = report_dir / "not-a-date-2026"
        bad_dir.mkdir(parents=True)

        csv_content = "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n,rsi_oversold,0.65,2.1,3.5,30\n"
        (bad_dir / "signal_scorecard.csv").write_text(csv_content)
        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)

        data, age = cand_mod._load_scorecard()
        # ValueError 흡수 → age_days 는 None 으로 남되 데이터는 그대로 로드.
        assert age is None
        assert "rsi_oversold" in data

    def test_drops_stale_sell_with_pf_above_one(self, tmp_path, monkeypatch):
        """112-118: SELL 시그널의 PF>1.0 (pre-B-1 buy-perspective 측정) → 해당 시그널 drop.

        SELL_SIGNALS 의 실제 시그널 ID 가져와 stale 데이터 주입.
        """
        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend import candidates as cand_mod

        if not SELL_SIGNALS:
            pytest.skip("SELL_SIGNALS 비어있음 — 회귀 시 skip")

        sell_sig = next(iter(SELL_SIGNALS))
        report_dir = tmp_path / "reports_stale_sell"
        day_dir = report_dir / "2026-04-30"
        day_dir.mkdir(parents=True)

        # SELL 시그널이 PF=2.5 (>1.0) — pre-B-1 buggy 데이터.
        # 그리고 정상 BUY 시그널 1개 추가 (drop 안 되는지 확인).
        csv_content = (
            "ticker,signal_id,win_rate,profit_factor,avg_return,total_trades\n"
            f",{sell_sig},0.55,2.5,1.0,20\n"
            ",rsi_oversold,0.60,1.8,2.0,25\n"
        )
        (day_dir / "signal_scorecard.csv").write_text(csv_content)
        monkeypatch.setattr(cand_mod, "REPORT_DIR", report_dir)

        data, _ = cand_mod._load_scorecard()
        # stale SELL 은 drop 됨, 정상 시그널은 유지.
        assert sell_sig not in data
        assert "rsi_oversold" in data


# ═══════════════════════════════════════════════════════
# 154→157: _get_regime_context — empty signal_regime_stats
# ═══════════════════════════════════════════════════════


class TestGetRegimeContextEmptyStats:
    def test_strategy_with_empty_signal_regime_stats(self, monkeypatch):
        """154→157: strategy 존재하지만 signal_regime_stats falsy → regime_stats={} 유지.

        mock 으로 strategy.signal_regime_stats={} 주입해 154 if 의 두번째 조건 False.
        """
        from nuri.trading.recommend import candidates as cand_mod

        mock_regime = MagicMock(regime="bull_low_vol")
        mock_strategy = MagicMock(
            recommended_signals=["rsi_oversold"],
            avoid_signals=[],
            position_sizing="normal",
            signal_regime_stats={},  # falsy → 154 condition False → 157 로 fall through
        )
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda **kw: mock_regime,
        )
        monkeypatch.setattr(
            "nuri.quant.regime.strategy_map.map_regime_to_strategy",
            lambda *a, **kw: mock_strategy,
        )

        ctx = cand_mod._get_regime_context()
        assert ctx is not None
        assert ctx["regime"] == "bull_low_vol"
        assert ctx["regime_stats"] == {}  # 빈 dict — 154 False 분기 통과 증거
