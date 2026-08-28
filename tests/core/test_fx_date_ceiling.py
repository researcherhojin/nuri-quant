"""미래 날짜 환율 행이 "현재 환율" 자리를 차지하지 못하게 잠근다 (#1278).

## 무엇이 잘못됐었나

"최신 환율" 을 `ORDER BY date DESC LIMIT 1` 로 읽는 곳이 **9군데** 있었고 전부 날짜
상한이 없었다. `macro` 에 미래 날짜 행이 하나라도 들어오면 그게 영구히 최신이 된다.

2026-08-29 실측 — dev DB 에 `2027-09-14` 행이 섞여 `get_exchange_rate()` 가 **1417.4**
를 반환했다. 정상 최신은 `2026-08-21 1385.01`, 프로덕션은 `1383.35`. 오차 +2.46% 가
모든 KRW 환산 총액·계좌 비중·현금 합산에 곱해진다. 그리고 `2027-09-14` 행은 **1년 넘게**
최신 자리를 지킨다 — 시간이 지나도 스스로 낫지 않는다.

곁가지로 노후 경고까지 죽어 있었다: `age_days = (now - latest).days` 가 미래 날짜에서
**음수**라 `age_days > 7` 이 영원히 거짓이었다. 이중으로 눈이 멀어 있었다.

## 왜 여러 소비자를 각각 잠그나

`tests/CLAUDE.md` Time-bomb 2차 발생의 교훈이다 — *"규칙 하나에 잠금이 한 경로만
걸려 있으면 나머지 경로는 무방비다."* 실제로 이 결함은 9곳에 흩어져 있었고, 이슈는
그중 2곳만 지목했다.
"""

import pandas as pd
import pytest

from nuri.core.db import get_db, init_db
from nuri.core.fx import latest_usd_krw, latest_usd_krw_value
from nuri.core.timezone import today_kst

TODAY = today_kst()
FUTURE = "2099-01-01"
PAST = "2020-01-01"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import nuri.core.db as db_mod

    path = tmp_path / "fx.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    return path


def _seed(db_path, rows):
    with get_db(db_path) as conn:
        conn.executemany(
            "INSERT INTO macro (indicator, date, value, source) VALUES ('usd_krw', ?, ?, 'test')",
            rows,
        )


class TestLatestUsdKrwHonoursTheCeiling:
    def test_future_row_never_becomes_the_rate(self, db):
        """결함 그 자체. Mutation lock: `AND date <= ?` 를 지우면 FAIL."""
        _seed(db, [(TODAY, 1380.0), (FUTURE, 9999.0)])
        assert latest_usd_krw_value() == pytest.approx(1380.0), "미래 행을 현재 환율로 썼다"

    def test_latest_below_ceiling_wins(self, db):
        """대조군 — 상한 안에서는 여전히 **최신**이어야 한다 (오래된 걸 집으면 안 된다)."""
        _seed(db, [(PAST, 1100.0), (TODAY, 1380.0)])
        got = latest_usd_krw()
        assert got is not None
        assert got[0] == pytest.approx(1380.0) and got[1] == TODAY

    def test_only_future_rows_means_no_rate(self, db):
        """미래 행밖에 없으면 **숫자를 지어내지 않는다** — 부재는 None."""
        _seed(db, [(FUTURE, 9999.0)])
        assert latest_usd_krw_value() is None

    def test_empty_table_returns_none(self, db):
        assert latest_usd_krw_value() is None

    def test_future_rows_are_logged_not_silently_dropped(self, db, caplog):
        """조용히 버리면 수집기 결함이 영영 안 보인다.

        Mutation lock: `_warn_if_future_rows` 호출을 지우면 FAIL.
        """
        import logging

        _seed(db, [(TODAY, 1380.0), (FUTURE, 9999.0)])
        with caplog.at_level(logging.WARNING, logger="nuri.core.fx"):
            latest_usd_krw_value()
        assert caplog.records, "미래 행을 발견하고도 경고하지 않았다"
        assert FUTURE in caplog.text, "어느 날짜가 문제인지 말하지 않는다"

    def test_clean_table_logs_nothing(self, db, caplog):
        """대조군 — 정상일 때 경고가 뜨면 그 경고는 곧 무시된다 (false-red)."""
        import logging

        _seed(db, [(TODAY, 1380.0)])
        with caplog.at_level(logging.WARNING, logger="nuri.core.fx"):
            latest_usd_krw_value()
        assert not caplog.records, f"정상인데 경고했다: {caplog.text}"

    def test_db_error_in_diagnostic_is_swallowed(self, db, monkeypatch):
        """진단이 본 작업을 게이트하면 안 된다 (#894) — 미래행 카운트가 죽어도 환율은 나온다."""
        import nuri.core.fx as fx
        from nuri.core.db import OperationalError

        _seed(db, [(TODAY, 1380.0)])
        real = fx.query
        calls = {"n": 0}

        def _flaky(sql, *a, **k):
            calls["n"] += 1
            if "COUNT(*)" in sql:
                raise OperationalError("no such table")
            return real(sql, *a, **k)

        monkeypatch.setattr(fx, "query", _flaky)
        assert latest_usd_krw_value() == pytest.approx(1380.0), "진단 실패가 환율을 막았다"
        assert calls["n"] >= 2, "진단 쿼리가 아예 안 돌았다 — 축이 성립 안 함"


