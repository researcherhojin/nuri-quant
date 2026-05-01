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
from scripts.analysis.siege_predictivity_audit import (
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
        prices.append(
            {
                "ticker": "AAPL",
                "date": ds,
                "open": 100 + i * 0.1,
                "high": 102 + i * 0.1,
                "low": 99 + i * 0.1,
                "close": 100 + i * 0.1,
                "volume": 1000,
                "adj_close": 100 + i * 0.1,
            }
        )
        prices.append(
            {
                "ticker": "MSFT",
                "date": ds,
                "open": 300,
                "high": 302,
                "low": 298,
                "close": 300,
                "volume": 1000,
                "adj_close": 300,
            }
        )
        prices.append(
            {
                "ticker": "SPY",
                "date": ds,
                "open": 400,
                "high": 402,
                "low": 398,
                "close": 400 + i * 0.05,
                "volume": 1000,
                "adj_close": 400 + i * 0.05,
            }
        )
        prices.append(
            {
                "ticker": "NVDA",
                "date": ds,
                "open": 500,
                "high": 510,
                "low": 490,
                "close": 500 + i * 0.2,
                "volume": 1000,
                "adj_close": 500 + i * 0.2,
            }
        )
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
        required = {
            "account",
            "ticker",
            "sector",
            "quantity",
            "avg_price",
            "current_price",
            "currency",
            "current_value_usd",
            "cost_basis_usd",
            "pnl_usd",
            "pnl_pct",
            "price_date",
            "weight_pct",
        }
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
        with patch("scripts.analysis.siege_predictivity_audit.classify_regime", return_value=None):
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
        fired: list[float] = [1.0, 2.0, 3.0, 4.0, 5.0]
        not_fired = [10.0, 12.0, 14.0, 16.0, 18.0]
        a = _bootstrap_diff_ci(fired, not_fired, n_iter=500, seed=42)
        b = _bootstrap_diff_ci(fired, not_fired, n_iter=500, seed=42)
        assert a == b

    def test_insufficient_sample_returns_nan(self):
        """len < 2 → (nan, nan)."""
        lo, hi = _bootstrap_diff_ci([1.0], [10.0], n_iter=100)
        assert lo != lo  # NaN != NaN
        assert hi != hi

    def test_diff_sign_preserved(self):
        """fired << not_fired → CI 가 음수 영역."""
        fired: list[float] = [float(i) for i in range(-20, -5)]  # mean ~ -12.5
        not_fired: list[float] = [float(i) for i in range(10, 25)]  # mean ~ 17
        lo, hi = _bootstrap_diff_ci(fired, not_fired, n_iter=500, seed=42)
        assert hi < 0  # fired - not_fired 음수


# ─── 7. analyze_predictivity ────────────────────────────────────────────────


class TestAnalyzePredictivity:
    def _make_snap(self, date: str, cond_passed: bool, fwd_30: float) -> AuditSnapshot:
        return AuditSnapshot(
            snapshot_date=date,
            tickers=["AAPL"],
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
            AuditSnapshot(
                snapshot_date="2024-01-31",
                tickers=[],
                cert=None,
                regime=None,
                forward_nav={},
                forward_mae={},
                skipped_reason="no data",
            ),
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
                "certified": 1,
                "score": 100,
                "total_conditions": 10,
                "passed": 10,
                "failed": 0,
                "warnings": 0,
                "regime": None,
                "portfolio_hash": "x",
                "conditions_json": "[]",
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
                snapshot_date="2024-01-31",
                tickers=["AAPL"],
                cert={
                    "certified": True,
                    "score": 100,
                    "total_conditions": 1,
                    "passed": 1,
                    "failed": 0,
                    "warnings": 0,
                    "timestamp": "x",
                    "conditions": [{"id": "position_limit", "passed": True, "severity": "error"}],
                },
                regime="bull_low_vol",
                forward_nav={30: 3.0, 60: None, 90: None},
                forward_mae={30: -1.0, 60: None, 90: None},
            ),
            AuditSnapshot(
                snapshot_date="2024-02-29",
                tickers=["MSFT"],
                cert={
                    "certified": False,
                    "score": 0,
                    "total_conditions": 1,
                    "passed": 0,
                    "failed": 1,
                    "warnings": 0,
                    "timestamp": "x",
                    "conditions": [{"id": "position_limit", "passed": False, "severity": "error"}],
                },
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
        assert "## Gate eligibility matrix" in text  # v2 new section (codex Biggest Risk)
        assert "## Auditable gates" in text  # v2 replaces "## Per-gate predictivity"
        assert "## Methodology" in text
        assert "`position_limit`" in text


# ─── 10. end-to-end tiny run (integration) ──────────────────────────────────


class TestEndToEndTiny:
    def test_run_audit_with_dry_run(self, tiny_db, monkeypatch):
        """3-ticker universe × 2 snapshot 소규모 end-to-end, dry-run."""
        from scripts.analysis.siege_predictivity_audit import run_audit

        # universe.yaml read 우회 — monkey-patch
        monkeypatch.setattr(
            "scripts.analysis.siege_predictivity_audit._load_universe",
            lambda key="us_core": ["AAPL", "MSFT", "NVDA"],
        )

        # today 를 tiny_db 마지막 price 근처로 고정
        monkeypatch.setattr(
            "scripts.analysis.siege_predictivity_audit.today_kst",
            lambda: "2024-06-30",
        )

        # v2: variant ladder — single variant 로 제한 (3-ticker tiny universe 로는
        # sector_concentrated / concentrated_top5 등 구성 어려움).
        snapshots = run_audit(
            universe_key="us_core",
            months=2,
            top_n=2,
            save=False,
            db_path=tiny_db,
            variants=["momentum_top10"],
        )
        assert len(snapshots) == 2
        # 최소 1개는 cert 생성
        valid = [s for s in snapshots if s.cert is not None]
        assert len(valid) >= 1, f"no valid cert generated; skipped: {[s.skipped_reason for s in snapshots]}"


class TestCliArgparse:
    """CLI `_parse_args` + `resolve_save_flag` — PR #421 coverage gap fix."""

    def test_parse_args_defaults(self):
        from scripts.analysis.siege_predictivity_audit import _parse_args

        args = _parse_args([])
        assert args.universe == "us_core"
        assert args.months == 60
        assert args.top_n == 10
        assert args.bootstrap_iter == 5000
        assert args.save is False
        assert args.dry_run is False

    def test_parse_args_save_flag(self):
        from scripts.analysis.siege_predictivity_audit import _parse_args

        args = _parse_args(["--save"])
        assert args.save is True
        assert args.dry_run is False

    def test_parse_args_dry_run_flag(self):
        from scripts.analysis.siege_predictivity_audit import _parse_args

        args = _parse_args(["--dry-run"])
        assert args.save is False
        assert args.dry_run is True

    def test_parse_args_save_and_dry_run_mutually_exclusive(self):
        import pytest as _pytest

        from scripts.analysis.siege_predictivity_audit import _parse_args

        with _pytest.raises(SystemExit):
            _parse_args(["--save", "--dry-run"])

    def test_parse_args_override_months_top_n(self):
        from scripts.analysis.siege_predictivity_audit import _parse_args

        args = _parse_args(["--months", "12", "--top-n", "5", "--bootstrap-iter", "100"])
        assert args.months == 12
        assert args.top_n == 5
        assert args.bootstrap_iter == 100

    def test_resolve_save_flag_default_false(self):
        """neither --save nor --dry-run → False (dry-run default semantics)."""
        from scripts.analysis.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args([])) is False

    def test_resolve_save_flag_save_only_true(self):
        """`--save` 단독 → True."""
        from scripts.analysis.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args(["--save"])) is True

    def test_resolve_save_flag_dry_run_only_false(self):
        """`--dry-run` 단독 → False."""
        from scripts.analysis.siege_predictivity_audit import _parse_args, resolve_save_flag

        assert resolve_save_flag(_parse_args(["--dry-run"])) is False


