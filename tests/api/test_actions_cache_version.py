"""#1279 — 포트폴리오 쓰기가 캐시를 무효화하고, 미상 손익이 0 으로 둔갑하지 않는다.

## 왜 이 테스트가 있나

`/api/actions` 의 5분 TTL 캐시는 write-blind 였다. 포트폴리오를 갱신하는 정상 경로
(`scripts/ops/import_portfolio.py`)는 API 를 거치지 않고 DB 에 직접 쓰므로, API 는
변경 사실을 알 방법이 없었다.

2026-08-29 프로덕션 실측: 보유 갱신 직후 현대차가 **`urgent` · conf 100 ·
"손절선 -20% 돌파"** 로 나왔는데 실제 손익은 -13.1% 로 돌파하지 않았다. -31.9% 는
갱신 **전** 평단으로 계산된 값이었다. 낡은 숫자가 아니라 **거짓 청산 신호**다.

곁가지로 같은 함수가 시세 없는 보유(비상장)의 손익을 `0.0%` 로 냈다 — 원가를
현재가로 대체하면서 생긴 값이라 화면에서는 "보합" 으로 읽혔다.
"""

import time

import pytest

from nuri.api.cache import portfolio_version
from nuri.core.db import get_db, init_db, upsert_portfolio

#: 합성 계좌명. 실제 증권사·계좌 식별자는 공개 레포에 넣지 않는다 (STRATEGY §4.4).
ACCOUNT = "Brokerage Alpha"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """격리 DB + **real-account 필터 고정**.

    `_get_portfolio_map` 은 `_get_real_accounts()`(= gitignored `config/portfolio.yaml`)
    로 행을 거른다. 그대로 두면 이 테스트가 앰비언트 파일에 의존한다 — 로컬에는 파일이
    있어 합성 계좌가 **걸러지고**, CI 에는 없어 필터가 꺼져 통과한다. 로컬 red / CI green
    이라는 반대 방향의 분기다. 필터를 명시적으로 고정해 양쪽에서 같은 것을 잰다.
    """
    import nuri.core.db as db_mod
    from nuri.api.routes import actions

    path = tmp_path / "t.db"
    init_db(path)
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    monkeypatch.setattr(actions, "_get_real_accounts", lambda: {ACCOUNT})
    return path


def _add(db_path, ticker, qty, avg, account=ACCOUNT):
    # mock 이 아니라 실 writer 를 쓴다 — `sector` 를 포함한 필드 집합이 `upsert_portfolio`
    # 의 실제 계약이다 (형태가 어긋난 시드는 버그를 잠근다, #1180 계열).
    upsert_portfolio(
        [
            {
                "account": account,
                "ticker": ticker,
                "quantity": qty,
                "avg_price": avg,
                "currency": "USD",
                "sector": "Test",
            }
        ],
        db_path,
    )


