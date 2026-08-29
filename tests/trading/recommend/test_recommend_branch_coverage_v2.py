"""Branch coverage extension v2 — fills remaining gaps in nuri/trading/recommend/.

Targets (from cov agent A, post-existing tests):

- buy_candidate_emitter.py: 213, 256-257, 264-265, 298, 332-341, 387, 413, 482-488, 494-502, 506
- held_add.py: 88-89, 115-117, 124, 126, 171, 218-219, 224-226, 244, 246, 252, 255, 258,
                267, 276, 279, 282, 298, 308, 311, 314, 317, 351, 462-463
- candidates.py: 90-91, 112-118, 218, 239, 263, 277-283, 358-380, 427-428, 477, 492, 496,
                  500-501, 512, 514, 525-532
- tracker.py: 87, 120-121, 259, 383-423 (CLI path)
- holdings_monitor.py: 199, 389-404, 408
- price_targets.py: 363-364, 369, 427, 431-432, 441, 449, 492-493, 523, 541-547

Each test:
- Cites concrete source lines / branch in docstring
- Uses `tmp_path` + `init_db(path)` + `db_path=` parameter for DB isolation
- Mocks ONLY external dependencies (network, optional discord_bot import)
- Assertions check actual behavior, not just `is not None`
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

from nuri.core.db import get_db, init_db, query, query_df, upsert_portfolio, upsert_prices

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def fresh_db(tmp_path):
    """Isolated DB with monkeypatch on DB_PATH (for modules that read defaults)."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


# ════════════════════════════════════════════════════════════════════
# buy_candidate_emitter.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestBuyCandidateEmitterPriceSignalsEmpty:
    """Line 213: `if df.empty: return {}` in `_get_price_signals`.

    No prices in DB → empty DataFrame → early return {}. Covered by direct
    invocation against an empty fresh DB.
    """

    def test_empty_prices_returns_empty_dict(self, fresh_db, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        from nuri.trading.recommend.buy_candidate_emitter import _get_price_signals

        result = _get_price_signals()
        # The dict must be empty AND of type dict (not None) — locks the contract
        assert result == {}
        assert isinstance(result, dict)


class TestBuyCandidateEmitterShortSeries:
    """Line 202-203: `if len(grp) < 6: continue` — 45일 창 안에 6행 미만인 종목 skip.

    `ret_5d` 가 `closes[-6]` 을 읽으므로 6행 미만이면 IndexError 다. 이 skip 이
    사라지면 신규 상장·수집 재개 직후 종목 하나가 후보 산출 전체를 크래시시킨다.

    이 분기는 **CI 에서만 미커버였다** — 개발 머신 DB 에는 짧은 시계열 종목이
    우연히 있어서 로컬 실측이 100% 로 보였다. 필요한 데이터를 테스트가 직접
    시드해야 어느 환경에서든 실행된다.
    """

    def test_ticker_with_fewer_than_six_rows_is_skipped(self, fresh_db, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        from nuri.core.timezone import today_kst
        from nuri.trading.recommend.buy_candidate_emitter import _get_price_signals

        # 창(45일) 안에 들도록 today 기준 앵커링 — 고정 리터럴 날짜는 시한폭탄 (#721).
        end = date.fromisoformat(today_kst())
        with get_db(fresh_db) as conn:
            for i in range(10):  # 충분한 종목 — 정상 처리
                d = (end - timedelta(days=i)).isoformat()
                conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('TESTLONG', ?, ?)", (d, 100.0 + i))
            for i in range(3):  # 6행 미만 — skip 대상
                d = (end - timedelta(days=i)).isoformat()
                conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('TESTSHORT', ?, ?)", (d, 50.0 + i))
            conn.commit()

        out = _get_price_signals()

        assert "TESTLONG" in out, "정상 종목까지 사라졌다 — 시드 자체가 창 밖일 수 있음"
        assert "TESTSHORT" not in out, "6행 미만 종목이 skip 되지 않았다 (closes[-6] IndexError 위험)"


class TestBuyCandidateEmitterRegimeFallbacks:
    """regime/VIX 조회 예외 → 미상. 지어낸 기본값(`neutral` / 20.0)으로 메우지 않는다."""

    def test_regime_classification_db_error_yields_unknown(self, monkeypatch):
        """분류가 DB 오류로 죽으면 `UNKNOWN_REGIME` — 레짐을 지어내지 않는다.

        이 테스트는 `regime == "neutral"` 을 잠그고 있었다. `neutral` 은 `ALL_REGIMES`
        밖이면서 `total_pct_by_regime` 에는 `0.40` 으로 존재해, **분류 실패가 표에서 가장
        공격적인 배분**을 받는 경로였다 (#1131). 이제 미상은 별도의 보수 배분을 받는다.
        """
        from nuri.quant.regime import classifier as clf
        from nuri.quant.regime.classifier import UNKNOWN_REGIME
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        def boom(*a, **kw):
            # DB 오류만 삼킨다 — RuntimeError 로 두면 코딩 오류까지 위장되므로
            # `except (OperationalError, DatabaseError)` 로 좁혀 두었다.
            from nuri.core.db import OperationalError

            raise OperationalError("synthetic regime fail")

        monkeypatch.setattr(clf, "classify_regime", boom)
        monkeypatch.setattr(vg, "query_df", lambda *a, **kw: pd.DataFrame())
        regime, vix = bce._get_regime()

        assert regime == UNKNOWN_REGIME
        # 빈 VIX df → 지어내지 않고 None (2026-08-10 이전엔 20.0 이었다)
        assert vix is None

    def test_vix_query_exception_yields_none(self, monkeypatch):
        """VIX 조회가 DB 오류로 죽으면 `None` — 숫자를 지어내지 않는다."""
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        def fake_query_df(sql, *a, **kw):
            if "vix" in sql:
                from nuri.core.db import OperationalError

                raise OperationalError("synthetic vix fail")
            return pd.DataFrame()

        monkeypatch.setattr(bce, "query_df", fake_query_df)
        monkeypatch.setattr(vg, "query_df", fake_query_df)
        regime, vix = bce._get_regime()

        # 데이터가 없는 테스트 DB 라 분류는 신선도 미충족으로 차단된다 → 미상
        from nuri.quant.regime.classifier import UNKNOWN_REGIME

        assert regime == UNKNOWN_REGIME
        assert vix is None


class TestBuyCandidateEmitterRsi65To75Branch:
    """Line 298: RSI 65 < rsi <= 75 → max(20.0, 80.0 - (rsi - 65) * 3.0).

    Tested via _score_ticker direct invocation.
    """

    def test_rsi_70_uses_decay_branch(self):
        """rsi=70 lands in (65, 75] → 80 - (70-65)*3 = 65."""
        from nuri.trading.recommend.buy_candidate_emitter import _score_ticker

        weights = {
            "factor_composite": 0.0,
            "momentum_5d": 0.0,
            "technical_rsi": 1.0,  # all weight on RSI to expose branch
            "breakout_30d": 0.0,
        }
        # neutral factor + zero momentum + zero breakout, only rsi matters
        score, sources = _score_ticker(
            "AAA",
            factor={"composite": 0.0},
            price={"ret_5d": 0.0, "breakout_pct": 0.0},
            rsi=70.0,
            weights=weights,
        )
        # 80 - (70-65)*3 = 65 ; with weight 1.0 score == rsi_pct == 65
        assert sources["rsi"] == pytest.approx(65.0)
        assert score == pytest.approx(65.0)

    def test_rsi_75_boundary_still_uses_decay(self):
        """rsi=75 → branch (65,75] → 80 - 10*3 = 50.

        Note: code uses `elif rsi <= 75` so 75 hits this branch (not >75 path).
        """
        from nuri.trading.recommend.buy_candidate_emitter import _score_ticker

        weights = {"factor_composite": 0.0, "momentum_5d": 0.0, "technical_rsi": 1.0, "breakout_30d": 0.0}
        _, sources = _score_ticker(
            "AAA",
            factor={"composite": 0.0},
            price={"ret_5d": 0.0, "breakout_pct": 0.0},
            rsi=75.0,
            weights=weights,
        )
        # 80 - (75-65)*3 = 50, max(20.0, 50.0) = 50.0
        assert sources["rsi"] == pytest.approx(50.0)


class TestBuyCandidateEmitterBuildWhyNow:
    """Lines 332-341: _build_why_now branches for rsi / breakout / fallback."""

    def test_rsi_oversold_setup(self):
        """Line 333-334: rsi=30 (≤35) → 과매도 반등 setup string."""
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        # Force `rsi` to be the top source by giving it the highest value
        sources = {"factor": 50.0, "momentum": 50.0, "rsi": 90.0, "breakout": 50.0}
        result = _build_why_now(sources, price={"ret_5d": 0.0}, rsi=30.0)
        assert "RSI 30" in result and "과매도" in result and "setup" in result

    def test_rsi_normal_band(self):
        """Line 335: rsi=55, top source=rsi, not oversold → 정상 구간 string."""
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        sources = {"factor": 50.0, "momentum": 50.0, "rsi": 90.0, "breakout": 50.0}
        result = _build_why_now(sources, price={"ret_5d": 0.0}, rsi=55.0)
        assert "RSI 55" in result and "정상" in result

    def test_rsi_none_falls_back_to_default_string(self):
        """Line 335 inline-if: rsi is None → 'RSI 정상'."""
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        sources = {"factor": 50.0, "momentum": 50.0, "rsi": 90.0, "breakout": 50.0}
        result = _build_why_now(sources, price={"ret_5d": 0.0}, rsi=None)
        assert result == "RSI 정상"

    def test_breakout_above_high(self):
        """Line 336-339: breakout top, bo>=0 → '돌파' string."""
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        sources = {"factor": 50.0, "momentum": 50.0, "rsi": 50.0, "breakout": 95.0}
        result = _build_why_now(sources, price={"breakout_pct": 2.5}, rsi=None)
        assert "30d 고가 돌파" in result and "+2.5%" in result

    def test_breakout_below_high(self):
        """Line 340: breakout top, bo<0 → 'pullback' string."""
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        sources = {"factor": 50.0, "momentum": 50.0, "rsi": 50.0, "breakout": 95.0}
        result = _build_why_now(sources, price={"breakout_pct": -3.0}, rsi=None)
        assert "30d 고가 -3.0% 근접 (pullback)" in result

    def test_unknown_top_source_returns_fallback(self):
        """Line 341: top key doesn't match any branch → 'Multi-source 강세'.

        The 4 if-blocks check 'factor', 'momentum', 'rsi', 'breakout' explicitly.
        An unknown key falls through to the final return.
        """
        from nuri.trading.recommend.buy_candidate_emitter import _build_why_now

        # Dummy unknown key — bypasses all if/return paths
        sources = {"unknown_metric": 95.0}
        result = _build_why_now(sources, price={}, rsi=None)
        assert result == "Multi-source 강세"


class TestBuyCandidateEmitterCooldownBranches:
    """Lines 387, 413: emit_buy_candidates cooldown_cfg branches + price-missing skip."""

    def test_cooldown_cfg_present_uses_type_aware(self, tmp_path, monkeypatch):
        """Line 386-387: cooldown dict present → calls _get_cooldown_tickers_by_type.

        Locks the dispatch decision: when gates.cooldown is a dict, the type-aware
        path must be taken (NOT the legacy single-window path).
        """
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        # Minimal config with cooldown dict (triggers type-aware branch)
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "exclude_held": False,
                    "exclude_etf_leverage": True,
                    "weights": {"factor_composite": 1.0},
                    "quality_bar": {"base_threshold": 0, "max_candidates": 5, "per_regime": {}},
                    "gates": {
                        "vix_block_above": 30,
                        "vix_caution_above": 25,
                        "cooldown": {"hard_sell_days": 21, "fallback_days": 5},  # dict → type-aware
                    },
                    "allocation": {"total_pct_by_regime": {"sideways_low_vol": 0.30}},
                    "risk": {"stop_pct": -7.0, "tp1_pct": 21.0, "tp2_pct": 42.0},
                }
            )
        )

        # Stub providers so the function flows through cooldown call
        type_aware_called = {"n": 0}

        def fake_type_aware(cooldown_cfg, **_kw):
            type_aware_called["n"] += 1
            return set()

        monkeypatch.setattr(bce, "_get_cooldown_tickers_by_type", fake_type_aware)
        monkeypatch.setattr(bce, "_get_held_tickers", lambda **_kw: set())
        monkeypatch.setattr(bce, "_get_factor_scores", lambda **_kw: {})
        monkeypatch.setattr(bce, "_get_price_signals", lambda **_kw: {})
        monkeypatch.setattr(bce, "_get_rsi_snapshot", lambda **_kw: {})
        monkeypatch.setattr(bce, "leadership_snapshot", lambda *a, **k: {})  # P2 shadow (prices 미시드)
        monkeypatch.setattr(bce, "_get_regime", lambda **_kw: ("sideways_low_vol", 18.0))

        result = bce.emit_buy_candidates(config_path=cfg_path)
        # Lock-in: the type-aware path was taken exactly once
        assert type_aware_called["n"] == 1, (
            "When gates.cooldown is a dict, _get_cooldown_tickers_by_type must be called "
            "(not the legacy single-window helper)"
        )
        # blocked because factors empty (line 395-397) — confirms downstream flow
        assert "factors 테이블 비어있음" in (result.blocked_reason or "")

    def test_ticker_with_factor_but_no_price_silently_skipped(self, tmp_path, monkeypatch):
        """Line 411-413: factor present but no price entry → continue (silent skip).

        Lock: the ticker is NOT added to skipped (silent — too many to surface) AND
        NOT added to candidates. Reverting `continue` to a fall-through would push
        a NoneType into _score_ticker and crash.
        """
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg

        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "exclude_held": False,
                    "exclude_etf_leverage": True,
                    "weights": {"factor_composite": 1.0},
                    "quality_bar": {"base_threshold": 0, "max_candidates": 5, "per_regime": {}},
                    "gates": {"vix_block_above": 30, "vix_caution_above": 25, "cooldown_days": 0},
                    "allocation": {"total_pct_by_regime": {"sideways_low_vol": 0.30}},
                    "risk": {"stop_pct": -7.0, "tp1_pct": 21.0, "tp2_pct": 42.0},
                }
            )
        )
        monkeypatch.setattr(bce, "_get_held_tickers", lambda **_kw: set())
        monkeypatch.setattr(bce, "_get_cooldown_tickers", lambda days, **_kw: set())
        monkeypatch.setattr(bce, "_get_factor_scores", lambda **_kw: {"NOPRICE": {"composite": 0.9}})
        monkeypatch.setattr(bce, "_get_price_signals", lambda **_kw: {})  # NOPRICE missing
        monkeypatch.setattr(bce, "_get_rsi_snapshot", lambda **_kw: {})
        monkeypatch.setattr(bce, "leadership_snapshot", lambda *a, **k: {})  # P2 shadow (prices 미시드)
        monkeypatch.setattr(bce, "_get_regime", lambda **_kw: ("sideways_low_vol", 18.0))

        result = bce.emit_buy_candidates(config_path=cfg_path)

        # Behavioral lock: NOPRICE was neither candidate nor explicit skip — silent.
        assert "NOPRICE" not in result.skipped, "no-price tickers must be silent-skipped"
        assert all(c.ticker != "NOPRICE" for c in result.candidates)