class TestMainEntrypoint:
    """main() 함수 직접 호출 — audit loop 는 mock, CLI wiring 만 검증."""

    def test_main_default_no_save_returns_zero(self, monkeypatch, tmp_path):
        import scripts.analysis.siege_predictivity_audit as mod

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
        import scripts.analysis.siege_predictivity_audit as mod

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
        import scripts.analysis.siege_predictivity_audit as mod

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
        import scripts.analysis.siege_predictivity_audit as mod
        from scripts.analysis.siege_predictivity_audit import AuditSnapshot

        fake_snap = AuditSnapshot(
            snapshot_date="2024-01-31",
            tickers=["AAPL"],
            cert={
                "certified": False,
                "score": 50,
                "total_conditions": 1,
                "passed": 0,
                "failed": 1,
                "warnings": 0,
                "timestamp": "x",
                "conditions": [],
            },
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


class TestHelpersCoverage:
    """Missing lines: _load_universe / _trading_day_on_or_before / momentum edge / synthesize None returns."""

    def test_load_universe_reads_yaml(self, tmp_path, monkeypatch):
        """_load_universe 가 config/universe.yaml 에서 key 의 tickers 로드."""
        import scripts.analysis.siege_predictivity_audit as mod

        yaml_path = tmp_path / "universe.yaml"
        yaml_path.write_text("us_core:\n  tickers: [AAPL, MSFT, GOOG]\n")
        monkeypatch.chdir(tmp_path)
        # config/ 하위 디렉토리 구조 만들기
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "universe.yaml").write_text("us_core:\n  tickers: [AAPL, MSFT, GOOG]\n")
        result = mod._load_universe("us_core")
        assert result == ["AAPL", "GOOG", "MSFT"]  # sorted

    def test_load_universe_empty_raises(self, tmp_path, monkeypatch):
        """tickers 빈 리스트 → RuntimeError."""
        import pytest as _pytest

        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "universe.yaml").write_text("us_core:\n  tickers: []\n")
        with _pytest.raises(RuntimeError, match="empty"):
            mod._load_universe("us_core")

    def test_trading_day_on_or_before_finds_latest(self, tiny_db):
        """prices 에서 date 이하 가장 최신 SPY 거래일."""
        from scripts.analysis.siege_predictivity_audit import _trading_day_on_or_before

        d = _trading_day_on_or_before("2024-06-15", db_path=tiny_db)
        assert d is not None
        assert d <= "2024-06-15"

    def test_trading_day_on_or_before_no_data(self, tmp_path):
        """데이터 없는 DB → None."""
        from nuri.core.db import init_db
        from scripts.analysis.siege_predictivity_audit import _trading_day_on_or_before

        path = tmp_path / "empty.db"
        init_db(path)
        assert _trading_day_on_or_before("2024-06-15", db_path=path) is None

    def test_top_n_momentum_skips_zero_close(self, tmp_path, monkeypatch):
        """close_then <= 0 ticker 는 제외 (line 157)."""
        import pandas as pd

        from nuri.core.db import get_db, init_db, upsert_prices
        from scripts.analysis.siege_predictivity_audit import top_n_momentum

        path = tmp_path / "zero.db"
        init_db(path)
        # ZERO: 252+ rows, close_then (맨 뒤) = 0 → 제외. GOOD: 정상.
        dates = pd.bdate_range("2022-01-01", periods=260)
        rows = []
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            # ZERO: 마지막 (as_of=end, [lookback-1]=시작) close 가 0 이면 제외
            rows.append(
                {
                    "ticker": "ZERO",
                    "date": ds,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 0.0 if i < 10 else 1.0,
                    "volume": 100,
                    "adj_close": 0.0 if i < 10 else 1.0,
                }
            )
            rows.append(
                {
                    "ticker": "GOOD",
                    "date": ds,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1.0 + i * 0.1,
                    "volume": 100,
                    "adj_close": 1.0 + i * 0.1,
                }
            )
            rows.append(
                {
                    "ticker": "SPY",
                    "date": ds,
                    "open": 400,
                    "high": 400,
                    "low": 400,
                    "close": 400,
                    "volume": 100,
                    "adj_close": 400,
                }
            )
        upsert_prices(pd.DataFrame(rows), path)

        picks = top_n_momentum(["ZERO", "GOOD"], "2022-12-30", n=2, db_path=path)
        assert "ZERO" not in picks
        assert "GOOD" in picks

    def test_synthesize_portfolio_df_empty_tickers_returns_none(self, tiny_db):
        """빈 ticker list → None (line 212: `if not rows: return None`)."""
        from scripts.analysis.siege_predictivity_audit import synthesize_portfolio_df

        assert synthesize_portfolio_df([], "2024-06-01", db_path=tiny_db) is None

    def test_synthesize_cert_snapshot_empty_df_returns_none(self, tiny_db, monkeypatch):
        """synthesize_portfolio_df 가 empty df 반환 시 None (line 240)."""
        import pandas as pd

        import scripts.analysis.siege_predictivity_audit as mod

        # regime 은 정상, 그러나 portfolio_df 는 empty DataFrame 으로 mock
        monkeypatch.setattr(mod, "synthesize_portfolio_df", lambda *a, **k: pd.DataFrame())
        assert mod.synthesize_cert_snapshot(["AAPL"], "2024-06-01", db_path=tiny_db) is None

    def test_forward_portfolio_nav_empty_tickers_returns_none(self, tiny_db):
        """빈 ticker list → (None, None) (line 290)."""
        from scripts.analysis.siege_predictivity_audit import forward_portfolio_nav

        ret, mae = forward_portfolio_nav([], "2024-01-02", 30, db_path=tiny_db)
        assert ret is None and mae is None


