"""print_candidates branch coverage — Issue #616 Phase 3-B4.

candidates.py 의 print 분기 닫음. CLI block (525-532) 은 관행상 제외.

| line | branch / stmt | trigger |
|---|---|---|
| 477 | `elif vix_gate=="caution":` | vix_gate caution |
| 492 | `flags.append("UNSCORED")` | unscored=True |
| 496 | `flags.append("CONF")` | conflict 표시 + tier 가 _print_table 대상 |
| 500-501 | unscored 시 wr/pf 를 "—" 로 표시 | unscored=True |
| 512 | advisory _print_table | advisory + regime_fit=True |
| 514 | avoid _print_table | avoid + regime_fit=True |
"""

from __future__ import annotations

from unittest.mock import patch


def _make_candidate(**overrides):
    """기본 ACTIONABLE BUY candidate. overrides 로 필드 변경."""
    from nuri.trading.recommend.candidates import TIER_ACTIONABLE, Candidate

    base = {
        "ticker": "TEST",
        "signal_id": "rsi_oversold",
        "signal_date": "2026-03-30",
        "direction": "BUY",
        "confidence": 50.0,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "regime_fit": True,
        "price": 100.0,
        "notes": "test",
        "drift_status": "",
        "conflict": "",
        "scoring_detail": None,
        "unscored": False,
        "tier": TIER_ACTIONABLE,
    }
    base.update(overrides)
    return Candidate(**base)


# ═══════════════════════════════════════════════════════
# 477: VIX caution 분기
# ═══════════════════════════════════════════════════════


class TestPrintVixCaution:
    def test_vix_caution_prints_warning(self, capsys):
        """477: vix_gate=='caution' → 경고 print."""
        from nuri.trading.recommend.candidates import print_candidates

        candidates = [_make_candidate()]
        with patch(
            "nuri.trading.recommend.candidates._check_vix_gate",
            return_value={"vix": 27.0, "gate": "caution", "msg": "VIX 27.0 caution"},
        ):
            print_candidates(candidates)

        out = capsys.readouterr().out
        assert "27.0 caution" in out  # 477 line 의 print 출력 확인


# ═══════════════════════════════════════════════════════
# 492, 496, 500-501: unscored + conflict flags / unscored wr/pf 표시
# ═══════════════════════════════════════════════════════


class TestPrintFlags:
    def test_unscored_and_conflict_flags_printed(self, capsys):
        """492 + 496 + 500-501: unscored=True + conflict 표시 → flags + '—' 표시."""
        from nuri.trading.recommend.candidates import print_candidates

        # ACTIONABLE + regime_fit=True → _print_table 대상이 되도록.
        candidates = [
            _make_candidate(
                unscored=True,
                conflict="direction_conflict",
                drift_status="critical",
            ),
        ]
        with patch(
            "nuri.trading.recommend.candidates._check_vix_gate",
            return_value={"vix": 15, "gate": "normal", "msg": ""},
        ):
            print_candidates(candidates)

        out = capsys.readouterr().out
        # 492: UNSCORED flag 출력
        assert "UNSCORED" in out
        # 496: CONF flag 출력
        assert "CONF" in out
        # 500-501: unscored 시 wr/pf 자리에 "—" 표시
        assert "—" in out  # em-dash for missing stats


# ═══════════════════════════════════════════════════════
# 512, 514: advisory / avoid _print_table
# ═══════════════════════════════════════════════════════


class TestPrintTierTables:
    def test_advisory_and_avoid_tables_printed(self, capsys):
        """512 + 514: regime_fit=True + tier ADVISORY/AVOID → 별도 table 출력."""
        from nuri.trading.recommend.candidates import (
            TIER_ADVISORY,
            TIER_AVOID,
            print_candidates,
        )

        candidates = [
            _make_candidate(ticker="ADV", tier=TIER_ADVISORY, notes="low-sample"),
            _make_candidate(ticker="AVD", tier=TIER_AVOID, notes="negative-edge"),
        ]
        with patch(
            "nuri.trading.recommend.candidates._check_vix_gate",
            return_value={"vix": 15, "gate": "normal", "msg": ""},
        ):
            print_candidates(candidates)

        out = capsys.readouterr().out
        # 512: Advisory table title
        assert "Advisory" in out
        assert "ADV" in out
        # 514: Avoid table title
        assert "Avoid" in out
        assert "AVD" in out
