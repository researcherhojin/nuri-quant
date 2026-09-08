"""#1485 — crypto / fundamental / options / retail: NaN/±inf 입력은 '없음' 이지 값이 아니다.

#1479(technical) → #1481(korean_market · wallstreet) 와 같은 클래스. macro / fundamentals 의 REAL 컬럼에
NaN 이 들어오면 `is not None` 게이트를 통과해 판정과 data_points 로 새고, /api/consensus 의 strict
json.dumps 가 500 으로 죽는다. 네 에이전트 전부 `allow_nan=False` 로 잠근다.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from nuri.core.db import get_db


def _macro(db_path, indicator, value, date="2026-09-01"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO macro (indicator, date, value, source) VALUES (?, ?, ?, ?)",
            (indicator, date, value, "test"),
        )


NAN = float("nan")
INF = float("inf")


class TestCryptoAgent:
    def test_nan_change_and_inf_dominance_are_absent(self, db_path):
        from nuri.trading.agents.crypto_agent import CryptoAgent

        _macro(db_path, "btc_24h_change_pct", NAN)
        _macro(db_path, "btc_dominance", INF)
        _macro(db_path, "btc_usd_cg", NAN)
        v = CryptoAgent().analyze("BTC", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "btc_24h_change" not in v.data_points
        assert "btc_dominance" not in v.data_points
        assert "btc_price" not in v.data_points
        assert v.abstained  # 값이 전부 부재 → 기권, 판정 아님


class TestFundamentalAgent:
    def test_nan_fields_count_as_missing(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("NANF", "2026-09-01", NAN, INF, NAN, -INF),
            )
        v = FundamentalAgent().analyze("NANF", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.data_points == {"pe": None, "roe": None, "growth": None, "debt": None}
        assert v.confidence == 0  # 전부-NULL 게이트와 같은 출구

    def test_partial_nan_keeps_the_finite_fields(self, db_path):
        from nuri.trading.agents.fundamental import FundamentalAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe, revenue_growth, debt_to_equity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("MIXF", "2026-09-01", 10.0, NAN, 0.30, 1.0),
            )
        v = FundamentalAgent().analyze("MIXF", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.data_points["pe"] == 10.0 and v.data_points["roe"] is None
        assert v.action == "BUY"


class TestOptionsAgent:
    def test_nan_rows_do_not_enter_the_pcr_average(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent

        for i, val in enumerate([NAN, INF, 1.5, NAN, 1.3]):
            _macro(db_path, "put_call_ratio", val, date=f"2026-09-0{i + 1}")
        v = OptionsAgent().analyze("SPY", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.data_points["pcr_avg"] == pytest.approx(1.4)  # (1.5 + 1.3) / 2 — NaN/inf 가 섞이면 NaN
        assert v.data_points["lookback_count"] == 2
        assert "공포" in v.reasoning

    def test_all_nan_rows_abstain_like_null(self, db_path):
        from nuri.trading.agents.options_agent import OptionsAgent

        for i in range(3):
            _macro(db_path, "put_call_ratio", NAN, date=f"2026-09-0{i + 1}")
        v = OptionsAgent().analyze("SPY", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.abstained and v.action == "HOLD"


class TestRetailAgent:
    def test_nan_mentions_and_inf_posts_are_absent(self, db_path):
        from nuri.trading.agents.retail_agent import RetailAgent

        _macro(db_path, "wsb_mention_GME", NAN)
        _macro(db_path, "wsb_post_count", INF)
        v = RetailAgent().analyze("GME", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "wsb_mentions" not in v.data_points
        assert "wsb_post_count" not in v.data_points
        assert v.abstained


# ── SQLite 는 NaN 을 NULL 로 저장한다. 진짜 NaN 경로는 DB 를 거치지 않는 값(yfinance 프레임, 캐시 dict,
#    `_safe_query` 를 우회한 주입)에서만 생기므로 아래는 `_safe_query` 를 patch 해 NaN 을 그대로 흘린다 (Codex P2).
from nuri.trading.agents.base import QueryRows  # noqa: E402


def _rows(*dicts):
    return QueryRows(list(dicts))


class TestRawNanViaSafeQuery:
    def test_crypto_nan_rows_abstain(self, db_path, monkeypatch):
        from nuri.trading.agents.crypto_agent import CryptoAgent

        calls = iter([_rows({"value": NAN}), _rows({"value": NAN}), _rows({"value": NAN})])
        monkeypatch.setattr(CryptoAgent, "_safe_query", lambda self, *a, **k: next(calls))
        v = CryptoAgent().analyze("BTC", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.abstained and v.data_points == {}

    def test_fundamental_nan_row_abstains_not_holds(self, db_path, monkeypatch):
        from nuri.trading.agents.fundamental import FundamentalAgent

        monkeypatch.setattr(
            FundamentalAgent,
            "_safe_query",
            lambda self, *a, **k: _rows({"pe_ratio": NAN, "roe": NAN, "revenue_growth": NAN, "debt_to_equity": NAN}),
        )
        v = FundamentalAgent().analyze("NANF", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.abstained and v.confidence == 0
        assert v.data_points == {"pe": None, "roe": None, "growth": None, "debt": None}

    def test_options_nan_rows_abstain(self, db_path, monkeypatch):
        from nuri.trading.agents.options_agent import OptionsAgent

        monkeypatch.setattr(OptionsAgent, "_safe_query", lambda self, *a, **k: _rows({"value": NAN}, {"value": NAN}))
        v = OptionsAgent().analyze("SPY", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.abstained

    def test_retail_nan_rows_abstain(self, db_path, monkeypatch):
        from nuri.trading.agents.retail_agent import RetailAgent

        calls = iter([_rows({"value": NAN}), _rows({"value": NAN})])
        monkeypatch.setattr(RetailAgent, "_safe_query", lambda self, *a, **k: next(calls))
        v = RetailAgent().analyze("GME", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert v.abstained and v.data_points == {}


class TestRiskAgentVeto:
    def test_negative_infinite_price_does_not_fire_the_stop_loss_veto(self, db_path):
        """-inf 는 truthy — (current-avg)/avg 가 -inf 라 손절 돌파로 읽혀 100 확신 FLAT 거부권이 발동했다 (Codex P1)."""
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
                ("test", "INFP", 10, 100.0),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INFP", "2026-09-01", 1, 1, 1, -INF, 1),
            )
        v = RiskAgent().analyze("INFP", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "손절선" not in v.reasoning
        assert v.alpha_action != "FLAT"
        assert v.confidence < 80  # 거부권 임계 아래

    def test_infinite_avg_price_row_is_skipped(self, db_path):
        from nuri.trading.agents.risk_agent import RiskAgent

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)",
                ("test", "INFA", 10, INF),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("INFA", "2026-09-01", 1, 1, 1, 50.0, 1),
            )
        v = RiskAgent().analyze("INFA", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "손절선" not in v.reasoning and "손실 중" not in v.reasoning


class TestSmartMoneyTargets:
    def test_negative_infinite_target_does_not_sell(self, db_path, monkeypatch):
        from nuri.trading.agents import smart_money as mod

        real = mod.SmartMoneyAgent._safe_query

        def fake(self, sql, params=(), db_path=None):
            if "FROM estimates" in sql and "MAX" not in sql:
                return _rows(
                    {"date": "2099-01-01", "recommendation": "hold", "target_mean": -INF, "current_price": 100.0}
                )
            return real(self, sql, params, db_path)

        monkeypatch.setattr(mod.SmartMoneyAgent, "_safe_query", fake)
        v = mod.SmartMoneyAgent().analyze("INFT", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "하락" not in v.reasoning and v.action != "SELL"


class TestWallstreetCachedPath:
    def test_cached_negative_infinite_surprise_does_not_sell(self, db_path, monkeypatch):
        """캐시 경로(`_check_cached`)는 라이브 경로의 정제를 우회했다 — -inf surprise 가 SELL 을 만들었다 (Codex P2)."""
        from nuri.trading.agents import wallstreet as mod

        def fake(self, sql, params=(), db_path=None):
            if "earnings_surprises" in sql:
                return _rows({"surprise_pct": -INF})
            return QueryRows([])

        monkeypatch.setattr(mod.WallStreetAgent, "_safe_query", fake)
        v = mod.WallStreetAgent().analyze("CINF", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "실적" not in v.reasoning and v.action != "SELL"


class TestMacroMomentum:
    def test_non_finite_closes_are_not_candles(self, db_path, monkeypatch):
        from types import SimpleNamespace

        from nuri.trading.agents.macro_agent import MacroAgent

        # 테스트 DB 엔 SPY 가 없어 레짐이 None → 모멘텀 블록 전에 기권한다. 횡보 레짐을 주입해 블록에 들어가게 한다.
        monkeypatch.setattr(
            "nuri.quant.regime.classifier.classify_regime",
            lambda db_path=None: SimpleNamespace(trend="sideways", regime="sideways", confidence=0.6, details={}),
        )
        monkeypatch.setattr(
            "nuri.quant.regime.macro_score.compute_macro_score", lambda db_path=None: SimpleNamespace(total_score=50)
        )
        with get_db(db_path) as conn:
            for i in range(12):
                conn.execute(
                    "INSERT INTO prices (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    # 최신 3캔들이 -inf (DESC 정렬이라 closes[0..2]) → 예전 산식은 ret_5d=-inf 로 '약세' 를 찍었다
                    ("MINF", f"2026-08-{i + 1:02d}", 1, 1, 1, -INF if i >= 9 else 100.0 + i, 1),
                )
        v = MacroAgent().analyze("MINF", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        assert "약세" not in v.reasoning


class TestTechnicalChartMetrics:
    def test_infinite_chart_metrics_do_not_count_as_signals(self, db_path, monkeypatch):
        from types import SimpleNamespace

        from nuri.trading.agents import technical as mod
        from tests.trading.agents._helpers import _seed_ticker

        _seed_ticker(db_path, "CHRT", n=60)
        chart = SimpleNamespace(
            price=100.0,
            macd_turn="none",
            bb_position=INF,
            dist_from_52w_low=-INF,
            dist_from_52w_high=INF,
            trend_strength=INF,
            poc_price=NAN,
            visual_bias="neutral",
        )
        monkeypatch.setattr(mod, "analyze_chart", lambda *a, **k: chart)
        v = mod.TechnicalAgent().analyze("CHRT", db_path=db_path)
        json.dumps(asdict(v), allow_nan=False)
        for token in ("BB 상단", "BB 하단", "52주", "추세강세", "추세약세"):
            assert token not in v.reasoning


class TestKoreanEventConfidence:
    @pytest.mark.parametrize("bad", [NAN, INF])
    def test_non_finite_event_confidence_falls_back_to_default(self, db_path, monkeypatch, bad):
        """`avg_conf or 0.5` 는 NaN 을 못 거른다 — `int(min(cnt*nan*3, 8))` 이 ValueError 로 에이전트를 죽였고,
        inf 는 최대 부스트로 둔갑했다 (Codex P2). 둘 다 기본 0.5 로 떨어져야 한다."""
        from nuri.trading.agents import korean_market as mod

        def fake(self, sql, params=(), db_path=None):
            if "macro_events" in sql:
                return _rows({"category": "export_surge", "cnt": 3, "avg_conf": bad})
            return QueryRows([])

        monkeypatch.setattr(mod.KoreanMarketAgent, "_safe_query", fake)
        boost = mod.KoreanMarketAgent()._get_macro_event_boost("Semiconductor", db_path=db_path)
        assert boost == int(min(3 * 0.5 * 3, 8))