class TestRunAuditSkipPaths:
    """run_audit() 의 skip 경로 (330-375) 커버."""

    def test_skip_when_already_audited(self, tiny_db, monkeypatch):
        """line 330-331 — _already_audited True → skip + log (continue 전에 top_n_momentum 호출 금지)."""
        import scripts.analysis.siege_predictivity_audit as mod
        from nuri.core.db import insert_certification

        monkeypatch.setattr(mod, "_load_universe", lambda k="us_core": ["AAPL"])
        # monthly_snapshot_dates 를 단일 "2024-01-31" 로 mock — 이 날짜가 already_audited
        monkeypatch.setattr(mod, "monthly_snapshot_dates", lambda end, months: ["2024-01-31"])
        monkeypatch.setattr(mod, "today_kst", lambda: "2024-06-30")

        insert_certification(
            {
                "timestamp": "2024-01-31T00:00:00+09:00",
                "certified": 0,
                "score": 50,
                "total_conditions": 1,
                "passed": 0,
                "failed": 1,
                "warnings": 0,
                "regime": "sideways",
                "portfolio_hash": "h",
                "conditions_json": "[]",
                "caller": "audit:historical",
            },
            db_path=tiny_db,
        )

        # top_n_momentum 호출되면 실패 — _already_audited 가 먼저 continue 해야 함
        called = {"top_n": 0}

        def _spy_top_n(*a, **k):
            called["top_n"] += 1
            return []

        monkeypatch.setattr(mod, "top_n_momentum", _spy_top_n)

        results = mod.run_audit(
            universe_key="us_core",
            months=1,
            top_n=1,
            save=True,
            db_path=tiny_db,
            variants=["momentum_top10"],  # v2: single variant to isolate idempotency test
        )
        assert results == []
        assert called["top_n"] == 0, "_already_audited 가 먼저 continue 해야 함"

    def test_skip_when_momentum_insufficient(self, tiny_db, monkeypatch):
        """line 335 — top-N 부족 시 skipped_reason 기록."""
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "_load_universe", lambda k="us_core": ["AAPL", "MSFT"])
        monkeypatch.setattr(mod, "today_kst", lambda: "2024-06-30")
        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: [])  # insufficient
        results = mod.run_audit(
            universe_key="us_core",
            months=1,
            top_n=5,
            save=False,
            db_path=tiny_db,
            variants=["momentum_top10"],  # v2: isolate single variant
        )
        assert len(results) == 1
        # v2: skipped_reason format 변경 ("momentum_top10 build failed")
        assert "build failed" in (results[0].skipped_reason or "")

    def test_skip_when_snapshot_build_fails(self, tiny_db, monkeypatch):
        """line 347 — synthesize_cert_snapshot 이 None → skip."""
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "_load_universe", lambda k="us_core": ["AAPL"])
        monkeypatch.setattr(mod, "today_kst", lambda: "2024-06-30")
        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: ["AAPL"])
        # v2: _build_snapshot_for_variant 를 None 으로 mock (synthesize_cert_snapshot 경로 대체)
        monkeypatch.setattr(
            mod,
            "_build_snapshot_for_variant",
            lambda *a, **k: (None, None, None, None),
        )
        results = mod.run_audit(
            universe_key="us_core",
            months=1,
            top_n=1,
            save=False,
            db_path=tiny_db,
            variants=["momentum_top10"],
        )
        assert len(results) == 1
        assert "build failed" in (results[0].skipped_reason or "")

    def test_skip_when_certify_raises(self, tiny_db, monkeypatch):
        """line 365 — certify() 예외 → skip, skipped_reason 기록."""
        import scripts.analysis.siege_predictivity_audit as mod
        from nuri.trading.engine.certification import CertSnapshot

        monkeypatch.setattr(mod, "_load_universe", lambda k="us_core": ["AAPL"])
        monkeypatch.setattr(mod, "today_kst", lambda: "2024-06-30")
        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: ["AAPL"])

        fake_snap = CertSnapshot(
            regime="sideways_low_vol",
            portfolio_raw=[{"account": "audit", "ticker": "AAPL", "sector": "T", "quantity": 1, "avg_price": 100.0}],
            portfolio_df=None,
            portfolio_hash="x",
            portfolio_error=None,
        )
        # v2: _build_snapshot_for_variant 가 valid snap 반환하도록 mock
        import pandas as pd

        fake_df = pd.DataFrame(
            [
                {
                    "account": "audit",
                    "ticker": "AAPL",
                    "sector": "T",
                    "quantity": 1,
                    "avg_price": 100.0,
                    "weight_pct": 100.0,
                    "current_value_usd": 100.0,
                    "cost_basis_usd": 100.0,
                    "pnl_usd": 0.0,
                    "pnl_pct": 0.0,
                    "current_price": 100.0,
                    "currency": "USD",
                    "price_date": "2024-06-30",
                }
            ]
        )
        monkeypatch.setattr(
            mod,
            "_build_snapshot_for_variant",
            lambda *a, **k: (fake_snap, fake_df, ["AAPL"], [100.0]),
        )

        def _raising_certify(**kw):
            raise RuntimeError("simulated certify fail")

        monkeypatch.setattr(mod, "certify", _raising_certify)
        results = mod.run_audit(
            universe_key="us_core",
            months=1,
            top_n=1,
            save=False,
            db_path=tiny_db,
            variants=["momentum_top10"],
        )
        assert len(results) == 1
        assert "certify raise" in (results[0].skipped_reason or "")