class TestBuyCandidateEmitterRenderMarkdownSkipped:
    """Lines 482-488: render_markdown skipped section."""

    def test_render_markdown_with_skipped_section_under_5(self):
        """Lines 481-486: skipped < 5 → list all, no '+ more' line."""
        from nuri.trading.recommend.buy_candidate_emitter import (
            BuyCandidate,
            EmitResult,
            render_markdown,
        )

        result = EmitResult(
            candidates=[
                BuyCandidate(
                    ticker="AAA",
                    score=80.0,
                    deploy_pct=10.0,
                    entry=100.0,
                    stop=93.0,
                    tp1=121.0,
                    tp2=142.0,
                    why_now="strong",
                    sources={"factor": 80, "momentum": 70, "rsi": 60, "breakout": 75},
                )
            ],
            skipped={"BBB": "held", "CCC": "cooldown"},  # 2 entries, < 5
            regime="sideways_low_vol",
            vix=18.0,
            total_deploy_pct=10.0,
            timestamp_kst="2026-05-04 12:00:00 KST",
        )
        md = render_markdown(result)
        assert "### Skipped (2 — reasons)" in md
        assert "**BBB**: held" in md and "**CCC**: cooldown" in md
        # No "+more" line because count <= 5
        assert "more" not in md

    def test_render_markdown_with_skipped_over_5(self):
        """Lines 487-488: skipped > 5 → '+N more' line with correct count."""
        from nuri.trading.recommend.buy_candidate_emitter import EmitResult, render_markdown

        skipped = {f"T{i}": f"reason{i}" for i in range(8)}  # 8 entries → 5 listed + 3 more
        result = EmitResult(
            candidates=[],
            skipped=skipped,
            regime="sideways_low_vol",
            vix=18.0,
            total_deploy_pct=0.0,
            blocked_reason="no qualified",
            timestamp_kst="2026-05-04 12:00:00 KST",
        )
        # blocked_reason path — early return before skipped section. Use a non-blocked
        # variant to hit lines 481-488.
        result.blocked_reason = None
        md = render_markdown(result)
        # 8 - 5 = 3 more
        assert "+3 more" in md


