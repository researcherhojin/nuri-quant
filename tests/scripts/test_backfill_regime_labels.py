"""Tests for scripts/ops/backfill_regime_labels.py — recommendations.regime 백필 (#832).

#832 Gotcha-Test Pair (b): 백필 멱등성 — 재실행 시 이미 canonical 라벨된 행 skip.
tmp_path DB 격리 (tests/CLAUDE.md), 티커/가격은 전부 합성 placeholder (privacy).
"""

from __future__ import annotations

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db, query, upsert_prices
from nuri.core.timezone import today_kst
from scripts.ops.backfill_regime_labels import backfill_regime_labels


@pytest.fixture
def seeded_db(tmp_path):
    """SPY 260 영업일 (today_kst 앵커 — time-bomb 방지) + 비-canonical regime 행 6개."""
    path = tmp_path / "test.db"
    init_db(path)

    # 완만한 상승 추세 → classify_regime 이 deterministic 하게 canonical 라벨 반환
    dates = pd.bdate_range(end=today_kst(), periods=260)
    rows = []
    for i, d in enumerate(dates):
        p = 100.0 + i * 0.5
        rows.append(
            {
                "ticker": "SPY",
                "date": d.strftime("%Y-%m-%d"),
                "open": p,
                "high": p + 1,
                "low": p - 1,
                "close": p,
                "volume": 1_000_000,
                "adj_close": p,
            }
        )
    upsert_prices(pd.DataFrame(rows), path)

    recent = dates[-3].strftime("%Y-%m-%d")
    with get_db(path) as conn:
        conn.executemany(
            "INSERT INTO recommendations (date, ticker, action, confidence, regime, signals, entry_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (recent, "TEST1", "BUY", 70.0, None, "[]", 100.0),  # NULL → 라벨
                (recent, "TEST2", "BUY", 70.0, "", "[]", 100.0),  # 빈문자열 → 라벨
                (recent, "TEST3", "SELL", 60.0, "[recovery] 비중 축소", "[]", 100.0),  # free-text → 라벨
                (recent, "TEST4", "BUY", 70.0, "bear_high_vol", "[]", 100.0),  # canonical → skip
                ("2020-01-02", "TEST5", "BUY", 70.0, None, "[]", 100.0),  # 데이터 이전 → NULL 유지
                ("2020-01-03", "TEST6", "BUY", 70.0, "junk", "[]", 100.0),  # 분류불가 free-text → NULL 정규화
            ],
        )
    return path


def _regimes(db_path) -> dict[str, str | None]:
    rows = query("SELECT ticker, regime FROM recommendations", db_path=db_path)
    return {r["ticker"]: r["regime"] for r in rows}


class TestBackfill:
    def test_backfill_labels_noncanonical_rows(self, seeded_db):
        from nuri.quant.regime.classifier import ALL_REGIMES

        stats = backfill_regime_labels(db_path=seeded_db)

        assert stats["candidates"] == 5  # TEST4 (canonical) 제외
        assert stats["relabeled"] == 3  # TEST1/2/3
        assert stats["kept_null"] == 1  # TEST5
        assert stats["normalized_null"] == 1  # TEST6

        regimes = _regimes(seeded_db)
        for t in ("TEST1", "TEST2", "TEST3"):
            assert regimes[t] in ALL_REGIMES, f"{t} 는 canonical 라벨이어야 함"
        assert regimes["TEST4"] == "bear_high_vol", "이미 canonical 인 행은 미변경"
        assert regimes["TEST5"] is None, "분류 불가 NULL 행은 NULL 유지 ('unknown' 금지)"
        assert regimes["TEST6"] is None, "분류 불가 free-text 는 NULL 로 정규화"

    def test_backfill_idempotent_on_rerun(self, seeded_db):
        """재실행 시 이미 라벨된 행 skip — 결과/행 값 불변 (멱등성)."""
        backfill_regime_labels(db_path=seeded_db)
        first = _regimes(seeded_db)

        stats2 = backfill_regime_labels(db_path=seeded_db)
        assert stats2["candidates"] == 2  # TEST5 + TEST6 (둘 다 NULL 잔존) 만 재후보
        assert stats2["relabeled"] == 0
        assert stats2["normalized_null"] == 0
        assert stats2["kept_null"] == 2
        assert _regimes(seeded_db) == first, "재실행이 어떤 행도 바꾸지 않아야 함"

    def test_dry_run_writes_nothing(self, seeded_db):
        before = _regimes(seeded_db)
        stats = backfill_regime_labels(db_path=seeded_db, dry_run=True)
        assert stats["relabeled"] == 3  # 변경 예정 카운트는 보고
        assert _regimes(seeded_db) == before, "dry-run 은 DB write 없음"
