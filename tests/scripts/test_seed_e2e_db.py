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