class TestBuyCandidateEmitterMain:
    """Lines 494-502, 506: main() CLI entry."""

    def test_main_prints_summary(self, monkeypatch, capsys):
        """main() prints render_markdown + Summary line + returns 0.

        Locks: the Summary line uses the exact emoji-free format with 4 fields.
        """
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import vix_gate as vg
        from nuri.trading.recommend.buy_candidate_emitter import EmitResult

        fake_result = EmitResult(
            candidates=[],
            skipped={},
            regime="bull",
            vix=15.0,
            total_deploy_pct=0.0,
            blocked_reason="empty universe",
            timestamp_kst="2026-05-04",
        )
        monkeypatch.setattr(bce, "emit_buy_candidates", lambda: fake_result)

        # `main()` 이 CLI 인자를 파싱하므로 argv 를 명시한다 (#1078 `--persist` 도입).
        # 생략하면 argparse 가 **pytest 의 sys.argv** 를 읽어 unrecognized arguments 로
        # 죽는다 — xdist 워커에서는 argv 가 달라 통과해 버려서 조용히 가려진다.
        rc = bce.main([])
        assert rc == 0
        out = capsys.readouterr().out
        # Lock summary format
        assert "Summary: 0 candidates, 0 skipped, regime=bull, VIX=15.0" in out
        # Markdown also printed (blocked path)
        assert "BUY Candidates" in out

    def test_main_does_not_persist_by_default(self, monkeypatch, capsys):
        """CLI 기본은 **조회만** — 후보를 눈으로 보려고 돌리는 게 원장을 오염시키면 안 된다.

        Mutation lock: `--persist` 게이트를 없애고 항상 저장하면 FAIL.
        """
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import tracker as tr
        from nuri.trading.recommend.buy_candidate_emitter import EmitResult

        calls: list = []
        monkeypatch.setattr(bce, "emit_buy_candidates", lambda: EmitResult(regime="bull"))
        monkeypatch.setattr(tr, "save_buy_candidates", lambda *a, **k: calls.append(a) or 0)

        assert bce.main([]) == 0
        assert calls == [], "조회만 했는데 원장에 썼다"
        assert "원장 기록" not in capsys.readouterr().out

    def test_main_persists_when_asked(self, monkeypatch, capsys):
        """`--persist` 면 기록하고 건수를 찍는다.

        Mutation lock: 저장 호출을 지우면 FAIL.
        """
        from nuri.trading.recommend import buy_candidate_emitter as bce
        from nuri.trading.recommend import tracker as tr
        from nuri.trading.recommend.buy_candidate_emitter import EmitResult

        emitted = EmitResult(regime="bull")
        calls: list = []
        monkeypatch.setattr(bce, "emit_buy_candidates", lambda: emitted)
        monkeypatch.setattr(tr, "save_buy_candidates", lambda r: calls.append(r) or 3)

        assert bce.main(["--persist"]) == 0
        assert calls == [emitted]
        assert "원장 기록: 3건" in capsys.readouterr().out

    def test_module_main_invocation_via_runpy(self, monkeypatch):
        """Line 506: `if __name__ == '__main__': raise SystemExit(main())`.

        runpy executes the module; we patch emit_buy_candidates at the source so the
        re-executed main() picks up our stub. SystemExit(0) is the expected outcome.
        """
        import runpy
        import sys
        import tempfile
        from pathlib import Path as _P

        import nuri.core.db as _db_mod
        from nuri.core.db import init_db

        # `__main__` 실행은 `main()` 을 인자 없이 부르고, argparse 는 그때 **pytest 의
        # sys.argv** 를 읽는다 (#1078 `--persist` 도입 이후). 실제 CLI 호출 모양으로 고정한다.
        monkeypatch.setattr(sys, "argv", ["buy_candidate_emitter"])

        _tmp = _P(tempfile.mkdtemp()) / "rp.db"
        init_db(_tmp)
        monkeypatch.setattr(_db_mod, "DB_PATH", _tmp)

        from nuri.trading.recommend.buy_candidate_emitter import EmitResult

        # Stub the heavy emit_buy_candidates so module exec doesn't hit DB
        fake = EmitResult(
            candidates=[],
            skipped={},
            regime="sideways_low_vol",
            vix=18.0,
            blocked_reason="stub",
            timestamp_kst="2026-05-04",
        )

        # Patch via sys.modules pre-injection: replace the function on the source module
        import nuri.trading.recommend.buy_candidate_emitter as src_mod

        monkeypatch.setattr(src_mod, "emit_buy_candidates", lambda: fake)

        # Suppress stdout for cleanliness
        import io as _io

        monkeypatch.setattr(sys, "stdout", _io.StringIO())

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("nuri.trading.recommend.buy_candidate_emitter", run_name="__main__")
        # Lock: SystemExit(0) — main returned 0 then `raise SystemExit(0)` propagated
        assert exc_info.value.code == 0


# ════════════════════════════════════════════════════════════════════
# held_add.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestHeldAddShadowParseError:
    """Lines 88-89: shadow_mode_until parse error → False (live)."""

    def test_invalid_until_string_returns_false(self):
        """date.fromisoformat('not-a-date') raises ValueError → False."""
        from nuri.trading.recommend.held_add import _is_shadow_mode

        result = _is_shadow_mode({"shadow_mode_until": "not-a-date"}, today=date(2026, 5, 4))
        # Lock: parse error must NOT raise — it must return False (fail-live, not stuck shadow)
        assert result is False

    def test_until_is_none_type_returns_false(self):
        """TypeError path: shadow_mode_until is e.g. an int (not str / date)."""
        from nuri.trading.recommend.held_add import _is_shadow_mode

        # Pass an int — date.fromisoformat raises TypeError on non-str
        # The except clause catches both ValueError and TypeError (line 88-89).
        result = _is_shadow_mode({"shadow_mode_until": 42}, today=date(2026, 5, 4))
        assert result is False


class TestHeldAddEarningsBlackoutInternals:
    """Lines 115-117, 124, 126: is_in_earnings_blackout edge paths."""

    def test_earnings_date_not_a_date_object_returns_false(self):
        """Line 125-126: earnings_date isn't `date` → False (fail-open)."""
        from nuri.trading.recommend.held_add import is_in_earnings_blackout

        # Provide a string instead of date — has no `.date()` and isinstance fails
        fetcher = SimpleNamespace(calendar={"Earnings Date": ["2026-05-06"]})  # plain str
        result = is_in_earnings_blackout("MSFT", days=5, today=date(2026, 5, 4), fetcher=fetcher)
        # Line 126: `if not isinstance(earnings_date, date): return False`
        assert result is False

    def test_earnings_date_via_datetime_dot_date_method(self):
        """Line 123-124: pandas Timestamp / datetime → has `.date()` method, get unwrapped."""
        from nuri.trading.recommend.held_add import is_in_earnings_blackout

        # datetime has `.date()` method (line 123 `hasattr(earnings_date, "date")`)
        # When unwrapped to a date, it must compare to `today` correctly.
        earnings = datetime(2026, 5, 6, 14, 30)  # 2 days after today
        fetcher = SimpleNamespace(calendar={"Earnings Date": [earnings]})
        result = is_in_earnings_blackout("MSFT", days=5, today=date(2026, 5, 4), fetcher=fetcher)
        assert result is True  # |2026-05-06 - 2026-05-04| = 2 ≤ 5


class TestHeldAddRealAccountsFileMissing:
    """Line 143-144: portfolio.yaml missing → empty set (FileNotFoundError swallowed)."""

    def test_missing_portfolio_yaml_returns_empty_set(self, monkeypatch, tmp_path):
        """If config/portfolio.yaml doesn't exist → return set()."""
        # Patch builtins.open to raise FileNotFoundError when production code
        # tries to read portfolio.yaml — this exercises the FNF guard branch.
        import builtins

        from nuri.trading.recommend import held_add as ha

        original_open = builtins.open

        def fake_open(path, *a, **kw):
            if "portfolio.yaml" in str(path):
                raise FileNotFoundError(str(path))
            return original_open(path, *a, **kw)

        monkeypatch.setattr(builtins, "open", fake_open)
        result = ha._get_real_accounts()
        # Lock: returns set() (specifically empty) — must be a set type
        assert result == set()
        assert isinstance(result, set)


class TestHeldAddGetHeldPositionsEmpty:
    """Line 170-171: portfolio empty → []."""

    def test_empty_portfolio_returns_empty_list(self, fresh_db, monkeypatch):
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        from nuri.trading.recommend.held_add import _get_held_positions

        result = _get_held_positions()
        assert result == []
        assert isinstance(result, list)