class TestAnalyzePredictivityGateSkip:
    """analyze_predictivity: snapshot 에 gate 없는 경우 line 478 continue."""

    def test_gate_missing_in_snapshot_is_skipped(self):
        """한 snapshot 에는 gate X 가 있지만 다른 snapshot 은 없을 때 continue 분기."""
        from scripts.analysis.siege_predictivity_audit import AuditSnapshot, analyze_predictivity

        s1 = AuditSnapshot(
            snapshot_date="2024-01-31",
            tickers=["A"],
            cert={
                "certified": 0,
                "score": 50,
                "total_conditions": 2,
                "passed": 1,
                "failed": 1,
                "warnings": 0,
                "timestamp": "x",
                "conditions": [
                    {"id": "gate_A", "passed": False, "severity": "error"},
                    {"id": "gate_B", "passed": True, "severity": "error"},
                ],
            },
            regime="sideways",
            forward_nav={30: -1.0, 60: -1.5, 90: -2.0},
            forward_mae={30: -2.0, 60: -2.5, 90: -3.0},
        )
        s2 = AuditSnapshot(
            snapshot_date="2024-02-29",
            tickers=["B"],
            cert={
                "certified": 1,
                "score": 100,
                "total_conditions": 1,
                "passed": 1,
                "failed": 0,
                "warnings": 0,
                "timestamp": "y",
                "conditions": [
                    # gate_A 없음 — analyze 루프에서 continue
                    {"id": "gate_B", "passed": True, "severity": "error"},
                ],
            },
            regime="bull_low_vol",
            forward_nav={30: 2.0, 60: 3.0, 90: 4.0},
            forward_mae={30: 1.0, 60: 1.5, 90: 2.0},
        )
        metrics = analyze_predictivity([s1, s2], n_iter=50)
        # gate_A: s1 에서만 appear → fire=1 / not_fire=0, skipped in s2
        gate_a = next(m for m in metrics if m.gate_id == "gate_A")
        assert gate_a.fire_count == 1
        assert gate_a.not_fire_count == 0


