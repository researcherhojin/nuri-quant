"""Tests for nuri.collectors.universe_sync (#272 Phase 2a).

Unit tests cover compute_diff (pure function), CLI plumbing, and the
two public fetch helpers. Network calls are mocked.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

from nuri.collectors.universe_sync import (
    UniverseSyncCollector,
    _fetch_kospi200,
    _fetch_sp500_from_wikipedia,
    compute_diff,
)

# ───────────────────────────────────────────────
# compute_diff — pure function, no I/O
# ───────────────────────────────────────────────


class TestComputeDiff:
    def test_no_changes(self):
        cur = {"AAPL", "MSFT"}
        result = compute_diff(cur, set(), cur, set())
        assert result["us_added"] == []
        assert result["us_removed"] == []
        assert result["us_coverage_pct"] == 1.0

    def test_added_only(self):
        cur_us = {"AAPL"}
        fetched = {"AAPL", "GOOGL", "MSFT"}
        result = compute_diff(cur_us, set(), fetched, set())
        assert result["us_added"] == ["GOOGL", "MSFT"]
        assert result["us_removed"] == []

    def test_removed_only(self):
        cur_us = {"AAPL", "OLD"}
        fetched = {"AAPL"}
        result = compute_diff(cur_us, set(), fetched, set())
        assert result["us_added"] == []
        assert result["us_removed"] == ["OLD"]

    def test_added_and_removed(self):
        result = compute_diff({"A", "B"}, {"X"}, {"B", "C"}, {"X", "Y"})
        assert result["us_added"] == ["C"]
        assert result["us_removed"] == ["A"]
        assert result["kr_added"] == ["Y"]
        assert result["kr_removed"] == []

    def test_coverage_pct_partial(self):
        # 503 fetched, 339 in current, intersection = 339 (all current ⊆ fetched)
        cur = {f"T{i}" for i in range(339)}
        fetched = {f"T{i}" for i in range(503)}
        result = compute_diff(cur, set(), fetched, set())
        # coverage = (current ∩ fetched) / fetched = 339/503
        assert result["us_coverage_pct"] == pytest.approx(339 / 503, rel=1e-3)

    def test_coverage_pct_zero_fetched(self):
        # fetched empty → coverage 0 (zero-division guard)
        result = compute_diff({"A"}, set(), set(), set())
        assert result["us_coverage_pct"] == 0.0
        assert result["kr_coverage_pct"] == 0.0

    def test_alphabetical_sort(self):
        # added/removed must be sorted (deterministic output)
        result = compute_diff({"Z", "A", "M"}, set(), {"A", "B", "C"}, set())
        assert result["us_added"] == ["B", "C"]
        assert result["us_removed"] == ["M", "Z"]


# ───────────────────────────────────────────────
# _fetch_sp500_from_wikipedia — mock urllib + pandas
# ───────────────────────────────────────────────


class TestFetchSP500:
    def _mock_html_with_symbols(self, symbols: list[str]) -> str:
        rows = "".join(f"<tr><td>{s}</td><td>Acme {s}</td></tr>" for s in symbols)
        return f"<html><body><table><thead><tr><th>Symbol</th><th>Security</th></tr></thead><tbody>{rows}</tbody></table></body></html>"

    def test_normal_fetch(self):
        html = self._mock_html_with_symbols(["AAPL", "MSFT", "BRK.B"])
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_sp500_from_wikipedia()

        # BRK.B → BRK-B (yfinance compat)
        assert result == ["AAPL", "BRK-B", "MSFT"]

    def test_dedup(self):
        html = self._mock_html_with_symbols(["AAPL", "AAPL", "MSFT"])
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_sp500_from_wikipedia()

        assert len(result) == 2  # dedup'd

    def test_missing_symbol_column(self):
        html = "<html><body><table><thead><tr><th>NotSymbol</th></tr></thead><tbody><tr><td>X</td></tr></tbody></table></body></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="Wikipedia S&P 500 표 형식 변경"):
                _fetch_sp500_from_wikipedia()


# ───────────────────────────────────────────────
# _fetch_kospi200 — mock FinanceDataReader
# ───────────────────────────────────────────────


class TestFetchKospi200:
    def test_fdr_not_installed(self):
        # Simulate ImportError by removing FDR from sys.modules + blocking import
        with patch.dict(sys.modules, {"FinanceDataReader": None}):
            with pytest.raises(FileNotFoundError, match="finance-datareader"):
                _fetch_kospi200()

    def _kospi_df(self, n: int):
        """Mock StockListing('KOSPI') output — Code + Marcap 컬럼 포함."""
        return pd.DataFrame(
            {
                "Code": [f"{i:06d}" for i in range(n)],
                "Marcap": [n - i for i in range(n)],  # 내림차순 시총
            }
        )

    def test_fdr_returns_data(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._kospi_df(300)  # 300 KOSPI → top 200

        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            result = _fetch_kospi200()

        assert len(result) == 200  # top 200 only
        assert result[0].endswith(".KS")

    def test_fdr_returns_empty(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame()

        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="unexpected"):
                _fetch_kospi200()

    def test_fdr_missing_marcap(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = pd.DataFrame({"Code": ["005930"]})  # no Marcap

        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="unexpected"):
                _fetch_kospi200()

    def test_fdr_too_few(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.return_value = self._kospi_df(50)  # < 100 minimum

        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="< 100 minimum"):
                _fetch_kospi200()

    def test_fdr_raises(self):
        mock_fdr = MagicMock()
        mock_fdr.StockListing.side_effect = ValueError("KRX API change")

        with patch.dict(sys.modules, {"FinanceDataReader": mock_fdr}):
            with pytest.raises(RuntimeError, match="KOSPI listing fetch 실패"):
                _fetch_kospi200()


# ───────────────────────────────────────────────
# UniverseSyncCollector — collect + save behavior
# ───────────────────────────────────────────────


class TestUniverseSyncCollector:
    @pytest.fixture
    def universe_yaml(self, tmp_path: Path):
        path = tmp_path / "universe.yaml"
        data = {
            "us_core": {"description": "core", "tickers": ["AAPL", "MSFT"]},
            "us_sp500_extended": {"description": "ext", "tickers": ["GOOGL", "ARKK"]},
            "kr_kospi200": {"description": "kr", "tickers": ["005930.KS"]},
        }
        with path.open("w") as f:
            yaml.safe_dump(data, f)
        return path

    def test_collect_us_only_no_changes(self, universe_yaml, monkeypatch):
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        # SP500 fetch returns same set as current (AAPL+MSFT+GOOGL+ARKK)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["AAPL", "MSFT", "GOOGL", "ARKK"],
        ):
            c = UniverseSyncCollector()
            result = c.collect(market="us", dry_run=True)

        assert result["us_added"] == []
        assert result["us_removed"] == []

    def test_collect_us_only_addition(self, universe_yaml, monkeypatch):
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["AAPL", "MSFT", "GOOGL", "ARKK", "NEW"],
        ):
            c = UniverseSyncCollector()
            result = c.collect(market="us", dry_run=True)

        assert result["us_added"] == ["NEW"]

    def test_collect_kr_skipped_when_fdr_missing(self, universe_yaml, monkeypatch, capsys):
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        with (
            patch(
                "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
                return_value=["AAPL"],
            ),
            patch(
                "nuri.collectors.universe_sync._fetch_kospi200",
                side_effect=FileNotFoundError("FDR missing"),
            ),
        ):
            c = UniverseSyncCollector()
            result = c.collect(dry_run=True)

        assert c._kr_skipped is True
        # KR diff stays at 0 (current preserved)
        assert result["kr_added"] == []
        assert result["kr_removed"] == []

    def test_collect_kr_only_raises_when_fdr_missing(self, universe_yaml, monkeypatch):
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        with patch(
            "nuri.collectors.universe_sync._fetch_kospi200",
            side_effect=FileNotFoundError("FDR missing"),
        ):
            c = UniverseSyncCollector()
            # market='kr' explicitly → should still NOT raise (FileNotFoundError, not RuntimeError)
            c.collect(market="kr", dry_run=True)

        # kr skipped, returns empty diff (US untouched since market filter='kr')
        assert c._kr_skipped is True

    def test_save_dry_run_no_yaml_change(self, universe_yaml, monkeypatch, capsys):
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["AAPL", "MSFT", "GOOGL", "ARKK", "NEW"],
        ):
            c = UniverseSyncCollector()
            c.collect(market="us", dry_run=True)
            # Capture diff for save
            data = c.collect(market="us", dry_run=True)
            count = c.save(data)

        # Verify yaml unchanged
        with universe_yaml.open() as f:
            after = yaml.safe_load(f)
        assert "NEW" not in after["us_sp500_extended"]["tickers"]
        assert count == 1  # one diff item

    def test_save_apply_with_safety(self, universe_yaml, monkeypatch):
        """--apply without --allow-removal: only adds, no removes."""
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        # SP500 = AAPL,MSFT,NEW (GOOGL+ARKK get "removed", but safety preserves)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["AAPL", "MSFT", "NEW"],
        ):
            c = UniverseSyncCollector()
            data = c.collect(market="us", dry_run=False, allow_removal=False)
            c.save(data)

        with universe_yaml.open() as f:
            after = yaml.safe_load(f)
        # NEW added
        assert "NEW" in after["us_sp500_extended"]["tickers"]
        # GOOGL + ARKK PRESERVED (safety)
        assert "GOOGL" in after["us_sp500_extended"]["tickers"]
        assert "ARKK" in after["us_sp500_extended"]["tickers"]

    def test_save_apply_with_allow_removal(self, universe_yaml, monkeypatch):
        """--apply with --allow-removal: actually removes."""
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["AAPL", "MSFT", "NEW"],
        ):
            c = UniverseSyncCollector()
            data = c.collect(market="us", dry_run=False, allow_removal=True)
            c.save(data)

        with universe_yaml.open() as f:
            after = yaml.safe_load(f)
        # NEW added, GOOGL+ARKK actually removed
        assert "NEW" in after["us_sp500_extended"]["tickers"]
        assert "GOOGL" not in after["us_sp500_extended"]["tickers"]
        assert "ARKK" not in after["us_sp500_extended"]["tickers"]

    def test_save_apply_us_core_preserved(self, universe_yaml, monkeypatch):
        """us_core (hand-curated mega caps) MUST never change, even with --allow-removal."""
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", universe_yaml)
        # SP500 doesn't include AAPL/MSFT (us_core) or anything else from current
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
            return_value=["NEW"],
        ):
            c = UniverseSyncCollector()
            data = c.collect(market="us", dry_run=False, allow_removal=True)
            c.save(data)

        with universe_yaml.open() as f:
            after = yaml.safe_load(f)
        # us_core untouched
        assert set(after["us_core"]["tickers"]) == {"AAPL", "MSFT"}


# ───────────────────────────────────────────────
# Logging / UX — verify no traceback explosion
# ───────────────────────────────────────────────


class TestExtraCoverage:
    """추가 분기 커버리지 — US fetch 실패, KR success path, KR apply."""

    def test_us_fetch_raises_when_us_only(self, monkeypatch, tmp_path):
        path = tmp_path / "u.yaml"
        path.write_text(
            yaml.safe_dump(
                {"us_core": {"tickers": []}, "us_sp500_extended": {"tickers": []}, "kr_kospi200": {"tickers": []}}
            )
        )
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", path)
        with patch(
            "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia", side_effect=RuntimeError("Wikipedia down")
        ):
            c = UniverseSyncCollector()
            with pytest.raises(RuntimeError, match="Wikipedia down"):
                c.collect(market="us", dry_run=True)

    def test_us_fetch_warning_when_full_sync(self, monkeypatch, tmp_path):
        """Full sync: US 실패해도 raise 안 하고 KR 계속 시도."""
        path = tmp_path / "u.yaml"
        path.write_text(
            yaml.safe_dump(
                {"us_core": {"tickers": ["AAPL"]}, "us_sp500_extended": {"tickers": []}, "kr_kospi200": {"tickers": []}}
            )
        )
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", path)
        with (
            patch(
                "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia", side_effect=RuntimeError("Wikipedia down")
            ),
            patch("nuri.collectors.universe_sync._fetch_kospi200", side_effect=FileNotFoundError("FDR missing")),
        ):
            c = UniverseSyncCollector()
            # 전체 sync — US 실패해도 raise 안 함
            result = c.collect(dry_run=True)
        # current 그대로 → diff 0
        assert result["us_added"] == []

    def test_kr_runtime_error_never_raises(self, monkeypatch, tmp_path):
        """market='kr' + RuntimeError → NO raise (regression for retry noise bug).

        이전 behavior: raise → BaseCollector retry 3회 → 같은 traceback 3개.
        새 behavior: 항상 _kr_skipped 플래그 + warning 1줄. exit clean.
        """
        path = tmp_path / "u.yaml"
        path.write_text(
            yaml.safe_dump(
                {"us_core": {"tickers": []}, "us_sp500_extended": {"tickers": []}, "kr_kospi200": {"tickers": []}}
            )
        )
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", path)
        with patch(
            "nuri.collectors.universe_sync._fetch_kospi200", side_effect=RuntimeError("KRX returned malformed data")
        ):
            c = UniverseSyncCollector()
            # raise 안 함
            result = c.collect(market="kr", dry_run=True)
        assert c._kr_skipped is True
        assert result["kr_added"] == []  # current preserved

    def test_kr_full_path_save_apply(self, monkeypatch, tmp_path, capsys):
        """KR fetch 성공 + apply: kr_kospi200 갱신 검증."""
        path = tmp_path / "u.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": ["AAPL"]},
                    "us_sp500_extended": {"tickers": []},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", path)
        with (
            patch("nuri.collectors.universe_sync._fetch_sp500_from_wikipedia", return_value=["AAPL"]),
            patch(
                "nuri.collectors.universe_sync._fetch_kospi200", return_value=["005930.KS", "000660.KS"]
            ),  # KOSPI 200 + 1
        ):
            c = UniverseSyncCollector()
            data = c.collect(dry_run=False, allow_removal=False)
            c.save(data)

        with path.open() as f:
            after = yaml.safe_load(f)
        assert "000660.KS" in after["kr_kospi200"]["tickers"]
        assert "005930.KS" in after["kr_kospi200"]["tickers"]


class TestRunNoRetry:
    """Override run() should NOT retry on permanent failures (regression for noise bug)."""

    def test_run_kr_only_with_runtime_error_no_retry_explosion(self, monkeypatch, tmp_path, caplog):
        """Real-world bug: FDR 설치된 상태에서 KRX 일시 장애 시 BaseCollector retry로
        같은 traceback 3개 발생. Override run()으로 1회만 시도되어야 함."""
        import logging

        path = tmp_path / "u.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "us_core": {"tickers": []},
                    "us_sp500_extended": {"tickers": []},
                    "kr_kospi200": {"tickers": ["005930.KS"]},
                }
            )
        )
        monkeypatch.setattr("nuri.collectors.universe_sync.UNIVERSE_PATH", path)

        call_count = {"n": 0}

        def failing_fetch():
            call_count["n"] += 1
            raise RuntimeError("KRX upstream 500")

        with patch("nuri.collectors.universe_sync._fetch_kospi200", side_effect=failing_fetch):
            c = UniverseSyncCollector()
            with caplog.at_level(logging.WARNING):
                # market='kr' 이지만 retry 없이 1회만 호출되어야
                count = c.run(market="kr", dry_run=True)

        # Critical assertion: fetch 호출 1회만 (retry 없음)
        assert call_count["n"] == 1, f"Expected 1 fetch call, got {call_count['n']} (retry should be disabled)"
        # Counts as 0 changes since KR fetch failed
        assert count == 0
        assert c._kr_skipped is True
        # No retry warnings
        retry_warnings = [r for r in caplog.records if "재시도" in r.message]
        assert retry_warnings == [], f"Expected no retry warnings, got {[r.message for r in retry_warnings]}"


class TestNoNoisyOutput:
    def test_kr_skip_emits_one_warning_only(self, caplog):
        """Regression test for issue: pykrx fallback used to emit hundreds of traceback lines."""
        import logging

        with patch(
            "nuri.collectors.universe_sync._fetch_kospi200",
            side_effect=FileNotFoundError("FDR missing"),
        ):
            c = UniverseSyncCollector()
            # collect with full sync (US + KR), KR fails
            with patch(
                "nuri.collectors.universe_sync._fetch_sp500_from_wikipedia",
                return_value=["AAPL"],
            ):
                with caplog.at_level(logging.WARNING):
                    c.collect(dry_run=True)

        # Only one KR warning should appear (no traceback explosion)
        kr_warnings = [r for r in caplog.records if "KR sync" in r.message or "KOSPI" in r.message]
        assert len(kr_warnings) <= 2  # one info ("fetching") + one warning ("skipped")


class TestPhase5NegativeGuardrails:
    """P1 D — Phase 5 QA negative cases (docs/TODO.md Tier 2 #272 완결).

    3 graceful-degradation contracts that must hold for fresh-clone /
    corrupted-setup 상황. Codex-reviewed minimal set — API key 테스트는
    collectors 가 keyless (wallstreet/estimates/stock* 모두 yfinance/FDR
    기반) 이라서 의미 없어 제외.
    """

    def test_missing_universe_yaml_raises_actionable_error(self, tmp_path, monkeypatch):
        """universe.yaml 이 없으면 FileNotFoundError 에 복구 명령 포함."""
        import nuri.collectors.universe_sync as mod

        # UNIVERSE_PATH 를 tmp_path 에 없는 경로로 치환
        missing_path = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr(mod, "UNIVERSE_PATH", missing_path)

        with pytest.raises(FileNotFoundError) as exc:
            mod._load_universe()

        msg = str(exc.value)
        assert "없습니다" in msg, "에러 메시지는 한국어로 상태 설명"
        assert "make setup" in msg or "git checkout" in msg, "복구 명령 포함"

    def test_malformed_universe_yaml_raises_actionable_error(self, tmp_path, monkeypatch):
        """universe.yaml YAML 문법 오류면 ValueError 에 원인 + 해결 명령."""
        import nuri.collectors.universe_sync as mod

        bad_yaml = tmp_path / "universe.yaml"
        bad_yaml.write_text("us:\n  - AAPL\n  bad_indent\nkr: [005930.KS]\n  extra:\n")
        monkeypatch.setattr(mod, "UNIVERSE_PATH", bad_yaml)

        with pytest.raises(ValueError) as exc:
            mod._load_universe()

        msg = str(exc.value)
        assert "파싱 실패" in msg
        assert "git checkout" in msg, "복구 명령 포함"

    def test_empty_universe_yaml_raises_actionable_error(self, tmp_path, monkeypatch):
        """universe.yaml 이 비어있으면 ValueError — 최소 섹션 필요 안내."""
        import nuri.collectors.universe_sync as mod

        empty = tmp_path / "universe.yaml"
        empty.write_text("")
        monkeypatch.setattr(mod, "UNIVERSE_PATH", empty)

        with pytest.raises(ValueError) as exc:
            mod._load_universe()

        assert "비어있음" in str(exc.value)