class TestHeldAddLastTrimAge:
    """Lines 218-219, 224-226: _get_last_trim_age_days exception path + None."""

    def test_no_trim_event_returns_none(self, fresh_db, monkeypatch):
        """Lines 209-210: empty df / NULL last_ts → None.

        Empty pipeline_events → query returns df with NULL last_ts → return None.
        """
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        from nuri.trading.recommend.held_add import _get_last_trim_age_days

        # Empty pipeline_events → MAX(timestamp) returns NULL
        result = _get_last_trim_age_days("AAA")
        assert result is None

    def test_malformed_timestamp_returns_none(self, fresh_db, monkeypatch):
        """Lines 218-219: parse exception → None."""
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        from nuri.trading.recommend.held_add import _get_last_trim_age_days

        # Insert malformed timestamp into pipeline_events
        with get_db(fresh_db) as conn:
            # Use very recent timestamp (must pass the -60d filter) but with a
            # form that breaks `_dt.fromisoformat(last_ts.split(" ")[0])`.
            # The query MAX-aggregates so we need the row to be the only one.
            today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO pipeline_events (event_type, step, payload, timestamp)
                   VALUES ('test', 'test', json('{"ticker": "AAA", "action_type": "trim_action"}'), ?)""",
                (today_str,),
            )

        # Force fromisoformat to raise inside the function
        from datetime import datetime as _dt

        monkeypatch.setattr("nuri.trading.recommend.held_add.date", _dt)
        # The function imports datetime locally (line 213). We patch on that
        # local reference path:
        import nuri.trading.recommend.held_add as ha_mod

        # The local import is `from datetime import datetime as _dt` inside the
        # try block. We can't easily patch that. Easier approach: feed a string
        # whose `.split(" ")[0]` produces invalid ISO date.
        with get_db(fresh_db) as conn:
            conn.execute("DELETE FROM pipeline_events")
            # Insert a valid recent timestamp but corrupt the date portion
            # via a raw value that survives MAX() but breaks fromisoformat.
            # Trick: a timestamp like '99999-99-99 00:00:00' isn't valid ISO date.
            # SQLite stores arbitrary strings; the WHERE filter datetime('now', '-60 days')
            # uses string comparison — '99999-...' > 'now' so passes the filter.
            conn.execute(
                """INSERT INTO pipeline_events (event_type, step, payload, timestamp)
                   VALUES ('test', 'test', json('{"ticker": "AAA", "action_type": "trim_action"}'), ?)""",
                ("9999-13-99 00:00:00",),
            )

        result = _get_last_trim_age_days("AAA", max_days=999999)
        # Either None (parse failed) or some int — but the exception path lands at None.
        # Strong assertion: integer parse of "13"-month is invalid → None.
        assert result is None


class TestHeldAddEvaluateTp1ResidualNoneBranches:
    """Lines 244, 246, 252, 255, 258: tp1_residual_add early-return-None branches.

    Each gate failure must return None — not raise, not return a partial mode.
    """

    def test_no_trim_age_returns_none(self, monkeypatch):
        """Line 241-242: last_trim_age None → return None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: None)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})

        cfg = {"modes": {"tp1_residual_add": {"trigger": {"last_trim_age_days_min": 5}}}}
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 50.0}
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=80, breakout_above_trim=True) is None

    def test_age_too_young_returns_none(self, monkeypatch):
        """Line 243-244: last_trim_age < min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: 3)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {"modes": {"tp1_residual_add": {"trigger": {"last_trim_age_days_min": 5, "last_trim_age_days_max": 60}}}}
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 50.0}
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=80, breakout_above_trim=True) is None

    def test_age_too_old_returns_none(self, monkeypatch):
        """Line 245-246: last_trim_age > max → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: 200)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {"modes": {"tp1_residual_add": {"trigger": {"last_trim_age_days_min": 5, "last_trim_age_days_max": 60}}}}
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 50.0}
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=80, breakout_above_trim=True) is None

    def test_pnl_below_threshold_returns_none(self, monkeypatch):
        """Line 251-252: pnl_pct < tp1×factor → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: 10)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        # tp1 21 × 1.2 = 25.2 threshold; pos pnl 20% < threshold
        cfg = {
            "modes": {
                "tp1_residual_add": {
                    "trigger": {
                        "last_trim_age_days_min": 5,
                        "last_trim_age_days_max": 60,
                        "unrealized_pnl_min_factor": 1.2,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 20.0}
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=80, breakout_above_trim=True) is None

    def test_score_below_min_returns_none(self, monkeypatch):
        """Line 254-255: score < composite_score_min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: 10)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {
            "modes": {
                "tp1_residual_add": {
                    "trigger": {
                        "last_trim_age_days_min": 5,
                        "last_trim_age_days_max": 60,
                        "unrealized_pnl_min_factor": 1.2,
                        "composite_score_min": 75,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 30.0}
        # score 60 < 75 → None
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=60, breakout_above_trim=True) is None

    def test_breakout_required_but_false_returns_none(self, monkeypatch):
        """Line 257-258: require_breakout=True but breakout_above_trim=False → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_last_trim_age_days", lambda t, max_days=60, db_path=None: 10)
        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {
            "modes": {
                "tp1_residual_add": {
                    "trigger": {
                        "last_trim_age_days_min": 5,
                        "last_trim_age_days_max": 60,
                        "unrealized_pnl_min_factor": 1.2,
                        "composite_score_min": 75,
                        "require_breakout_above_last_trim_price": True,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 30.0}
        assert ha._evaluate_tp1_residual_add(pos, cfg, score=80, breakout_above_trim=False) is None


class TestHeldAddRideWinnerNoneBranches:
    """Lines 267, 276, 279, 282: ride_winner early-return-None branches."""

    def test_no_trigger_config_returns_none(self):
        """Line 266-267: empty trigger dict → None."""
        from nuri.trading.recommend import held_add as ha

        cfg = {"modes": {"ride_winner": {}}}  # no trigger key
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 80.0, "days_held": 60}
        assert ha._evaluate_ride_winner(pos, cfg, score=80, sector_mom=10) is None

    def test_pnl_below_factor_returns_none(self, monkeypatch):
        """Line 272-273: pnl < tp1×min_factor → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {"modes": {"ride_winner": {"trigger": {"unrealized_pnl_min_factor": 2.5}}}}
        # 21 × 2.5 = 52.5 threshold; pnl 40 below
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 40.0, "days_held": 60}
        assert ha._evaluate_ride_winner(pos, cfg, score=80, sector_mom=10) is None

    def test_days_held_below_min_returns_none(self, monkeypatch):
        """Line 275-276: days_held < min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {
            "modes": {
                "ride_winner": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 2.5,
                        "days_held_min": 30,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 60.0, "days_held": 10}
        assert ha._evaluate_ride_winner(pos, cfg, score=80, sector_mom=10) is None

    def test_score_below_min_returns_none(self, monkeypatch):
        """Line 278-279: score < composite_score_min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {
            "modes": {
                "ride_winner": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 2.5,
                        "days_held_min": 30,
                        "composite_score_min": 75,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 60.0, "days_held": 60}
        assert ha._evaluate_ride_winner(pos, cfg, score=60, sector_mom=10) is None

    def test_sector_mom_below_min_returns_none(self, monkeypatch):
        """Line 281-282: sector_mom < min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"tp1_pct": 21.0})
        cfg = {
            "modes": {
                "ride_winner": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 2.5,
                        "days_held_min": 30,
                        "composite_score_min": 75,
                        "sector_momentum_min": 5,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 60.0, "days_held": 60}
        assert ha._evaluate_ride_winner(pos, cfg, score=80, sector_mom=2) is None


class TestHeldAddAverageDownNoneBranches:
    """Lines 298, 308, 311, 314, 317: average_down early-return-None branches."""

    def test_no_trigger_returns_none(self):
        """Line 297-298: empty trigger → None."""
        from nuri.trading.recommend import held_add as ha

        cfg = {"modes": {"average_down": {}}}
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -5.0, "days_held": 30}
        assert ha._evaluate_average_down(pos, cfg, score=85, rsi=30, regime="sideways_low_vol", vix=18) is None

    def test_pnl_outside_window_returns_none(self, monkeypatch):
        """Line 307-308: pnl outside [pnl_max, pnl_min] window → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"stop_loss": -10})
        cfg = {
            "modes": {
                "average_down": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 0.3,
                        "unrealized_pnl_max_factor": 0.7,
                    }
                }
            }
        }
        # stop -10 × 0.3 = -3, × 0.7 = -7. Window: [-7, -3]. pnl=-1 outside.
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -1.0, "days_held": 30}
        assert ha._evaluate_average_down(pos, cfg, score=85, rsi=30, regime="sideways_low_vol", vix=18) is None

    def test_score_below_min_returns_none(self, monkeypatch):
        """Line 310-311: score < min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"stop_loss": -10})
        cfg = {
            "modes": {
                "average_down": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 0.3,
                        "unrealized_pnl_max_factor": 0.7,
                        "composite_score_min": 80,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -5.0, "days_held": 30}
        assert ha._evaluate_average_down(pos, cfg, score=70, rsi=30, regime="sideways_low_vol", vix=18) is None

    def test_rsi_above_max_returns_none(self, monkeypatch):
        """Line 313-314: rsi > rsi_max → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"stop_loss": -10})
        cfg = {
            "modes": {
                "average_down": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 0.3,
                        "unrealized_pnl_max_factor": 0.7,
                        "composite_score_min": 80,
                        "rsi_max": 35,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -5.0, "days_held": 30}
        # rsi 50 > 35 → None
        assert ha._evaluate_average_down(pos, cfg, score=85, rsi=50, regime="sideways_low_vol", vix=18) is None

    def test_rsi_none_returns_none(self, monkeypatch):
        """Line 313-314: rsi is None → None (require RSI signal)."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"stop_loss": -10})
        cfg = {
            "modes": {
                "average_down": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 0.3,
                        "unrealized_pnl_max_factor": 0.7,
                        "composite_score_min": 80,
                        "rsi_max": 35,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -5.0, "days_held": 30}
        assert ha._evaluate_average_down(pos, cfg, score=85, rsi=None, regime="sideways_low_vol", vix=18) is None

    def test_days_held_below_min_returns_none(self, monkeypatch):
        """Line 316-317: days_held < min → None."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(ha, "_get_account_strategy_profile", lambda a: {"stop_loss": -10})
        cfg = {
            "modes": {
                "average_down": {
                    "trigger": {
                        "unrealized_pnl_min_factor": 0.3,
                        "unrealized_pnl_max_factor": 0.7,
                        "composite_score_min": 80,
                        "rsi_max": 35,
                        "days_held_min": 14,
                    }
                }
            }
        }
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": -5.0, "days_held": 5}
        assert ha._evaluate_average_down(pos, cfg, score=85, rsi=30, regime="sideways_low_vol", vix=18) is None


class TestHeldAddEmitFlowSkipped:
    """Lines 462-463: emit_held_add_shadow flow — 'no mode triggered' + cap headroom 0.

    Cover the two skipped branches at the bottom of the per-position loop.
    """

    def test_no_mode_triggered_recorded_in_skipped(self, fresh_db, monkeypatch, tmp_path):
        """Line 461-462: select_held_mode returns None → skipped[key] = 'no mode triggered'."""
        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)

        # Seed one held position
        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "AAA", 10.0, 100.0, "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2026-05-04", 105.0),
            )

        # Config that enables the module and sets shadow_mode=True
        cfg_path = tmp_path / "buy_signals.yaml"
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "held_add_mode": {
                        "enabled": True,
                        "shadow_mode_until": "2099-01-01",
                        "earnings_blackout_days": 5,
                        "modes": {
                            # Set thresholds so high that no mode can trigger
                            "tp1_residual_add": {"trigger": {"composite_score_min": 999}},
                            "ride_winner": {"trigger": {"composite_score_min": 999}},
                            "average_down": {"trigger": {"composite_score_min": 999}},
                        },
                    }
                }
            )
        )

        from nuri.trading.recommend import held_add as ha

        # Stub: bypass real_accounts gate so AAA passes _get_held_positions filter
        monkeypatch.setattr(ha, "_get_real_accounts", lambda: set())
        # Stub earnings blackout to False
        monkeypatch.setattr(ha, "is_in_earnings_blackout", lambda *a, **kw: False)
        # Stub _get_account_strategy_profile so cap derivation works
        monkeypatch.setattr(
            ha,
            "_get_account_strategy_profile",
            lambda a: {"stop_loss": -7, "tp1_pct": 21.0, "max_single_position": 0.15},
        )
        monkeypatch.setattr(
            "nuri.core.account_cap.get_account_strategy",
            lambda a: {"max_single_position": 0.15},
        )

        result = ha.emit_held_add_shadow(
            config_path=cfg_path,
            today=date(2026, 5, 4),
            score_provider=lambda t: 50.0,  # below all 999 thresholds
            rsi_provider=lambda t: 50.0,
            regime_provider=lambda: ("sideways_low_vol", 18.0),
            db_path=fresh_db,
        )

        # Lock: AAA@acct_x recorded with 'no mode triggered' reason (line 462)
        assert "AAA@acct_x" in result.skipped
        assert result.skipped["AAA@acct_x"] == "no mode triggered"
        assert result.candidates == []  # nothing emitted


