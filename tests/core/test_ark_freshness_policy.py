"""ARK freshness 정책 — 가장 낡은 펀드를 본다 (#1145).

ARK 는 엔드포인트가 200 인 채로 내용만 얼 수 있다. 수집기 실패율에도, `collector_runs`
에도 안 걸린다. 이 정책이 유일한 감시선이다.
"""

import pytest

from nuri.core.db import get_db, init_db
from nuri.core.freshness import FRESHNESS_POLICIES, check_freshness
from nuri.core.timezone import today_kst


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "ark_freshness.db"
    init_db(path)
    return path


def _seed(db_path, rows):
    with get_db(db_path) as c:
        for fund, date in rows:
            c.execute(
                "INSERT INTO ark (date,ticker,direction,shares,weight,fund) VALUES (?,?,?,?,?,?)",
                (date, "TSLA", "Hold", 1000.0, 1.0, fund),
            )


class TestArkFreshnessPolicy:
    def test_policy_is_registered(self):
        assert "ark" in FRESHNESS_POLICIES

    def test_all_funds_current_passes(self, db_path):
        _seed(db_path, [("ARKK", today_kst()), ("ARKG", today_kst())])
        assert check_freshness("ark", db_path=db_path)["status"] == "PASS"

    def test_one_frozen_fund_fails_even_when_the_others_are_current(self, db_path):
        """**이 테스트가 이 정책의 존재 이유다.**

        production 실측 상태 그대로 — ARKF 만 7.5개월 전, 나머지는 당일.
        """
        _seed(
            db_path,
            [
                ("ARKK", today_kst()),
                ("ARKG", today_kst()),
                ("ARKQ", today_kst()),
                ("ARKW", today_kst()),
                ("ARKF", "2026-01-02"),
            ],
        )
        assert check_freshness("ark", db_path=db_path)["status"] == "FAIL"

    def test_a_naive_max_date_would_have_passed_the_same_data(self, db_path):
        """정책이 `MIN(펀드별 MAX)` 이어야 하는 이유를 데이터로 못 박는다.

        같은 행 집합에 대해 맨 `MAX(date)` 는 오늘을 돌려준다 — 멀쩡한 펀드 4개가
        죽은 펀드 하나를 가린다. 쿼리를 `SELECT MAX(date) FROM ark` 로 되돌리면
        위 테스트가 FAIL 대신 PASS 를 보고 실패한다.
        """
        from nuri.core.db import query

        _seed(
            db_path,
            [("ARKK", today_kst()), ("ARKG", today_kst()), ("ARKF", "2026-01-02")],
        )
        naive = query("SELECT MAX(date) AS d FROM ark", db_path=db_path)[0]["d"]
        staleest = query(FRESHNESS_POLICIES["ark"]["query"], db_path=db_path)[0]
        assert naive == today_kst()  # 초록으로 보였을 값
        assert list(staleest.values())[0] == "2026-01-02"  # 실제로 봐야 하는 값

    def test_policy_fund_list_matches_the_collector(self):
        """정책의 IN 목록과 수집기의 `ARK_HOLDINGS_FILES` 는 같이 움직여야 한다.

        양방향이다 — 수집기에 펀드를 추가하고 정책을 안 고치면 그 펀드는 감시 밖이고,
        정책에만 남은 펀드는 영영 행이 안 생겨 정책을 영구 빨강으로 못박는다.
        """
        import re

        from nuri.collectors.ark import ARK_HOLDINGS_FILES

        in_clause = re.search(r"fund IN \(([^)]*)\)", FRESHNESS_POLICIES["ark"]["query"])
        assert in_clause, "정책 쿼리에서 fund IN 목록을 못 찾음"
        policy_funds = {f.strip().strip("'") for f in in_clause.group(1).split(",")}
        assert policy_funds == set(ARK_HOLDINGS_FILES)

    def test_a_stray_fund_value_cannot_pin_the_policy_red(self, db_path):
        """추적 목록 밖의 fund 값(오타·과거 실험)은 정책을 물들이지 않는다."""
        _seed(db_path, [("ARKK", today_kst()), ("TYPO_FUND", "2020-01-01")])
        assert check_freshness("ark", db_path=db_path)["status"] == "PASS"
