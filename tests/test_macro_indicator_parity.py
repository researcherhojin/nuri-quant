"""매크로 지표의 **소비/생산 짝**이 맞는지 잠근다 (#1025).

`classifier._detect_stagflation` 은 `macro.gdp_growth` 를 읽는다. 그런데 그 지표를
**쓰는 수집기가 하나도 없었다.** 함수는 매번 `if not gdp_rows: return False` 로 조기
탈출했고, 그래서 스태그플레이션 판정은 코드가 존재한 내내 **한 번도 도달하지 못했다.**

이게 조용했던 이유가 이 테스트의 존재 이유다:

- 단위 테스트는 통과한다. `tests/quant/test_regime_classifier.py::TestStagflation` 이
  `cpi_yoy=5.5` · `gdp_growth=0.5` 를 **직접 seed** 하므로 로직은 초록이다. 로직이
  맞다는 것과 입력이 도착한다는 것은 별개인데, 테스트는 앞엣것만 봤다.
- 런타임도 조용하다. 조기 탈출이 `logger.debug` 한 줄이라 아무 신호가 없다.
- 반환값도 조용하다. 데이터가 없어서 `False` 인 것과 재보니 아니어서 `False` 인 것이
  호출자 눈에 똑같다.

그래서 여기서 보는 것은 로직이 아니라 **배선**이다: 소비되는 지표는 전부 생산자가 있어야
한다. 짝이 없으면 그 소비처는 도달 불가 코드다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 매크로 지표를 이름으로 읽는 소비처.
CONSUMERS = [
    REPO_ROOT / "nuri" / "quant" / "regime" / "classifier.py",
    REPO_ROOT / "nuri" / "quant" / "regime" / "macro_score.py",
]

COLLECTORS_DIR = REPO_ROOT / "nuri" / "collectors"

# 소비 형태 3종: SQL 리터럴 · `_get_latest_macro(...)` · `_get_macro_trend(...)`
_CONSUME_PATTERNS = (
    r"indicator\s*=\s*'([a-z0-9_]+)'",
    r"_get_latest_macro\(\s*\"([a-z0-9_]+)\"",
    r"_get_macro_trend\(\s*\"([a-z0-9_]+)\"",
)

# 생산 형태: 수집기가 dict 로 쓰는 `"indicator": "..."`
_PRODUCE_PATTERN = r'"indicator":\s*"([a-z0-9_]+)"'


def _consumed() -> set[str]:
    found: set[str] = set()
    for path in CONSUMERS:
        text = path.read_text()
        for pat in _CONSUME_PATTERNS:
            found.update(re.findall(pat, text))
    return found


def _produced() -> set[str]:
    from nuri.collectors.macro import FRED_SERIES, YFINANCE_SYMBOLS

    found = set(FRED_SERIES) | set(YFINANCE_SYMBOLS)
    # macro.py 밖의 수집기들 (cboe → put_call_ratio, fear_greed, coingecko 등)
    for path in COLLECTORS_DIR.glob("*.py"):
        found.update(re.findall(_PRODUCE_PATTERN, path.read_text()))
    return found


class TestEveryConsumedIndicatorHasAProducer:
    def test_no_orphan_indicator(self):
        """Gotcha-Test Pair: `FRED_SERIES` 에서 `gdp_growth` 를 빼면 FAIL.

        그 상태가 정확히 #1025 이전이며, `_detect_stagflation` 이 도달 불가였다.
        """
        orphans = _consumed() - _produced()
        assert not orphans, (
            f"읽히는데 아무 수집기도 쓰지 않는 지표: {sorted(orphans)}\n"
            "해당 소비처는 데이터가 없어 조기 탈출하는 도달 불가 코드다. "
            "수집기에 배선하거나 소비처를 지울 것."
        )

    def test_consumption_scan_actually_finds_known_reads(self):
        """카나리아 — 소비 추출이 깨지면 위 테스트가 공허하게 통과한다."""
        consumed = _consumed()
        for known in ("cpi_yoy", "gdp_growth", "vix"):
            assert known in consumed, (
                f"소비처 스캔이 `{known}` 을 못 찾았다 — 읽는 형태가 바뀌었으면 _CONSUME_PATTERNS 도 같이 고칠 것"
            )

    def test_production_scan_actually_finds_known_writes(self):
        """카나리아 — 생산 추출이 비면 모든 지표가 고아로 잡혀 오탐만 난다."""
        produced = _produced()
        for known in ("cpi_yoy", "put_call_ratio", "fear_greed"):
            assert known in produced, f"수집기 스캔이 `{known}` 을 못 찾았다"
