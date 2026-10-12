"""API 테스트의 pykrx 이름 스텁이 그 창 밖의 import 로 새지 않는다 (#1777 CI).

`tests/api/conftest.py::_mock_pykrx_names` 는 모든 API 테스트에 autouse 로 걸린다. 예전엔
`sys.modules["pykrx"]` 를 가짜로 바꿔서, 그 사이에 처음 import 된 모듈이 가짜를 붙잡았다 —
`nuri.collectors.stock_kr` 가 그렇게 묶이면 뒤의 `test_stock_kr.py` 가 줄줄이 깨진다.
"""

from __future__ import annotations

import importlib
import sys

import pytest

import nuri.collectors as collectors_pkg

_STOCK_KR = "nuri.collectors.stock_kr"


def test_a_module_first_imported_during_an_api_test_binds_the_real_pykrx(monkeypatch):
    # 창 안에서의 "첫 import" 를 재현한다. 원래 모듈·패키지 속성은 teardown 에 되돌아온다 —
    # 되돌릴 원본이 있도록 먼저 import 해 둔다. worker 의 첫 import 를 이 테스트가 맡으면 원본이
    # 없어서, teardown 이 패키지 속성만 지우고 `sys.modules` 항목은 남겼다 (#1826).
    original = importlib.import_module(_STOCK_KR)
    monkeypatch.delitem(sys.modules, _STOCK_KR)
    monkeypatch.setattr(collectors_pkg, "stock_kr", original)

    stock_kr = importlib.import_module(_STOCK_KR)

    assert hasattr(stock_kr.krx, "get_market_ohlcv"), "pykrx 스텁이 새로 import 된 모듈에 새었다"


def test_the_first_import_case_leaves_the_package_and_sys_modules_in_agreement():
    """위 테스트가 worker 의 첫 `stock_kr` import 를 맡아도 teardown 뒤 두 경로가 같은 모듈을 가리킨다.

    어긋나면 문자열 타깃 `monkeypatch.setattr("nuri.collectors.stock_kr.…")` 가 전부 깨진다 —
    pytest 는 패키지 `getattr` 로 풀고, 실패하면 부르는 `__import__` 는 캐시 적중이라 속성을 다시
    붙이지 않는다. #1817 CI 에서 `test_stock_kr.py` 가 그렇게 깨졌다 (#1826).
    """
    with pytest.MonkeyPatch.context() as outer:
        # 아직 import 되지 않은 worker 를 만든다 — outer 가 원래대로 되돌린다.
        outer.delitem(sys.modules, _STOCK_KR, raising=False)
        outer.delattr(collectors_pkg, "stock_kr", raising=False)

        with pytest.MonkeyPatch.context() as inner:
            test_a_module_first_imported_during_an_api_test_binds_the_real_pykrx(inner)

        assert sys.modules[_STOCK_KR] is getattr(collectors_pkg, "stock_kr", None)


def test_the_name_lookup_is_still_stubbed():
    """스텁이 빠지면 맵에 없는 종목이 live KRX 를 탄다 — 여기서는 스텁이 빈 이름을 돌려준다."""
    import pykrx.stock

    assert pykrx.stock.get_market_ticker_name("005930") == "삼성전자"
    assert pykrx.stock.get_market_ticker_name("999999") == ""
