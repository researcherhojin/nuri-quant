"""e2e 용 합성 seed DB 생성 (#1240 — #1234 e2e CI 배선의 선행 조건).

CI 에는 populated `data/portfolio.db` 가 없다 (gitignored, private). 이 스크립트가
privacy-safe 합성 데이터로 e2e 가 의미 있게 도는 DB 를 만든다.

Privacy 규칙 (tests/CLAUDE.md): 실제 보유 종목·수량·가격·계좌명 금지 —
가짜 티커(AAA/BBB/CCC) + 지수 ETF(SPY/QQQ) + `Brokerage Alpha/Beta` 플레이스홀더,
라운드 값만. 날짜는 전부 오늘 앵커 (time-bomb 규칙 — 리터럴 날짜는 wall-clock 이
지나며 윈도우 밖으로 밀려 조용히 죽는다).

사용: .venv/bin/python scripts/dev/seed_e2e_db.py --db /tmp/e2e.db
`--db` 는 필수 — 기본값을 두면 dev DB 를 오염시키는 사고 경로가 생긴다.
"""

import argparse
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from nuri.core.db import (
    get_db,
    init_db,
    upsert_decision,
    upsert_macro,
    upsert_macro_events,
    upsert_portfolio,
    upsert_prices,
    upsert_signals,
)
from nuri.core.timezone import kst_now, today_kst

RNG_SEED = 20260826  # 결정론 — 같은 날짜에 같은 DB


def _price_frame(ticker: str, days: int, base: float, drift: float, rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(today_kst()), periods=days)
    steps = rng.normal(loc=drift, scale=0.01, size=days)
    closes = base * np.cumprod(1 + steps)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates.strftime("%Y-%m-%d"),
            "open": closes * 0.995,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1_000_000,
            "adj_close": closes,
        }
    )


