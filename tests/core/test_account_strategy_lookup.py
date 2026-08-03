"""계좌 전략 조회가 id·label·name 을 모두 받는지 잠근다 (#994).

Gotcha-Test Pair:
`portfolio.yaml` 은 계좌를 **id** 로 키잉하고(`toss`), DB/API 는 **label** 을 들고
다닌다(`Toss`). 조회가 id 만 보던 탓에 label 로 물으면 매칭에 실패했고, 실패가 예외가
아니라 조용한 폴백(`core`, stop_loss -7)이라 **전 계좌가 -7 로 평가**됐다.

2026-08-03 실측: Toss(long_term, 손절 -20%) 보유가 **-19.6% 에서 urgent SELL** 로 떴다.
돌파가 아닌데 기계적 청산 신호가 나간 것이다. `actions.py` 의 "A-3: 하드코딩 -7 제거"
주석은 그 시점에 이미 거짓이었다 — 코드는 계좌를 물어보는 모양만 갖췄고 값은 늘 -7 이었다.

영향 3 call site: `api/routes/actions.py`(대시보드) · `alerts/risk_signals.py`(Discord
Tier-1 손절) · `trading/agents/risk_agent.py`(consensus).

같은 폴백이 `get_account_strategy_name()` 에도 있었다. 이건 **연금 제외 판정**에 쓰이므로,
label 로 조회되는 경로에서는 연금이 일일 액션에서 안 빠졌다.
"""

from __future__ import annotations

import textwrap

import pytest

from nuri.core import rules


@pytest.fixture
def portfolio_yaml(tmp_path, monkeypatch):
    """실제 사용자 portfolio.yaml 대신 픽스처를 쓴다 (public repo — privacy)."""
    path = tmp_path / "portfolio.yaml"
    path.write_text(
        textwrap.dedent(
            """
            accounts:
              brokerage_alpha:
                name: Brokerage Alpha 기본계좌
                label: Alpha Main
                strategy: core
              brokerage_beta:
                name: Brokerage Beta 장기계좌
                label: Beta Long
                strategy: long_term
              retirement:
                name: 퇴직연금
                label: 연금
                strategy: pension
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rules, "PORTFOLIO_PATH", path)
    return path


@pytest.mark.parametrize(
    ("lookup", "expected_strategy"),
    [
        ("brokerage_beta", "long_term"),  # id
        ("Beta Long", "long_term"),  # label — 회귀 축
        ("Brokerage Beta 장기계좌", "long_term"),  # name
        ("beta long", "long_term"),  # 대소문자 무시
        ("  Beta Long  ", "long_term"),  # 공백 무시
    ],
)
def test_strategy_name_resolves_by_id_label_and_name(portfolio_yaml, lookup, expected_strategy):
    assert rules.get_account_strategy_name(lookup) == expected_strategy


def test_stop_loss_follows_the_account_profile_not_the_global_default(portfolio_yaml):
    """label 로 물어도 config 의 계좌 프로파일 값이 나와야 한다.

    회귀 시나리오: id-only 조회로 되돌리면 전부 global -7 이 되고, -19.6% 보유가
    -20% 프로파일에서 '돌파' 로 오판돼 urgent SELL 로 나간다.
    """
    long_term = rules.ACCOUNT_STRATEGIES["long_term"]["stop_loss"]
    core = rules.ACCOUNT_STRATEGIES["core"]["stop_loss"]
    assert long_term != core, "픽스처 전제 붕괴 — 두 프로파일이 같으면 이 테스트는 무의미"

    assert rules.get_stop_loss_for_account("Beta Long") == long_term
    assert rules.get_stop_loss_for_account("Alpha Main") == core

    # 그리고 그 차이가 판정을 바꾼다 (이게 사고의 본질)
    pnl = -19.6
    assert pnl > long_term, "long_term 프로파일에선 돌파가 아니다"
    assert pnl < core, "core 프로파일에선 돌파다 — 잘못 조회하면 여기로 떨어진다"


def test_pension_is_identifiable_by_label(portfolio_yaml):
    """연금 제외 판정이 label 경로에서도 서야 한다."""
    assert rules.get_account_strategy_name("연금") == "pension"
    assert rules.get_account_strategy_name("retirement") == "pension"


def test_empty_account_falls_back_without_touching_yaml(portfolio_yaml):
    """계좌명이 비면 조회 자체를 하지 않는다 — `_resolve_account_key` 의 early return."""
    assert rules.get_account_strategy("") == rules._DEFAULT_STRATEGY
    assert rules.get_account_strategy(None) == rules._DEFAULT_STRATEGY


def test_malformed_account_entry_is_skipped_not_crashed(tmp_path, monkeypatch):
    """yaml 의 계좌 엔트리가 dict 가 아니어도 죽지 않고 건너뛴다.

    portfolio.yaml 은 손으로 편집하는 파일이라 `account:` 뒤가 비어 null 이 되는 실수가
    난다. 그 한 줄이 손절 조회 전체를 죽이면 안 된다.
    """
    path = tmp_path / "portfolio.yaml"
    path.write_text(
        textwrap.dedent(
            """
            accounts:
              broken:
              brokerage_beta:
                label: Beta Long
                strategy: long_term
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rules, "PORTFOLIO_PATH", path)
    assert rules.get_account_strategy_name("Beta Long") == "long_term"
    assert rules.get_account_strategy_name("broken") == "core"


def test_unknown_account_falls_back_to_core(portfolio_yaml):
    assert rules.get_account_strategy_name("Nonexistent") == "core"
    assert rules.get_stop_loss_for_account("Nonexistent") == rules.ACCOUNT_STRATEGIES["core"]["stop_loss"]
    assert rules.get_stop_loss_for_account(None) == int(rules.STOCK_STOP_LOSS)
