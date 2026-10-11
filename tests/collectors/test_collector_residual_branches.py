"""collectors 의 나머지 분기 — 신선도 티커 집합 · 점수 없는 F&G · 같은 출처 묶음 · 실적 뒤 만기 없음."""

from __future__ import annotations

from datetime import date

from nuri.collectors import earnings_preview, external, fear_greed
from nuri.collectors.stock import _load_freshness_tickers


def test_freshness_tickers_skip_blank_and_non_yfinance_secondaries(monkeypatch):
    """보조 티커 중 빈 값과 yfinance 로 못 받는 지수(KOSPI)는 수집 목록에 넣지 않는다."""
    monkeypatch.setattr(
        "nuri.core.rules.RULES",
        {"freshness_tickers": {"us": {"primary": "TST_P", "secondary": ["", "KOSPI", "TST_S"]}}},
    )

    assert _load_freshness_tickers() == ["TST_P", "TST_S"]


def test_an_api_payload_without_a_score_yields_no_row(monkeypatch):
    """CNN 응답에 점수가 없으면 행을 만들지 않는다 — 0 이나 직전 값을 지어내지 않는다."""

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"fear_and_greed": {"rating": "neutral"}}

    monkeypatch.setattr(fear_greed.requests, "get", lambda *a, **k: _Resp())

    assert fear_greed.FearGreedCollector()._collect_api() == []


def test_rows_from_one_source_share_a_single_header(monkeypatch, capsys):
    monkeypatch.setattr(
        external,
        "get_external",
        lambda ticker, db_path=None: [
            {"source": "tipranks", "data_type": "consensus", "value": "Buy", "date": "2026-10-01"},
            {"source": "tipranks", "data_type": "target_price", "value": "250", "date": "2026-10-01"},
        ],
    )

    external.print_ticker_external("TST_A")

    out = capsys.readouterr().out
    header = f"[{external.SOURCES.get('tipranks', 'tipranks')}]"
    assert out.count(header) == 1
    assert "consensus: Buy" in out and "target_price: 250" in out


def test_without_an_expiry_after_earnings_the_first_one_past_the_cutoff_is_used(monkeypatch):
    """실적일 뒤 만기가 하나도 없으면 1순위를 포기하고 cutoff(오늘+2일) 이후 첫 만기로 간다."""
    monkeypatch.setattr(earnings_preview, "today_kst", lambda: "2026-10-07")

    chosen = earnings_preview._select_expiration(("2026-10-08", "2026-10-16", "2026-10-23"), date(2026, 11, 30))

    assert chosen == "2026-10-16"
