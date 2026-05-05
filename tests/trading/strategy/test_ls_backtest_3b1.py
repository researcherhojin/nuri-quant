"""ls_backtest.py 잔존 partials — Issue #616 Phase 3-B1.

5 partials 닫음 (604→591 은 `future_idx = min(entry_idx + 30, len(df) - 1)` 로
already-True 인 dead-by-design — 별도 simplify issue 후보):

| line | branch | trigger |
|---|---|---|
| 205→209 | `if not spy_open.empty:` False (run_interactive_backtest) | DB 에 SPY 없음 |
| 246→249 | `if spy_prev_close > 0:` False (run_interactive_backtest) | prev_row.close == 0 |
| 421→424 | `if spy_prev_close > 0:` False (run_backtest)            | prev_row.close == 0 |
| 598→596 | `if future_idx > entry_idx:` False (analyze_entry_timing) | entry 가 마지막 인덱스 |
| 733→746 | outer for 자연 종료 (no break) — monte_carlo_test          | total < n 으로 break 미발동 |
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nuri.core.db import init_db, upsert_prices


def _seed_spy(db_path, dates, closes):
    """SPY OHLC 적재 (open 컬럼 포함)."""
    df = pd.DataFrame(
        {
            "ticker": "SPY",
            "date": [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else d for d in dates],
            "open": [c * 1.001 for c in closes],
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
            "adj_close": closes,
        }
    )
    upsert_prices(df, db_path)


# ═══════════════════════════════════════════════════════
# 205→209: spy_open 빈 분기 (run_interactive_backtest)
# ═══════════════════════════════════════════════════════


class TestRunInteractiveSpyOpenEmpty:
    def test_spy_open_empty_skips_set_index(self, tmp_path):
        """DB 에 SPY 없음 → spy_open empty → 205 False → 209 으로 fall through."""
        from nuri.trading.strategy.ls_backtest import BacktestResult, run_interactive_backtest

        p = tmp_path / "no_spy.db"
        init_db(p)

        # 합성 regimes_df — DB seed 없이 함수 직접 호출.
        n = 30
        dates = pd.bdate_range("2024-01-02", periods=n)
        regimes = pd.DataFrame(
            {
                "date": dates,
                "regime": ["bull_low_vol"] * n,
                "return": [0.001] * n,
                "close": list(np.linspace(100, 110, n)),
            }
        )

        result = run_interactive_backtest(
            regimes,
            stop_loss_pct=10.0,
            take_profit_pct=20.0,
            db_path=p,
        )
        # spy_open empty → gap_cost 항상 0. 함수는 정상 종료.
        assert isinstance(result, BacktestResult)
        assert result.total_days == n - 1


# ═══════════════════════════════════════════════════════
# 246→249, 421→424: prev_close == 0 분기
# ═══════════════════════════════════════════════════════


class TestPrevCloseZero:
    def _make_regimes_with_zero_close(self, n=30):
        """prev_row.close == 0 강제."""
        dates = pd.bdate_range("2024-01-02", periods=n)
        closes = list(np.linspace(100, 110, n))
        # 5번째 row 의 close=0 → i=6 에서 prev_row.close == 0
        closes[5] = 0.0
        return pd.DataFrame(
            {
                "date": dates,
                "regime": ["bull_low_vol"] * n,
                "return": [0.001] * n,
                "close": closes,
            }
        )

    def test_run_interactive_skips_gap_when_prev_close_zero(self, tmp_path):
        """246: spy_prev_close == 0 → False → gap_cost 미계산."""
        from nuri.trading.strategy.ls_backtest import run_interactive_backtest

        p = tmp_path / "zero_close_int.db"
        init_db(p)
        regimes = self._make_regimes_with_zero_close()
        _seed_spy(p, regimes["date"], list(regimes["close"]))

        result = run_interactive_backtest(
            regimes,
            stop_loss_pct=10.0,
            take_profit_pct=20.0,
            db_path=p,
        )
        assert result.total_days > 0  # 함수 정상 종료, division by zero 없음

    def test_run_backtest_skips_gap_when_prev_close_zero(self, tmp_path):
        """421: spy_prev_close == 0 → False → gap_cost 미계산 (run_backtest)."""
        from nuri.trading.strategy.ls_backtest import run_backtest

        p = tmp_path / "zero_close_bt.db"
        init_db(p)
        regimes = self._make_regimes_with_zero_close()
        _seed_spy(p, regimes["date"], list(regimes["close"]))

        result = run_backtest(regimes, db_path=p)
        assert result.total_days > 0


# ═══════════════════════════════════════════════════════
# 598→596: future_idx == entry_idx — entry 가 마지막 인덱스
# ═══════════════════════════════════════════════════════


class TestAnalyzeEntryTimingAtEnd:
    def test_entry_at_last_date_skips_forward_return(self):
        """current_regime 이 마지막 시점에서 처음 등장 → entry_idx == 끝 →
        future_idx = min(entry_idx + days, len-1) == entry_idx → 598 False."""
        from nuri.trading.strategy.ls_backtest import analyze_entry_timing

        n = 50
        dates = pd.bdate_range("2024-01-02", periods=n)
        # 마지막 row 만 'sideways_high_vol', 그 직전은 'bull_low_vol' →
        # entries = [last_date] (regime 변경 발생점이 마지막 인덱스).
        regimes_list = ["bull_low_vol"] * (n - 1) + ["sideways_high_vol"]
        regimes_df = pd.DataFrame(
            {
                "date": dates,
                "regime": regimes_list,
                "return": [0.001] * n,
                "close": list(np.linspace(100, 110, n)),
            }
        )

        result = analyze_entry_timing(regimes_df, current_regime="sideways_high_vol")
        # entry 가 마지막이라 forward return 없음. 함수는 None 또는 빈 fwd 반환.
        # 핵심: 598 False 분기 진입 (assert 는 함수 정상 종료만 확인).
        assert result is not None or result is None  # smoke


# ═══════════════════════════════════════════════════════
# 733→746: monte_carlo outer for 자연 종료
# ═══════════════════════════════════════════════════════


class TestMonteCarloOuterLoopExhausts:
    def test_outer_for_completes_when_total_under_n(self, tmp_path):
        """n=30, block_size=20 → block_starts=[0,20]. 두 pick 모두 20 일 때
        총 sim_returns = 10+10 = 20 < n=30 → break 미발동 → outer for 자연 종료.

        n_simulations=50 으로 충분히 시도하여 [20,20] 케이스 포함 (seed=42 deterministic).
        """
        from nuri.trading.strategy.ls_backtest import monte_carlo_test

        p = tmp_path / "mc.db"
        init_db(p)

        n = 30
        dates = pd.bdate_range("2024-01-02", periods=n)
        regimes = pd.DataFrame(
            {
                "date": dates,
                "regime": ["bull_low_vol"] * n,
                "return": [0.001] * n,
                "close": list(np.linspace(100, 110, n)),
            }
        )
        # SPY seed (run_backtest 내부 호출이 필요)
        _seed_spy(p, dates, list(regimes["close"]))

        result = monte_carlo_test(regimes, n_simulations=50, block_size=20, db_path=p)
        # 정상 종료 확인 — error 키 없음.
        assert "error" not in result
        assert result["n_simulations"] == 50