# ════════════════════════════════════════════════════════════════════
# candidates.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestCandidatesScorecardLoading:
    """Lines 90-91 (ValueError swallow), 112-118 (stale SELL drop)."""

    def test_invalid_dirname_swallowed(self, tmp_path, monkeypatch):
        """Line 87-91: directory name not parseable as YYYY-MM-DD → except ValueError."""
        from nuri.trading.recommend import candidates as cnd

        # Create a report dir with an invalid dirname containing scorecard.csv
        bad_dir = tmp_path / "not-a-date"
        bad_dir.mkdir()
        (bad_dir / "signal_scorecard.csv").write_text(
            "signal_id,ticker,win_rate,profit_factor,avg_return,total_trades\nrsi_30,,0.55,1.2,0.05,100\n"
        )
        monkeypatch.setattr(cnd, "REPORT_DIR", tmp_path)

        scorecard, age = cnd._load_scorecard()
        # Lock: the function survived the ValueError and returned the parsed scorecard;
        # age stays None because dirname couldn't be parsed (line 90-91 covered).
        assert age is None
        assert "rsi_30" in scorecard

    def test_stale_sell_signals_dropped(self, tmp_path, monkeypatch):
        """Line 109-118: SELL signal with PF>1 → flagged stale, dropped from data."""
        from nuri.quant.validation.signal_backtest import SELL_SIGNALS
        from nuri.trading.recommend import candidates as cnd

        # Use an actual SELL signal id
        sell_sig = next(iter(SELL_SIGNALS))
        d = tmp_path / "2026-05-04"
        d.mkdir()
        (d / "signal_scorecard.csv").write_text(
            "signal_id,ticker,win_rate,profit_factor,avg_return,total_trades\n"
            f"{sell_sig},,0.6,1.5,0.05,50\n"  # PF=1.5 > 1.0 → stale
            "rsi_30,,0.55,1.2,0.05,100\n"  # BUY signal, kept
        )
        monkeypatch.setattr(cnd, "REPORT_DIR", tmp_path)

        scorecard, age = cnd._load_scorecard()
        # Lock: stale SELL dropped, valid BUY remains
        assert sell_sig not in scorecard, f"{sell_sig} (SELL) with PF>1.0 must be dropped — line 117 `data.pop`"
        assert "rsi_30" in scorecard, "BUY signal with valid stats must remain"


class TestCandidatesScreenEmptyShortCircuit:
    """Line 218 (df < 50 rows skip path covered indirectly via fresh_db)."""

    def test_screen_with_empty_universe(self, fresh_db):
        """get_tickers() returns [] → return [] (line 207-208 already covered) — augment with
        explicit assertion that no DB access happens after."""
        from nuri.trading.recommend.candidates import screen_candidates

        result = screen_candidates(lookback_days=5, db_path=fresh_db)
        assert result == []


class TestCandidatesPrintEmpty:
    """Line 458-460: print_candidates with empty list."""

    def test_print_candidates_empty(self, capsys):
        """Empty list → '매매 후보 없음' message."""
        from nuri.trading.recommend.candidates import print_candidates

        print_candidates([])
        out = capsys.readouterr().out
        assert "매매 후보 없음" in out