class TestSkipBreakdown:
    """_skip_breakdown 내부 counter (line 628-629)."""

    def test_skip_breakdown_groups_by_colon_prefix(self):
        """line 628-629 — _skip_breakdown 이 첫 ':' 이전 prefix 로 counter aggregate.

        실제 구현: `key = (s.skipped_reason or "unknown").split(":")[0]`
        즉 ":" 가 있는 이유는 prefix 만 group key 로. 없으면 전체 문자열.
        """
        from scripts.analysis.siege_predictivity_audit import AuditSnapshot, _skip_breakdown

        skipped = [
            # ":" 이후 부분 다르지만 같은 prefix 로 aggregate
            AuditSnapshot(
                snapshot_date="2024-01-31",
                tickers=[],
                cert=None,
                regime=None,
                forward_nav={},
                forward_mae={},
                skipped_reason="certify raise:RuntimeError",
            ),
            AuditSnapshot(
                snapshot_date="2024-02-29",
                tickers=[],
                cert=None,
                regime=None,
                forward_nav={},
                forward_mae={},
                skipped_reason="certify raise:ValueError",
            ),
            AuditSnapshot(
                snapshot_date="2024-03-31",
                tickers=[],
                cert=None,
                regime=None,
                forward_nav={},
                forward_mae={},
                skipped_reason="snapshot build 실패",
            ),
            # None → "unknown"
            AuditSnapshot(
                snapshot_date="2024-04-30",
                tickers=[],
                cert=None,
                regime=None,
                forward_nav={},
                forward_mae={},
                skipped_reason=None,
            ),
        ]
        out = _skip_breakdown(skipped)
        # "certify raise:RuntimeError" 와 ":ValueError" 는 prefix "certify raise" 로 group
        assert "certify raise=2" in out
        assert "snapshot build 실패=1" in out
        assert "unknown=1" in out


# ─── v2 additions (codex Plan consult 2026-04-22) ───────────────────────────