class TestPortfolioVersion:
    """버전 키가 **쓰기를 실제로 감지**하는가."""

    def test_quantity_change_bumps_the_version(self, db):
        """⚠️ `sleep` 이 **없다**. 초안(`MAX(updated_at)` 기반)은 `time.sleep(1.05)` 가
        있어야 통과했는데, 그건 수정이 아니라 결함을 우회한 것이었다 (codex P1).
        내용 해시는 벽시계와 무관하므로 sleep 이 사라진 것 자체가 잠금이다.
        """
        _add(db, "AAA", 10, 100.0)
        before = portfolio_version()
        _add(db, "AAA", 20, 100.0)
        assert portfolio_version() != before, "수량이 바뀌었는데 버전이 그대로다"

    def test_same_second_rewrite_is_detected(self, db):
        """`upsert_portfolio` 는 `datetime('now')` = **초 해상도**로 찍는다.

        1초 안의 연속 갱신(수동 편집 연타, 다계좌 일괄 sync)에서 행 수도 타임스탬프도
        그대로면 타임스탬프 기반 키는 눈이 먼다. 이 테스트는 의도적으로 sleep 없이 돈다.
        """
        _add(db, "AAA", 10, 100.0)
        seen = {portfolio_version()}
        for qty in (11, 12, 13):  # 전부 같은 초 안에서
            _add(db, "AAA", qty, 100.0)
            seen.add(portfolio_version())
        assert len(seen) == 4, f"같은 초 안의 갱신을 놓쳤다 — 서로 다른 버전 {len(seen)}/4"

    def test_offsetting_changes_are_detected(self, db):
        """합계 기반 키가 놓치는 축 — 한 종목 -1, 다른 종목 +1 이면 SUM 이 같다."""
        _add(db, "AAA", 10, 100.0)
        _add(db, "BBB", 10, 100.0)
        before = portfolio_version()
        _add(db, "AAA", 9, 100.0)
        _add(db, "BBB", 11, 100.0)
        assert portfolio_version() != before, "상쇄되는 변경을 놓쳤다"

    def test_version_is_invariant_to_row_order(self, tmp_path, monkeypatch):
        """같은 보유는 **삽입 순서와 무관하게** 같은 버전이어야 한다.

        `SELECT ... FROM portfolio` 는 ORDER BY 가 없으면 rowid(=삽입) 순으로 돌려준다.
        정렬 없이 이어붙이면 같은 내용이 다른 해시를 내고, 캐시가 영구 미스가 되어
        무거운 핸들러가 매 요청 재계산된다 (#1119 stampede).

        Mutation lock: `sorted(...)` 를 지우면 FAIL.
        """
        import nuri.core.db as db_mod

        def _build(order):
            path = tmp_path / f"{'-'.join(order)}.db"
            init_db(path)
            monkeypatch.setattr(db_mod, "DB_PATH", path)
            for t in order:
                _add(path, t, 10, 100.0)
            return portfolio_version()

        assert _build(["AAA", "BBB", "CCC"]) == _build(["CCC", "AAA", "BBB"]), (
            "삽입 순서가 버전을 바꿨다 — 같은 보유인데 캐시가 매번 미스한다"
        )

    def test_avg_price_change_bumps_the_version(self, db):
        """수량이 같아도 평단이 바뀌면 손익이 바뀐다 — #1279 의 실제 사고 형태다."""
        _add(db, "AAA", 10, 587000.0)
        before = portfolio_version()
        _add(db, "AAA", 10, 459857.14)
        assert portfolio_version() != before, "평단 변경을 놓쳤다"

    def test_row_deletion_bumps_the_version(self, db):
        """`MAX(updated_at)` 만 보면 놓치는 축 — 삭제는 남은 행의 타임스탬프를 안 바꾼다."""
        _add(db, "AAA", 10, 100.0)
        _add(db, "BBB", 5, 50.0)
        before = portfolio_version()
        with get_db(db) as conn:
            conn.execute("DELETE FROM portfolio WHERE ticker = 'BBB'")
        after = portfolio_version()
        assert after != before, "행이 지워졌는데 버전이 그대로다 — COUNT 축이 죽었다"

    def test_unchanged_portfolio_keeps_the_version(self, db):
        """대조군 — 안 바뀌면 그대로여야 캐시가 쓸모 있다 (매번 바뀌면 영구 미스)."""
        _add(db, "AAA", 10, 100.0)
        assert portfolio_version() == portfolio_version()

    def test_missing_table_degrades_instead_of_raising(self, tmp_path, monkeypatch):
        """조회 실패는 TTL-only 로 degrade — 진단이 본 작업을 죽이면 안 된다 (#894).

        그리고 **고정 sentinel** 이어야 한다. 매번 다른 값이면 캐시가 영구 미스가 되어
        무거운 핸들러가 매 요청 재계산된다 (#1119 stampede).
        """
        import nuri.core.db as db_mod

        empty = tmp_path / "no-schema.db"
        empty.write_bytes(b"")
        monkeypatch.setattr(db_mod, "DB_PATH", empty)
        assert portfolio_version() == portfolio_version()


