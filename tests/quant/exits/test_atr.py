"""Tests for nuri/quant/exits/atr.py — PR F commit 1 (codex bubble-bear #6).

Anchor contract + fallback regression lock (codex Plan Biggest Risk):
- OHLC 부족 (< 14 rows) → `stop_price=None` + detail "OHLC 부족" (never raise).
- NaN/0 ATR → None + detail "ATR NaN/0" graceful.
- Normal path: entry - k × regime_mult × ATR, breached check.
- Regime multiplier: bull_low_vol=0.8, neutral=1.0, bear_high_vol=1.3 (E3-3c parity).
- Grid frozen: K_GRID = (1.5, 2.0, 2.5, 3.0).

Revert detection: anchor contract 변경 (entry_price 재해석) or grid drift 시 fail.
"""
import pandas as pd
import pytest


class TestComputeAtr:
    def test_insufficient_rows_returns_none(self):
        """OHLC < 14 rows → None (graceful, never raise)."""
        from nuri.quant.exits.atr import compute_atr
        df = pd.DataFrame({"high": [10, 11, 12], "low": [9, 10, 11], "close": [9.5, 10.5, 11.5]})
        assert compute_atr(df) is None

    def test_missing_columns_returns_none(self):
        from nuri.quant.exits.atr import compute_atr
        df = pd.DataFrame({"close": list(range(20))})  # high/low 없음
        assert compute_atr(df) is None

    def test_none_df_returns_none(self):
        from nuri.quant.exits.atr import compute_atr
        assert compute_atr(None) is None  # type: ignore[arg-type]

    def test_sufficient_rows_returns_series(self):
        """20 rows + 가격 변동 → ATR Series 정상 반환."""
        import numpy as np

        from nuri.quant.exits.atr import compute_atr
        rng = np.random.default_rng(42)
        n = 30
        base = 100 + np.cumsum(rng.normal(0, 1, n))
        df = pd.DataFrame({
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
        })
        atr = compute_atr(df, period=14)
        assert atr is not None
        assert len(atr) == n
        # 마지막 값은 valid (NaN 아님)
        assert not pd.isna(atr.iloc[-1])
        assert atr.iloc[-1] > 0


class TestGridAndRegimeConstants:
    """Freeze lock — grid 또는 regime multiplier 변경은 STRATEGY 개정 PR 필요."""

    def test_k_grid_frozen(self):
        from nuri.quant.exits.atr import K_GRID
        assert K_GRID == (1.5, 2.0, 2.5, 3.0), (
            f"K_GRID changed — PR F validation 결과 재생산 불가. 변경은 STRATEGY 개정 + "
            f"paired walk-forward 재실행 PR 필요. 현 {K_GRID}"
        )

    def test_regime_multiplier_e3_3c_parity(self):
        """E3-3c regime_overrides 의 aggressive/conservative multiplier 와 동일.
        (그쪽은 per_position_max multiplier, 여기는 stop_distance multiplier — 숫자
        는 같게 frozen 해 두 system 이 같은 regime labeling 경계를 공유.)"""
        from nuri.quant.exits.atr import REGIME_MULTIPLIER
        assert REGIME_MULTIPLIER["bull_low_vol"] == 0.8
        assert REGIME_MULTIPLIER["bear_high_vol"] == 1.3
        assert REGIME_MULTIPLIER.get("neutral", None) == 1.0

    def test_default_k_within_grid(self):
        from nuri.quant.exits.atr import DEFAULT_K, K_GRID
        assert DEFAULT_K in K_GRID, "DEFAULT_K must be one of K_GRID values"


class TestComputeAtrStopGracefulFallback:
    """codex Biggest Risk — anchor mismatch 방지: insufficient data 는 None 반환 +
    detail 로 caller 에게 명시. Caller 가 legacy percent stop fallback 해야."""

    def test_no_price_history_returns_none_stop(self, db_path):
        from nuri.quant.exits.atr import compute_atr_stop
        r = compute_atr_stop("NOTFOUND", entry_price=100, current_price=95, db_path=db_path)
        assert r.stop_price is None
        assert r.atr is None
        assert r.breached is False
        assert "OHLC 부족" in r.detail

    def test_insufficient_rows_returns_none_stop(self, db_path):
        """10 rows < 14 → None."""
        from nuri.core.db import get_db
        from nuri.quant.exits.atr import compute_atr_stop

        with get_db(db_path) as conn:
            for i in range(10):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("SHORT", f"2026-04-{i+1:02d}", 100, 101, 99, 100, 1000),
                )
        r = compute_atr_stop("SHORT", entry_price=100, current_price=100, db_path=db_path)
        assert r.stop_price is None
        assert "OHLC 부족" in r.detail