def seed(db: Path) -> dict[str, int]:
    init_db(db)
    rng = np.random.default_rng(RNG_SEED)
    counts: dict[str, int] = {}

    # ── 가격: SPY 300 영업일 (SMA200/레짐 분류 요건), 나머지 120 ──
    frames = [
        _price_frame("SPY", 300, 500.0, 0.0006, rng),
        _price_frame("QQQ", 300, 400.0, 0.0007, rng),
        _price_frame("AAA", 120, 100.0, 0.001, rng),
        _price_frame("BBB", 120, 50.0, -0.003, rng),  # 손절선 위반 시나리오 (-25%대)
        _price_frame("CCC", 120, 200.0, 0.0005, rng),
    ]
    # 스캐너/기회탐색용 — 유니버스(공개 config) 티커 3종. 마지막 날 거래량 3배 →
    # scan_market 의 volume_spike (vol_ratio>=2) 가 결정론적으로 발화, 비보유라
    # /api/opportunities 에 잡힌다 (#1234 e2e 요건).
    # KR 한 종목 — `/explore` 한국어 검색 스펙(`search-result-005930.KS`)이 이름 해석을
    # 요구한다. CI 에는 `config/kr_ticker_names.json`(gitignored)이 없으므로 이름은
    # 아래 portfolio.metadata(=`get_ticker_name_local` 1차)에서 온다 (#1255).
    frames.append(_price_frame("005930.KS", 120, 70000.0, 0.0004, rng))
    for t, base in [("AAPL", 180.0), ("MSFT", 400.0), ("AMZN", 170.0)]:
        f = _price_frame(t, 60, base, 0.002, rng)
        f.loc[f.index[-1], "volume"] = 3_000_000
        frames.append(f)
    counts["prices"] = sum(upsert_prices(f, db_path=db) for f in frames)

    # ── 포트폴리오: 두 플레이스홀더 계좌, 라운드 값 ──
    counts["portfolio"] = upsert_portfolio(
        [
            {
                "account": "Brokerage Alpha",
                "ticker": "AAA",
                "quantity": 10,
                "avg_price": 90.0,
                "currency": "USD",
                "sector": "SectorA",
            },
            {
                "account": "Brokerage Alpha",
                "ticker": "SPY",
                "quantity": 5,
                "avg_price": 480.0,
                "currency": "USD",
                "sector": "ETF/Index",
            },
            {
                # 공개 지수 구성종목 — 합성 수량/계좌. `metadata.name` 이
                # `get_ticker_name_local` 1차(portfolio.metadata)를 만족시켜,
                # 맵 파일 없이도 CI 에서 "삼성" 검색이 결정론적으로 이 행을 찾는다.
                "account": "Brokerage Alpha",
                "ticker": "005930.KS",
                "quantity": 10,
                "avg_price": 70000.0,
                "currency": "KRW",
                "sector": "반도체",
                "metadata": json.dumps({"name": "삼성전자"}, ensure_ascii=False),
            },
            {
                "account": "Brokerage Beta",
                "ticker": "BBB",
                "quantity": 20,
                "avg_price": 60.0,
                "currency": "USD",
                "sector": "SectorB",
            },
            {
                "account": "Brokerage Beta",
                "ticker": "CCC",
                "quantity": 4,
                "avg_price": 180.0,
                "currency": "USD",
                "sector": "SectorC",
            },
        ],
        db_path=db,
    )

    # ── 매크로: VIX 252d, fear_greed 90d, 환율 ──
    dates = pd.bdate_range(end=pd.Timestamp(today_kst()), periods=252).strftime("%Y-%m-%d")
    vix = [
        {"indicator": "vix", "date": d, "value": round(float(v), 2), "source": "seed"}
        for d, v in zip(dates, 15 + 8 * rng.random(252))
    ]
    fg_dates = dates[-90:]
    fg = [
        {"indicator": "fear_greed", "date": d, "value": round(float(v), 1), "source": "seed"}
        for d, v in zip(fg_dates, 35 + 40 * rng.random(90))
    ]
    fx = [{"indicator": "usd_krw", "date": dates[-1], "value": 1400.0, "source": "seed"}]
    # ── compute_macro_score 의 나머지 7개 지표 (nuri/quant/regime/macro_score.py) ──
    # 없으면 스코어러가 성분을 제외하고 지표당 경고를 찍는다 — e2e 로그가 "매크로 지표
    # 누락" 42줄로 덮여 실제 오류가 안 보이고, 89개 테스트 전부가 **결측-축소 경로만**
    # 밟는다 (전 지표 경로는 미검증). 값은 중립 레짐의 그럴듯한 상수, 행은 2개
    # (최신 + 252d 전) — _get_macro_trend 의 3개월 lookback 까지 충족.
    STEADY = {
        "us_10y_yield": 4.25,
        "us_2y_yield": 3.85,
        "us_3m_yield": 4.05,
        "put_call_ratio": 0.90,
        "unemployment": 4.1,
        "cpi_yoy": 2.7,
        "fed_funds_rate": 4.00,
    }
    steady = [
        {"indicator": name, "date": d, "value": value, "source": "seed"}
        for name, value in STEADY.items()
        for d in (dates[0], dates[-1])
    ]
    counts["macro"] = upsert_macro(vix + fg + fx + steady, db_path=db)

    # ── 매크로 이벤트: 최근 3일 내 발행 (action-first 스펙의 7d 신선도 요건) ──
    #
    # ⚠️ 형태는 **소비자에서 복사한다** (#1262). 이전 판은 두 축이 다 어긋나 있었고,
    # 그 결과 CI e2e 전 구간에서 매크로/이벤트 스코어 체인이 죽은 채 89개 테스트가 돌았다:
    #   1. `sentiment` 를 문자열("positive")로 썼다 — 스키마는 `REAL`(migration:480)이고 prod
    #      5,062행은 전부 숫자다. SQLite 동적 타입이라 제약이 안 걸리고,
    #      `event_score.py:142` 의 `abs(sentiment)` 가 TypeError 로 터진다 →
    #      `compute_macro_score` → `map_regime_to_strategy` → `/api/rebalance` 가 **200 + error** 를 냈다.
    #   2. 카테고리가 `event_score.CATEGORY_WEIGHT` 어휘 밖이었다 (교집합 0개). 타입만 고치면
    #      `CATEGORY_WEIGHT.get(cat, 0.0)` 이 전부 0 을 줘서 예외는 없어지되 점수가 **정확히 0** 이다.
    # 그래서 카테고리는 어휘에서, sentiment 는 prod 관측 범위(-0.9~0.9)에서 고른다.
    now = kst_now()
    events = []
    for i, (headline, category, sentiment) in enumerate(
        [
            ("Central bank holds policy rate steady", "neutral", 0.05),
            ("Inflation print lands below forecast", "fed_dovish", 0.45),
            ("Chip sector guidance raised", "earnings_beat", 0.60),
            ("Oil supply disruption flagged", "oil_supply_shock", -0.50),
            ("Export volumes surge on strong demand", "export_surge", 0.70),
        ]
    ):
        events.append(
            {
                "published_at": (now - timedelta(days=i % 3, hours=i)).isoformat(),
                "source": "seed",
                "query_keyword": category,
                "headline": headline,
                "url": f"https://example.com/seed-{i}",
                "category": category,
                "sentiment": sentiment,
                "confidence": 0.8,
                "regime_hint": None,
                "raw_json": json.dumps({"seed": True}),
            }
        )
    counts["macro_events"] = upsert_macro_events(events, db_path=db)

    # ── 시그널: 최신일 지표 (signals 페이지/차트용) ──
    latest = dates[-1]
    sig_rows = []
    for t, rsi in [("AAA", 28.0), ("BBB", 72.0), ("CCC", 55.0)]:
        sig_rows.append(
            {
                "ticker": t,
                "date": latest,
                "rsi_14": rsi,
                "macd": 0.5,
                "macd_signal": 0.3,
                "macd_hist": 0.2,
                "bb_upper": 110.0,
                "bb_middle": 100.0,
                "bb_lower": 90.0,
                "sma_20": 100.0,
                "sma_50": 98.0,
                "sma_200": 95.0,
                "ema_12": 101.0,
                "ema_26": 99.0,
            }
        )
    counts["signals"] = upsert_signals(pd.DataFrame(sig_rows), db_path=db)

    # ── 의사결정: 판정 저널/상세 라우트용 3건 ──
    # 날짜는 recommendations 와 동일한 today — /api/actions·/api/dashboard 의
    # 증거 체인 join (#1182) 이 same-date (`d.date = r.date`) 라 어긋나면
    # decision_id 가 영영 NULL 이다 (codex #1241 P2).
    today = today_kst()
    for ticker, action, conf in [("AAA", "BUY", 0.7), ("BBB", "SELL", 0.6), ("CCC", "HOLD", 0.5)]:
        upsert_decision(
            {
                "date": today,
                "ticker": ticker,
                "action": action,
                "confidence": conf,
                "regime": "bull_low_vol",
                "vix": 18.0,
                "fear_greed": 55.0,
                "agreement_rate": 0.8,
                "reasoning": "seed decision for e2e",
                "entry_price": 100.0,
                "stop_loss": 93.0,
                "target_1": 120.0,
                "target_2": 140.0,
            },
            db_path=db,
        )
    counts["decisions"] = 3

    # ── recommendations: /api/actions 의 소스 (source IS NULL = 합의 산출물) ──
    with get_db(db) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO recommendations
               (date, ticker, action, confidence, regime, signals)
               VALUES (:date, :ticker, :action, :confidence, :regime, :signals)""",
            [
                # signals 는 dict JSON — 소비자가 .get("agreement_rate") 한다 (실 작성자 형태 복사)
                {
                    "date": today,
                    "ticker": "AAA",
                    "action": "HOLD",
                    "confidence": 65.0,
                    "regime": "bull_low_vol",
                    "signals": json.dumps({"agreement_rate": 0.7}),
                },
                {
                    "date": today,
                    "ticker": "BBB",
                    "action": "SELL",
                    "confidence": 72.0,
                    "regime": "bull_low_vol",
                    "signals": json.dumps({"agreement_rate": 0.8}),
                },
                {
                    "date": today,
                    "ticker": "CCC",
                    "action": "BUY",
                    "confidence": 80.0,
                    "regime": "bull_low_vol",
                    "signals": json.dumps({"agreement_rate": 0.9}),
                },
            ],
        )
    counts["recommendations"] = 3
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="e2e 합성 seed DB 생성")
    parser.add_argument("--db", required=True, help="생성할 DB 경로 (필수 — dev DB 오염 방지)")
    args = parser.parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    counts = seed(db)
    print(f"seeded {db}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
