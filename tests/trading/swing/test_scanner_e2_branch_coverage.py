"""Bucket E2 branch coverage — swing/scanner.

Targets `__main__` block (273-283) refactored to main(argv).
"""

from __future__ import annotations


class TestScannerMainCLI:
    def test_main_default_market_us(self, monkeypatch, capsys):
        """main([]) — default market=us, top=20."""
        from nuri.trading.swing import scanner as sc

        captured_args = {}

        def fake_scan(market, top_n, extended):
            captured_args.update({"market": market, "top_n": top_n, "extended": extended})
            return []

        monkeypatch.setattr(sc, "scan_market", fake_scan)
        monkeypatch.setattr(sc, "print_scan", lambda r: None)

        rc = sc.main([])
        assert rc == 0
        assert captured_args == {"market": "us", "top_n": 20, "extended": False}

    def test_main_kr_extended_top10(self, monkeypatch):
        """main(['--market', 'kr', '--top', '10', '--extended'])."""
        from nuri.trading.swing import scanner as sc

        captured = {}

        def fake_scan(market, top_n, extended):
            captured.update({"market": market, "top_n": top_n, "extended": extended})
            return []

        monkeypatch.setattr(sc, "scan_market", fake_scan)
        monkeypatch.setattr(sc, "print_scan", lambda r: None)

        rc = sc.main(["--market", "kr", "--top", "10", "--extended"])
        assert rc == 0
        assert captured["market"] == "kr"
        assert captured["top_n"] == 10
        assert captured["extended"] is True
