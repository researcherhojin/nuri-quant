"""Tests for nuri/llm/thesis_query.py — thesis Q&A engine (Issue #508)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from nuri.llm import thesis_query as tq

# ─── _slugify ──────────────────────────────────────────────────────


class TestSlugify:
    def test_basic_kebab(self) -> None:
        assert tq._slugify("Hello World") == "hello-world"

    def test_korean_preserved(self) -> None:
        assert tq._slugify("엔비디아 분석") == "엔비디아-분석"

    def test_empty_falls_back(self) -> None:
        assert tq._slugify("---") == "thesis"
        assert tq._slugify("") == "thesis"

    def test_max_len_truncates(self) -> None:
        long = "a" * 100
        assert len(tq._slugify(long, max_len=20)) == 20


# ─── _fetch_db_context ─────────────────────────────────────────────


@pytest.fixture
def mock_query_df(monkeypatch: pytest.MonkeyPatch):
    """Inject query_df responses by SQL substring → DataFrame."""
    responses: dict[str, pd.DataFrame] = {}

    def _mock(sql, params=None):
        for key, df in responses.items():
            if key in sql:
                return df
        return pd.DataFrame()

    monkeypatch.setattr("nuri.llm.thesis_query.query_df", _mock)
    return responses


class TestFetchDbContext:
    def test_full_data_renders_all_sections(self, mock_query_df) -> None:
        mock_query_df["FROM prices"] = pd.DataFrame(
            {
                "date": [f"2026-04-0{i}" for i in range(1, 8)],
                "close": [100, 102, 104, 106, 108, 110, 112],
                "volume": [1000] * 7,
            }
        )
        mock_query_df["FROM factors"] = pd.DataFrame(
            [
                {
                    "date": "2026-04-30",
                    "momentum_score": 0.7,
                    "value_score": 0.5,
                    "quality_score": 0.6,
                    "sentiment_score": 0.4,
                    "composite_score": 0.65,
                }
            ]
        )
        mock_query_df["FROM signals"] = pd.DataFrame(
            [
                {
                    "date": "2026-04-30",
                    "rsi_14": 55.0,
                    "macd": 1.5,
                    "macd_signal": 1.2,
                    "sma_20": 105.0,
                    "sma_50": 100.0,
                    "sma_200": 90.0,
                }
            ]
        )
        mock_query_df["FROM fundamentals"] = pd.DataFrame(
            [
                {
                    "pe_ratio": 25.0,
                    "forward_pe": 22.0,
                    "profit_margin": 0.18,
                    "revenue_growth": 0.15,
                    "market_cap": 5e11,
                    "debt_to_equity": 0.5,
                }
            ]
        )
        mock_query_df["FROM portfolio"] = pd.DataFrame(
            [{"account": "acct_alpha", "quantity": 14.0, "avg_price": 100.0, "sector": "Tech"}]
        )
        mock_query_df["FROM recommendations"] = pd.DataFrame(
            [
                {"date": "2026-05-01", "action": "BUY", "confidence": 0.8, "regime": "neutral"},
                {"date": "2026-04-30", "action": "HOLD", "confidence": 0.7, "regime": "neutral"},
            ]
        )

        ctx = tq._fetch_db_context("AAA")
        assert "close $112.00" in ctx["price"]
        assert "5d" in ctx["price"]
        assert "composite 0.650" in ctx["factor"]
        assert "RSI(14) 55.0" in ctx["technical"]
        assert "$500.0B" in ctx["fundamentals"]
        assert "HELD" in ctx["portfolio"]
        assert "BUY" in ctx["recent_calls"]

    def test_market_cap_trillion_format(self, mock_query_df) -> None:
        mock_query_df["FROM fundamentals"] = pd.DataFrame(
            [
                {
                    "pe_ratio": 25.0,
                    "forward_pe": 22.0,
                    "profit_margin": 0.18,
                    "revenue_growth": 0.15,
                    "market_cap": 2.5e12,
                    "debt_to_equity": 0.5,
                }
            ]
        )
        ctx = tq._fetch_db_context("AAA")
        assert "$2.50T" in ctx["fundamentals"]

    def test_market_cap_none_renders_dash(self, mock_query_df) -> None:
        mock_query_df["FROM fundamentals"] = pd.DataFrame(
            [
                {
                    "pe_ratio": 25.0,
                    "forward_pe": 22.0,
                    "profit_margin": None,
                    "revenue_growth": None,
                    "market_cap": None,
                    "debt_to_equity": 0.5,
                }
            ]
        )
        ctx = tq._fetch_db_context("AAA")
        assert "market cap —" in ctx["fundamentals"]
        assert "profit margin —" in ctx["fundamentals"]

    def test_empty_db_returns_fallback_strings(self, mock_query_df) -> None:
        ctx = tq._fetch_db_context("UNKNOWN")
        assert "no price data" in ctx["price"]
        assert "no factor data" in ctx["factor"]
        assert "no signal data" in ctx["technical"]
        assert "no fundamentals data" in ctx["fundamentals"]
        assert "NOT HELD" in ctx["portfolio"]
        assert "no recent system recommendations" in ctx["recent_calls"]

    def test_short_price_history_skips(self, mock_query_df) -> None:
        # 5 rows, function requires >= 6
        mock_query_df["FROM prices"] = pd.DataFrame(
            {"date": [f"2026-04-0{i}" for i in range(1, 6)], "close": [100, 101, 102, 103, 104], "volume": [1000] * 5}
        )
        ctx = tq._fetch_db_context("AAA")
        assert "< 6 rows" in ctx["price"]

    def test_query_exception_caught_per_section(self, monkeypatch) -> None:
        """각 section 의 try/except 가 다른 section 영향 없게 흡수 — error 문자열로 변환."""

        def _raises(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr("nuri.llm.thesis_query.query_df", _raises)
        ctx = tq._fetch_db_context("AAA")
        for key in ("price", "factor", "technical", "fundamentals", "portfolio", "recent_calls"):
            assert ctx[key].startswith("(error:")


# ─── _build_prompt ─────────────────────────────────────────────────


class TestBuildPrompt:
    def test_includes_question_and_ticker(self) -> None:
        ctx = {
            "price": "p",
            "factor": "f",
            "technical": "t",
            "fundamentals": "fu",
            "portfolio": "pf",
            "recent_calls": "rc",
        }
        prompt = tq._build_prompt("AAA", "Why is X?", ctx)
        assert "AAA" in prompt
        assert "Why is X?" in prompt
        assert "p" in prompt and "f" in prompt
        assert "rc" in prompt
        assert "Verdict" in prompt
        assert "Confidence" in prompt

    def test_missing_keys_use_dash(self) -> None:
        prompt = tq._build_prompt("AAA", "?", {})
        assert "—" in prompt
        assert "(no calls)" in prompt


# ─── price levels: canonical source only ───────────────────────────


class TestPriceLevelsCanonical:
    """가격 레벨은 `price_targets.calculate_targets` 만이 만든다.

    `.claude/rules/invariants.md` "No ad-hoc buy/sell calls" + `nuri/trading/
    recommend/CLAUDE.md` "price_targets.py is the canonical source — do not
    re-derive in callers". 이전에는 프롬프트가 LLM 에게 `Entry / Stop / TP
    (concrete prices)` 를 **직접 만들라**고 요구했다 — 실시간 가격도 ladder 도
    모르는 쪽이 숫자를 지어내는 경로였다.
    """

    _TARGETS = {
        "ticker": "AAA",
        "stock_type": "value",
        "current_price": 100.0,
        "entry_price": 100.0,
        "stop_loss": 90.0,
        "stop_loss_pct": -10,
        "target_1": 115.0,
        "target_1_pct": 15,
        "target_1_sell_pct": 50,
        "target_2": 130.0,
        "target_2_pct": 30,
        "target_2_sell_pct": 25,
        "trailing_stop_pct": -15,
        "is_leader": False,
    }

    def test_levels_come_from_calculate_targets(self, mock_query_df) -> None:
        with patch("nuri.trading.recommend.price_targets.calculate_targets", return_value=self._TARGETS):
            ctx = tq._fetch_db_context("AAA")
        assert "$90.00" in ctx["price_levels"]
        assert "$115.00" in ctx["price_levels"]
        assert "$130.00" in ctx["price_levels"]
        assert "sell 50%" in ctx["price_levels"]

    def test_leader_has_no_fixed_targets(self, mock_query_df) -> None:
        """리더는 고정 익절 폐기 → target_1/2 = None. 그 None 을 렌더하면 안 된다."""
        leader = {
            **self._TARGETS,
            "stock_type": "growth",
            "is_leader": True,
            "target_1": None,
            "target_2": None,
            "leader_ma": 95.0,
            "leader_ma_period": 50,
        }
        with patch("nuri.trading.recommend.price_targets.calculate_targets", return_value=leader):
            ctx = tq._fetch_db_context("AAA")
        assert "leader" in ctx["price_levels"]
        assert "50일선 트레일 $95.00" in ctx["price_levels"]
        assert "target_1" not in ctx["price_levels"]
        assert "None" not in ctx["price_levels"]

    def test_missing_price_data_reports_unavailable(self, mock_query_df) -> None:
        with patch(
            "nuri.trading.recommend.price_targets.calculate_targets",
            return_value={"ticker": "AAA", "error": "가격 데이터 없음"},
        ):
            ctx = tq._fetch_db_context("AAA")
        assert "unavailable" in ctx["price_levels"]

    def test_calculate_targets_exception_is_absorbed(self, mock_query_df) -> None:
        with patch("nuri.trading.recommend.price_targets.calculate_targets", side_effect=RuntimeError("boom")):
            ctx = tq._fetch_db_context("AAA")
        assert ctx["price_levels"].startswith("(error:")

    def test_prompt_forbids_llm_derived_levels(self) -> None:
        """회귀 잠금 — 프롬프트가 LLM 에게 가격을 만들라고 되돌아가면 FAIL."""
        prompt = tq._build_prompt("AAA", "?", {"price_levels": "  - stop_loss: $90.00"})
        assert "$90.00" in prompt
        assert "DO NOT derive your own" in prompt
        assert "Do NOT compute, round, adjust, or invent" in prompt
        assert "restate the system-computed levels" in prompt
        # 옛 문구가 되살아나면 FAIL
        assert "concrete prices" not in prompt


# ─── thesis_query (subprocess + filename rename) ───────────────────


class TestThesisQuery:
    def test_subprocess_success_renames_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("nuri.llm.thesis_query._fetch_db_context", lambda t: {})

        # llm_consult creates a file under our prefix; we simulate by writing one
        from nuri.core.timezone import today_kst as _tk

        date_str = _tk()
        consult_filename = f"{date_str}_thesis-aaa-test-question.md"
        target_filename = f"{date_str}_aaa_test-question.md"

        def _fake_run(*args, **kwargs):
            (tmp_path / consult_filename).write_text("# generated", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        out_path = tq.thesis_query("AAA", "test question", out_dir=tmp_path)
        assert out_path.name == target_filename
        assert out_path.exists()

    def test_subprocess_failure_logs_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr("nuri.llm.thesis_query._fetch_db_context", lambda t: {})
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr="err " * 200)
        )
        with caplog.at_level("ERROR"):
            tq.thesis_query("AAA", "q", out_dir=tmp_path)
        assert any("llm_consult failed" in rec.message for rec in caplog.records)

    def test_codex_only_appends_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def _capture(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("nuri.llm.thesis_query._fetch_db_context", lambda t: {})
        monkeypatch.setattr(subprocess, "run", _capture)
        tq.thesis_query("AAA", "q", out_dir=tmp_path, codex_only=True)
        assert "--codex-only" in captured["cmd"]
        assert "--qwen-only" not in captured["cmd"]

    def test_qwen_only_appends_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def _capture(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("nuri.llm.thesis_query._fetch_db_context", lambda t: {})
        monkeypatch.setattr(subprocess, "run", _capture)
        tq.thesis_query("AAA", "q", out_dir=tmp_path, qwen_only=True)
        assert "--qwen-only" in captured["cmd"]


# ─── main (argparse + print flag) ─────────────────────────────────


class TestMain:
    def test_main_returns_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out_file = tmp_path / "result.md"
        out_file.write_text("# generated", encoding="utf-8")
        monkeypatch.setattr("nuri.llm.thesis_query.thesis_query", lambda **kw: out_file)
        monkeypatch.setattr(sys, "argv", ["thesis_query.py", "--ticker", "AAA"])
        rc = tq.main()
        assert rc == 0

    def test_main_print_flag_outputs_content(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        out_file = tmp_path / "result.md"
        out_file.write_text("# generated thesis", encoding="utf-8")
        monkeypatch.setattr("nuri.llm.thesis_query.thesis_query", lambda **kw: out_file)
        monkeypatch.setattr(
            sys,
            "argv",
            ["thesis_query.py", "--ticker", "AAA", "--question", "test", "--print"],
        )
        tq.main()
        captured = capsys.readouterr()
        assert "saved:" in captured.out
        assert "generated thesis" in captured.out


# ─── __main__ guard ────────────────────────────────────────────────


def test_module_main_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`if __name__ == '__main__'` block — runpy로 entry-point 검증."""
    import runpy

    out_file = tmp_path / "stub.md"
    out_file.write_text("# stub", encoding="utf-8")
    # source-level patch (runpy reloads module so target-level patches don't survive)
    monkeypatch.setattr("nuri.llm.thesis_query.thesis_query", lambda **kw: out_file)
    monkeypatch.setattr(sys, "argv", ["thesis_query.py", "--ticker", "AAA"])
    # runpy 로 module 직접 실행 — sys.exit(main()) 호출 (return 0 → SystemExit(0))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("nuri.llm.thesis_query", run_name="__main__")
    assert exc.value.code == 0
