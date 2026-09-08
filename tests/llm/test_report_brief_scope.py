"""#1499 — `gather_context()` 한 번에 가중치 원장 스캔 1회, 레짐 분류 1회.

mini 실측: 34.6s 중 22s 가 `compute_canonical_weights` ×18 + `classify_regime` ×23 이었다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    init_db(path)
    return path


def _count_weights_and_regime(monkeypatch):
    from nuri.quant.regime import classifier
    from nuri.trading.agents import consensus as consensus_pkg

    counts = {"weights": 0, "regime": 0}
    real_w = consensus_pkg.compute_canonical_weights
    real_f = classifier._check_data_freshness

    def w(*a, **k):
        counts["weights"] += 1
        return real_w(*a, **k)

    def f(*a, **k):
        counts["regime"] += 1
        return real_f(*a, **k)

    monkeypatch.setattr(consensus_pkg, "compute_canonical_weights", w)  # _compute_weights 가 참조하는 이름
    monkeypatch.setattr(classifier, "_check_data_freshness", f)  # classify_regime 본체의 첫 줄 — 본체 진입 횟수
    return counts


def test_three_tickers_in_one_scope_share_weights_and_regime(db_path, monkeypatch):
    """gather_context → map_regime_to_strategy 가 하는 일: 한 범위 안에서 종목마다 analyze_ticker.
    가중치 원장 스캔과 레짐 본체(macro_agent 가 종목마다 부른다)는 그래도 1회여야 한다."""
    from nuri.core.brief_scope import brief_scope
    from nuri.trading.agents.consensus import analyze_ticker

    counts = _count_weights_and_regime(monkeypatch)
    with brief_scope():
        for t in ("AAA", "BBB", "CCC"):
            analyze_ticker(t, db_path=db_path)
    assert counts["weights"] == 1, f"가중치 원장 스캔 {counts['weights']}회 — 종목마다 다시 돈다"
    assert counts["regime"] == 1, f"레짐 분류 본체 {counts['regime']}회 — 종목마다 다시 돈다"


def test_gather_context_opens_one_scope(db_path, monkeypatch):
    """빈 DB 라 consensus 는 안 돌지만(레짐 None) 레짐 본체는 섹션마다 부르던 것이 1회로 준다."""
    from nuri.llm.report import gather_context

    counts = _count_weights_and_regime(monkeypatch)
    gather_context(db_path=db_path)
    assert counts["regime"] == 1, f"레짐 분류 본체 {counts['regime']}회"
    assert counts["weights"] <= 1


def test_outside_a_brief_nothing_is_cached(db_path, monkeypatch):
    """스케줄러는 07:02 outcome 갱신 뒤 07:05 consensus 를 같은 프로세스에서 돌린다 — 범위 밖 캐시는 낡은 가중치다."""
    from nuri.trading.agents import consensus as consensus_pkg
    from nuri.trading.agents.consensus import _compute_weights

    counts = {"n": 0}
    real = consensus_pkg.compute_canonical_weights

    def w(*a, **k):
        counts["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(consensus_pkg, "compute_canonical_weights", w)
    _compute_weights(db_path)
    _compute_weights(db_path)
    assert counts["n"] == 2