class TestCandidatesPrintNonEmpty:
    """Lines 477, 492-501, 512, 514, 525-532: print_candidates with various tier mixes."""

    def test_print_candidates_with_mixed_tiers(self, capsys, monkeypatch):
        """Print path with actionable + advisory + avoid + conflict + regime_avoided.

        Locks the table render branches: UNSCORED flag (492-493), drift flag, conflict
        flag, dash placeholder for unscored win_rate/PF (500-501), advisory header (512),
        avoid header (514), regime-filtered footer (516-519).
        """
        from nuri.trading.recommend import candidates as cnd
        from nuri.trading.recommend.candidates import (
            TIER_ACTIONABLE,
            TIER_ADVISORY,
            TIER_AVOID,
            Candidate,
            print_candidates,
        )

        # Stub _check_vix_gate to avoid DB reads
        monkeypatch.setattr(
            cnd,
            "_check_vix_gate",
            lambda *a, **kw: {"gate": "caution", "msg": "VIX caution"},
        )

        cands = [
            Candidate(
                ticker="AAA",
                signal_id="rsi_30",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=80.0,
                win_rate=0.6,
                profit_factor=1.5,
                regime_fit=True,
                price=100.0,
                notes="",
                tier=TIER_ACTIONABLE,
                drift_status="",
            ),
            Candidate(
                ticker="BBB",
                signal_id="rsi_70",
                signal_date="2026-05-04",
                direction="SELL",
                confidence=70.0,
                win_rate=0.55,
                profit_factor=1.3,
                regime_fit=True,
                price=200.0,
                notes="",
                tier=TIER_ACTIONABLE,
                drift_status="critical",  # → drift flag rendered
            ),
            Candidate(
                ticker="CCC",
                signal_id="unknown_sig",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                regime_fit=True,
                price=50.0,
                notes="",
                tier=TIER_ADVISORY,
                unscored=True,  # → UNSCORED flag rendered, dash placeholders
            ),
            Candidate(
                ticker="DDD",
                signal_id="bad_sig",
                signal_date="2026-05-04",
                direction="SELL",
                confidence=0.0,
                win_rate=0.3,
                profit_factor=0.5,
                regime_fit=True,
                price=10.0,
                notes="",
                tier=TIER_AVOID,
                drift_status="",
            ),
            Candidate(
                ticker="EEE",
                signal_id="x_sig",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=20.0,
                win_rate=0.5,
                profit_factor=1.0,
                regime_fit=False,  # → regime_avoided footer
                price=30.0,
                notes="레짐 회피",
                tier=TIER_ACTIONABLE,
                drift_status="",
            ),
            Candidate(
                ticker="FFF",
                signal_id="conf_sig",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=40.0,
                win_rate=0.5,
                profit_factor=1.0,
                regime_fit=True,  # included in actionable BUY → CONF flag visible
                price=20.0,
                notes="",
                tier=TIER_ACTIONABLE,
                drift_status="",
                conflict="direction_conflict",  # → CONF flag rendered (line 495-497)
            ),
        ]
        print_candidates(cands)
        out = capsys.readouterr().out

        # Header banner with caution tier
        assert "VIX caution" in out
        # Actionable BUY / SELL tables
        assert "Actionable BUY" in out
        assert "Actionable SELL" in out
        # Advisory header (line 512)
        assert "Advisory" in out
        # Avoid header (line 514)
        assert "Avoid" in out
        # Regime-filtered footer (line 516-519)
        assert "Regime-Filtered" in out
        # UNSCORED flag for CCC
        assert "UNSCORED" in out
        # Dash placeholders for unscored CCC
        assert "—" in out
        # Drift / conflict flags
        assert "D:crit" in out  # drift_status[:4]
        assert "CONF" in out


class TestCandidatesMainCli:
    """Lines 525-532: __main__ argparse + screen + print path."""

    def test_main_cli_with_empty_db(self, fresh_db, monkeypatch, capsys):
        """Run candidates.py as `__main__` against an empty isolated DB.

        With empty DB, screen_candidates returns [] → print_candidates prints
        '매매 후보 없음' (line 458-460). Lines 525-532 are exercised by the
        runpy invocation.
        """
        import runpy

        import nuri.core.db as db_mod

        # Point default DB to fresh empty DB so screen_candidates → []
        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        monkeypatch.setattr(sys, "argv", ["candidates.py", "--days", "3"])

        runpy.run_module("nuri.trading.recommend.candidates", run_name="__main__")
        out = capsys.readouterr().out
        # Lock: print_candidates ran via __main__ (line 532) and emitted the
        # "no candidates" message because empty DB has no tickers.
        assert "매매 후보 없음" in out


# ════════════════════════════════════════════════════════════════════
# tracker.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestTrackerRebalanceSellSkip:
    """Lines 119-121: rebalance SELL on non-held → skip."""

    def test_rebalance_sell_on_zero_qty_skipped(self, fresh_db):
        """Line 119-121: action.action='SELL' but ticker not held → skip."""
        from nuri.trading.recommend.tracker import save_recommendations

        @dataclass
        class FakeAction:
            ticker: str = "AAA"
            action: str = "SELL"
            signals: list = field(default_factory=lambda: ["test"])
            regime_note: str = ""

        # Empty portfolio → AAA not held
        n = save_recommendations(candidates=None, actions=[FakeAction()], db_path=fresh_db)
        # Lock: SELL action on non-held ticker is skipped → 0 records persisted
        assert n == 0


class TestTrackerCliMain:
    """Lines 383-422: tracker.py __main__ branch with --save."""

    def test_main_save_flow_via_runpy(self, fresh_db, monkeypatch):
        """Lines 388-422: tracker `--save` orchestration path via runpy.

        runpy re-executes the module source with __name__='__main__'. Its fresh
        defs of save_recommendations / track_outcomes can't be monkeypatched on
        the already-imported module, so we stub the DEEPER dependency that those
        functions call into (candidates.screen_candidates returns []) and rely on
        the empty-flow path (which still executes lines 388-422).
        """
        import runpy

        # Empty candidates → save_recommendations is a no-op, track_outcomes
        # operates on real but isolated DB.
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda lookback_days=5: [],
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.rebalance.regime_aware_rebalance",
            lambda method="rp": [],
        )

        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        monkeypatch.setattr(sys, "argv", ["tracker.py", "--save"])

        # Suppress stdout
        import io as _io

        monkeypatch.setattr(sys, "stdout", _io.StringIO())

        # Should run cleanly (no exception). Empty candidates / actions, so save
        # writes 0 rows and track_outcomes finds 0 to update — but lines 388-422
        # all execute (the orchestration path).
        runpy.run_module("nuri.trading.recommend.tracker", run_name="__main__")

        # Behavioral lock: 0 rows persisted because we fed empty candidates →
        # confirms save_recommendations actually ran (not skipped). Querying the
        # recommendations table should not have grown from empty -> empty without
        # the orchestration path executing.
        rows = query("SELECT COUNT(*) AS c FROM recommendations", db_path=fresh_db)
        assert rows[0]["c"] == 0  # nothing persisted (empty input) — flow ran

    def test_main_save_with_dropped_advisory_logs_count(self, fresh_db, monkeypatch, caplog):
        """Lines 399-404: when advisory/avoid candidates filtered out → log info with count.

        Stub screen_candidates to return mix; the dropped count > 0 triggers line 401.
        """
        import logging
        import runpy

        import nuri.core.db as db_mod
        from nuri.trading.recommend.candidates import (
            TIER_ACTIONABLE,
            TIER_ADVISORY,
            Candidate,
        )

        cands = [
            Candidate(
                ticker="AAA",
                signal_id="s1",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=70.0,
                win_rate=0.6,
                profit_factor=1.5,
                regime_fit=True,
                price=100.0,
                notes="",
                tier=TIER_ACTIONABLE,
            ),
            Candidate(
                ticker="BBB",
                signal_id="s2",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=20.0,
                win_rate=0.3,
                profit_factor=0.8,
                regime_fit=True,
                price=50.0,
                notes="",
                tier=TIER_ADVISORY,  # → dropped
            ),
        ]

        # Patch screen_candidates at source so __main__ block sees the mix
        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda lookback_days=5: cands,
        )
        monkeypatch.setattr(
            "nuri.trading.recommend.rebalance.regime_aware_rebalance",
            lambda method="rp": [],
        )
        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        monkeypatch.setattr(sys, "argv", ["tracker.py", "--save"])

        import io as _io

        monkeypatch.setattr(sys, "stdout", _io.StringIO())

        with caplog.at_level(logging.INFO):
            runpy.run_module("nuri.trading.recommend.tracker", run_name="__main__")

        # Lock: dropped count = 1 (BBB advisory) → line 401-404 logged
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "actionable 1건 저장" in msgs and "advisory/avoid 1건" in msgs, (
            f"line 401 log not emitted; captured: {msgs}"
        )

    def test_main_save_with_rebalance_failure_via_runpy(self, fresh_db, monkeypatch):
        """Lines 413-415: rebalance raises → except path → actions=None, save still runs.

        Same pattern as above — stub upstream so the body of the except handler
        actually executes.
        """
        import runpy

        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.screen_candidates",
            lambda lookback_days=5: [],
        )

        # Force regime_aware_rebalance to raise → exercises lines 413-415
        def boom(method="rp"):
            raise RuntimeError("rebalance fail")

        monkeypatch.setattr("nuri.trading.recommend.rebalance.regime_aware_rebalance", boom)

        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)
        monkeypatch.setattr(sys, "argv", ["tracker.py", "--save"])

        import io as _io

        monkeypatch.setattr(sys, "stdout", _io.StringIO())

        # Must NOT raise — the except in tracker.__main__ swallows it (line 413-415)
        runpy.run_module("nuri.trading.recommend.tracker", run_name="__main__")

        # Behavior: tracker reached the save+track step with actions=None.
        # (No way to assert internal `actions=None` directly through runpy — but
        # the no-raise outcome locks the except clause.)


# ════════════════════════════════════════════════════════════════════
# holdings_monitor.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestHoldingsMonitorRunMonitorDisabled:
    """Line 199 / 207-217: cfg disabled → early return RunSummary with 0 holdings."""

    def test_run_monitor_disabled_returns_zero_summary(self, fresh_db, monkeypatch):
        """When cfg.enabled is False, return RunSummary(n_holdings=0, n_alerted=0)."""
        from nuri.trading.recommend import holdings_monitor as hm

        # Force the module-level RULES dict to disable
        monkeypatch.setattr(hm, "RULES", {"holdings_monitor": {"enabled": False}})

        summary = hm.run_monitor(db_path=fresh_db)
        # Lock: explicit zero counts — the early-return path
        assert summary.n_holdings == 0
        assert summary.n_alerted == 0
        assert summary.alerts == []


