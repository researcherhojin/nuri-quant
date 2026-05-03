"""Tests for nuri.trading.strategy.pairs.

Extracted from the former tests/test_trading_strategy_all.py.
Shared fixtures live in conftest.py for this directory.
"""

from nuri.core.db import init_db, upsert_portfolio


class TestPairs:
    """From test_new_features.py — pairs trading basics."""

    def test_find_pairs(self, market_data):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=market_data)
        assert isinstance(pairs, list)

    def test_backtest(self, market_data):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=market_data)
        assert "pairs_found" in result


class TestPairsTrading:
    """From test_coverage_extra.py — pairs trading."""

    def test_find_pairs(self):
        from nuri.trading.strategy.pairs import find_pairs
        assert callable(find_pairs)

    def test_find_pairs_empty(self, db_path):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=db_path)
        assert isinstance(results, list)

    def test_find_pairs_with_data(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        results = find_pairs(db_path=rich_db)
        assert isinstance(results, list)


class TestFindPairs:
    """From test_coverage_round21.py — find_pairs deeper tests."""

    def test_finds_correlated_pairs(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.5, db_path=rich_db)
        assert isinstance(pairs, list)
        if pairs:
            assert hasattr(pairs[0], "ticker_a")
            assert pairs[0].correlation >= 0.5

    def test_empty_when_no_prices(self, tmp_path):
        path = tmp_path / "no_prices.db"
        init_db(path)
        upsert_portfolio([
            {"account": "t", "ticker": "AAPL", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
            {"account": "t", "ticker": "MSFT", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
        ], path)
        from nuri.trading.strategy.pairs import find_pairs
        assert find_pairs(db_path=path) == []

    def test_pairs_sorted_by_zscore(self, rich_db):
        from nuri.trading.strategy.pairs import find_pairs
        pairs = find_pairs(min_corr=0.3, db_path=rich_db)
        if len(pairs) >= 2:
            assert abs(pairs[0].current_z) >= abs(pairs[1].current_z)


class TestScanPairSignals:
    """From test_coverage_round21.py — scan pair signals."""

    def test_scan_returns_signals_or_empty(self, rich_db):
        from nuri.trading.strategy.pairs import scan_pair_signals
        signals = scan_pair_signals(db_path=rich_db)
        assert isinstance(signals, list)


class TestBacktestPairs:
    """From test_coverage_round21.py — backtest pairs."""

    def test_backtest_runs(self, rich_db):
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(max_hold=10, db_path=rich_db)
        assert isinstance(result, dict)
        assert "pairs_found" in result

    def test_backtest_empty_db(self, tmp_path):
        path = tmp_path / "empty.db"
        init_db(path)
        from nuri.trading.strategy.pairs import backtest_pairs
        result = backtest_pairs(db_path=path)
        assert result["total_trades"] == 0


class TestFindPairsZeroStdSpread:
    """std_spread==0 분기 (line 95) 가 실제 DB 데이터 경로에서 unreachable 임을 lock.

    pragma: no cover 정당화 — bit-identical 비례 가격(log-ratio = const)이라도
    pandas .std(ddof=1) 는 N>=30 에서 ~1e-16 잔차를 남기므로 `== 0` 비교가
    성립하지 않는다. find_pairs 는 `len(price_df) >= 30` 에서만 실행되므로
    분기는 unreachable. pragma 가 제거되면 이 테스트가 정량 근거를 제공한다.
    """

    def test_proportional_prices_yield_nonzero_std_after_30plus_rows(self, tmp_path):
        """완벽 비례 가격 60일치 → log-ratio std 는 0이 아닌 1e-15 미만 잔차."""
        import numpy as np
        import pandas as pd

        from nuri.core.db import upsert_portfolio, upsert_prices
        from nuri.trading.strategy.pairs import find_pairs

        path = tmp_path / "constant_ratio.db"
        init_db(path)

        rng = np.random.default_rng(42)
        n = 80
        base = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        dates = pd.date_range("2025-01-01", periods=n).strftime("%Y-%m-%d").tolist()

        rows = []
        for i, d in enumerate(dates):
            for ticker, mult in (("PROP_A", 1.0), ("PROP_B", 2.0)):
                px = float(base[i] * mult)
                rows.append({
                    "ticker": ticker, "date": d,
                    "open": px, "high": px, "low": px, "close": px,
                    "volume": 1_000_000, "adj_close": px,
                })
        upsert_prices(pd.DataFrame(rows), path)
        upsert_portfolio([
            {"account": "t", "ticker": "PROP_A", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
            {"account": "t", "ticker": "PROP_B", "quantity": 1,
             "avg_price": 200, "currency": "USD", "sector": "Tech"},
        ], path)

        pairs = find_pairs(min_corr=0.5, db_path=path)
        # 비례 쌍이 결과에 포함됨 = std==0 분기 미적용 = pragma 정당
        prop_pairs = [p for p in pairs if {p.ticker_a, p.ticker_b} == {"PROP_A", "PROP_B"}]
        assert len(prop_pairs) == 1
        # std_spread 가 round(_, 4) 후 0.0 이지만 raw 값은 비-0 이라
        # `== 0` 비교가 False 임을 확인 (즉 분기에 들어가지 않음)
        assert prop_pairs[0].std_spread == 0.0  # round 결과
        assert prop_pairs[0].correlation == 1.0  # 완벽 상관

    def test_pandas_std_of_identical_values_invariant(self):
        """pandas Series.std(ddof=1) 가 N>=30 동일값에 대해 비-0 을 반환한다는 invariant lock.

        이 invariant 가 깨져 std 가 정확히 0 이 되면 line 95 가 reachable 해지므로
        pragma 를 재검토해야 한다.
        """
        import pandas as pd
        s = pd.Series([-0.6931471805599454] * 60)
        # 동일값이지만 ddof=1 누적 알고리즘 잔차로 비-0
        assert s.std() != 0.0
        assert 0 < s.std() < 1e-14


class TestPairsMainBlock:
    """pairs.py `if __name__ == "__main__":` 블록 실행 검증 (lines 227-243).

    runpy.run_module 로 모듈 소스를 __main__ 으로 재실행한다.
    DB_PATH 를 소스 모듈에서 patch (target-level patch 금지 — 재실행 시 stale).
    """

    def test_main_runs_with_correlated_pairs(self, tmp_path, monkeypatch, capsys):
        """상관 0.7+ 와 |Z|>2 가 동시에 발생하는 데이터 → pairs/signals 루프 모두 출력."""
        import numpy as np
        import pandas as pd

        import nuri.core.db as db_mod
        from nuri.core.db import init_db as _init_db
        from nuri.core.db import upsert_portfolio, upsert_prices

        path = tmp_path / "main_pairs.db"
        _init_db(path)
        monkeypatch.setattr(db_mod, "DB_PATH", path)

        # 두 티커: 공통 수익률 거의 동일(corr~0.91) + 가장 오래된 1일 shock(b *= 0.95) → |Z|~7.6
        # find_pairs 가 ORDER BY date DESC LIMIT N 으로 로드 → ratio.iloc[-1] 은 OLDEST date
        # 따라서 divergence 는 시계열 시작 부분(인덱스 0)에 배치해야 시그널 발생
        rng = np.random.default_rng(1)
        n = 60
        ret_common = rng.normal(0.001, 0.015, n)
        noise = rng.normal(0, 0.0005, n)
        a_close = 100.0 * np.exp(np.cumsum(ret_common))
        b_close = 200.0 * np.exp(np.cumsum(ret_common + noise))
        b_close[0] *= 0.95  # 단일 shock — pct_change 의 NaN 으로 returns 에서는 제외 → corr 보존

        dates = pd.date_range("2025-01-01", periods=n).strftime("%Y-%m-%d").tolist()
        rows = []
        for ticker, closes in (("CORR_A", a_close), ("CORR_B", b_close)):
            for i, d in enumerate(dates):
                px = float(closes[i])
                rows.append({
                    "ticker": ticker, "date": d,
                    "open": px, "high": px, "low": px, "close": px,
                    "volume": 1_000_000, "adj_close": px,
                })
        upsert_prices(pd.DataFrame(rows), path)
        upsert_portfolio([
            {"account": "t", "ticker": "CORR_A", "quantity": 1,
             "avg_price": 100, "currency": "USD", "sector": "Tech"},
            {"account": "t", "ticker": "CORR_B", "quantity": 1,
             "avg_price": 200, "currency": "USD", "sector": "Tech"},
        ], path)

        import runpy
        runpy.run_module("nuri.trading.strategy.pairs", run_name="__main__")

        out = capsys.readouterr().out
        # 세 섹션 헤더 lock
        assert "=== Correlated Pairs ===" in out
        assert "=== Pair Signals (Z > 2.0) ===" in out
        assert "=== Pairs Backtest ===" in out
        # 페어 루프 라인 (line 232): "  CORR_A / CORR_B: corr=... Z=..."
        assert "CORR_A / CORR_B" in out or "CORR_B / CORR_A" in out
        assert "corr=" in out
        # 시그널 루프 라인 (line 237): "  Long ... / Short ..."
        assert "Long " in out and "Short " in out
        # backtest 결과 dict 출력 (line 243)
        assert "pairs_found:" in out