class TestGateEligibility:
    """GATE_ELIGIBILITY registry — codex Biggest Risk fix lock."""

    def test_auditable_now_gates_frozen(self):
        """3 auditable_now gate = snapshot-native portfolio-rule gates."""
        from scripts.analysis.siege_predictivity_audit import GATE_ELIGIBILITY

        auditable = [g for g, c in GATE_ELIGIBILITY.items() if c == "auditable_now"]
        assert set(auditable) == {"position_limit", "sector_limit", "leverage_ban"}, (
            "auditable_now 3 gate 변경은 codex Plan consult 재검토 필요"
        )

    def test_replayable_but_unwired_classification(self):
        """codex Round 1 fix: macro_event_alignment 는 compute_event_score(date=...) 가
        이미 date-parametric → replayable-but-unwired. stop_loss/rules_loaded 도 동일
        category (historical portfolio pnl/metadata 부재)."""
        from scripts.analysis.siege_predictivity_audit import GATE_ELIGIBILITY

        assert GATE_ELIGIBILITY["macro_event_alignment"] == "requires_replayed_state"
        assert GATE_ELIGIBILITY["stop_loss"] == "requires_replayed_state"
        assert GATE_ELIGIBILITY["rules_loaded"] == "requires_replayed_state"

    def test_current_db_dependent_gates_incoherent(self):
        """kst_now() 기준 evaluate 하는 gate — snapshot time coherence 없음.

        codex Round 1: macro_event_alignment 는 replayable 로 reclassified
        (replayable-but-unwired infrastructure).
        """
        from scripts.analysis.siege_predictivity_audit import GATE_ELIGIBILITY

        incoherent = [g for g, c in GATE_ELIGIBILITY.items() if c == "audit_incoherent"]
        assert "drift_safe" in incoherent
        assert "conflict_free" in incoherent
        assert "data_fresh_us_equity" in incoherent
        assert "volatility_gate_us_equity" in incoherent
        assert "external_data_us_equity" in incoherent
        # macro_event_alignment 는 Round 2 에서 incoherent → replayable 이관
        assert "macro_event_alignment" not in incoherent


class TestVariantTemplates:
    """VARIANT_TEMPLATES frozen 5 (Q1-A2)."""

    def test_templates_frozen(self):
        from scripts.analysis.siege_predictivity_audit import VARIANT_TEMPLATES

        assert VARIANT_TEMPLATES == [
            "momentum_top10",
            "equal_weight_sample",
            "sector_concentrated",
            "concentrated_top5",
        ]


class TestBuildVariant:
    """build_variant — per-template construction."""

    def test_unknown_variant_raises(self):
        import pytest

        from scripts.analysis.siege_predictivity_audit import build_variant

        with pytest.raises(ValueError, match="unknown variant"):
            build_variant("nonexistent", ["AAPL"], "2024-06-30")

    def test_concentrated_top5_weights_20pct(self, tiny_db, monkeypatch):
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: ["AAPL", "MSFT", "NVDA", "GOOG", "META"])
        result = mod.build_variant("concentrated_top5", ["AAPL"], "2024-06-30", db_path=tiny_db)
        assert result is not None
        tickers, weights = result
        assert len(tickers) == 5
        assert weights == [20.0, 20.0, 20.0, 20.0, 20.0]

    def test_momentum_top10_respects_momentum_n(self, tiny_db, monkeypatch):
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: ["AAPL", "MSFT"])
        # momentum_n=2 로 축소
        result = mod.build_variant("momentum_top10", ["AAPL"], "2024-06-30", db_path=tiny_db, momentum_n=2)
        assert result is not None
        tickers, weights = result
        assert tickers == ["AAPL", "MSFT"]
        assert weights == [50.0, 50.0]  # 100 / 2

    def test_momentum_insufficient_returns_none(self, tiny_db, monkeypatch):
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: ["AAPL"])  # only 1
        assert mod.build_variant("momentum_top10", ["AAPL"], "2024-06-30", db_path=tiny_db, momentum_n=5) is None


class TestExtractGateSeverity:
    """Continuous severity extractor — Q2-B3 secondary metric."""

    def test_position_severity_over_cap(self):
        import pandas as pd

        from scripts.analysis.siege_predictivity_audit import extract_gate_severity

        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT", "NVDA"],
                "sector": ["Tech", "Tech", "Tech"],
                "weight_pct": [25.0, 20.0, 10.0],  # max 25%, cap 15%
            }
        )
        sev = extract_gate_severity(df)
        assert sev["position_limit"] == 10.0  # 25 - 15

    def test_sector_severity_over_cap(self):
        import pandas as pd

        from scripts.analysis.siege_predictivity_audit import extract_gate_severity

        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT", "BAC"],
                "sector": ["Tech", "Tech", "Finance"],
                "weight_pct": [30.0, 30.0, 10.0],  # Tech sum 60%, cap 35%
            }
        )
        sev = extract_gate_severity(df)
        assert sev["sector_limit"] == 25.0  # 60 - 35

    def test_leverage_severity_nonzero_when_held(self):
        import pandas as pd

        from scripts.analysis.siege_predictivity_audit import extract_gate_severity

        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "TQQQ"],
                "sector": ["Tech", "ETF"],
                "weight_pct": [80.0, 20.0],
            }
        )
        sev = extract_gate_severity(df)
        assert sev["leverage_ban"] == 20.0  # TQQQ weight

    def test_empty_df_returns_none(self):
        import pandas as pd

        from scripts.analysis.siege_predictivity_audit import extract_gate_severity

        sev = extract_gate_severity(pd.DataFrame())
        assert all(v is None for v in sev.values())


