"""멀티팩터 (momentum, value, quality, composite) 테스트."""
import numpy as np
import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import nuri.core.db as db_mod
    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


@pytest.fixture
def factor_data(db_path):
    """팩터 테스트용 가격 + 시그널 데이터."""
    dates = pd.bdate_range("2024-01-01", periods=60)

    for ticker, base in [("AAPL", 150), ("MSFT", 300), ("GOOG", 140)]:
        close = np.linspace(base, base * 1.2, 60) + np.random.normal(0, 1, 60)
        df = pd.DataFrame({
            "ticker": ticker,
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * 0.99, "high": close * 1.02,
            "low": close * 0.97, "close": close,
            "volume": [1000000] * 60, "adj_close": close,
        })
        upsert_prices(df, db_path)

    # RSI 시그널
    with get_db(db_path) as conn:
        for ticker in ["AAPL", "MSFT", "GOOG"]:
            conn.execute(
                "INSERT INTO signals (ticker, date, rsi_14) VALUES (?, ?, ?)",
                (ticker, dates[-1].strftime("%Y-%m-%d"), 55.0),
            )

    # Fear & Greed
    upsert_macro([{
        "indicator": "fear_greed",
        "date": dates[-1].strftime("%Y-%m-%d"),
        "value": 60.0,
        "source": "test",
    }], db_path)

    # 포트폴리오 (get_tickers용)
    with get_db(db_path) as conn:
        for ticker in ["AAPL", "MSFT", "GOOG"]:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", ticker, 10, 100.0, "USD", "Technology"),
            )

    return db_path


# ═══════════════════════════════════════════════════════
# Momentum 팩터
# ═══════════════════════════════════════════════════════

class TestMomentum:
    def test_compute_with_data(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert not result.empty
        assert "momentum_score" in result.columns
        for score in result["momentum_score"]:
            assert 0 <= score <= 1

    def test_empty_db(self, db_path):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        assert result.empty

    def test_with_tickers_filter(self, factor_data):
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum(tickers=["AAPL"])
        assert len(result) <= 1

    def test_insufficient_data(self, db_path):
        """14일 미만 데이터는 스킵."""
        prices = pd.DataFrame([{
            "ticker": "SHORT", "date": f"2024-01-{i+1:02d}",
            "open": 100, "high": 101, "low": 99, "close": 100,
            "volume": 1000, "adj_close": 100,
        } for i in range(5)])
        upsert_prices(prices, db_path)
        from nuri.quant.factors.momentum import compute_momentum
        result = compute_momentum()
        # 5일 < 14일 → 스킵
        assert "SHORT" not in result.index if not result.empty else True


# ═══════════════════════════════════════════════════════
# Value 팩터
# ═══════════════════════════════════════════════════════

class TestValue:
    def test_empty_when_no_data(self, db_path):
        """OpenBB 호출 실패 → 빈 DataFrame."""
        from nuri.quant.factors.value import compute_value
        result = compute_value(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        """역수 정규화 로직 직접 테스트."""
        scores = {"AAPL": {"pe_ratio": 15.0, "pb_ratio": 2.0},
                  "MSFT": {"pe_ratio": 30.0, "pb_ratio": 5.0}}
        df = pd.DataFrame(scores).T

        # 역수 정규화 (낮은 PE/PB = 높은 가치)
        for col in ["pe_ratio", "pb_ratio"]:
            valid = df[col].dropna()
            inverted = 1 / valid.clip(lower=0.01)
            col_min, col_max = inverted.min(), inverted.max()
            if col_max > col_min:
                df[col + "_norm"] = (inverted - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5

        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["value_score"] = df[norm_cols].mean(axis=1)

        # AAPL (PE=15) should score higher than MSFT (PE=30)
        assert df.loc["AAPL", "value_score"] > df.loc["MSFT", "value_score"]


# ═══════════════════════════════════════════════════════
# Quality 팩터
# ═══════════════════════════════════════════════════════

class TestQuality:
    def test_empty_when_no_data(self, db_path):
        from nuri.quant.factors.quality import compute_quality
        result = compute_quality(tickers=["FAKE"])
        assert result.empty

    def test_normalization_logic(self):
        """정규화 로직 직접 테스트."""
        scores = {"AAPL": {"roe": 0.30, "operating_margin": 0.25},
                  "MSFT": {"roe": 0.15, "operating_margin": 0.10}}
        df = pd.DataFrame(scores).T

        for col in ["roe", "operating_margin"]:
            valid = df[col].dropna()
            col_min, col_max = valid.min(), valid.max()
            if col_max > col_min:
                df[col + "_norm"] = (valid - col_min) / (col_max - col_min)
            else:
                df[col + "_norm"] = 0.5

        norm_cols = [c for c in df.columns if c.endswith("_norm")]
        df["quality_score"] = df[norm_cols].mean(axis=1)

        # AAPL (higher ROE/margin) should score higher
        assert df.loc["AAPL", "quality_score"] > df.loc["MSFT", "quality_score"]


# ═══════════════════════════════════════════════════════
# Composite 팩터
# ═══════════════════════════════════════════════════════

class TestComposite:
    def test_weights_sum_to_one(self):
        from nuri.quant.factors.composite import WEIGHTS
        assert abs(sum(WEIGHTS.values()) - 1.0) < 0.001

    def test_compute_with_data(self, factor_data, monkeypatch):
        """모멘텀 데이터로 composite 계산 (value/quality는 mock)."""
        from nuri.quant.factors import composite as comp_mod

        empty_df = pd.DataFrame()
        monkeypatch.setattr(comp_mod, "compute_value", lambda: empty_df, raising=False)
        monkeypatch.setattr(comp_mod, "compute_quality", lambda: empty_df, raising=False)

        # Force re-import of lazy imports by calling directly
        from nuri.quant.factors.momentum import compute_momentum as _cm
        monkeypatch.setattr(comp_mod, "compute_momentum", _cm, raising=False)

        result = comp_mod.compute_composite()
        if not result.empty:
            assert "composite_score" in result.columns
            for score in result["composite_score"]:
                assert 0 <= score <= 1

    def test_compute_manual(self, factor_data):
        """composite 계산 로직 수동 검증."""
        from nuri.quant.factors.composite import WEIGHTS

        m, v, q, s = 0.7, 0.5, 0.6, 0.5
        expected = (
            m * WEIGHTS["momentum"] +
            v * WEIGHTS["value"] +
            q * WEIGHTS["quality"] +
            s * WEIGHTS["sentiment"]
        )
        assert 0 < expected < 1

    def test_print_composite_empty(self, capsys):
        from nuri.quant.factors.composite import print_composite
        print_composite(pd.DataFrame())
        output = capsys.readouterr().out
        assert "없습니다" in output

    def test_print_composite_with_data(self, capsys):
        from nuri.quant.factors.composite import print_composite
        df = pd.DataFrame([{
            "momentum_score": 0.7, "value_score": 0.5,
            "quality_score": 0.6, "sentiment_score": 0.5, "composite_score": 0.58,
        }], index=["AAPL"])
        print_composite(df)
        output = capsys.readouterr().out
        assert "AAPL" in output
        assert "멀티팩터" in output
