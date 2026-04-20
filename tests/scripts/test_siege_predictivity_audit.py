"""E4-0b — siege_predictivity_audit.py regression tests.

docs/plans/e4_0b.md §3.5 요구 사항: ≥15 regression tests.

분류:
- Snapshot date 생성 + momentum selection (determinism + no-lookahead)
- Synthesize helpers (portfolio_df schema + cert snapshot hash/regime)
- Forward NAV (equal-weight + partial data)
- Bootstrap CI (reproducibility)
- Predictivity aggregation (fire/not-fire bucketing)
- Idempotency (fixed_timestamp + already_audited)
- Report output (markdown shape)
- End-to-end tiny run
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, upsert_macro, upsert_prices

# Script import
from scripts.siege_predictivity_audit import (
    AuditSnapshot,
    GateMetric,
    _already_audited,
    _bootstrap_diff_ci,
    _fixed_timestamp,
    analyze_predictivity,
    forward_portfolio_nav,
    monthly_snapshot_dates,
    synthesize_cert_snapshot,
    synthesize_portfolio_df,
    top_n_momentum,
    write_report,
)

# ─── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def tiny_db(tmp_path, monkeypatch):
    """3-ticker universe × 400 trading days prices. For momentum + NAV tests."""
    import nuri.core.db as db_mod

    path = tmp_path / "tiny.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)

    with get_db(path) as conn:
        # Minimal portfolio row (sector lookup)
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES ('audit', 'AAPL', 10, 150, 'USD', 'Technology')"
        )
        conn.execute(
            "INSERT INTO portfolio (account, ticker, quantity, avg_price, currency, sector) "
            "VALUES ('audit', 'MSFT', 5, 300, 'USD', 'Technology')"
        )

    # 400 business days price series — AAPL up trend, MSFT flat, SPY required for _trading_day_on_or_before
    start = pd.Timestamp("2023-01-02")
    dates = pd.bdate_range(start, periods=400)
    prices = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        prices.append({"ticker": "AAPL", "date": ds, "open": 100 + i * 0.1, "high": 102 + i * 0.1,
                       "low": 99 + i * 0.1, "close": 100 + i * 0.1, "volume": 1000, "adj_close": 100 + i * 0.1})
        prices.append({"ticker": "MSFT", "date": ds, "open": 300, "high": 302, "low": 298,
                       "close": 300, "volume": 1000, "adj_close": 300})
        prices.append({"ticker": "SPY", "date": ds, "open": 400, "high": 402, "low": 398,
                       "close": 400 + i * 0.05, "volume": 1000, "adj_close": 400 + i * 0.05})
        prices.append({"ticker": "NVDA", "date": ds, "open": 500, "high": 510, "low": 490,
                       "close": 500 + i * 0.2, "volume": 1000, "adj_close": 500 + i * 0.2})
    upsert_prices(pd.DataFrame(prices), path)

    # VIX + macro for regime classification
    macro = []
    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        macro.append({"indicator": "vix", "date": ds, "value": 15.0 + (i % 5), "source": "test"})
        macro.append({"indicator": "usd_krw", "date": ds, "value": 1380.0, "source": "test"})
    upsert_macro(macro, path)

    return path


# ─── 1. monthly_snapshot_dates ──────────────────────────────────────────────


class TestMonthlySnapshotDates:
    def test_determinism(self):
        """같은 입력 → 같은 리스트."""
        a = monthly_snapshot_dates("2026-04-01", months=12)
        b = monthly_snapshot_dates("2026-04-01", months=12)
        assert a == b
        assert len(a) == 12

    def test_month_end_format(self):
        """각 원소가 YYYY-MM-DD 형식 + 월말 근처 (day ≥ 28)."""
        dates = monthly_snapshot_dates("2026-04-01", months=6)
        for d in dates:
            assert len(d) == 10
            day = int(d.split("-")[-1])
            assert day >= 28, f"{d} is not month-end"

    def test_oldest_first_ordering(self):
        """return 리스트는 oldest → newest 정렬."""
        dates = monthly_snapshot_dates("2026-04-01", months=6)
        assert dates == sorted(dates)


# ─── 2. top_n_momentum ──────────────────────────────────────────────────────


class TestTopNMomentum:
    def test_picks_highest_return(self, tiny_db):
        """최대 % return 보유 ticker 선택 — AAPL (+25% over 252d) > NVDA (+10%) > MSFT (0%)."""
        picks = top_n_momentum(["AAPL", "MSFT", "NVDA"], "2024-06-01", n=1, db_path=tiny_db)
        # AAPL: 100→125.2 (+25%), NVDA: 500→550.4 (+10%), MSFT: flat — AAPL top.
        assert picks == ["AAPL"]

    def test_picks_top_n_ordered_by_return(self, tiny_db):
        """top-N 이 return 내림차순 정렬."""
        picks = top_n_momentum(["AAPL", "MSFT", "NVDA"], "2024-06-01", n=3, db_path=tiny_db)
        assert picks == ["AAPL", "NVDA", "MSFT"]

    def test_excludes_sparse_coverage(self, tiny_db):
        """252d 미만 coverage ticker 는 제외."""
        # fake 이력 없는 ticker
        picks = top_n_momentum(["AAPL", "GHOST"], "2024-06-01", n=2, db_path=tiny_db)
        assert "GHOST" not in picks
        assert "AAPL" in picks

    def test_no_lookahead(self, tiny_db):
        """as_of 이후 close 로 계산하지 않음 — as_of 이전 ≥252d 필수."""
        # tiny_db 가 2023-01-02 시작이므로 as_of 가 너무 이르면 returns 제외
        picks = top_n_momentum(["AAPL"], "2023-06-01", n=1, db_path=tiny_db)
        # 2023-01 ~ 2023-06 = ~100d 거래일 → 252d lookback 부족 → 제외
        assert picks == []


# ─── 3. synthesize_portfolio_df ─────────────────────────────────────────────


class TestSynthesizePortfolioDf:
    def test_returns_analyze_portfolio_schema(self, tiny_db):
        """df columns 가 analyze_portfolio output 과 일치."""
        df = synthesize_portfolio_df(["AAPL", "MSFT"], "2024-06-01", db_path=tiny_db)
        assert df is not None
        required = {"account", "ticker", "sector", "quantity", "avg_price",
                    "current_price", "currency", "current_value_usd", "cost_basis_usd",
                    "pnl_usd", "pnl_pct", "price_date", "weight_pct"}
        assert required.issubset(set(df.columns))

    def test_equal_weight(self, tiny_db):
        """모든 ticker 가 동일 weight_pct — 10 positions → 10% 각각."""
        df = synthesize_portfolio_df(["AAPL", "MSFT", "NVDA"], "2024-06-01", db_path=tiny_db)
        assert df is not None
        weights = df["weight_pct"].tolist()
        assert all(abs(w - weights[0]) < 0.01 for w in weights), "weight_pct 가 동일하지 않음"

    def test_missing_price_returns_none(self, tiny_db):
        """데이터 없는 ticker 포함 → None."""
        df = synthesize_portfolio_df(["AAPL", "NONEXISTENT"], "2024-06-01", db_path=tiny_db)
        assert df is None

    def test_sector_fallback_unknown(self, tiny_db):
        """portfolio 에 sector 없는 ticker → 'Unknown'."""
        # NVDA 는 portfolio 테이블에 없음 → Unknown 폴백
        df = synthesize_portfolio_df(["NVDA"], "2024-06-01", db_path=tiny_db)
        assert df is not None
        assert df.iloc[0]["sector"] == "Unknown"


# ─── 4. synthesize_cert_snapshot ────────────────────────────────────────────


class TestSynthesizeCertSnapshot:
    def test_hash_matches_raw(self, tiny_db):
        """CertSnapshot.portfolio_hash 가 portfolio_raw 에서 바로 파생."""
        from nuri.trading.engine.certification import _compute_portfolio_hash

        snap = synthesize_cert_snapshot(["AAPL", "MSFT"], "2024-06-01", db_path=tiny_db)
        assert snap is not None
        assert snap.portfolio_hash == _compute_portfolio_hash(rows=snap.portfolio_raw)

    def test_regime_populated_from_classifier(self, tiny_db):
        """snap.regime 이 classify_regime(date=...) 결과."""
        snap = synthesize_cert_snapshot(["AAPL", "MSFT"], "2024-06-01", db_path=tiny_db)
        assert snap is not None
        assert snap.regime is not None

    def test_none_when_regime_fails(self, tiny_db):
        """regime 실패 시 None (historical 데이터 부족)."""
        with patch("scripts.siege_predictivity_audit.classify_regime", return_value=None):
            snap = synthesize_cert_snapshot(["AAPL"], "2024-06-01", db_path=tiny_db)
            assert snap is None


# ─── 5. forward_portfolio_nav ───────────────────────────────────────────────


class TestForwardPortfolioNav:
    def test_equal_weight_average(self, tiny_db):
        """return = 2 tickers 의 단순 평균."""
        ret, mae = forward_portfolio_nav(["AAPL", "MSFT"], "2024-01-02", 30, db_path=tiny_db)
        assert ret is not None
        # AAPL 상승 + MSFT flat → 평균은 양수의 절반 수준
        assert ret > 0

    def test_partial_data_returns_none(self, tiny_db):
        """일부 ticker 데이터 부족 → None (conservative)."""
        ret, mae = forward_portfolio_nav(["AAPL", "GHOST"], "2024-01-02", 30, db_path=tiny_db)
        assert ret is None
        assert mae is None

    def test_mae_is_lower_bound(self, tiny_db):
        """MAE 는 entry 이후 최저 close 기준 — ret 이하 (flat 이상에서)."""
        ret, mae = forward_portfolio_nav(["AAPL"], "2024-01-02", 30, db_path=tiny_db)
        assert ret is not None and mae is not None
        # 상승 ticker 의 MAE 는 entry close 보다 작거나 같음 (intra-window low)
        assert mae <= ret


# ─── 6. bootstrap CI ────────────────────────────────────────────────────────


class TestBootstrapDiffCi:
    def test_reproducibility_same_seed(self):
        """같은 seed + 입력 → 같은 CI."""
        fired = [1.0, 2.0, 3.0, 4.0, 5.0]
        notf = [10.0, 12.0, 14.0, 16.0, 18.0]
        a = _bootstrap_diff_ci(fired, notf, n_iter=500, seed=42)
        b = _bootstrap_diff_ci(fired, notf, n_iter=500, seed=42)
        assert a == b

    def test_insufficient_sample_returns_nan(self):
        """len < 2 → (nan, nan)."""
        lo, hi = _bootstrap_diff_ci([1.0], [10.0], n_iter=100)
        assert lo != lo  # NaN != NaN
        assert hi != hi

    def test_diff_sign_preserved(self):
        """fired << not_fired → CI 가 음수 영역."""
        fired = list(range(-20, -5))  # mean ~ -12.5
        notf = list(range(10, 25))  # mean ~ 17
        lo, hi = _bootstrap_diff_ci(fired, notf, n_iter=500, seed=42)
        assert hi < 0  # fired - notf 음수


# ─── 7. analyze_predictivity ────────────────────────────────────────────────


class TestAnalyzePredictivity:
    def _make_snap(self, date: str, cond_passed: bool, fwd_30: float) -> AuditSnapshot:
        return AuditSnapshot(
            snapshot_date=date, tickers=["AAPL"],
            cert={
                "certified": cond_passed,
                "score": 100 if cond_passed else 50,
                "total_conditions": 1,
                "passed": 1 if cond_passed else 0,
                "failed": 0 if cond_passed else 1,
                "warnings": 0,
                "conditions": [
                    {"id": "position_limit", "passed": cond_passed, "severity": "error"},
                ],
                "timestamp": f"{date}T00:00:00+09:00",
            },
            regime="bull_low_vol",
            forward_nav={30: fwd_30, 60: None, 90: None},
            forward_mae={30: fwd_30 - 1, 60: None, 90: None},
        )

    def test_buckets_by_fired_not_fired(self):
        """fired (passed=False) vs not_fired (passed=True) 분리 카운트."""
        snaps = [
            self._make_snap("2024-01-31", False, -5.0),  # fired
            self._make_snap("2024-02-29", False, -3.0),  # fired
            self._make_snap("2024-03-31", True, 2.0),  # not fired
            self._make_snap("2024-04-30", True, 4.0),  # not fired
        ]
        metrics = analyze_predictivity(snaps, n_iter=100)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.fire_count == 2
        assert m.not_fire_count == 2
        assert m.mean_when_fired[30] == -4.0
        assert m.mean_when_not_fired[30] == 3.0
        assert m.cond_mean_diff[30] == -7.0  # fired - not = -4 - 3

    def test_empty_snapshots_returns_empty(self):
        """빈 입력 → empty metrics."""
        assert analyze_predictivity([]) == []

    def test_skipped_snapshots_excluded(self):
        """cert=None 인 snapshot 은 제외."""
        snaps = [
            AuditSnapshot(snapshot_date="2024-01-31", tickers=[], cert=None, regime=None,
                          forward_nav={}, forward_mae={}, skipped_reason="no data"),
            self._make_snap("2024-02-29", False, -2.0),
            self._make_snap("2024-03-31", True, 3.0),
        ]
        metrics = analyze_predictivity(snaps, n_iter=100)
        assert metrics[0].fire_count == 1
        assert metrics[0].not_fire_count == 1


# ─── 8. idempotency helpers ─────────────────────────────────────────────────


class TestIdempotency:
    def test_fixed_timestamp_format(self):
        """_fixed_timestamp 가 YYYY-MM-DDT00:00:00+09:00 형식."""
        assert _fixed_timestamp("2024-06-01") == "2024-06-01T00:00:00+09:00"

    def test_already_audited_false_empty_db(self, tiny_db):
        """빈 certifications → False."""
        assert _already_audited("2024-06-01", db_path=tiny_db) is False

    def test_already_audited_true_after_insert(self, tiny_db):
        """audit:historical row 있으면 True."""
        from nuri.core.db import insert_certification

        insert_certification(
            {
                "timestamp": "2024-06-01T00:00:00+09:00",
                "certified": 0,
                "score": 50,
                "total_conditions": 10,
                "passed": 5,
                "failed": 1,
                "warnings": 4,
                "regime": "bull_low_vol",
                "portfolio_hash": "abc",
                "conditions_json": "[]",
                "caller": "audit:historical",
            },
            db_path=tiny_db,
        )
        assert _already_audited("2024-06-01", db_path=tiny_db) is True

    def test_already_audited_excludes_other_callers(self, tiny_db):
        """같은 timestamp 라도 caller 다르면 False (audit 전용)."""
        from nuri.core.db import insert_certification

        insert_certification(
            {
                "timestamp": "2024-06-01T00:00:00+09:00",
                "certified": 1, "score": 100, "total_conditions": 10,
                "passed": 10, "failed": 0, "warnings": 0,
                "regime": None, "portfolio_hash": "x", "conditions_json": "[]",
                "caller": "cli",  # NOT audit
            },
            db_path=tiny_db,
        )
        assert _already_audited("2024-06-01", db_path=tiny_db) is False


# ─── 9. write_report markdown shape ─────────────────────────────────────────


class TestWriteReport:
    def test_produces_markdown_sections(self, tmp_path):
        """report 에 예상된 sections 모두 포함."""
        snapshots = [
            AuditSnapshot(
                snapshot_date="2024-01-31", tickers=["AAPL"],
                cert={"certified": True, "score": 100, "total_conditions": 1,
                      "passed": 1, "failed": 0, "warnings": 0, "timestamp": "x",
                      "conditions": [{"id": "position_limit", "passed": True, "severity": "error"}]},
                regime="bull_low_vol",
                forward_nav={30: 3.0, 60: None, 90: None},
                forward_mae={30: -1.0, 60: None, 90: None},
            ),
            AuditSnapshot(
                snapshot_date="2024-02-29", tickers=["MSFT"],
                cert={"certified": False, "score": 0, "total_conditions": 1,
                      "passed": 0, "failed": 1, "warnings": 0, "timestamp": "x",
                      "conditions": [{"id": "position_limit", "passed": False, "severity": "error"}]},
                regime="bull_low_vol",
                forward_nav={30: -5.0, 60: None, 90: None},
                forward_mae={30: -6.0, 60: None, 90: None},
            ),
        ]
        metrics = analyze_predictivity(snapshots, n_iter=100)
        output_path = tmp_path / "report.md"
        write_report(snapshots, metrics, output_path)

        text = output_path.read_text()
        assert "# E4-0b" in text
        assert "## Summary" in text
        assert "## Per-gate predictivity" in text
        assert "## Methodology" in text
        assert "`position_limit`" in text


# ─── 10. end-to-end tiny run (integration) ──────────────────────────────────


class TestEndToEndTiny:
    def test_run_audit_with_dry_run(self, tiny_db, monkeypatch):
        """3-ticker universe × 2 snapshot 소규모 end-to-end, dry-run."""
        from scripts.siege_predictivity_audit import run_audit

        # universe.yaml read 우회 — monkey-patch
        monkeypatch.setattr(
            "scripts.siege_predictivity_audit._load_universe",
            lambda key="us_core": ["AAPL", "MSFT", "NVDA"],
        )

        # today 를 tiny_db 마지막 price 근처로 고정
        monkeypatch.setattr(
            "scripts.siege_predictivity_audit.today_kst",
            lambda: "2024-06-30",
        )

        snapshots = run_audit(universe_key="us_core", months=2, top_n=2, save=False, db_path=tiny_db)
        assert len(snapshots) == 2
        # 최소 1개는 cert 생성
        valid = [s for s in snapshots if s.cert is not None]
        assert len(valid) >= 1, f"no valid cert generated; skipped: {[s.skipped_reason for s in snapshots]}"


class TestCliArgparse:
    """CLI `_parse_args` + `resolve_save_flag` — PR #421 coverage gap fix."""

    def test_parse_args_defaults(self):
        from scripts.siege_predictivity_audit import _parse_args

        args = _parse_args([])
        assert args.universe == "us_core"
        assert args.months == 60
        assert args.top_n == 10
        assert args.bootstrap_iter == 5000
        assert args.save is False
        assert args.dry_run is False

    def test_parse_args_save_flag(self):
        from scripts.siege_predictivity_audit import _parse_args

        args = _parse_args(["--save"])
        assert args.save is True
        assert args.dry_run is False

    def test_parse_args_dry_run_flag(self):
        from scripts.siege_predictivity_audit import _parse_args

        args = _parse_args(["--dry-run"])
        assert args.save is False
        assert args.dry_run is True

    def test_parse_args_save_and_dry_run_mutually_exclusive(self):
        import pytest as _pytest

        from scripts.siege_predictivity_audit import _parse_args

        with _pytest.raises(SystemExit):
            _parse_args(["--save", "--dry-run"])

    def test_parse_args_override_months_top_n(self):
        from scripts.siege_predictivity_audit import _parse_args

        args = _parse_args(["--months", "12", "--top-n", "5", "--bootstrap-iter", "100"])
        assert args.months == 12
        assert args.top_n == 5
        assert args.bootstrap_iter == 100

    def test_resolve_save_flag_default_false(self):
        """neither --save nor --dry-run → False (dry-run default semantics)."""
        from scripts.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args([])) is False

    def test_resolve_save_flag_save_only_true(self):
        """`--save` 단독 → True."""
        from scripts.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args(["--save"])) is True

    def test_resolve_save_flag_dry_run_only_false(self):
        """`--dry-run` 단독 → False."""
        from scripts.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args(["--dry-run"])) is False