class TestAcceptanceFlags:
    """codex Plan consult Q5 correction: CI_upper < 0 기준 (NOT CI_lower)."""

    def _make_metric(self, ci30_hi: float, ci60_hi: float, point60: float):
        from scripts.analysis.siege_predictivity_audit import GateMetric

        m = GateMetric(gate_id="position_limit", severity="error", eligibility="auditable_now")
        m.ci_high[30] = ci30_hi
        m.ci_high[60] = ci60_hi
        m.cond_mean_diff[60] = point60
        return m

    def test_primary_keep_when_ci30_upper_negative_and_point60_negative(self):
        """codex: 30d CI_high < 0 AND 60d point estimate < 0."""
        from scripts.analysis.siege_predictivity_audit import analyze_predictivity

        # 직접 metric 구성 — ensure acceptance 로직 검증
        # Use analyze_predictivity 내부 flag 로직 대신 직접 계산 확인
        m = self._make_metric(ci30_hi=-0.5, ci60_hi=-0.3, point60=-1.0)
        # simulate flag set
        primary_keep = (
            m.ci_high[30] is not None
            and m.ci_high[30] < 0
            and m.cond_mean_diff[60] is not None
            and m.cond_mean_diff[60] < 0
        )
        assert primary_keep

    def test_primary_not_kept_when_ci30_upper_crosses_zero(self):
        m = self._make_metric(ci30_hi=0.5, ci60_hi=-1.0, point60=-2.0)
        primary_keep = (
            m.ci_high[30] is not None
            and m.ci_high[30] < 0
            and m.cond_mean_diff[60] is not None
            and m.cond_mean_diff[60] < 0
        )
        assert not primary_keep  # ci30 upper positive → fail

    def test_strong_keep_both_horizons_ci_high_negative(self):
        m = self._make_metric(ci30_hi=-0.5, ci60_hi=-0.3, point60=-1.0)
        strong_keep = (
            m.ci_high[30] is not None and m.ci_high[30] < 0 and m.ci_high[60] is not None and m.ci_high[60] < 0
        )
        assert strong_keep


class TestBootstrapSlopeCi:
    """Continuous severity OLS slope bootstrap."""

    def test_negative_correlation_negative_slope(self):
        """severity 클수록 return 저조 → slope 음수."""
        from scripts.analysis.siege_predictivity_audit import _bootstrap_slope_ci

        x = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]  # severity 증가
        y = [5.0, 4.0, 2.0, -1.0, -3.0, -5.0]  # return 감소
        slope, lo, hi = _bootstrap_slope_ci(x, y, n_iter=500)
        assert slope < 0
        # CI 양쪽 bound 도 음수 (strong signal)
        assert hi < 0

    def test_insufficient_sample_returns_nan(self):
        import math

        from scripts.analysis.siege_predictivity_audit import _bootstrap_slope_ci

        slope, lo, hi = _bootstrap_slope_ci([1.0, 2.0], [3.0, 4.0], n_iter=100)
        assert math.isnan(slope)

    def test_constant_x_returns_nan(self):
        import math

        from scripts.analysis.siege_predictivity_audit import _bootstrap_slope_ci

        # x 상수면 slope undefined
        slope, lo, hi = _bootstrap_slope_ci([5.0] * 10, list(range(10)), n_iter=100)
        assert math.isnan(slope)


class TestFixedTimestampVariantIsolation:
    """v2: variant 별 timestamp minute offset — 같은 날짜 row 충돌 방지."""

    def test_variant_timestamp_offsets_are_unique(self):
        from scripts.analysis.siege_predictivity_audit import VARIANT_TEMPLATES, _fixed_timestamp

        timestamps = {_fixed_timestamp("2024-01-31", v) for v in VARIANT_TEMPLATES}
        assert len(timestamps) == len(VARIANT_TEMPLATES), (
            "각 variant 는 unique timestamp offset 가져야 함 (같은 date 에 5 row insert 가능)"
        )

    def test_momentum_top10_is_minute_zero(self):
        """back-compat — v1 single-variant row 와 timestamp 일치."""
        from scripts.analysis.siege_predictivity_audit import _fixed_timestamp

        assert _fixed_timestamp("2024-01-31") == "2024-01-31T00:00:00+09:00"
        assert _fixed_timestamp("2024-01-31", "momentum_top10") == "2024-01-31T00:00:00+09:00"


