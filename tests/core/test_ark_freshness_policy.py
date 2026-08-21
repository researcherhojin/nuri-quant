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


ALL_FUNDS = ("ARKK", "ARKW", "ARKG", "ARKQ", "ARKF")


def _seed(db_path, rows):
    """펀드별 **CSV 발행일**을 심는다 — 수집기가 보유 필터와 무관하게 쓰는 그 값이다."""
    with get_db(db_path) as c:
        for fund, date in rows:
            c.execute(
                "INSERT INTO ark_source_dates (fund, csv_date, observed_at) VALUES (?, ?, ?)",
                (fund, date, date),
            )


class TestArkFreshnessPolicy:
    def test_policy_is_registered(self):
        assert "ark" in FRESHNESS_POLICIES

    def test_all_funds_current_passes(self, db_path):
        _seed(db_path, [(f, today_kst()) for f in ALL_FUNDS])
        assert check_freshness("ark", db_path=db_path)["status"] == "PASS"

    def test_one_frozen_fund_fails_even_when_the_others_are_current(self, db_path):
        """**이 테스트가 이 정책의 존재 이유다.**

        production 실측 상태 그대로 — ARKF 만 7.5개월 전, 나머지는 당일.
        """
        _seed(
            db_path,
            [(f, today_kst()) for f in ("ARKK", "ARKG", "ARKQ", "ARKW")] + [("ARKF", "2026-01-02")],
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
            [(f, today_kst()) for f in ("ARKK", "ARKG", "ARKQ", "ARKW")] + [("ARKF", "2026-01-02")],
        )
        naive = query("SELECT MAX(csv_date) AS d FROM ark_source_dates", db_path=db_path)[0]["d"]
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
        """추적 목록 밖의 값(오타·과거 실험)은 정책을 물들이지 않는다."""
        _seed(db_path, [(f, today_kst()) for f in ALL_FUNDS] + [("TYPO_FUND", "2020-01-01")])
        assert check_freshness("ark", db_path=db_path)["status"] == "PASS"

    def test_a_current_fund_we_hold_nothing_from_stays_green(self, db_path):
        """**이 테스트가 #1147 의 본체다.**

        정책이 `ark` 테이블을 보던 시절에는, CSV 를 매일 갱신하는 펀드라도 우리가 그
        보유 종목을 하나도 안 들면 행이 안 생겨 가장 낡은 펀드로 지목됐다 — 소스 감시가
        우리 포트폴리오 구성에 의존했다. production 에서 ARKG 가 실제로 그랬다.

        발행일은 최신인데 `ark` 에는 행이 하나도 없는 상태를 만들고 PASS 를 요구한다.
        """
        from nuri.core.db import query

        _seed(db_path, [(f, today_kst()) for f in ALL_FUNDS])
        assert query("SELECT COUNT(*) AS n FROM ark", db_path=db_path)[0]["n"] == 0
        assert check_freshness("ark", db_path=db_path)["status"] == "PASS"

    def test_the_collector_writes_what_the_policy_reads(self, db_path):
        """기록 쪽과 판정 쪽이 같은 자리를 가리키는지 — 배선이 어긋나면 정책은
        영원히 '데이터 없음' 이고 아무도 눈치채지 못한다."""
        from nuri.collectors.ark import ARKCollector

        dates = {f: today_kst() for f in ALL_FUNDS}
        dates["ARKF"] = "2026-01-02"
        ARKCollector()._record_source_dates(dates, db_path)
        result = check_freshness("ark", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["last_updated"].startswith("2026-01-02")

    def test_a_fund_with_no_row_at_all_fails(self, db_path):
        """**부재는 최신이 아니라 미상이고, 미상은 통과가 아니다** (#1147 codex P1).

        `COUNT(*) = 5` 가 없으면 MIN 이 있는 펀드들만 보고 초록을 준다. 새 펀드를 추가했는데
        수집이 한 번도 성공 못 한 경우가 정확히 그 모양이라, "진짜로 얼었는데 초록" 이
        그대로 남는다.
        """
        _seed(db_path, [(f, today_kst()) for f in ("ARKK", "ARKW", "ARKG", "ARKQ")])  # ARKF 없음
        assert check_freshness("ark", db_path=db_path)["status"] == "FAIL"

    def test_policy_count_matches_the_collector_fund_count(self):
        """쿼리의 `COUNT(*) = N` 이 추적 펀드 수와 어긋나면 검사가 조용히 무의미해진다 —
        N 이 작으면 부재를 못 잡고, 크면 영구 빨강이다."""
        import re

        from nuri.collectors.ark import ARK_HOLDINGS_FILES

        m = re.search(r"COUNT\(\*\) = (\d+)", FRESHNESS_POLICIES["ark"]["query"])
        assert m, "정책 쿼리에서 존재 검사(COUNT)를 못 찾음"
        assert int(m.group(1)) == len(ARK_HOLDINGS_FILES)

    def test_fund_metadata_never_lands_in_external_analysis(self, db_path):
        """`external_analysis.ticker` 는 **실제 종목 심볼 네임스페이스**다 (#1147 codex P2).

        `ARKK`/`ARKF` 는 진짜 ETF 티커라, 펀드명을 거기 쓰면 `get_external()` ·
        `/api/external/{ticker}` · `get_external_summary()` 가 이걸 그 ETF 에 대한 외부
        분석으로 돌려주고, certification 의 `_count_external_for_class()` 는 **SIEGE
        external evidence 로 센다**. 메타데이터가 신호 자리로 새는 형태다.
        """
        from nuri.collectors.ark import ARKCollector
        from nuri.core.db import query

        ARKCollector()._record_source_dates({f: today_kst() for f in ALL_FUNDS}, db_path)
        leaked = query("SELECT COUNT(*) AS n FROM external_analysis WHERE source = 'ark'", db_path=db_path)[0]["n"]
        assert leaked == 0