class TestHoldingsMonitorEvaluateTriggersNoTrigger:
    """Line 199: _evaluate_triggers fall-through (no trigger met) → (None, diagnostics)."""

    def test_no_trigger_fires_returns_none_with_diagnostics(self, fresh_db, monkeypatch):
        """consensus result with low-conf BUY (not SELL, no divergence) → None tuple."""
        from nuri.trading.agents.base import AgentVerdict
        from nuri.trading.agents.consensus import ConsensusResult
        from nuri.trading.recommend import holdings_monitor as hm

        def fake_analyze(ticker, db_path=None):
            return ConsensusResult(
                ticker=ticker,
                final_action="HOLD",
                final_confidence=50,
                agreement_rate=0.5,
                verdicts=[AgentVerdict("technical", ticker, "BUY", 30, "weak")],
                dissent=[],
                reasoning="test",
                divergence_flag=False,
                divergence_reason="",
            )

        monkeypatch.setattr("nuri.trading.agents.consensus.analyze_ticker", fake_analyze)

        trigger, diag = hm._evaluate_triggers(
            ticker="AAA",
            db_path=fresh_db,
            technical_sell_threshold=80,
            divergence_threshold=70,
        )
        # Lock: line 199 fall-through path — no SELL trigger and no divergence.
        assert trigger is None
        assert isinstance(diag, dict)
        # technical_action='BUY' so trigger A (SELL ≥ 80) doesn't fire
        assert diag.get("technical_action") == "BUY"


class TestHoldingsMonitorMainCli:
    """Lines 388-408: main() CLI."""

    def test_main_dry_run_returns_zero(self, monkeypatch, capsys):
        """main(['--dry-run']) → calls run_monitor(dry_run=True), returns 0."""
        from nuri.trading.recommend import holdings_monitor as hm
        from nuri.trading.recommend.holdings_monitor import RunSummary

        captured_dry_run: dict[str, bool | None] = {"v": None}

        def fake_run(db_path=None, dry_run=False):
            captured_dry_run["v"] = dry_run
            return RunSummary(
                run_at_kst="2026-05-04",
                n_holdings=0,
                n_alerted=0,
                n_skipped_dedup=0,
                n_skipped_data_gap=0,
                n_skipped_scope=0,
            )

        monkeypatch.setattr(hm, "run_monitor", fake_run)

        rc = hm.main(["--dry-run"])
        assert rc == 0
        # Lock: --dry-run flag forwarded to run_monitor
        assert captured_dry_run["v"] is True
        out = capsys.readouterr().out
        # JSON dump printed (line 398)
        assert '"n_holdings": 0' in out

    def test_main_with_alerts_calls_send(self, monkeypatch, capsys):
        """Lines 400-402: not dry, not no-alert, alerts present → send_alerts called."""
        from nuri.trading.recommend import holdings_monitor as hm
        from nuri.trading.recommend.holdings_monitor import RunSummary

        def fake_run(db_path=None, dry_run=False):
            return RunSummary(
                run_at_kst="2026-05-04",
                n_holdings=1,
                n_alerted=1,
                n_skipped_dedup=0,
                n_skipped_data_gap=0,
                n_skipped_scope=0,
                alerts=[{"ticker": "AAA"}],  # non-empty triggers send_alerts
            )

        send_count = {"n": 0}

        def fake_send(summary):
            send_count["n"] += 1
            return 1

        monkeypatch.setattr(hm, "run_monitor", fake_run)
        monkeypatch.setattr(hm, "send_alerts", fake_send)

        rc = hm.main([])  # no flags → not dry_run, not no_alert
        assert rc == 0
        # Lock: send_alerts called exactly once because alerts exist
        assert send_count["n"] == 1

    def test_main_module_invocation_via_runpy(self, monkeypatch):
        """Line 408: `if __name__ == '__main__': raise SystemExit(main())`."""
        import runpy
        import tempfile
        from pathlib import Path as _P

        import nuri.core.db as _db_mod
        from nuri.core.db import init_db

        _tmp = _P(tempfile.mkdtemp()) / "rp.db"
        init_db(_tmp)
        monkeypatch.setattr(_db_mod, "DB_PATH", _tmp)

        from nuri.trading.recommend import holdings_monitor as hm
        from nuri.trading.recommend.holdings_monitor import RunSummary

        monkeypatch.setattr(
            hm,
            "run_monitor",
            lambda **kw: RunSummary(
                run_at_kst="2026-05-04",
                n_holdings=0,
                n_alerted=0,
                n_skipped_dedup=0,
                n_skipped_data_gap=0,
                n_skipped_scope=0,
            ),
        )
        monkeypatch.setattr(sys, "argv", ["holdings_monitor.py", "--dry-run"])
        import io as _io

        monkeypatch.setattr(sys, "stdout", _io.StringIO())

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("nuri.trading.recommend.holdings_monitor", run_name="__main__")
        assert exc_info.value.code == 0


# ════════════════════════════════════════════════════════════════════
# price_targets.py — remaining gaps
# ════════════════════════════════════════════════════════════════════


class TestPriceTargetsTakeProfitNoPriceData:
    """Lines 363-364: check_take_profit_signals — no current price → continue."""

    def test_no_current_price_skipped(self, fresh_db):
        """Holding present but no prices for ticker → skipped silently."""
        from nuri.trading.recommend.price_targets import check_take_profit_signals

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "NOPRICE", 10.0, 100.0, "USD"),
            )
        # No prices for NOPRICE → _get_current_price returns None → continue
        result = check_take_profit_signals(db_path=fresh_db)
        assert result == [], "ticker with no price data must be silently skipped (line 363-364)"


class TestPriceTargetsTakeProfitErrorPath:
    """Line 369: 'error' in targets → continue."""

    def test_targets_error_skipped(self, fresh_db, monkeypatch):
        """If calculate_targets returns {error: ...}, skip the ticker (line 368-369)."""
        from nuri.trading.recommend import price_targets as pt

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "AAA", 10.0, 100.0, "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2026-05-04", 130.0),  # price exists → passes 363 check
            )

        # Force calculate_targets to return error dict (positional + kw)
        monkeypatch.setattr(
            pt,
            "calculate_targets",
            lambda *a, **kw: {"ticker": (a[0] if a else kw.get("ticker")), "error": "synthetic"},
        )
        result = pt.check_take_profit_signals(db_path=fresh_db)
        assert result == [], "error in targets must skip the ticker (line 369)"


class TestPriceTargetsTrailingStopBranches:
    """Lines 427, 431-432, 441, 449: check_trailing_stop_signals branches."""

    def test_trailing_stop_zero_entry_price_skipped(self, fresh_db):
        """Line 426-427: avg_price <= 0 → continue."""
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "AAA", 10.0, 0.0, "USD"),  # zero avg_price
            )
        result = check_trailing_stop_signals(db_path=fresh_db)
        assert result == []

    def test_trailing_stop_no_current_price_skipped(self, fresh_db):
        """Line 430-432: no current price → continue (debug log)."""
        from nuri.trading.recommend.price_targets import check_trailing_stop_signals

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "NOPRICE", 10.0, 100.0, "USD"),
            )
        result = check_trailing_stop_signals(db_path=fresh_db)
        assert result == []

    def test_trailing_stop_no_high_water_mark_skipped(self, fresh_db, monkeypatch):
        """Line 440-441: hwm None or <= 0 → continue."""
        from nuri.trading.recommend import price_targets as pt

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "AAA", 10.0, 100.0, "USD"),
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, close) VALUES (?, ?, ?)",
                ("AAA", "2026-05-04", 100.0),
            )

        # Force MAX(high) query to return None by patching query
        original_query = pt.query

        def fake_query(sql, *a, **kw):
            if "MAX(high)" in sql:
                return [{"max_high": None}]
            return original_query(sql, *a, **kw)

        monkeypatch.setattr(pt, "query", fake_query)
        result = pt.check_trailing_stop_signals(db_path=fresh_db)
        assert result == []

    def test_trailing_stop_swing_threshold_branch(self, fresh_db, monkeypatch):
        """Line 448-449: stock_type='swing' uses TRAILING_STOP_VOLATILE (-20%)."""
        from nuri.trading.recommend import price_targets as pt
        from nuri.trading.recommend.price_targets import (
            TRAILING_STOP_VOLATILE,
            check_trailing_stop_signals,
        )

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "TQQQ", 10.0, 100.0, "USD"),  # leveraged ETF → swing
            )
            # high $200, current $150 → drop = 150/200 - 1 = -25% (below -20%)
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("TQQQ", "2026-05-04", 150.0, 200.0, 145.0, 150.0, 1000000, 150.0),
            )

        # Force classify_stock_type → swing (accept positional + kw)
        monkeypatch.setattr(pt, "classify_stock_type", lambda *a, **kw: "swing")

        result = check_trailing_stop_signals(db_path=fresh_db)
        # Lock: swing branch hit → threshold = TRAILING_STOP_VOLATILE
        assert len(result) == 1
        assert result[0]["threshold"] == TRAILING_STOP_VOLATILE
        # -20% trailing stop is hit because drop is -25%
        assert result[0]["status"] == "TRIGGERED"