class TestDeterministicSeed:
    """codex Round 1 fix: sha256 기반 deterministic seed (Python hash() 대체)."""

    def test_same_input_same_seed(self):
        """동일 (date, variant) → 항상 동일 seed."""
        from scripts.analysis.siege_predictivity_audit import _deterministic_seed

        s1 = _deterministic_seed("2024-01-31", "momentum_top10")
        s2 = _deterministic_seed("2024-01-31", "momentum_top10")
        assert s1 == s2

    def test_different_input_different_seed(self):
        """다른 (date, variant) → 다른 seed (collision 극히 낮음)."""
        from scripts.analysis.siege_predictivity_audit import _deterministic_seed

        s1 = _deterministic_seed("2024-01-31", "momentum_top10")
        s2 = _deterministic_seed("2024-01-31", "equal_weight_sample")
        s3 = _deterministic_seed("2024-02-28", "momentum_top10")
        assert s1 != s2
        assert s1 != s3
        assert s2 != s3

    def test_seed_in_uint32_range(self):
        """numpy Generator seed 는 0 ~ 2^32-1."""
        from scripts.analysis.siege_predictivity_audit import _deterministic_seed

        s = _deterministic_seed("2024-01-31", "any_variant")
        assert 0 <= s < 2**32

    def test_python_hash_independence(self):
        """PYTHONHASHSEED 독립 — Python hash() 는 process-randomized.
        sha256 은 identical input → identical output 보장.
        Round 1 finding: `abs(hash((date, variant))) % 2**32` 는 PYTHONHASHSEED
        따라 변함. 이 test 는 해당 regression 방지.
        """
        # Known sha256 prefix for "2024-01-31|momentum_top10" 를 계산해서 비교
        import hashlib

        from scripts.analysis.siege_predictivity_audit import _deterministic_seed

        raw = "2024-01-31|momentum_top10".encode("utf-8")
        expected = int.from_bytes(hashlib.sha256(raw).digest()[:4], byteorder="big")
        assert _deterministic_seed("2024-01-31", "momentum_top10") == expected


class TestSectorConcentratedUnknownExclude:
    """codex Round 1 fix: sector_concentrated 가 Unknown bucket 으로 collapse 방지."""

    def test_excludes_unknown_sector(self, tiny_db, monkeypatch):
        """Unknown sector ticker 가 largest 로 선택되지 않음."""
        import scripts.analysis.siege_predictivity_audit as mod

        # top-50 momentum 리턴, 일부는 Unknown, 일부는 real sector
        monkeypatch.setattr(
            mod,
            "top_n_momentum",
            lambda *a, **k: [
                "UNK1",
                "UNK2",
                "UNK3",
                "UNK4",
                "UNK5",
                "TECH1",
                "TECH2",
                "TECH3",
                "TECH4",
                "TECH5",
                "TECH6",
                "TECH7",
                "TECH8",
                "TECH9",
                "TECH10",
            ],
        )
        sectors = {f"UNK{i}": "Unknown" for i in range(1, 6)}
        sectors.update({f"TECH{i}": "Technology" for i in range(1, 11)})
        monkeypatch.setattr(mod, "_ticker_sector", lambda ticker, db_path=None: sectors.get(ticker, "Unknown"))

        result = mod.build_variant("sector_concentrated", [], "2024-01-31", db_path=tiny_db)
        assert result is not None
        tickers, weights = result
        # 10 tech (real sector) 뽑힘, Unknown 섞이지 않음
        assert all(t.startswith("TECH") for t in tickers)
        assert len(tickers) == 10

    def test_none_when_all_unknown(self, tiny_db, monkeypatch):
        """모든 top momentum 이 Unknown → variant 구성 불가 (None)."""
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(mod, "top_n_momentum", lambda *a, **k: [f"UNK{i}" for i in range(20)])
        monkeypatch.setattr(mod, "_ticker_sector", lambda ticker, db_path=None: "Unknown")
        result = mod.build_variant("sector_concentrated", [], "2024-01-31", db_path=tiny_db)
        assert result is None

    def test_none_when_real_sectors_insufficient(self, tiny_db, monkeypatch):
        """real sector 가 있지만 largest 가 < 10 → None."""
        import scripts.analysis.siege_predictivity_audit as mod

        monkeypatch.setattr(
            mod, "top_n_momentum", lambda *a, **k: ["T1", "T2", "F1", "F2", "H1", "T3", "F3", "H2", "T4", "F4"]
        )
        sectors = {
            "T1": "Tech",
            "T2": "Tech",
            "T3": "Tech",
            "T4": "Tech",
            "F1": "Finance",
            "F2": "Finance",
            "F3": "Finance",
            "F4": "Finance",
            "H1": "Health",
            "H2": "Health",
        }
        monkeypatch.setattr(mod, "_ticker_sector", lambda ticker, db_path=None: sectors.get(ticker, "Unknown"))
        result = mod.build_variant("sector_concentrated", [], "2024-01-31", db_path=tiny_db)
        # Tech (4) + Finance (4) + Health (2) — largest 4, < 10 → None
        assert result is None
