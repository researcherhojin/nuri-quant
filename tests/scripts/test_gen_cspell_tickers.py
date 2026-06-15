"""Tests for scripts/ops/gen_cspell_tickers.py — cSpell 티커 사전 생성."""

from __future__ import annotations

import yaml

from scripts.ops import gen_cspell_tickers as g


class TestBuildTickerWords:
    def test_splits_dot_and_hyphen_alpha_only(self):
        uni = {
            "us": {"tickers": ["AAPL", "BRK-B", "BF-B"]},
            "kr": {"tickers": ["005930.KS", "000660.KQ"]},
        }
        words = g.build_ticker_words(uni)
        # alpha len>=2: AAPL, BRK, BF, KS, KQ. 단일문자 B 제외, 숫자코드 제외.
        assert words == ["AAPL", "BF", "BRK", "KQ", "KS"]

    def test_excludes_single_char_and_numeric(self):
        uni = {"g": {"tickers": ["A", "F", "T", "123456.KS"]}}
        # 단일문자 전부 제외, 숫자 제외 → KS 만
        assert g.build_ticker_words(uni) == ["KS"]

    def test_dedupe_and_sort(self):
        uni = {"a": {"tickers": ["MSFT", "aapl"]}, "b": {"tickers": ["AAPL", "MSFT"]}}
        assert g.build_ticker_words(uni) == ["AAPL", "MSFT"]

    def test_ignores_groups_without_tickers(self):
        uni = {"meta": {"description": "no tickers here"}, "g": {"tickers": ["NVDA"]}}
        assert g.build_ticker_words(uni) == ["NVDA"]


class TestWriteTickerWords:
    def test_writes_one_per_line_trailing_newline(self, tmp_path):
        path = tmp_path / "tickers.txt"
        count = g.write_ticker_words(["AAPL", "MSFT", "NVDA"], path)
        assert count == 3
        assert path.read_text(encoding="utf-8") == "AAPL\nMSFT\nNVDA\n"

    def test_creates_parent_dir(self, tmp_path):
        path = tmp_path / "nested" / "tickers.txt"
        g.write_ticker_words(["AAPL"], path)
        assert path.exists()


class TestRegenerate:
    def test_load_build_write(self, tmp_path):
        uni_path = tmp_path / "universe.yaml"
        uni_path.write_text(yaml.safe_dump({"us": {"tickers": ["AAPL", "BRK-B"]}}), encoding="utf-8")
        out_path = tmp_path / "tickers.txt"
        count = g.regenerate(universe_path=uni_path, out_path=out_path)
        assert count == 2
        assert out_path.read_text(encoding="utf-8") == "AAPL\nBRK\n"

    def test_empty_universe_yaml(self, tmp_path):
        uni_path = tmp_path / "universe.yaml"
        uni_path.write_text("", encoding="utf-8")  # yaml.safe_load → None → {} fallback
        out_path = tmp_path / "tickers.txt"
        assert g.regenerate(universe_path=uni_path, out_path=out_path) == 0


class TestMain:
    def test_main_writes_default_paths(self, tmp_path, monkeypatch, capsys):
        uni_path = tmp_path / "universe.yaml"
        uni_path.write_text(yaml.safe_dump({"us": {"tickers": ["AAPL", "NVDA"]}}), encoding="utf-8")
        monkeypatch.setattr(g, "UNIVERSE_PATH", uni_path)
        monkeypatch.setattr(g, "TICKERS_PATH", tmp_path / "tickers.txt")
        g.main()
        out = capsys.readouterr().out
        assert "2개 저장" in out
        assert (tmp_path / "tickers.txt").read_text(encoding="utf-8") == "AAPL\nNVDA\n"
