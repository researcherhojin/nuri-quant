"""#1499 — `classify_regime` 의 브리프 범위 메모 키: 라이브/as-of 모드, KST 날짜, DB 경로 타입을 구분한다 (Codex P2)."""

from __future__ import annotations

from nuri.core.brief_scope import brief_scope
from nuri.quant.regime import classifier


def _count_bodies(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        classifier, "_classify_regime_uncached", lambda date, db_path: calls.append((date, db_path)) or None
    )
    return calls


class TestRegimeMemoKey:
    def test_live_and_asof_today_do_not_share_a_key(self, monkeypatch, tmp_path):
        """date=None 은 신선도 검사를 포함한 라이브, date=오늘 은 as-of — 결과가 같아도 의미가 다르다."""
        calls = _count_bodies(monkeypatch)
        monkeypatch.setattr(classifier, "today_kst", lambda: "2026-09-09")
        with brief_scope():
            classifier.classify_regime(db_path=tmp_path)
            classifier.classify_regime(date="2026-09-09", db_path=tmp_path)
            classifier.classify_regime(db_path=tmp_path)
            classifier.classify_regime(date="2026-09-09", db_path=tmp_path)
        assert calls == [(None, tmp_path), ("2026-09-09", tmp_path)]

    def test_kst_rollover_inside_one_scope_recomputes(self, monkeypatch, tmp_path):
        calls = _count_bodies(monkeypatch)
        today = {"d": "2026-09-09"}
        monkeypatch.setattr(classifier, "today_kst", lambda: today["d"])
        with brief_scope():
            classifier.classify_regime(db_path=tmp_path)
            today["d"] = "2026-09-10"
            classifier.classify_regime(db_path=tmp_path)
        assert len(calls) == 2, "자정을 넘긴 범위가 어제의 레짐을 재사용했다"

    def test_none_db_and_a_path_named_none_are_different_keys(self, monkeypatch, tmp_path):
        calls = _count_bodies(monkeypatch)
        monkeypatch.setattr(classifier, "today_kst", lambda: "2026-09-09")
        weird = tmp_path / "None"
        with brief_scope():
            classifier.classify_regime(db_path=None)
            classifier.classify_regime(db_path=weird)
        assert len(calls) == 2
