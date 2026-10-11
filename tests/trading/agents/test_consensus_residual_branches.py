"""합의 계층의 나머지 분기 — 저장 0건 CLI · 전원 default 가중치."""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest

import nuri.trading.agents.consensus as consensus_pkg
import nuri.trading.agents.consensus.__main__ as consensus_cli
from nuri.trading.agents.consensus.models import AgentEligibility
from nuri.trading.agents.consensus.registry import DEFAULT_WEIGHTS


def test_a_single_ticker_run_that_saves_nothing_still_records_the_decision(monkeypatch, caplog):
    """recommendations 저장이 0건이면 저장 로그를 내지 않지만, 의사결정 저널 기록은 그대로 간다."""
    result = SimpleNamespace(ticker="TST_A")
    recorded = []
    monkeypatch.setattr(sys, "argv", ["consensus", "--ticker", "TST_A"])
    monkeypatch.setattr(consensus_cli, "analyze_ticker", lambda ticker: result)
    monkeypatch.setattr(consensus_cli, "print_consensus", lambda results, verbose=False: None)
    monkeypatch.setattr(consensus_cli, "save_to_recommendations", lambda results: 0)
    monkeypatch.setattr(
        "nuri.trading.engine.decisions.record_decisions", lambda results: recorded.append(results) or len(results)
    )

    with caplog.at_level(logging.INFO, logger=consensus_cli.logger.name):
        consensus_cli.main()

    assert recorded == [[result]]
    assert "recommendations 테이블에" not in caplog.text
    assert "decisions 테이블에 1건 기록" in caplog.text


@pytest.fixture
def all_default(monkeypatch):
    """어느 agent 도 eligible 이 아니지만 표본은 있다 → 전원 `default` (structurally_unsaturating 아님)."""
    ineligible = {
        n: AgentEligibility(name=n, sample_count=5, weight=w, eligible=False) for n, w in DEFAULT_WEIGHTS.items()
    }
    monkeypatch.setattr(consensus_pkg, "compute_canonical_weights", lambda db_path=None: ineligible)
    monkeypatch.setattr(consensus_pkg, "compute_provisional_weights", lambda db_path=None: {})


def test_all_default_weights_log_no_source_line(all_default, caplog):
    with caplog.at_level(logging.DEBUG, logger=consensus_pkg.logger.name):
        weights = consensus_pkg._compute_weights_uncached()

    total = sum(DEFAULT_WEIGHTS.values())
    assert weights == pytest.approx({n: w / total for n, w in DEFAULT_WEIGHTS.items()})
    assert "_compute_weights per-agent" not in caplog.text
