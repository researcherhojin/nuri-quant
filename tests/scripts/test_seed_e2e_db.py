"""seed_e2e_db 의 macro_events 형태가 프로덕션과 일치하는지 잠근다 (#1262).

왜 이 파일이 있나: 이전 seed 는 `macro_events.sentiment` 에 문자열("positive")을 쓰고
카테고리도 `event_score.CATEGORY_WEIGHT` 어휘 밖 값을 썼다. 두 축 다 어긋난 채로
CI `frontend-e2e` 가 3일 넘게 돌았고, 그동안 `/api/rebalance` 는 매 런마다
`TypeError: bad operand type for abs(): 'str'` 로 죽어 200 + error 를 냈다.
스키마가 `sentiment REAL` 이어도 SQLite 동적 타입이라 아무 제약도 안 걸린다.

**"예외 안 남" 만으로는 부족하다** — 타입만 고치면 예외는 사라지지만
`CATEGORY_WEIGHT.get(cat, 0.0)` 이 전부 0 을 줘서 점수가 정확히 0 이 된다.
그래서 behavioral 잠금은 **0 이 아님**까지 단언한다.
"""

import pytest

from nuri.core.db import query
from nuri.quant.regime.event_score import CATEGORY_WEIGHT, compute_event_score
from scripts.dev.seed_e2e_db import seed


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    """seed 는 수 초 걸리므로 모듈당 한 번만 만든다."""
    db = tmp_path_factory.mktemp("seed_e2e") / "e2e.db"
    seed(db)
    return db


class TestSeedMacroEventsShape:
    def test_sentiment_is_numeric(self, seeded_db):
        """스키마가 REAL 이라도 SQLite 는 TEXT 를 받는다 — 값의 타입을 직접 본다."""
        rows = query("SELECT sentiment, typeof(sentiment) AS t FROM macro_events", db_path=seeded_db)
        assert rows, "seed 가 macro_events 를 하나도 안 만들었다"
        assert {r["t"] for r in rows} == {"real"}, f"sentiment 타입: {sorted({r['t'] for r in rows})}"

    def test_categories_are_in_category_weight_vocabulary(self, seeded_db):
        """어휘 밖 카테고리는 가중치 0 이라 점수에 기여하지 못한다."""
        rows = query("SELECT DISTINCT category FROM macro_events", db_path=seeded_db)
        unknown = sorted({r["category"] for r in rows} - set(CATEGORY_WEIGHT))
        assert not unknown, f"CATEGORY_WEIGHT 어휘 밖: {unknown}"

    def test_event_score_is_computable_and_nonzero(self, seeded_db):
        """behavioral 잠금 — 타입-only 수정은 예외는 없애도 점수 0 을 남긴다."""
        result = compute_event_score(db_path=seeded_db)
        assert result.event_count > 0, "신뢰도 floor 에 전부 걸렸거나 lookback 밖이다"
        assert result.score != 0.0, "카테고리가 어휘 밖이면 기여가 전부 0 이 되어 여기서 걸린다"


class TestSeedResolvesKoreanName:
    """CI 에는 `config/kr_ticker_names.json` 이 없다 (gitignored, 생성 단계도 없음).

    그래서 `/explore` 한국어 검색 스펙(`search-result-005930.KS`)이 요구하는 이름은
    seed 의 `portfolio.metadata` = `get_ticker_name_local` 1차에서 와야 한다 (#1255).
    """

    def test_kr_name_resolves_with_no_local_map(self, seeded_db, monkeypatch, tmp_path):
        """맵을 없애도(CI 조건) seed 만으로 이름이 나오고, 나머지는 조용히 None."""
        import nuri.core.db as db_mod
        from nuri.core import ticker_names as tn

        monkeypatch.setattr(db_mod, "DB_PATH", seeded_db)
        monkeypatch.setattr(tn, "_KR_NAMES_PATH", tmp_path / "absent.json")
        tn._load_kr_name_map.cache_clear()
        tn.get_ticker_name_local.cache_clear()
        try:
            assert tn._load_kr_name_map() == {}, "맵 부재 재현 실패 — 이 테스트의 전제가 깨졌다"
            assert tn.get_ticker_name_local("005930.KS") == "삼성전자", (
                "seed 의 portfolio.metadata 가 1차를 만족시키지 못한다 — CI 에서 한국어 검색이 0건이 된다"
            )
            # 맵·보유 어디에도 없는 종목은 네트워크로 내려가지 않고 None 이다.
            assert tn.get_ticker_name_local("000660.KS") is None
        finally:
            tn._load_kr_name_map.cache_clear()
            tn.get_ticker_name_local.cache_clear()


class TestMacroIndicatorsComplete:
    """seed 가 compute_macro_score 의 전 지표를 채우는지 잠근다.

    지표가 빠지면 예외가 아니라 **성분 제외 + 경고**라 e2e 는 초록인 채로
    (1) 89개 테스트 전부가 결측-축소 경로만 밟고 전-지표 경로는 미검증이 되고,
    (2) suite 로그가 지표당 경고 반복으로 덮여 실제 오류가 안 보인다 (2026-09-02
    run #3161 실측: "매크로 지표 누락" 42줄). 침묵 회귀라 동작으로 잠근다.

    **Test:** tests/scripts/test_seed_e2e_db.py::TestMacroIndicatorsComplete::test_macro_score_has_no_missing_components
    """

    def test_macro_score_has_no_missing_components(self, seeded_db):
        from nuri.quant.regime.macro_score import compute_macro_score

        ms = compute_macro_score(db_path=seeded_db)

        # 무경고면 warnings=None (빈 리스트가 아니다) — falsy 검사로 둘 다 받는다.
        assert not ms.warnings, f"seed 가 매크로 지표를 빠뜨렸다 — e2e 가 결측-축소 경로만 검증하게 된다: {ms.warnings}"
        assert ms.coverage == 1.0, f"성분 커버리지 {ms.coverage} < 1.0 — 어떤 지표가 가중치에서 제외됐다"
