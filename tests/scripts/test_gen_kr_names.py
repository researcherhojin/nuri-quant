"""Tests for scripts/ops/gen_kr_names.py — KR 종목명 맵 생성."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.ops import gen_kr_names as kr_names


def _listing_df(n: int) -> pd.DataFrame:
    """Mock StockListing('KOSPI') — Code/Name/Marcap 컬럼."""
    return pd.DataFrame(
        {
            "Code": [f"{i:06d}" for i in range(n)],
            "Name": [f"종목{i}" for i in range(n)],
            "Marcap": [n - i for i in range(n)],  # 내림차순 시총
        }
    )


class TestBuildNameMap:
    def test_maps_code_to_name_sorted(self):
        df = _listing_df(3)
        result = kr_names.build_name_map(df)
        assert result == {"000000.KS": "종목0", "000001.KS": "종목1", "000002.KS": "종목2"}
        assert list(result.keys()) == sorted(result.keys())

    def test_caps_at_top_n_by_marcap(self, monkeypatch):
        monkeypatch.setattr(kr_names, "_TOP_N", 2)
        df = _listing_df(5)  # Marcap 5,4,3,2,1 → top2 = code 000000, 000001
        result = kr_names.build_name_map(df)
        assert set(result) == {"000000.KS", "000001.KS"}

    def test_skips_blank_names(self):
        df = pd.DataFrame({"Code": ["005930", "000660"], "Name": ["삼성전자", "  "], "Marcap": [100, 90]})
        result = kr_names.build_name_map(df)
        assert result == {"005930.KS": "삼성전자"}


class TestWriteNameMap:
    def test_writes_json_returns_count(self, tmp_path):
        path = tmp_path / "kr.json"
        count = kr_names.write_name_map({"005930.KS": "삼성전자", "000660.KS": "SK하이닉스"}, path)
        assert count == 2
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["005930.KS"] == "삼성전자"

    def test_creates_parent_dir(self, tmp_path):
        path = tmp_path / "nested" / "kr.json"
        kr_names.write_name_map({"005930.KS": "삼성전자"}, path)
        assert path.exists()


class TestFetchKospiListing:
    def test_fdr_not_installed(self):
        with patch.dict(sys.modules, {"FinanceDataReader": None}):
            with pytest.raises(FileNotFoundError, match="finance-datareader"):
                kr_names._fetch_kospi_listing()

    def test_fdr_returns_data(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = _listing_df(10)
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            df = kr_names._fetch_kospi_listing()
        assert len(df) == 10

    def test_fdr_empty(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame()
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="unexpected"):
                kr_names._fetch_kospi_listing()

    def test_fdr_missing_name_column(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({"Code": ["005930"], "Marcap": [100]})
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="unexpected"):
                kr_names._fetch_kospi_listing()

    def test_fdr_raises(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.side_effect = ValueError("KRX API change")
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="KOSPI listing fetch 실패"):
                kr_names._fetch_kospi_listing()


class TestRegenerate:
    def test_fetch_build_write(self, tmp_path):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = _listing_df(3)
        path = tmp_path / "kr.json"
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            count = kr_names.regenerate(path)
        assert count == 3
        assert json.loads(path.read_text(encoding="utf-8"))["000000.KS"] == "종목0"


class TestMain:
    def test_main_writes_default_path(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(kr_names, "KR_NAMES_PATH", tmp_path / "kr.json")
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = _listing_df(4)
        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            kr_names.main()
        out = capsys.readouterr().out
        assert "4건 저장" in out
        assert (tmp_path / "kr.json").exists()