class TestComputeAtrStopNormalPath:
    def _seed(self, db_path, ticker: str, rows: int = 30, base: float = 100, noise: float = 2):
        """noise = high-low spread (= ATR proxy)."""
        from nuri.core.db import get_db
        with get_db(db_path) as conn:
            for i in range(rows):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, f"2026-03-{(i % 28) + 1:02d}" if i < 28 else f"2026-04-{i - 27:02d}",
                     base, base + noise, base - noise, base, 100000),
                )

    def test_normal_path_computes_stop(self, db_path):
        from nuri.quant.exits.atr import compute_atr_stop

        self._seed(db_path, "NORM", rows=20, base=100, noise=2)
        r = compute_atr_stop("NORM", entry_price=100, current_price=98,
                             regime="neutral", k=2.0, db_path=db_path)
        assert r.atr is not None
        assert r.stop_price is not None
        # ATR ≈ 4 (high-low=4 constant) → k=2 × 1.0 × 4 = 8 → stop ≈ 92
        # noise 가 일정해서 TR 이 4, 첫 rows 는 NaN 채우기
        assert 85 < r.stop_price < 95
        assert r.stop_pct is not None and -15 < r.stop_pct < -5
        assert r.breached is False  # current 98 > stop ~92

    def test_breached_detection(self, db_path):
        """current_price <= stop_price 시 breached=True."""
        from nuri.quant.exits.atr import compute_atr_stop

        self._seed(db_path, "BRCH", rows=20, base=100, noise=2)
        # stop ≈ 92, current 80 → breached
        r = compute_atr_stop("BRCH", entry_price=100, current_price=80,
                             regime="neutral", k=2.0, db_path=db_path)
        assert r.stop_price is not None
        assert r.breached is True
        assert "BREACHED" in r.detail

    def test_regime_multiplier_widens_stop_in_bear(self, db_path):
        """bear_high_vol (mult 1.3) stop 이 neutral (1.0) 보다 entry 에서 더 멀어짐
        (더 넓은 stop = whipsaw 방지)."""
        from nuri.quant.exits.atr import compute_atr_stop

        self._seed(db_path, "REGI", rows=20, base=100, noise=2)
        r_neu = compute_atr_stop("REGI", entry_price=100, current_price=100,
                                  regime="neutral", k=2.0, db_path=db_path)
        r_bear = compute_atr_stop("REGI", entry_price=100, current_price=100,
                                   regime="bear_high_vol", k=2.0, db_path=db_path)
        assert r_neu.stop_price is not None and r_bear.stop_price is not None
        # bear 의 stop 은 neutral 보다 entry 에서 더 멀어짐 (더 낮은 stop_price)
        assert r_bear.stop_price < r_neu.stop_price
        assert r_bear.regime_multiplier == 1.3
        assert r_neu.regime_multiplier == 1.0

    def test_regime_multiplier_tightens_stop_in_bull_low_vol(self, db_path):
        """bull_low_vol (mult 0.8) stop 이 neutral 보다 entry 에 더 가까움 —
        quick exit on any deterioration."""
        from nuri.quant.exits.atr import compute_atr_stop

        self._seed(db_path, "BULL", rows=20, base=100, noise=2)
        r_neu = compute_atr_stop("BULL", entry_price=100, current_price=100,
                                  regime="neutral", k=2.0, db_path=db_path)
        r_bull = compute_atr_stop("BULL", entry_price=100, current_price=100,
                                   regime="bull_low_vol", k=2.0, db_path=db_path)
        assert r_neu.stop_price is not None and r_bull.stop_price is not None
        # bull_low_vol multiplier 0.8 — stop 이 entry 에 더 가까움 (higher stop_price)
        assert r_bull.stop_price > r_neu.stop_price
        assert r_bull.regime_multiplier == 0.8


class TestAnchorContractFrozen:
    """codex Plan Biggest Risk — anchor mismatch 재발 방지.

    이 PR 의 semantic: `entry_price = held=avg_price, non-held=current_price`.
    `ATR` = 최신 (period=14) at computation time (= entry_atr_fixed basis).
    trailing dynamic 은 PR F2.
    """

    def test_basis_is_entry_atr_fixed(self, db_path):
        """result.basis 가 'entry_atr_fixed' 고정 — trailing 경로 재도입 차단."""
        from nuri.core.db import get_db
        from nuri.quant.exits.atr import compute_atr_stop

        with get_db(db_path) as conn:
            for i in range(20):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("ABC", f"2026-04-{i+1:02d}", 100, 102, 98, 100, 1000),
                )
        r = compute_atr_stop("ABC", entry_price=100, current_price=100, db_path=db_path)
        assert r.basis == "entry_atr_fixed"

    def test_entry_price_is_explicit_not_derived(self, db_path):
        """compute_atr_stop 는 entry_price 를 명시적 파라미터로 받음 — caller 가
        anchor 선택 책임 (held=avg_price, non-held=current_price). 함수 내부에서
        'current_price fallback' 같은 silent anchor 분기 없음."""
        import inspect

        from nuri.quant.exits import atr as atr_mod
        sig = inspect.signature(atr_mod.compute_atr_stop)
        # entry_price 는 keyword-only required (default 없음)
        assert "entry_price" in sig.parameters
        param = sig.parameters["entry_price"]
        assert param.default is inspect.Parameter.empty, (
            "entry_price must be explicit (no default) — anchor contract lock"
        )


@pytest.fixture
def db_path(tmp_path):
    from nuri.core.db import init_db
    path = tmp_path / "test.db"
    init_db(path)
    return path
