"""Tests for nuri/core/axis.py — alpha/portfolio axis helpers (PR B, codex #2).

이 helper 가 PR A codex Review caveat ("writer discipline 의존") 을 제거하는
핵심 layer. 재발 방지 lock-in:
- strict=False (default) 는 back-compat — pre-migration-22 legacy SELL 허용.
- strict=True 는 PR C 이후 전환 포인트 — 명시적으로 alpha_action 설정만 허용.
- derive_alpha_action 은 writer (candidates/tracker) 가 legacy `action` 에서
  axis 를 채울 때 사용 — consensus.py save_to_recommendations 와 동일 mapping.
"""
import pytest

from nuri.core.axis import derive_alpha_action, is_alpha_flat_sell, is_alpha_long_buy


class TestIsAlphaFlatSell:
    """SELL semantic detection — urgent/check bucket 진입 gate."""

    def test_explicit_flat_is_sell(self):
        assert is_alpha_flat_sell("FLAT", "SELL") is True
        assert is_alpha_flat_sell("FLAT", "HOLD") is True  # action 과 무관하게 FLAT 우선
        assert is_alpha_flat_sell("FLAT", None) is True

    def test_legacy_sell_backcompat(self):
        """pre-PR-A writer 는 alpha_action=None + action='SELL'."""
        assert is_alpha_flat_sell(None, "SELL") is True

    def test_hold_is_not_sell(self):
        assert is_alpha_flat_sell(None, "HOLD") is False
        assert is_alpha_flat_sell(None, None) is False

    def test_long_or_buy_is_not_sell(self):
        """alpha_action=LONG 또는 legacy BUY 는 SELL 경로 진입 금지."""
        assert is_alpha_flat_sell("LONG", "BUY") is False
        assert is_alpha_flat_sell("LONG", "SELL") is False  # 모순 case — alpha 우선
        assert is_alpha_flat_sell(None, "BUY") is False

    def test_strict_mode_blocks_legacy_fallback(self):
        """PR C 승격 후 strict=True: 명시적 FLAT 만 허용. writer discipline 강제."""
        assert is_alpha_flat_sell("FLAT", "SELL", strict=True) is True
        # Legacy 가 strict 에서 거부됨
        assert is_alpha_flat_sell(None, "SELL", strict=True) is False
        assert is_alpha_flat_sell(None, "HOLD", strict=True) is False

    def test_concentration_only_sell_blocked_at_reader(self):
        """Regression lock — PR A codex Review 의 핵심 risk.

        가상의 future writer 가 concentration 만 보고 action='SELL' + alpha_action=None
        을 emit 해도, reader 는 alpha 신호로 취급 안 함 → urgent/check 경로에서
        portfolio bucket (또는 hold) 으로 redirect. writer discipline 없이도
        semantic 안전.

        단 legacy SELL 도 alpha 로 간주하는 현 default 에선 해당 false positive 가
        여전히 발생 가능 — strict=True 전환 필요. 이 테스트는 경계를 명시화."""
        # Concentration-only writer (alpha=None, action=SELL) — default 는 SELL 취급
        # (back-compat 정책, codex Plan Q1-B).
        assert is_alpha_flat_sell(None, "SELL") is True
        # Strict 모드로 가면 reader 가 default-safe (SELL 거부).
        assert is_alpha_flat_sell(None, "SELL", strict=True) is False
        # 그러나 risk_agent (PR A) 는 이미 concentration 을 action=SELL 으로 emit 안 함 —
        # portfolio_action=REBALANCE + alpha_action=None + action=HOLD 로 writing.
        # 따라서 실제 production 경로에서는 strict=False 로도 concentration-only
        # SELL 이 불가능 (writer + reader 이중 방어).
        assert is_alpha_flat_sell(None, "HOLD") is False


class TestIsAlphaLongBuy:
    """BUY semantic detection — dashboard.py BUY card surface gate."""

    def test_explicit_long_is_buy(self):
        assert is_alpha_long_buy("LONG", "BUY") is True
        assert is_alpha_long_buy("LONG", "HOLD") is True

    def test_legacy_buy_backcompat(self):
        assert is_alpha_long_buy(None, "BUY") is True

    def test_hold_and_sell_not_buy(self):
        assert is_alpha_long_buy(None, "HOLD") is False
        assert is_alpha_long_buy(None, "SELL") is False
        assert is_alpha_long_buy("FLAT", "SELL") is False

    def test_strict_mode(self):
        assert is_alpha_long_buy("LONG", "BUY", strict=True) is True
        assert is_alpha_long_buy(None, "BUY", strict=True) is False


class TestDeriveAlphaAction:
    """Writer mapping — consensus.py save_to_recommendations 와 동일해야 함."""

    @pytest.mark.parametrize("action,expected", [
        ("BUY", "LONG"),
        ("SELL", "FLAT"),
        ("HOLD", None),
        (None, None),
        ("UNKNOWN", None),
    ])
    def test_derive_from_action(self, action, expected):
        assert derive_alpha_action(action) == expected