class TestEveryConsumerIsCovered:
    """소비자별 잠금 — 한 경로만 잠그면 나머지는 무방비다 (tests/CLAUDE.md)."""

    def test_get_exchange_rate_ignores_future_rows(self, db):
        from nuri.analysis.portfolio import get_exchange_rate

        _seed(db, [(TODAY, 1380.0), (FUTURE, 9999.0)])
        assert get_exchange_rate() == pytest.approx(1380.0)

    def test_stale_warning_works_again(self, db, caplog):
        """미래 행이 있으면 나이가 **음수**가 되어 7일 경고까지 죽었다 — 곁가지 결함."""
        import logging

        old = "2020-01-01"
        _seed(db, [(old, 1100.0), (FUTURE, 9999.0)])
        with caplog.at_level(logging.WARNING, logger="nuri.analysis.portfolio"):
            from nuri.analysis.portfolio import get_exchange_rate

            assert get_exchange_rate() == pytest.approx(1100.0)
        assert "경과" in caplog.text, "노후 환율인데 경고가 없다"

    def test_korean_market_fx_rate_ignores_future_rows(self, db):
        from nuri.trading.agents.korean_market import KoreanMarketAgent

        _seed(db, [(TODAY, 1380.0), (FUTURE, 9999.0)])
        agent = KoreanMarketAgent()
        assert agent._get_fx_rate() == pytest.approx(1380.0)


#: 날짜 상한을 **일부러 두지 않는** 조회. 사유를 반드시 함께 적는다.
#: 양방향 검사라 낡은 항목(이제 상한이 생긴 파일)도 FAIL 한다 — allowlist 가 조용히
#: 커지는 걸 막는 것이 이 목록의 존재 이유다 (`test_cross_stage_imports.py` 와 같은 규율).
CEILING_EXEMPT: dict[str, str] = {
    "quant/validation/strategy_walkforward.py": (
        "데이터셋을 평가하는 백테스트 입력. 벽시계로 자르면 (1) 실행 날짜에 따라 결과가 "
        "달라져 재현 불가, (2) 가격 패널에는 상한이 없어 FX 만 잘리면 "
        "`reindex(prices.index).fillna(0.0)` 가 오늘 이후 FX 수익률을 전부 0 으로 채워 "
        "KRW 결과가 조용히 왜곡된다. 게다가 그 reindex 가 가격 범위 밖 FX 날짜를 "
        "어차피 버리므로 상한은 이득도 없다 (codex 리뷰 P2)."
    ),
}


