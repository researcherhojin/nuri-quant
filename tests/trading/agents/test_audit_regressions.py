"""합성 DB로 전수 조사에서 발견한 단위·범위·거부권 오류를 재현한다."""

from datetime import timedelta

import pytest

from nuri.core.db import OperationalError, get_db
from nuri.core.timezone import kst_now, today_kst
from nuri.core.valuation import holding_value_usd
from nuri.trading.agents.fundamental import FundamentalAgent
from nuri.trading.agents.korean_market import KoreanMarketAgent
from nuri.trading.agents.options_agent import OptionsAgent
from nuri.trading.agents.risk_agent import RiskAgent
from nuri.trading.agents.smart_money import SmartMoneyAgent
from nuri.trading.agents.technical import TechnicalAgent
from nuri.trading.agents.wallstreet import WallStreetAgent


def day(days=0):
    return (kst_now() - timedelta(days=days)).date().isoformat()


def holding(db_path, ticker="DEMO", price=89, quantity=1, currency="USD"):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio(account,ticker,quantity,avg_price,currency) VALUES('Demo',?,?,100,?)",
            (ticker, quantity, currency),
        )
        for i in range(30):
            value = price if i == 0 else (100 if i % 2 else 80)
            conn.execute("INSERT INTO prices(ticker,date,close) VALUES(?,?,?)", (ticker, day(i), value))


def test_loss_and_volatility_cannot_create_stop_veto(db_path, monkeypatch):
    holding(db_path)
    monkeypatch.setattr("nuri.trading.agents.risk_agent.get_stop_loss_for_account", lambda account: -20)
    verdict = RiskAgent().analyze("DEMO", db_path=db_path)
    assert verdict.data_points["score"] == -2
    assert verdict.action == "HOLD"
    assert verdict.alpha_action is None
    assert verdict.data_points["stop_loss_fired"] is False


def test_measured_stop_survives_volatility_db_failure(db_path, monkeypatch):
    holding(db_path, price=50)

    def fail(*args, **kwargs):
        raise OperationalError("synthetic failure")

    monkeypatch.setattr("nuri.trading.agents.risk_agent.query_df", fail)
    verdict = RiskAgent().analyze("DEMO", db_path=db_path)
    assert verdict.action == "SELL" and verdict.alpha_action == "FLAT"
    assert not verdict.degraded


def test_closed_position_cannot_fire_a_stop(db_path):
    holding(db_path, price=50, quantity=0)
    assert RiskAgent().analyze("DEMO", db_path=db_path).alpha_action is None


def test_mixed_currency_weight_uses_market_value(db_path):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio(account,ticker,quantity,avg_price,currency) VALUES('Demo','KRDEMO.KS',1,100000,'KRW')"
        )
        conn.execute(
            "INSERT INTO portfolio(account,ticker,quantity,avg_price,currency) VALUES('Demo','USDEMO',1,1000,'USD')"
        )
        conn.execute("INSERT INTO prices(ticker,date,close) VALUES('KRDEMO.KS',?,100000)", (day(),))
        conn.execute("INSERT INTO prices(ticker,date,close) VALUES('USDEMO',?,1000)", (day(),))
        conn.execute("INSERT INTO macro(indicator,date,value) VALUES('usd_krw',?,1000)", (day(),))
    verdict = RiskAgent().analyze("KRDEMO.KS", db_path=db_path)
    assert verdict.data_points["position_pct"] == pytest.approx(100 / 1100 * 100)
    assert verdict.portfolio_action is None
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM macro")
    assert RiskAgent().analyze("USDEMO", db_path=db_path).data_points["position_pct"] is None


@pytest.mark.parametrize(
    "quantity,price,rate",
    [("invalid", 1, 1000), (1, "invalid", 1000), (1, 1, "invalid"), (1, float("inf"), 1000), (-1, -1, 1000)],
)
def test_malformed_valuation_is_unknown(quantity, price, rate):
    assert holding_value_usd("DEMO.KS", "KRW", quantity, price, rate) is None


@pytest.mark.parametrize("percent,expected", [(100, "BUY"), (300, "HOLD")])
def test_debt_percentage_matches_ratio_rule(db_path, percent, expected):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO fundamentals(ticker,date,pe_ratio,debt_to_equity) VALUES('DEMO',?,10,?)", (day(), percent)
        )
    verdict = FundamentalAgent().analyze("DEMO", db_path=db_path)
    assert verdict.action == expected
    assert verdict.data_points["debt"] == percent / 100
    assert "100.0x" not in verdict.reasoning


def test_kosdaq_suffix_is_a_domestic_market(db_path):
    holding(db_path, ticker="000001.KQ", price=100, currency="KRW")
    verdict = KoreanMarketAgent().analyze("000001.KQ", db_path=db_path)
    assert verdict.data_points["is_korean"]
    assert verdict.data_points["market"] == "KOSDAQ"
    assert not verdict.abstained


def test_flat_prices_do_not_invent_a_macd_sell(db_path, monkeypatch):
    with get_db(db_path) as conn:
        for i in range(200):
            conn.execute("INSERT INTO prices(ticker,date,close) VALUES('DEMO',?,100)", (day(i),))
    monkeypatch.setattr("nuri.trading.agents.technical.analyze_chart", lambda *args, **kwargs: None)
    verdict = TechnicalAgent().analyze("DEMO", db_path=db_path)
    assert verdict.action == "HOLD"
    assert "MACD<Signal" not in verdict.reasoning


