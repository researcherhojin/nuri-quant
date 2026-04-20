"""E4-0b — certify() snapshot injection + timestamp override regression tests.

docs/plans/e4_0b.md §3.1 에 따라 `certify(snapshot=..., timestamp=...)` 확장.
Historical audit 모드 — 실 DB portfolio 를 건드리지 않고 synthetic snapshot 주입.

중요 invariant:
- snapshot=None 이면 _capture_snapshot() 호출 (기존 production 동작 불변)
- snapshot 주입 시 _capture_snapshot() 호출 안 됨 (재-read 금지)
- timestamp 주입 시 Certificate.timestamp + certifications row 에 동일 반영
- caller="audit:historical" 이 CallerTag Literal 에 등록
- ContextVar 경유로 gate 들이 주입된 snapshot 값 읽음 (R2/R4 rigor 유지)
"""

from __future__ import annotations

import pandas as pd

from nuri.core.db import query
from nuri.trading.engine.certification import (
    Certificate,
    CertSnapshot,
    _compute_portfolio_hash,
    certify,
)


def _make_snapshot(portfolio_raw: list[dict], *, regime: str = "bull_low_vol") -> CertSnapshot:
    """Synthetic CertSnapshot — portfolio_df 는 analyze_portfolio output schema 모사."""
    df = pd.DataFrame(
        [
            {
                "account": r["account"],
                "ticker": r["ticker"],
                "sector": r["sector"],
                "quantity": r["quantity"],
                "avg_price": r["avg_price"],
                "current_price": r["avg_price"],  # flat — no P&L
                "currency": "USD",
                "current_value_usd": round(r["quantity"] * r["avg_price"], 2),
                "cost_basis_usd": round(r["quantity"] * r["avg_price"], 2),
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "price_date": "2024-01-31",
            }
            for r in portfolio_raw
        ]
    )
    total_value = df["current_value_usd"].sum() or 1
    df["weight_pct"] = round(df["current_value_usd"] / total_value * 100, 2)
    df.attrs["warnings"] = []
    df.attrs["total_value_usd"] = round(total_value, 2)
    df.attrs["usd_krw"] = 1380.0
    return CertSnapshot(
        regime=regime,
        portfolio_raw=portfolio_raw,
        portfolio_df=df,
        portfolio_hash=_compute_portfolio_hash(rows=portfolio_raw),
        portfolio_error=None,
    )


class TestSnapshotInjection:
    """snapshot 파라미터가 _capture_snapshot 호출을 대체한다."""

    def test_snapshot_provided_skips_capture(self, populated_db_cert, monkeypatch):
        """snapshot 주입 시 _capture_snapshot() 호출 0회 — 재-read 금지."""
        calls = {"n": 0}
        from nuri.trading.engine import certification as cert_mod

        original = cert_mod._capture_snapshot

        def counting(**kw):
            calls["n"] += 1
            return original(**kw)

        monkeypatch.setattr(cert_mod, "_capture_snapshot", counting)

        snap = _make_snapshot(
            [{"account": "test", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}]
        )
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap)

        assert calls["n"] == 0, "snapshot 주입 시 _capture_snapshot 호출되면 재-read 발생"

    def test_snapshot_none_calls_capture_once(self, populated_db_cert, monkeypatch):
        """snapshot=None 이면 _capture_snapshot 정확히 1회 호출 (production path 유지)."""
        calls = {"n": 0}
        from nuri.trading.engine import certification as cert_mod

        original = cert_mod._capture_snapshot

        def counting(**kw):
            calls["n"] += 1
            return original(**kw)

        monkeypatch.setattr(cert_mod, "_capture_snapshot", counting)

        certify(db_path=populated_db_cert, caller="test")
        assert calls["n"] == 1

    def test_injected_snapshot_regime_used_by_gates(self, populated_db_cert):
        """주입된 snapshot.regime 이 gate 내부 _current_regime() 호출 결과로 보임."""
        snap = _make_snapshot(
            [{"account": "test", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}],
            regime="stagflation",
        )
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap)
        rows = query("SELECT regime FROM certifications", db_path=populated_db_cert)
        assert rows[0]["regime"] == "stagflation"

    def test_injected_snapshot_hash_persisted(self, populated_db_cert):
        """snapshot.portfolio_hash 가 그대로 persist — recomputation 없음."""
        raw = [
            {"account": "audit", "ticker": "GOOG", "sector": "Tech", "quantity": 5, "avg_price": 200.0},
            {"account": "audit", "ticker": "NVDA", "sector": "Tech", "quantity": 3, "avg_price": 500.0},
        ]
        snap = _make_snapshot(raw)
        expected_hash = snap.portfolio_hash
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap)
        rows = query("SELECT portfolio_hash FROM certifications", db_path=populated_db_cert)
        assert rows[0]["portfolio_hash"] == expected_hash


