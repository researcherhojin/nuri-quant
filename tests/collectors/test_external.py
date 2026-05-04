"""Per-collector tests for external.

Split from tests/test_collectors_all.py for module-level isolation.
"""


class TestExternalSave:
    def test_save_external(self, db_path):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", 4.5) is True

    def test_save_tipranks(self, db_path):
        from nuri.collectors.external import save_tipranks

        save_tipranks("AAPL", "Strong Buy", 230.0, 30)

    def test_save_superinvestor(self, db_path):
        from nuri.collectors.external import save_superinvestor

        save_superinvestor("AAPL", 5, "increasing")

    def test_get_external(self, db_path):
        from nuri.collectors.external import get_external, save_external

        save_external("test_src", "AAPL", "rating", "Buy", 4.0)
        result = get_external("AAPL")
        assert isinstance(result, list)

    def test_get_external_summary(self, db_path):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("test", "AAPL", "score", "high", 9.0)
        summary = get_external_summary()
        assert isinstance(summary, dict)

    def test_print_summary(self, db_path, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("test", "AAPL", "score", "high", 9.0)
        print_summary()
        output = capsys.readouterr().out
        assert len(output) > 0


# ##############################################################################
# Source: test_coverage_round4.py
# ##############################################################################


class TestExternalCollectorSaveAndGet:
    def test_save_external_success(self, rich_db):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=rich_db) is True

    def test_save_external_unknown_source(self, rich_db):
        from nuri.collectors.external import save_external

        assert save_external("unknown_source", "AAPL", "test", "val", db_path=rich_db) is False

    def test_save_tipranks(self, rich_db):
        from nuri.collectors.external import get_external, save_tipranks

        save_tipranks("NVDA", "Strong Buy", 273.61, 38, upside_pct=63.0, db_path=rich_db)
        data = get_external("NVDA", source="tipranks", db_path=rich_db)
        assert len(data) >= 3

    def test_save_superinvestor(self, rich_db):
        from nuri.collectors.external import get_external, save_superinvestor

        save_superinvestor("AAPL", 14, "buying", details="Buffett +5%", db_path=rich_db)
        data = get_external("AAPL", source="dataroma", db_path=rich_db)
        assert len(data) >= 2

    def test_get_external_no_source(self, rich_db):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        save_external("dataroma", "AAPL", "count", "10", db_path=rich_db)
        data = get_external("AAPL", db_path=rich_db)
        sources = {d["source"] for d in data}
        assert "tipranks" in sources

    def test_get_external_empty(self, rich_db):
        from nuri.collectors.external import get_external

        assert get_external("ZZZZ", db_path=rich_db) == []

    def test_get_external_summary(self, rich_db):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] >= 1

    def test_get_external_summary_empty(self, rich_db):
        from nuri.collectors.external import get_external_summary

        summary = get_external_summary(db_path=rich_db)
        assert summary["total_records"] == 0

    def test_save_external_with_numeric(self, rich_db):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "TSLA", "target_price", "400.0", numeric_value=400.0, db_path=rich_db)
        data = get_external("TSLA", source="tipranks", db_path=rich_db)
        assert data[0]["numeric_value"] == 400.0

    def test_print_summary(self, rich_db, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        print_summary(db_path=rich_db)
        out = capsys.readouterr().out
        assert "tipranks" in out.lower() or "TipRanks" in out

    def test_print_ticker_external_empty(self, rich_db, capsys):
        from nuri.collectors.external import print_ticker_external

        print_ticker_external("ZZZZ", db_path=rich_db)
        out = capsys.readouterr().out
        assert "없음" in out

    def test_print_ticker_external_with_data(self, rich_db, capsys):
        from nuri.collectors.external import print_ticker_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=rich_db)
        print_ticker_external("AAPL", db_path=rich_db)
        out = capsys.readouterr().out
        assert "AAPL" in out