def test_13f_latest_filing_deduplicates_and_detects_exit(db_path):
    with get_db(db_path) as conn:
        for ago in [90, 0]:
            conn.execute(
                "INSERT INTO superinvestors(investor,filing_date,ticker,portfolio_pct) VALUES('Demo Manager',?,'DEMO',6)",
                (day(ago),),
            )
    verdict = SmartMoneyAgent().analyze("DEMO", db_path=db_path)
    assert verdict.data_points["n_superinvestors"] == 1
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM superinvestors WHERE ticker='DEMO' AND filing_date=?", (day(),))
        conn.execute(
            "INSERT INTO superinvestors(investor,filing_date,ticker,portfolio_pct) VALUES('Demo Manager',?,'OTHER',6)",
            (day(),),
        )
    verdict = SmartMoneyAgent().analyze("DEMO", db_path=db_path)
    assert verdict.data_points["n_superinvestors"] == 0
    assert verdict.abstained


def test_first_13f_observation_is_not_a_new_purchase(db_path):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO superinvestors(investor,filing_date,ticker,portfolio_pct) VALUES('Demo Manager',?,'DEMO',1)",
            (day(),),
        )
    assert "신규 매수" not in SmartMoneyAgent().analyze("DEMO", db_path=db_path).reasoning


# 출처로 거르지 않는다 — 운영 PCR 은 yfinance_SPY 뿐이라(CBOE 는 2026-08-30 부터 403) 출처 조건은
# 옵션 표를 매일 전 종목 기권으로 만든다. SPY 단일 만기 값의 스케일 문제는 별도 이슈로 다룬다.
@pytest.mark.parametrize("source,ago", [("yfinance_SPY", 30), ("CBOE", 30)])
def test_stale_pcr_cannot_cast_an_absolute_vote(db_path, source, ago):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro(indicator,date,value,source) VALUES('put_call_ratio',?,1.5,?)", (day(ago), source)
        )
    verdict = OptionsAgent().analyze("DEMO", db_path=db_path)
    assert verdict.abstained and verdict.confidence == 0
    assert verdict.data_points["scope"] == "us_market"


def test_current_yfinance_pcr_still_votes(db_path):
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO macro(indicator,date,value,source) VALUES('put_call_ratio',?,1.5,'yfinance_SPY')", (day(),)
        )
    verdict = OptionsAgent().analyze("DEMO", db_path=db_path)
    assert not verdict.abstained
    assert verdict.data_points["source"] == "yfinance_SPY"


def test_pcr_source_change_is_not_averaged(db_path):
    with get_db(db_path) as conn:
        conn.execute("INSERT INTO macro(indicator,date,value,source) VALUES('put_call_ratio',?,0.5,'CBOE')", (day(),))
        conn.execute(
            "INSERT INTO macro(indicator,date,value,source) VALUES('put_call_ratio',?,10,'yfinance_SPY')", (day(1),)
        )
    verdict = OptionsAgent().analyze("DEMO", db_path=db_path)
    assert verdict.data_points["pcr_avg"] == 0.5
    assert verdict.data_points["lookback_count"] == 1


def test_old_wallstreet_cache_cannot_create_current_sell(db_path):
    with get_db(db_path) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO analyst_ratings(ticker,date,firm,action) VALUES('DEMO',? ,?,'down')",
                (day(300 + i), f"Firm{i}"),
            )
    assert WallStreetAgent()._check_cached("DEMO", db_path=db_path) is None


@pytest.mark.parametrize("dated,ago", [(True, 300), (False, 1), (True, -2)])
def test_remote_wallstreet_unverified_dates_cannot_vote(db_path, monkeypatch, dated, ago):
    from types import SimpleNamespace

    import pandas as pd
    import yfinance

    index = pd.DatetimeIndex([kst_now() - timedelta(days=ago)]) if dated else pd.RangeIndex(1)
    remote = SimpleNamespace(
        upgrades_downgrades=None,
        earnings_history=pd.DataFrame([{"surprisePercent": -0.5}], index=index),
        insider_transactions=pd.DataFrame(
            [{"Text": "Sale"}] * 5, index=pd.DatetimeIndex([kst_now() - timedelta(days=300)] * 5)
        ),
        recommendations=None,
    )
    monkeypatch.setattr(yfinance, "Ticker", lambda ticker: remote)
    verdict = WallStreetAgent().analyze("DEMO", db_path=db_path)
    assert verdict.abstained and verdict.action == "HOLD"
    assert "earnings_surprise" not in verdict.data_points
    assert verdict.data_points.get("insider_sells", 0) == 0


def test_korean_calibration_failure_is_reported(db_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("synthetic calibration failure")

    monkeypatch.setattr("nuri.trading.agents.korean_market.query_df", fail)
    verdict = KoreanMarketAgent().analyze("DEMO.KQ", db_path=db_path)
    assert verdict.degraded and not verdict.abstained
    assert "fx_calibration" in verdict.data_points["read_failures"]


def test_null_latest_price_cannot_claim_normal_risk(db_path):
    holding(db_path, price=50)
    with get_db(db_path) as conn:
        conn.execute("UPDATE prices SET close=NULL WHERE ticker='DEMO' AND date=?", (day(),))
    verdict = RiskAgent().analyze("DEMO", db_path=db_path)
    assert verdict.degraded and verdict.confidence == 0
    assert verdict.alpha_action is None
    assert "손절 점검 미실행" in verdict.reasoning