class TestTimestampOverride:
    """timestamp 파라미터 — historical snapshot 의 고정 timestamp 로 dedupe 가능."""

    def test_timestamp_none_uses_kst_now(self, populated_db_cert):
        """timestamp=None 이면 kst_now() 기반 — 현재 시각 prefix 매치."""
        from nuri.core.timezone import today_kst

        today = today_kst()  # already ISO string 'YYYY-MM-DD'
        cert = certify(db_path=populated_db_cert, caller="test")
        assert cert.timestamp.startswith(today)

    def test_timestamp_override_reflected_in_cert(self, populated_db_cert):
        """timestamp 주입 시 Certificate.timestamp 가 그 값 그대로."""
        fixed = "2024-03-15T00:00:00+09:00"
        snap = _make_snapshot(
            [{"account": "audit", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}]
        )
        cert = certify(
            db_path=populated_db_cert,
            caller="audit:historical",
            snapshot=snap,
            timestamp=fixed,
        )
        assert cert.timestamp == fixed

    def test_timestamp_override_persisted(self, populated_db_cert):
        """timestamp 주입 시 certifications row 의 timestamp 도 동일."""
        fixed = "2024-06-01T00:00:00+09:00"
        snap = _make_snapshot(
            [{"account": "audit", "ticker": "MSFT", "sector": "Tech", "quantity": 2, "avg_price": 400.0}]
        )
        certify(
            db_path=populated_db_cert,
            caller="audit:historical",
            snapshot=snap,
            timestamp=fixed,
        )
        rows = query("SELECT timestamp FROM certifications", db_path=populated_db_cert)
        assert rows[0]["timestamp"] == fixed

    def test_timestamp_enables_dedupe_by_snapshot_date(self, populated_db_cert):
        """같은 timestamp 로 2회 persist → 2 rows (애플리케이션 레벨 dedup 책임 확인).

        중복 감지는 script-level idempotency guard 책임 (docs/plans/e4_0b.md §3.4).
        engine layer 는 timestamp 를 그대로 저장, dedupe 강제 안 함.
        """
        fixed = "2024-09-10T00:00:00+09:00"
        snap = _make_snapshot(
            [{"account": "audit", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}]
        )
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap, timestamp=fixed)
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap, timestamp=fixed)
        rows = query(
            "SELECT COUNT(*) c FROM certifications WHERE timestamp = ?",
            (fixed,),
            db_path=populated_db_cert,
        )
        assert rows[0]["c"] == 2


class TestCallerTagAuditHistorical:
    """audit:historical caller 가 CallerTag Literal 에 등록 + persist 가능."""

    def test_audit_historical_caller_persists(self, populated_db_cert):
        snap = _make_snapshot(
            [{"account": "audit", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}]
        )
        certify(
            db_path=populated_db_cert,
            caller="audit:historical",
            snapshot=snap,
        )
        rows = query("SELECT caller FROM certifications", db_path=populated_db_cert)
        assert rows[0]["caller"] == "audit:historical"


class TestBackwardCompat:
    """기존 production path — snapshot/timestamp=None — 모든 동작 불변."""

    def test_no_params_matches_prior_behavior(self, populated_db_cert):
        """신규 kwargs 없이 호출 → production 동작 (Certificate 반환, 1 row persist)."""
        cert = certify(db_path=populated_db_cert, caller="test")
        assert isinstance(cert, Certificate)
        rows = query("SELECT COUNT(*) c FROM certifications", db_path=populated_db_cert)
        assert rows[0]["c"] == 1

    def test_snapshot_param_does_not_leak_contextvar(self, populated_db_cert):
        """certify(snapshot=...) 후 _CERT_SNAPSHOT 는 reset 되어 외부 코드에 누수 안 됨."""
        from nuri.trading.engine.certification import _CERT_SNAPSHOT

        snap = _make_snapshot(
            [{"account": "audit", "ticker": "AAPL", "sector": "Tech", "quantity": 10, "avg_price": 150}]
        )
        assert _CERT_SNAPSHOT.get() is None
        certify(db_path=populated_db_cert, caller="audit:historical", snapshot=snap)
        assert _CERT_SNAPSHOT.get() is None  # reset 확인