class TestMainEntrypoint:
    """main() 함수 직접 호출 — audit loop 는 mock, CLI wiring 만 검증."""

    def test_main_default_no_save_returns_zero(self, monkeypatch, tmp_path):
        import scripts.siege_predictivity_audit as mod

        called = {}

        def fake_run_audit(**kwargs):
            called.update(kwargs)
            return []

        def fake_analyze(*a, **k):
            return []

        def fake_write(snapshots, metrics, output_path):
            called["output_path"] = output_path

        monkeypatch.setattr(mod, "run_audit", fake_run_audit)
        monkeypatch.setattr(mod, "analyze_predictivity", fake_analyze)
        monkeypatch.setattr(mod, "write_report", fake_write)
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-04-21")
        monkeypatch.chdir(tmp_path)

        exit_code = mod.main([])
        assert exit_code == 0
        assert called["save"] is False  # default dry-run
        assert called["universe_key"] == "us_core"
        assert called["months"] == 60
        assert called["top_n"] == 10
        # output_path 기본값: data/reports/{today}/e4_0b_siege_predictivity.md
        assert str(called["output_path"]).endswith("e4_0b_siege_predictivity.md")

    def test_main_save_flag_propagates(self, monkeypatch, tmp_path):
        import scripts.siege_predictivity_audit as mod

        called = {}
        monkeypatch.setattr(mod, "run_audit", lambda **kw: (called.update(kw), [])[1])
        monkeypatch.setattr(mod, "analyze_predictivity", lambda *a, **k: [])
        monkeypatch.setattr(mod, "write_report", lambda *a, **k: None)
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-04-21")
        monkeypatch.chdir(tmp_path)

        mod.main(["--save", "--months", "2", "--top-n", "3"])
        assert called["save"] is True
        assert called["months"] == 2
        assert called["top_n"] == 3

    def test_main_console_summary_dry_run(self, monkeypatch, tmp_path, capsys):
        import scripts.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "run_audit", lambda **kw: [])
        monkeypatch.setattr(mod, "analyze_predictivity", lambda *a, **k: [])
        monkeypatch.setattr(mod, "write_report", lambda *a, **k: None)
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-04-21")
        monkeypatch.chdir(tmp_path)

        mod.main([])
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "Audit complete" in out

    def test_main_console_summary_save(self, monkeypatch, tmp_path, capsys):
        import scripts.siege_predictivity_audit as mod
        from scripts.siege_predictivity_audit import AuditSnapshot

        fake_snap = AuditSnapshot(
            snapshot_date="2024-01-31", tickers=["AAPL"],
            cert={"certified": False, "score": 50, "total_conditions": 1,
                  "passed": 0, "failed": 1, "warnings": 0, "timestamp": "x",
                  "conditions": []},
            regime="sideways_low_vol",
            forward_nav={30: None, 60: None, 90: None},
            forward_mae={30: None, 60: None, 90: None},
        )
        monkeypatch.setattr(mod, "run_audit", lambda **kw: [fake_snap])
        monkeypatch.setattr(mod, "analyze_predictivity", lambda *a, **k: [])
        monkeypatch.setattr(mod, "write_report", lambda *a, **k: None)
        monkeypatch.setattr(mod, "today_kst", lambda: "2026-04-21")
        monkeypatch.chdir(tmp_path)

        mod.main(["--save"])
        out = capsys.readouterr().out
        assert "audit:historical rows persisted" in out
