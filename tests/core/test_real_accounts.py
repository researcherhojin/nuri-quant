"""실계좌 판별 + import 필터 회귀 테스트.

Gotcha-Test Pair (2026-07-29 프로덕션 사고):

`config/portfolio.yaml` 에는 실제 증권계좌와 함께 픽스처 계좌(`test`/`sample`/
`main`)가 섞여 있었고, `import_portfolio.py` 에 계좌 필터가 없어 **한 번의 import
실행으로 픽스처 9행이 프로덕션 portfolio 에 들어갔다.** 가짜 티커(`BBB`)까지
#515 auto-consensus 를 타 추천 3건이 오늘 날짜로 생성됐다.

방어선은 있다고 적혀 있었다 — `_get_real_accounts()` docstring 이 "test/sample
stub 차단 (#527 root cause)". 그런데 판정 기준이
`("label","name","strategy","holdings","balance")` 중 하나라도 있으면 실계좌라
**픽스처도 `holdings` 를 가져 전부 통과했다.** 8개 계좌 전부가 real 로 나왔다.

그래서 여기서 잠그는 건 두 가지다: 판별이 실제로 픽스처를 걸러내는가, 그리고
import 가 그 판별을 쓰는가.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from nuri.core import rules as rules_mod
from scripts.ops.import_portfolio import load_holdings_by_account

_YAML = textwrap.dedent(
    """
    accounts:
      brokerage_alpha:
        name: 실계좌 (Main)
        broker: Brokerage Alpha
        currency: USD
        strategy: core
        holdings:
        - {ticker: AAA, qty: 10.0, avg: 100.0}
      pension:
        name: 연금
        broker: Brokerage Beta
        currency: KRW
        strategy: pension
        holdings:
        - {ticker: 005930.KS, qty: 5.0, avg: 70000.0}
      test:
        currency: USD
        holdings:
        - {ticker: BBB, qty: 1.0, avg: 1.0}
      sample:
        currency: USD
        holdings:
        - {ticker: VOO, qty: 2.0, avg: 500.0}
      main:
        currency: USD
        holdings:
        - {ticker: AAPL, qty: 1.0, avg: 100.0}
    """
).strip()


@pytest.fixture
def yaml_path(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "portfolio.yaml"
    p.write_text(_YAML, encoding="utf-8")
    # rules.get_real_accounts 는 repo 상대경로를 직접 읽는다 — 테스트용으로 치환.
    real_open = open

    def fake_open(path, *a, **kw):
        if str(path).endswith("config/portfolio.yaml"):
            return real_open(p, *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    return p


class TestGetRealAccounts:
    def test_fixture_accounts_are_excluded(self, yaml_path):
        """`holdings` 만 있는 stub 은 실계좌가 아니다 — 이게 뚫려 있어서 사고가 났다."""
        assert rules_mod.get_real_accounts() == {"brokerage_alpha", "pension"}

    def test_holdings_alone_is_not_enough(self, yaml_path):
        """옛 기준(`holdings` 포함)으로 되돌리면 픽스처가 통과한다."""
        real = rules_mod.get_real_accounts()
        for stub in ("test", "sample", "main"):
            assert stub not in real, f"{stub} 은 broker/name 이 없으므로 실계좌가 아니다"

    def test_missing_file_is_empty_not_crash(self, tmp_path, monkeypatch):
        """yaml 을 못 읽어도 예외 대신 빈 집합 — 호출자가 필터를 건너뛰게 둔다."""

        def boom(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr("builtins.open", boom)
        assert rules_mod.get_real_accounts() == set()


class TestImportSkipsFixtureAccounts:
    def test_only_real_accounts_are_synced(self, yaml_path):
        """import 가 픽스처를 DB 로 넘기지 않는다 (#515 auto-consensus 도 안 탄다)."""
        by_account = load_holdings_by_account(yaml_path)
        assert set(by_account) == {"brokerage_alpha", "pension"}

    def test_fake_tickers_never_reach_the_record_set(self, yaml_path):
        """`BBB` / `VOO` / `AAPL` 은 실제로 프로덕션에 들어갔던 티커다."""
        tickers = {r["ticker"] for records in load_holdings_by_account(yaml_path).values() for r in records}
        assert tickers == {"AAA", "005930.KS"}
        assert not tickers & {"BBB", "VOO", "AAPL"}
