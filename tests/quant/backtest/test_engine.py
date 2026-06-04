"""Tests for nuri.quant.backtest.engine — VectorBT momentum backtest.

Codex Plan consult v1 (2026-04-28) — focus on signal-construction correctness,
not just line coverage. Boundary at vbt.Portfolio.from_signals (mocked) so we
test our own logic, not vectorbt internals.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _make_prices_df(
    tickers: list[str] | None = None,
    n_days: int = 60,
    start_date: str = "2025-01-01",
) -> pd.DataFrame:
    """Build a long-format prices DataFrame in the shape `query_df` returns."""
    tickers = tickers or ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]
    dates = pd.date_range(start_date, periods=n_days, freq="B")
    rows = []
    for i, t in enumerate(tickers):
        base = 100 + i * 50
        for j, d in enumerate(dates):
            rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"), "close": base + j * 0.5})
    return pd.DataFrame(rows)


def _make_stub_portfolio(stats_dict: dict | None = None) -> MagicMock:
    """Build a vbt.Portfolio mock with .stats() and .returns()."""
    pf = MagicMock()
    stats_dict = stats_dict or {
        "Total Return [%]": 12.5,
        "Sharpe Ratio": 1.4,
        "Max Drawdown [%]": -8.2,
        "Win Rate [%]": 62.0,
        "Total Trades": 15,
    }
    pf.stats.return_value = pd.Series(stats_dict)
    pf.returns.return_value = pd.Series(
        [0.001 * (i % 10 - 5) for i in range(20)],
        index=pd.date_range("2025-01-01", periods=20, freq="B"),
    )
    return pf


# ──────────────────────────────────────────────────────────────
# Empty / boundary input → empty dict
# ──────────────────────────────────────────────────────────────


class TestEmptyInputs:
    def test_empty_prices_returns_empty_dict(self):
        from nuri.quant.backtest import engine

        with patch.object(engine, "query_df", return_value=pd.DataFrame(columns=["ticker", "date", "close"])):
            result = engine.run_momentum_backtest()
        assert result == {}

    def test_kr_only_universe_returns_empty_dict(self):
        """All `.KS` tickers are filtered out (currency-mixing guard)."""
        from nuri.quant.backtest import engine

        kr_only = _make_prices_df(tickers=["005930.KS", "000660.KS", "035420.KS"])
        with patch.object(engine, "query_df", return_value=kr_only):
            result = engine.run_momentum_backtest()
        assert result == {}

    def test_insufficient_history_returns_empty_dict(self):
        """<20 rows after KR filter → returns {}."""
        from nuri.quant.backtest import engine

        # 10 days only
        df = _make_prices_df(tickers=["AAPL", "MSFT"], n_days=10)
        with patch.object(engine, "query_df", return_value=df):
            result = engine.run_momentum_backtest()
        assert result == {}


# ──────────────────────────────────────────────────────────────
# Happy path + signal-construction (codex Plan v1 critical test)
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def stubbed_quantstats():
    """Stub quantstats.reports.html so happy-path tests don't write real tearsheet HTML
    (codex Round 1 review: real seaborn warnings + data/exports artifact noise)."""
    import sys

    fake_qs = MagicMock()
    fake_qs.reports.html.return_value = None
    with patch.dict(sys.modules, {"quantstats": fake_qs}):
        yield fake_qs


class TestHappyPath:
    def test_returns_metrics_dict_with_expected_keys_and_types(self, stubbed_quantstats):
        """Happy path → dict with strategy/period/total_return_pct/sharpe/MDD/win_rate/trades."""
        from nuri.quant.backtest import engine

        prices = _make_prices_df(n_days=60)
        pf = _make_stub_portfolio()
        with (
            patch.object(engine, "query_df", return_value=prices),
            patch.object(engine.vbt.Portfolio, "from_signals", return_value=pf),
        ):
            result = engine.run_momentum_backtest(period="3mo", top_n=3, rebalance_days=20)

        assert result["strategy"] == "Momentum Top-3"
        assert result["period"] == "3mo"
        assert result["rebalance_days"] == 20
        assert result["total_return_pct"] == 12.5
        assert result["sharpe_ratio"] == 1.4
        assert result["max_drawdown_pct"] == -8.2
        assert result["win_rate_pct"] == 62.0
        assert result["total_trades"] == 15

    def test_from_signals_called_with_correct_signal_matrices(self, stubbed_quantstats):
        """Codex Round 1 review: prove the contract by computing exact expected
        rebalance indices AND exact top-N winners, then assert equality row-by-row.

        Engine logic (engine.py:60-77):
            lookback = min(rebalance_days, max(5, len(pivot)//4))
            momentum = pivot.pct_change(lookback)
            for i in range(lookback, len(pivot), rebalance_days):
                exits.iloc[i] = True
                top_tickers = momentum.iloc[i].nlargest(top_n).index
                entries.loc[..., top_tickers] = True

        We construct prices with KNOWN momentum so we can compute expected
        winners deterministically without reimplementing the engine.
        """
        from nuri.quant.backtest import engine

        # 5 US + 1 KR. KR must be filtered.
        # Each ticker has constant linear growth; growth slope determines momentum rank.
        # Slopes: AAPL=0.5/d, MSFT=1.0/d, NVDA=2.0/d, TSLA=3.0/d, GOOGL=4.0/d.
        # → momentum (pct_change over lookback) ordering: GOOGL > TSLA > NVDA > MSFT > AAPL.
        # Top-3 winners every rebalance: {GOOGL, TSLA, NVDA}.
        n_days = 80
        dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
        slopes = {"AAPL": 0.5, "MSFT": 1.0, "NVDA": 2.0, "TSLA": 3.0, "GOOGL": 4.0}
        rows = []
        for t, slope in slopes.items():
            base = 100.0
            for j, d in enumerate(dates):
                rows.append({"ticker": t, "date": d.strftime("%Y-%m-%d"), "close": base + j * slope})
        # Add KR ticker that should be filtered.
        for j, d in enumerate(dates):
            rows.append({"ticker": "005930.KS", "date": d.strftime("%Y-%m-%d"), "close": 60000 + j * 100})
        prices = pd.DataFrame(rows)

        pf = _make_stub_portfolio()
        with (
            patch.object(engine, "query_df", return_value=prices),
            patch.object(engine.vbt.Portfolio, "from_signals", return_value=pf) as mock_from_signals,
        ):
            engine.run_momentum_backtest(period="3mo", top_n=3, rebalance_days=20)

        assert mock_from_signals.call_count == 1
        call_kwargs = mock_from_signals.call_args.kwargs
        close_df = call_kwargs["close"]
        entries_df = call_kwargs["entries"]
        exits_df = call_kwargs["exits"]

        # ── KR exclusion ──
        assert "005930.KS" not in close_df.columns
        assert set(close_df.columns) == {"AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"}

        # ── Shape alignment ──
        assert entries_df.shape == close_df.shape == (n_days, 5)
        assert exits_df.shape == close_df.shape

        # ── Compute EXPECTED rebalance indices ──
        # lookback = min(20, max(5, 80 // 4)) = min(20, 20) = 20
        # range(lookback, len, rebalance) = range(20, 80, 20) = [20, 40, 60]
        expected_rebalance_indices = [20, 40, 60]

        # ── Verify exits matrix: ONLY rebalance rows are all-True ──
        for i in range(n_days):
            row = exits_df.iloc[i]
            if i in expected_rebalance_indices:
                assert row.all(), f"Row {i} should be a rebalance row (all-True exits)"
            else:
                assert not row.any(), f"Row {i} should be False (non-rebalance)"

        # ── Verify entries matrix: only {GOOGL, TSLA, NVDA} True at rebalance rows, else False ──
        expected_winners = {"GOOGL", "TSLA", "NVDA"}
        expected_losers = {"AAPL", "MSFT"}
        for i in range(n_days):
            row = entries_df.iloc[i]
            if i in expected_rebalance_indices:
                truthies = set(row.index[row].tolist())
                assert truthies == expected_winners, (
                    f"Row {i}: expected entries True for {expected_winners}, got {truthies}"
                )
                # Losers explicitly False.
                for loser in expected_losers:
                    assert not row[loser], f"Row {i} loser {loser} should be False"
            else:
                assert not row.any(), f"Non-rebalance row {i} should be all-False entries"

        # ── Sizing arguments ──
        assert call_kwargs["size"] == 100000 / 3
        assert call_kwargs["size_type"] == "value"
        assert call_kwargs["init_cash"] == 100000
        assert call_kwargs["freq"] == "1D"

    def test_quantstats_exception_does_not_crash_backtest(self):
        """Tear sheet generation failure must not break the metrics return path."""
        from nuri.quant.backtest import engine

        prices = _make_prices_df(n_days=60)
        pf = _make_stub_portfolio()

        # Patch quantstats import inside the function via sys.modules.
        import sys

        fake_qs = MagicMock()
        fake_qs.reports.html.side_effect = RuntimeError("tearsheet boom")
        with (
            patch.object(engine, "query_df", return_value=prices),
            patch.object(engine.vbt.Portfolio, "from_signals", return_value=pf),
            patch.dict(sys.modules, {"quantstats": fake_qs}),
        ):
            # Must not raise; metrics dict still returned.
            result = engine.run_momentum_backtest(top_n=3)
        assert result["total_return_pct"] == 12.5
        assert result["strategy"] == "Momentum Top-3"


# ──────────────────────────────────────────────────────────────
# print_backtest
# ──────────────────────────────────────────────────────────────


class TestPrintBacktest:
    def test_empty_dict_prints_no_data_message(self, capsys):
        from nuri.quant.backtest.engine import print_backtest

        print_backtest({})
        out = capsys.readouterr().out
        assert "백테스트 데이터 없음" in out

    def test_full_dict_prints_all_metrics(self, capsys):
        from nuri.quant.backtest.engine import print_backtest

        result = {
            "strategy": "Momentum Top-5",
            "period": "1y",
            "rebalance_days": 20,
            "total_return_pct": 18.34,
            "sharpe_ratio": 1.62,
            "max_drawdown_pct": -12.4,
            "win_rate_pct": 58.3,
            "total_trades": 27,
        }
        print_backtest(result)
        out = capsys.readouterr().out
        # Verify each metric label and value appears.
        assert "Momentum Top-5" in out
        assert "+18.34%" in out
        assert "1.62" in out
        assert "-12.40%" in out
        assert "58.3%" in out
        assert "27" in out


# ──────────────────────────────────────────────────────────────
# Corner case (codex)
# ──────────────────────────────────────────────────────────────


class TestCornerCases:
    def test_top_n_zero_raises_zero_division(self):
        """Codex flagged: top_n=0 → ZeroDivisionError on size calc.

        Existing code does NOT guard against this — locking the current
        behavior so a future change doesn't silently swallow the divide-by-zero.
        """
        from nuri.quant.backtest import engine

        prices = _make_prices_df(n_days=60)
        with patch.object(engine, "query_df", return_value=prices):
            with pytest.raises(ZeroDivisionError):
                engine.run_momentum_backtest(top_n=0)


# ──────────────────────────────────────────────────────────────
# persist=True → backtests 테이블 영속화 (P1a wiring)
# ──────────────────────────────────────────────────────────────


class TestPersist:
    def test_persist_true_writes_one_backtest_row(self, db_path_mp, stubbed_quantstats):
        """persist=True → backtests 1행 (실측 구간 + 메트릭). 결과 dict 와 일치."""
        from nuri.core.db import query
        from nuri.quant.backtest import engine

        prices = _make_prices_df(n_days=60)  # 2025-01-01 시작, 5개 US 종목
        pf = _make_stub_portfolio()
        with (
            patch.object(engine, "query_df", return_value=prices),
            patch.object(engine.vbt.Portfolio, "from_signals", return_value=pf),
        ):
            result = engine.run_momentum_backtest(top_n=3, rebalance_days=20, persist=True)

        rows = query("SELECT * FROM backtests", db_path=db_path_mp)
        assert len(rows) == 1
        r = rows[0]
        assert r["strategy_id"] == "Momentum Top-3"
        assert r["total_return"] == 12.5  # stub Total Return [%]
        assert r["sharpe"] == 1.4
        assert r["max_drawdown"] == -8.2
        assert r["win_rate"] == 62.0
        # 실측 가격 구간 (period 문자열이 아닌 실제 날짜)
        assert r["start_date"] == "2025-01-01"
        assert r["start_date"] == result["start_date"]
        assert r["end_date"] == result["end_date"]

    def test_default_call_writes_nothing(self, db_path_mp, stubbed_quantstats):
        """persist 인자 없이 호출(verify.py:203 스타일) → DB 미기록.

        default 가 False 임을 시그니처+동작 양쪽에서 잠근다 — production data/portfolio.db
        오염 방지. default 가 True 로 뒤집히거나 persist 분기가 제거되면 이 테스트가 깨진다.
        """
        import inspect

        from nuri.core.db import query
        from nuri.quant.backtest import engine

        # 시그니처 레벨 잠금: default 자체가 False (read-only 호출 보호 계약)
        sig = inspect.signature(engine.run_momentum_backtest)
        assert sig.parameters["persist"].default is False

        prices = _make_prices_df(n_days=60)
        pf = _make_stub_portfolio()
        with (
            patch.object(engine, "query_df", return_value=prices),
            patch.object(engine.vbt.Portfolio, "from_signals", return_value=pf),
        ):
            engine.run_momentum_backtest(top_n=3)  # persist 인자 없음 → default 적용

        assert query("SELECT * FROM backtests", db_path=db_path_mp) == []
