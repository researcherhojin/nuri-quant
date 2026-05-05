"""screen_candidates main flow — Issue #616 Phase 3-B3.

candidates.py 의 main loop / drift / catalyst / conflict / scorecard-stale 분기 닫음.
helpers (3-B2 PR #635) / print_candidates (3-B4 다음 PR) 와 분리.

| line | branch / stmt | trigger |
|---|---|---|
| 218 | `len(df) < 50: continue` | ticker 가격 < 50 rows |
| 239 | `not is_actionable: continue` | mock is_actionable False |
| 263 | `total_trades < MIN: tier=ADVISORY` | scorecard total_trades=5 |
| 277-283 | SELL with no catalyst → downgrade | has_recent_catalyst=(False, ...) |
| 358-359 | `if drift_status in DRIFT_MULT:` 적용 | drift_status="critical" |
| 368 | catalyst-induced advisory note | SELL 다운그레이드 후 notes |
| 370 | low-sample advisory note | total_trades 부족 |
| 374 | scorecard stale note | age_days > 7 |
| 380 | drift critical/degrading note | drift_status critical |
| 409→408 | non-direction_conflict skip | conflict_type 다른 값 |
| 418→424 | sev != "high" skip discount | sev="medium" |
| 427-428 | detect_conflicts 예외 흡수 | mock raise |

Skip (dead-by-design — 별도 simplify issue 후보):
- 439→435, 447→443: candidate.scoring_detail 항상 dict (None 분기 unreachable)
- 424→413: 단일 candidate 만 있을 때 next-iteration 분기 (test 작성에 비해 의미 낮음)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from nuri.core.db import init_db, upsert_portfolio, upsert_prices


def _seed_minimal_ticker(db_path, ticker, n_days=100):
    """ticker 1개에 n_days 가격 + portfolio 삽입."""
    upsert_portfolio(
        [
            {
                "account": "test",
                "ticker": ticker,
                "quantity": 10,
                "avg_price": 100,
                "currency": "USD",
                "sector": "Tech",
            }
        ],
        db_path,
    )
    dates = pd.bdate_range("2024-06-01", periods=n_days, freq="B")
    rows = [
        {
            "ticker": ticker,
            "date": d.strftime("%Y-%m-%d"),
            "open": 100 + i * 0.1,
            "high": 100 + i * 0.1 + 1,
            "low": 100 + i * 0.1 - 1,
            "close": 100 + i * 0.1 + 0.5,
            "volume": 1_000_000,
            "adj_close": 100 + i * 0.1 + 0.5,
        }
        for i, d in enumerate(dates)
    ]
    upsert_prices(pd.DataFrame(rows), db_path)


def _patch_helpers(scorecard=None, age=None, regime_ctx=None, drift_map=None):
    """screen_candidates 내부 helper 들 일괄 patch."""
    return [
        patch("nuri.trading.recommend.candidates._load_scorecard", return_value=(scorecard or {}, age)),
        patch("nuri.trading.recommend.candidates._get_regime_context", return_value=regime_ctx),
        patch("nuri.trading.recommend.candidates._get_drift_map", return_value=drift_map or {}),
    ]


# ═══════════════════════════════════════════════════════
# 218: len(df) < 50 → continue
# ═══════════════════════════════════════════════════════


class TestPriceDataInsufficient:
    def test_short_price_df_skips_ticker(self, tmp_path):
        """ticker 의 prices 가 < 50 rows → 218 continue → 후보 없음."""
        from nuri.trading.recommend.candidates import screen_candidates

        p = tmp_path / "short.db"
        init_db(p)
        _seed_minimal_ticker(p, "SHORT", n_days=30)  # 30 < 50

        with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
            with self._stack(_patch_helpers()):
                result = screen_candidates(lookback_days=5, db_path=p)

        assert result == []

    @staticmethod
    def _stack(patches):
        """contextlib.ExitStack 를 single context 로 감쌈."""
        from contextlib import ExitStack

        es = ExitStack()
        for p in patches:
            es.enter_context(p)
        return es


# ═══════════════════════════════════════════════════════
# 239: is_actionable False → continue
# ═══════════════════════════════════════════════════════


class TestSignalNotActionable:
    def test_non_actionable_signals_skipped(self, tmp_path):
        """모든 signal 이 not actionable → 239 continue 만 발생 → 후보 없음."""
        from nuri.trading.recommend.candidates import screen_candidates

        p = tmp_path / "noact.db"
        init_db(p)
        _seed_minimal_ticker(p, "TEST", n_days=100)

        with patch("nuri.core.signal_config.is_actionable", return_value=False):
            with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                with TestPriceDataInsufficient._stack(_patch_helpers()):
                    result = screen_candidates(lookback_days=5, db_path=p)

        assert result == []


# ═══════════════════════════════════════════════════════
# 263, 358-359, 368, 370, 374, 380: scorecard / drift / notes
# ═══════════════════════════════════════════════════════


class TestScreenCandidatesNotesAndScoring:
    def _force_signal_entry(self):
        """detect_signal_entries 를 patch 해 마지막 인덱스 1개 entry 반환."""
        return patch(
            "nuri.trading.recommend.candidates.detect_signal_entries",
            side_effect=lambda df, signal_id: [len(df) - 1] if signal_id == "rsi_oversold" else [],
        )

    def test_low_total_trades_marks_advisory_with_low_sample_note(self, tmp_path):
        """263, 370: total_trades < MIN_TRADES_FOR_VALIDATION → ADVISORY + low-sample note."""
        from nuri.trading.recommend.candidates import screen_candidates

        p = tmp_path / "low_trades.db"
        init_db(p)
        _seed_minimal_ticker(p, "LOWTR", n_days=100)

        # total_trades=5 (< 30) — pf>1 이지만 sample 부족.
        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 1.0,
                "total_trades": 5,
            }
        }

        with self._force_signal_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                    with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                        result = screen_candidates(lookback_days=200, db_path=p)

        rsi_cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi_cands
        c = rsi_cands[0]
        assert c.tier == "advisory"
        assert "low-sample" in c.notes

    def test_drift_critical_applies_multiplier_and_note(self, tmp_path):
        """358-359, 380: drift_status='critical' → multiplier 0.3 + critical note."""
        from nuri.trading.recommend.candidates import screen_candidates

        p = tmp_path / "drift.db"
        init_db(p)
        _seed_minimal_ticker(p, "DRIFT", n_days=100)

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 1.0,
                "total_trades": 50,
            }
        }
        drift_map = {"rsi_oversold": {"status": "critical", "drift_pct": -50}}

        with self._force_signal_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                    with TestPriceDataInsufficient._stack(
                        _patch_helpers(scorecard=scorecard, age=1, drift_map=drift_map)
                    ):
                        result = screen_candidates(lookback_days=200, db_path=p)

        rsi_cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi_cands
        c = rsi_cands[0]
        assert c.scoring_detail["drift_multiplier"] == 0.3
        assert "critical" in c.notes

    def test_scorecard_stale_appends_warning(self, tmp_path):
        """374: scorecard age_days > 7 → 'X일 전' note 추가."""
        from nuri.trading.recommend.candidates import screen_candidates

        p = tmp_path / "stale.db"
        init_db(p)
        _seed_minimal_ticker(p, "STALE", n_days=100)

        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 1.0,
                "total_trades": 50,
            }
        }

        with self._force_signal_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                    with TestPriceDataInsufficient._stack(
                        _patch_helpers(scorecard=scorecard, age=10)  # > 7
                    ):
                        result = screen_candidates(lookback_days=200, db_path=p)

        rsi_cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert rsi_cands
        assert "10일 전" in rsi_cands[0].notes


# ═══════════════════════════════════════════════════════
# 277-283, 368: SELL no catalyst → downgrade
# ═══════════════════════════════════════════════════════


class TestSellCatalystDowngrade:
    def test_sell_without_catalyst_downgrades_to_advisory(self, tmp_path):
        """277-283, 368: SELL ACTIONABLE + no catalyst → tier=ADVISORY, note '근거 없음'."""
        import pytest

        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend.candidates import screen_candidates

        if not SELL_SIGNALS:
            pytest.skip("SELL_SIGNALS 비어있음")

        sell_sig = next(iter(SELL_SIGNALS))

        p = tmp_path / "sell.db"
        init_db(p)
        _seed_minimal_ticker(p, "SELLT", n_days=100)

        # ACTIONABLE 조건: total_trades >= 30, pf >= 1.0
        scorecard = {
            sell_sig: {
                "win_rate": 0.55,
                "profit_factor": 1.5,
                "avg_return": 1.0,
                "total_trades": 50,
            }
        }

        # detect_signal_entries → 마지막 인덱스만 fire (sell_sig 한정)
        def _fire_sell(df, signal_id):
            return [len(df) - 1] if signal_id == sell_sig else []

        # has_recent_catalyst → (False, reason) → downgrade trigger
        with patch(
            "nuri.trading.recommend.candidates.detect_signal_entries",
            side_effect=_fire_sell,
        ):
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch(
                    "nuri.core.catalyst.has_recent_catalyst",
                    return_value=(False, "최근 catalyst 없음"),
                ):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                            result = screen_candidates(lookback_days=200, db_path=p)

        sell_cands = [c for c in result if c.signal_id == sell_sig]
        assert sell_cands
        c = sell_cands[0]
        assert c.tier == "advisory"
        assert "SELL 근거 없음" in c.notes

    def test_sell_with_catalyst_keeps_actionable(self, tmp_path):
        """282-283: SELL ACTIONABLE + catalyst 있음 → tier 유지, catalyst_note 기록."""
        import pytest

        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend.candidates import screen_candidates

        if not SELL_SIGNALS:
            pytest.skip("SELL_SIGNALS 비어있음")

        sell_sig = next(iter(SELL_SIGNALS))

        p = tmp_path / "sell_cat.db"
        init_db(p)
        _seed_minimal_ticker(p, "SELLOK", n_days=100)

        scorecard = {
            sell_sig: {
                "win_rate": 0.55,
                "profit_factor": 1.5,
                "avg_return": 1.0,
                "total_trades": 50,
            }
        }

        def _fire_sell(df, signal_id):
            return [len(df) - 1] if signal_id == sell_sig else []

        with patch(
            "nuri.trading.recommend.candidates.detect_signal_entries",
            side_effect=_fire_sell,
        ):
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch(
                    "nuri.core.catalyst.has_recent_catalyst",
                    return_value=(True, "earnings_miss"),
                ):
                    with patch("nuri.trading.engine.conflicts.detect_conflicts", return_value=[]):
                        with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                            result = screen_candidates(lookback_days=200, db_path=p)

        sell_cands = [c for c in result if c.signal_id == sell_sig]
        assert sell_cands
        c = sell_cands[0]
        # ACTIONABLE 유지 (catalyst 존재) + scoring_detail catalyst_note 기록
        assert c.tier == "actionable"
        assert c.scoring_detail["catalyst_note"].startswith("catalyst:")


# ═══════════════════════════════════════════════════════
# 409→408, 418→424, 427-428: conflict detection 분기
# ═══════════════════════════════════════════════════════


class TestConflictDetectionBranches:
    def _setup_actionable(self, tmp_path, name):
        """ACTIONABLE rsi_oversold 후보 생성 환경."""
        p = tmp_path / f"{name}.db"
        init_db(p)
        _seed_minimal_ticker(p, "CONF", n_days=100)
        scorecard = {
            "rsi_oversold": {
                "win_rate": 0.6,
                "profit_factor": 2.0,
                "avg_return": 1.0,
                "total_trades": 50,
            }
        }
        return p, scorecard

    def _force_entry(self):
        return patch(
            "nuri.trading.recommend.candidates.detect_signal_entries",
            side_effect=lambda df, sid: [len(df) - 1] if sid == "rsi_oversold" else [],
        )

    def test_non_direction_conflict_type_not_marked(self, tmp_path):
        """409→408: cf.conflict_type != 'direction_conflict' → 후보 conflict 미설정."""
        from nuri.trading.recommend.candidates import screen_candidates

        p, scorecard = self._setup_actionable(tmp_path, "nondir")

        # detect_conflicts 가 다른 type 반환 → conflict_tickers 비어있음.
        non_dir_conflict = MagicMock(
            ticker="CONF",
            conflict_type="weight_imbalance",
            severity="medium",
        )

        with self._force_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch(
                    "nuri.trading.engine.conflicts.detect_conflicts",
                    return_value=[non_dir_conflict],
                ):
                    with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                        result = screen_candidates(lookback_days=200, db_path=p)

        cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert cands
        assert cands[0].conflict == ""  # 미설정 — 409 False 분기 통과 증거

    def test_low_severity_conflict_skips_discount(self, tmp_path):
        """418→424: sev='medium' (not 'high') → conflict 표시는 되지만 0.5 할인 X."""
        from nuri.trading.recommend.candidates import screen_candidates

        p, scorecard = self._setup_actionable(tmp_path, "lowsev")
        cf = MagicMock(
            ticker="CONF",
            conflict_type="direction_conflict",
            severity="medium",
        )

        with self._force_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch(
                    "nuri.trading.engine.conflicts.detect_conflicts",
                    return_value=[cf],
                ):
                    with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                        result = screen_candidates(lookback_days=200, db_path=p)

        cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert cands
        c = cands[0]
        assert c.conflict == "direction_conflict"
        # high 할인 없음 → notes 에 충돌 텍스트 없음.
        assert "충돌" not in c.notes
        # 418 False → 419-422 skip. conflict_penalty 는 1.0 으로 기록 (424 block 은 항상 실행).
        assert c.scoring_detail["conflict_penalty"] == 1.0

    def test_detect_conflicts_exception_is_swallowed(self, tmp_path):
        """427-428: detect_conflicts raise → except 흡수 → 후보 정상 반환."""
        from nuri.trading.recommend.candidates import screen_candidates

        p, scorecard = self._setup_actionable(tmp_path, "raise")

        with self._force_entry():
            with patch("nuri.core.signal_config.is_actionable", return_value=True):
                with patch(
                    "nuri.trading.engine.conflicts.detect_conflicts",
                    side_effect=RuntimeError("conflict detection 실패"),
                ):
                    with TestPriceDataInsufficient._stack(_patch_helpers(scorecard=scorecard, age=1)):
                        result = screen_candidates(lookback_days=200, db_path=p)

        # 예외 흡수 → 후보 리스트 정상 반환.
        cands = [c for c in result if c.signal_id == "rsi_oversold"]
        assert cands
        assert cands[0].conflict == ""  # exception 으로 미설정
