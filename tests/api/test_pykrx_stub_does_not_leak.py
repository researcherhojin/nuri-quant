"""API 테스트의 pykrx 이름 스텁이 그 창 밖의 import 로 새지 않는다 (#1777 CI).

`tests/api/conftest.py::_mock_pykrx_names` 는 모든 API 테스트에 autouse 로 걸린다. 예전엔
`sys.modules["pykrx"]` 를 가짜로 바꿔서, 그 사이에 처음 import 된 모듈이 가짜를 붙잡았다 —
`nuri.collectors.stock_kr` 가 그렇게 묶이면 뒤의 `test_stock_kr.py` 가 줄줄이 깨진다.
"""

from __future__ import annotations

import importlib
import sys

import nuri.collectors as collectors_pkg


def test_a_module_first_imported_during_an_api_test_binds_the_real_pykrx(monkeypatch):
    # 창 안에서의 "첫 import" 를 재현한다. 원래 모듈·패키지 속성은 teardown 에 되돌아온다.
    monkeypatch.delitem(sys.modules, "nuri.collectors.stock_kr", raising=False)
    monkeypatch.setattr(collectors_pkg, "stock_kr", getattr(collectors_pkg, "stock_kr", None), raising=False)

    stock_kr = importlib.import_module("nuri.collectors.stock_kr")

    assert hasattr(stock_kr.krx, "get_market_ohlcv"), "pykrx 스텁이 새로 import 된 모듈에 새었다"


def test_the_name_lookup_is_still_stubbed():
    """스텁이 빠지면 맵에 없는 종목이 live KRX 를 탄다 — 여기서는 스텁이 빈 이름을 돌려준다."""
    import pykrx.stock

    assert pykrx.stock.get_market_ticker_name("005930") == "삼성전자"
    assert pykrx.stock.get_market_ticker_name("999999") == ""