class TestActionsCacheHonoursPortfolioWrites:
    """캐시가 포트폴리오 쓰기를 넘겨받는가 — 이 PR 의 핵심."""

    def _seed_cache(self, actions, payload, version):
        actions._actions_cache.update({"data": payload, "timestamp": time.time(), "version": version})

    def test_stale_version_is_not_served(self, db, monkeypatch):
        """Mutation lock: `_fresh` 에서 version 비교를 지우면 FAIL."""
        from nuri.api.routes import actions

        _add(db, "AAA", 10, 100.0)
        stale = {"urgent": [{"ticker": "STALE"}], "check": [], "hold": [], "portfolio": []}
        self._seed_cache(actions, stale, portfolio_version())

        _add(db, "AAA", 20, 100.0)  # 사용자가 보유를 갱신했다 (sleep 불필요 — 내용 해시)

        rebuilt = {"urgent": [], "check": [], "hold": [], "portfolio": []}
        monkeypatch.setattr(actions, "_build_actions", lambda: rebuilt)
        assert actions.get_actions() is rebuilt, "갱신 뒤에도 옛 캐시를 내줬다 — 거짓 신호 창"

    def test_same_version_within_ttl_is_served(self, db, monkeypatch):
        """대조군 — 버전이 같으면 캐시가 살아 있어야 한다. 아니면 5분 TTL 이 무의미."""
        from nuri.api.routes import actions

        _add(db, "AAA", 10, 100.0)
        cached = {"urgent": [{"ticker": "CACHED"}], "check": [], "hold": [], "portfolio": []}
        self._seed_cache(actions, cached, portfolio_version())

        def _boom():
            raise AssertionError("캐시가 유효한데 재계산했다")

        monkeypatch.setattr(actions, "_build_actions", _boom)
        assert actions.get_actions() is cached


class TestUnpricedHoldingIsUnknownNotFlat:
    """시세 없는 보유의 손익은 `0.0` 이 아니라 `None` 이다."""

    def test_pnl_is_none_when_no_market_price(self, db):
        from nuri.api.routes.actions import _get_portfolio_map

        _add(db, "PRIVATECO", 15, 167.74)  # prices 에 행이 없다 (비상장)
        m = _get_portfolio_map()
        h = m["PRIVATECO"]
        assert h["pnl_pct"] is None, "측정 불가를 숫자로 메웠다 — 화면에서 보합으로 읽힌다"
        assert h["current_price"] is None, "원가를 현재가로 내보내면 '정확히 평단' 처럼 보인다"
        # 비중은 남아야 한다 — 보유 자체는 존재하고, 0 으로 지우면 다른 종목이 부풀려진다.
        assert h["position_pct"] > 0

    def test_priced_holding_still_reports_a_number(self, db):
        """대조군 — 시세가 있으면 그대로 숫자여야 한다."""
        from nuri.api.routes.actions import _get_portfolio_map

        _add(db, "AAA", 10, 100.0)
        with get_db(db) as conn:
            conn.execute("INSERT INTO prices (ticker, date, close) VALUES ('AAA', '2026-08-29', 90.0)")
        h = _get_portfolio_map()["AAA"]
        assert h["pnl_pct"] == pytest.approx(-10.0)


class TestWorstPnlAggregationIsNoneSafe:
    """`_is_worse` — None 은 '가장 나쁨' 이 아니라 '모름' 이다."""

    def test_unknown_never_displaces_a_measured_loss(self):
        from nuri.api.routes.actions import _is_worse

        # 미상이 측정값을 밀어내면 그 티커의 손절 판정이 통째로 삼켜진다.
        assert _is_worse(None, -30.0) is False

    def test_measured_replaces_unknown(self):
        from nuri.api.routes.actions import _is_worse

        assert _is_worse(-5.0, None) is True

    def test_both_unknown_changes_nothing(self):
        from nuri.api.routes.actions import _is_worse

        assert _is_worse(None, None) is False

    def test_worse_number_wins(self):
        from nuri.api.routes.actions import _is_worse

        assert _is_worse(-30.0, -5.0) is True
        assert _is_worse(-5.0, -30.0) is False


class TestUnknownPnlNeverClaimsAStopBreach:
    """손익을 모르면 '손절선 돌파' 를 주장할 수 없다."""

    def test_phrase_does_not_fabricate_a_number(self):
        from nuri.api.routes.actions import _pnl_phrase

        assert _pnl_phrase(None) == "손익 미상"
        assert _pnl_phrase(21.8) == "+22%"

    def test_loss_keeps_its_minus_sign(self):
        """codex P2: 리터럴 `+` 를 붙이면 손실이 `+-5%` 로 찍힌다.

        리더 트레일링은 고점 대비 이탈이라 **진입가 아래에서도** 발화할 수 있어
        실제 도달 가능한 경로다.
        """
        from nuri.api.routes.actions import _pnl_phrase

        assert _pnl_phrase(-5.0) == "-5%"
        assert "+-" not in _pnl_phrase(-5.0)