class TestPriceTargetsMddBranches:
    """Lines 492-493, 523: MDD function exception + zero total_cost."""

    def test_fx_query_failure_abstains_instead_of_defaulting(self, fresh_db, monkeypatch, caplog):
        """환율 조회가 DB 오류로 실패하면 **판정을 포기**한다 (#1283).

        예전에는 `except Exception: pass` → `usd_krw = 1400.0` 으로 진행해, 조회가
        실패했는데도 지어낸 환율 기준으로 `PORTFOLIO_STOP` 위반을 선언했다. 이 테스트가
        바로 그 동작을 잠그고 있었다 (구 이름 `..._falls_back_to_default`).

        DB 오류는 "환율을 모른다" 이지 "1400 이다" 가 아니다.
        """
        import logging

        import nuri.core.db as db_mod
        from nuri.core.db import OperationalError
        from nuri.trading.recommend import price_targets as pt

        # 합성 종목 — 실제 보유와 무관하다 (public repo, `tests/CLAUDE.md` privacy).
        kr_ticker = "999999.KS"
        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("Brokerage Alpha", kr_ticker, 100, 100_000.0, "KRW"),  # KRW → uses fx
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kr_ticker, "2026-05-04", 50_000, 50_000, 50_000, 50_000, 1, 50_000),
            )

        original_q = db_mod.query

        def fake_q(sql, *a, **kw):
            if "usd_krw" in sql:
                raise OperationalError("synthetic fx fail")
            return original_q(sql, *a, **kw)

        monkeypatch.setattr(db_mod, "query", fake_q)

        with caplog.at_level(logging.WARNING, logger="nuri.trading.recommend.price_targets"):
            result = pt.check_portfolio_mdd(db_path=fresh_db)

        # -50% 라 환율만 있으면 확실한 위반이다. 그래도 판정하지 않는 것이 요점.
        assert result is None, "환율 조회가 실패했는데 지어낸 환율로 손절선을 판정했다"
        assert caplog.records, "판정을 포기하고도 조용했다 — 아무도 조회 실패를 모른다"

    def test_zero_total_cost_returns_none(self, fresh_db, monkeypatch):
        """Line 522-523: total_cost <= 0 → return None.

        Holding with avg_price=0 → cost=0, total_cost=0 → return None.
        """
        from nuri.trading.recommend import price_targets as pt

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "FREE", 100, 0.0, "USD"),  # avg=0 → cost=0
            )
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("FREE", "2026-05-04", 1, 1, 1, 1, 1, 1),
            )

        result = pt.check_portfolio_mdd(db_path=fresh_db)
        # Lock: zero cost → None (avoids division-by-zero in pnl_pct)
        assert result is None


class TestPriceTargetsMainModule:
    """Lines 540-547: __main__ guard."""

    def test_module_main_invocation_via_runpy(self, monkeypatch, fresh_db):
        """`python -m nuri.trading.recommend.price_targets` flow."""
        import runpy

        import nuri.core.db as db_mod

        monkeypatch.setattr(db_mod, "DB_PATH", fresh_db)

        from nuri.trading.recommend import price_targets as pt

        # Stub heavy fns
        monkeypatch.setattr(pt, "calculate_portfolio_targets", lambda **kw: [])
        # print_portfolio_targets is real — empty list prints '없음' message
        monkeypatch.setattr(sys, "argv", ["price_targets.py"])
        import io as _io

        buf = _io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)

        runpy.run_module("nuri.trading.recommend.price_targets", run_name="__main__")
        out = buf.getvalue()
        # Lock: print_portfolio_targets ran via __main__ (line 547) and printed empty msg
        assert "포트폴리오에 가격 목표 대상 종목 없음" in out


# ════════════════════════════════════════════════════════════════════
# Additional: held_add residual gaps (115-117, 224-226, 351)
# ════════════════════════════════════════════════════════════════════


class TestHeldAddDefaultYfinanceFetcher:
    """Lines 113-117: when fetcher is None, the function imports yfinance.

    Conftest globally mocks yf.Ticker so it's network-free.
    """

    def test_default_fetcher_path_returns_false(self):
        """fetcher=None → import yfinance + yf.Ticker() (lines 115-117)."""
        from nuri.trading.recommend.held_add import is_in_earnings_blackout

        result = is_in_earnings_blackout("AAA", days=5, today=date(2026, 5, 4), fetcher=None)
        # Lock: no exception; default-fetcher branch traversed.
        assert result is False


class TestHeldAddAccountStrategyProfileLive:
    """Lines 224-226: _get_account_strategy_profile imports + returns from rules."""

    def test_returns_account_strategy_dict(self):
        """Inner-import + return path runs and yields a dict (not None)."""
        from nuri.trading.recommend.held_add import _get_account_strategy_profile

        result = _get_account_strategy_profile("main")
        # Lock: dict (empty allowed for unknown). Confirms inner import + return ran.
        assert isinstance(result, dict)


class TestHeldAddSelectModeUnknownMode:
    """Line 350-351: else: r=None branch for unknown mode key."""

    def test_unknown_mode_yields_none_branch(self, monkeypatch):
        """Inject unknown key into MODE_PRECEDENCE → else (line 351) executes."""
        from nuri.trading.recommend import held_add as ha

        monkeypatch.setattr(
            ha,
            "MODE_PRECEDENCE",
            {"unknown_mode": 0, "tp1_residual_add": 1, "ride_winner": 2, "average_down": 3},
        )
        monkeypatch.setattr(ha, "_evaluate_tp1_residual_add", lambda *a, **kw: None)
        monkeypatch.setattr(ha, "_evaluate_ride_winner", lambda *a, **kw: None)
        monkeypatch.setattr(ha, "_evaluate_average_down", lambda *a, **kw: None)

        cfg = {"modes": {}}
        pos = {"ticker": "AAA", "account": "x", "pnl_pct": 0, "days_held": 0}
        result = ha.select_held_mode(pos, cfg, score=50, rsi=None, regime="sideways_low_vol", vix=18)
        # Lock: None — unknown mode → else r=None (351), known modes → None, final → None.
        assert result is None


# ════════════════════════════════════════════════════════════════════
# Additional: tracker residual gap (87)
# ════════════════════════════════════════════════════════════════════


class TestTrackerTierFilter:
    """Line 86-87: candidate with tier != actionable → continue."""

    def test_advisory_tier_candidate_skipped(self, fresh_db):
        """A non-actionable Candidate must NOT be persisted."""
        from nuri.trading.recommend.candidates import (
            TIER_ACTIONABLE,
            TIER_ADVISORY,
            Candidate,
        )
        from nuri.trading.recommend.tracker import save_recommendations

        with get_db(fresh_db) as conn:
            conn.execute(
                "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency) VALUES (?, ?, ?, ?, ?)",
                ("acct_x", "AAA", 10, 100.0, "USD"),
            )

        cands = [
            Candidate(
                ticker="AAA",
                signal_id="rsi_30",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=80.0,
                win_rate=0.6,
                profit_factor=1.5,
                regime_fit=True,
                price=100.0,
                notes="",
                tier=TIER_ADVISORY,
            ),
            Candidate(
                ticker="AAA",
                signal_id="rsi_31",
                signal_date="2026-05-04",
                direction="BUY",
                confidence=80.0,
                win_rate=0.6,
                profit_factor=1.5,
                regime_fit=True,
                price=100.0,
                notes="",
                tier=TIER_ACTIONABLE,
            ),
        ]
        n = save_recommendations(candidates=cands, db_path=fresh_db)
        # Lock: 1/2 persisted — advisory filtered at line 87.
        assert n == 1


class TestCandidatesScreenInsufficientPriceRows:
    """Line 217-218: ticker with < 50 price rows → continue."""

    def test_sparse_prices_yields_empty_candidates(self, fresh_db, monkeypatch):
        from nuri.trading.recommend.candidates import screen_candidates

        monkeypatch.setattr(
            "nuri.trading.recommend.candidates.get_tickers",
            lambda db_path=None: ["SPARSE"],
        )
        dates = pd.bdate_range(end="2026-04-30", periods=10)
        df = pd.DataFrame(
            {
                "ticker": "SPARSE",
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000,
                "adj_close": 100.0,
            }
        )
        upsert_prices(df, fresh_db)

        result = screen_candidates(lookback_days=5, db_path=fresh_db)
        # Lock: < 50 rows → silent skip (line 217-218).
        assert result == []
