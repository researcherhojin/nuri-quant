"""price_targets.py branch coverage — Issue #616 Phase 3-C1.

51→58: `if _STOCK_TYPES_PATH.exists():` False (yaml 부재) → 빈 mapping 반환.
"""

from __future__ import annotations


class TestLoadStockTypesYamlMissing:
    def test_returns_empty_when_yaml_path_missing(self, tmp_path, monkeypatch):
        """51→58: _STOCK_TYPES_PATH 존재 안 함 → 빈 mapping."""
        from nuri.trading.recommend import price_targets as pt_mod

        # cache 무효화 후 존재하지 않는 path 주입.
        monkeypatch.setattr(pt_mod, "_stock_types_cache", None)
        monkeypatch.setattr(
            pt_mod,
            "_STOCK_TYPES_PATH",
            tmp_path / "nonexistent" / "stock_types.yaml",
        )

        result = pt_mod._load_stock_types()
        assert result == {}