class TestBacktestFxIsBoundedByTheDatasetNotTheClock:
    """백테스트 FX 는 **벽시계가 아니라 데이터셋 지평**을 따른다 (codex 리뷰 P2).

    초안이 여기에도 상한을 넣었다가 되돌렸다. 두 가지가 깨졌기 때문이다:
      1. 같은 DB·같은 코드가 **실행 날짜에 따라** 다른 결과를 낸다 (재현 불가).
      2. `_build_us_panel` 은 가격에 상한이 없어서, FX 만 자르면
         `fx_ret … .reindex(prices.index).fillna(0.0)` 가 오늘 이후 FX 수익률을
         **전부 0(환율 불변)** 으로 채운다 — 조용한 왜곡이라 더 나쁘다.

    "미래 행" 방어는 여기 필요 없다: 위 reindex 가 가격 인덱스 밖 FX 날짜를 버린다.
    """

    def test_series_includes_dates_beyond_today(self, db):
        """Mutation lock: `_load_fx_series` 에 `AND date <= ?` 를 넣으면 FAIL."""
        from nuri.quant.validation.strategy_walkforward import _load_fx_series

        _seed(db, [(PAST, 1100.0), (TODAY, 1380.0), (FUTURE, 1500.0)])
        series = _load_fx_series(db)
        assert pd.Timestamp(FUTURE) in series.index, (
            "데이터셋 지평을 벽시계로 잘랐다 — 실행 날짜에 따라 백테스트 결과가 달라진다"
        )
        assert len(series) == 3


class TestNoUnboundedLatestReadRemains:
    """구조 스윕 — 새 소비자가 상한 없이 또 읽는 걸 막는다.

    동작 잠금은 **지금 존재하는** 소비자만 덮는다. 이 결함이 9곳으로 번진 방식이
    바로 "새 곳에서 같은 쿼리를 다시 쓰기" 였다.
    """

    @staticmethod
    def _unbounded() -> dict[str, list[int]]:
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "nuri"
        pat = re.compile(r"indicator\s*=\s*['\"]usd_krw['\"]")
        out: dict[str, list[int]] = {}
        for f in sorted(root.rglob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line) and "date <=" not in line and "date >" not in line:
                    out.setdefault(str(f.relative_to(root)), []).append(i)
        return out

    def test_no_unlisted_query_lacks_a_date_ceiling(self):
        found = self._unbounded()
        unlisted = {k: v for k, v in found.items() if k not in CEILING_EXEMPT}
        assert not unlisted, f"상한 없는 usd_krw 조회가 새로 생겼다: {unlisted}"

    def test_every_exemption_is_still_needed(self):
        """양방향 — 상한이 생긴 파일이 목록에 남아 있으면 그 사유는 이미 거짓이다."""
        found = self._unbounded()
        stale = [k for k in CEILING_EXEMPT if k not in found]
        assert not stale, f"낡은 예외 항목(이미 상한이 있음): {stale}"

    def test_every_exemption_states_a_reason(self):
        for path, why in CEILING_EXEMPT.items():
            assert len(why) > 40, f"{path}: 사유가 너무 짧다 — 다음 사람이 판단할 수 없다"

    def test_the_sweep_has_eyes(self):
        """카나리아 — 정규식이 조용히 아무것도 안 잡으면 위 테스트는 영원히 초록이다."""
        import re

        pat = re.compile(r"indicator\s*=\s*['\"]usd_krw['\"]")
        bad = "SELECT value FROM macro WHERE indicator='usd_krw' ORDER BY date DESC LIMIT 1"
        good = "SELECT value FROM macro WHERE indicator='usd_krw' AND date <= ? ORDER BY date DESC"
        assert pat.search(bad) and "date <=" not in bad
        assert pat.search(good) and "date <=" in good