class TestExternalCollectorMoreScenarios:
    def test_save_external_success(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("tipranks", "AAPL", "consensus", "Strong Buy", db_path=db_with_portfolio) is True

    def test_save_external_unknown_source(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert save_external("unknown_source", "AAPL", "test", "val", db_path=db_with_portfolio) is False

    def test_save_external_with_date(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert (
            save_external("tipranks", "AAPL", "consensus", "Buy", target_date="2025-01-15", db_path=db_with_portfolio)
            is True
        )

    def test_save_external_with_numeric(self, db_with_portfolio):
        from nuri.collectors.external import save_external

        assert (
            save_external("tipranks", "AAPL", "target_price", "250.0", numeric_value=250.0, db_path=db_with_portfolio)
            is True
        )

    def test_save_tipranks(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_tipranks

        save_tipranks("AAPL", "Strong Buy", 250.0, 30, upside_pct=15.5, db_path=db_with_portfolio)
        data = get_external("AAPL", source="tipranks", db_path=db_with_portfolio)
        assert len(data) >= 3

    def test_save_superinvestor(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_superinvestor

        save_superinvestor("AAPL", 14, "buying", details="Buffett +10%", db_path=db_with_portfolio)
        data = get_external("AAPL", source="dataroma", db_path=db_with_portfolio)
        assert len(data) >= 2

    def test_get_external_all_sources(self, db_with_portfolio):
        from nuri.collectors.external import get_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        save_external("dataroma", "AAPL", "count", "5", db_path=db_with_portfolio)
        assert len(get_external("AAPL", db_path=db_with_portfolio)) >= 2

    def test_get_external_summary(self, db_with_portfolio):
        from nuri.collectors.external import get_external_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        assert get_external_summary(db_path=db_with_portfolio)["total_records"] >= 1

    def test_print_ticker_external_no_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external

        print_ticker_external("ZZZZ", db_path=db_with_portfolio)
        assert "외부 데이터 없음" in capsys.readouterr().out

    def test_print_ticker_external_with_data(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_ticker_external, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        print_ticker_external("AAPL", db_path=db_with_portfolio)
        assert "AAPL" in capsys.readouterr().out

    def test_print_summary(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary, save_external

        save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio)
        print_summary(db_path=db_with_portfolio)
        assert "외부 데이터 요약" in capsys.readouterr().out

    def test_print_summary_empty(self, db_with_portfolio, capsys):
        from nuri.collectors.external import print_summary

        print_summary(db_path=db_with_portfolio)
        assert "0건" in capsys.readouterr().out


class TestExternalEdgeCases:
    def test_save_external_db_error(self, monkeypatch, db_with_portfolio):
        from contextlib import contextmanager

        from nuri.collectors.external import save_external

        @contextmanager
        def bad_db(path=None):
            raise Exception("DB write error")
            yield  # pragma: no cover

        monkeypatch.setattr("nuri.collectors.external.get_db", bad_db)
        assert save_external("tipranks", "AAPL", "consensus", "Buy", db_path=db_with_portfolio) is False


class TestExternalCliRunpy:
    """`__main__` block else-branch (line 218) — runpy invocation with non-empty summary."""

    def test_main_default_branch_with_records_invokes_print_summary(self, monkeypatch):
        """summary["total_records"]>0 → else 분기 print_summary 호출 (line 218).

        runpy 가 module source 를 재실행해 monkeypatch 가 무효화되는 문제를 피하기 위해
        main(argv) 추출 후 직접 호출. (PR #595/#605/#608 패턴)
        """
        from nuri.collectors import external as ext_mod

        called: list[bool] = []

        monkeypatch.setattr(
            ext_mod,
            "get_external_summary",
            lambda *a, **kw: {"total_records": 5, "sources": []},
        )
        monkeypatch.setattr(ext_mod, "print_summary", lambda *a, **kw: called.append(True))

        rc = ext_mod.main([])
        assert rc == 0
        assert called == [True]
