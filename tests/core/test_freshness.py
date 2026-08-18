"""nuri.core.freshness 모듈 테스트 — 데이터 신선도 SLA 체크."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from nuri.core.db import init_db
from nuri.core.timezone import KST


@pytest.fixture
def db_path(tmp_path):
    """임시 DB 경로 픽스처."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestFreshnessPolicies:
    """FRESHNESS_POLICIES 구조 검증."""

    def test_policies_is_dict(self):
        from nuri.core.freshness import FRESHNESS_POLICIES

        assert isinstance(FRESHNESS_POLICIES, dict)
        assert len(FRESHNESS_POLICIES) > 0

    def test_all_policies_have_required_keys(self):
        from nuri.core.freshness import FRESHNESS_POLICIES

        required = {"query", "warn_hours", "fail_hours", "label"}
        for key, policy in FRESHNESS_POLICIES.items():
            for req in required:
                assert req in policy, f"Policy '{key}' missing '{req}'"

    def test_warn_less_than_fail(self):
        """warn_hours < fail_hours 인지 검증."""
        from nuri.core.freshness import FRESHNESS_POLICIES

        for key, policy in FRESHNESS_POLICIES.items():
            assert policy["warn_hours"] < policy["fail_hours"], (
                f"Policy '{key}': warn_hours ({policy['warn_hours']}) >= fail_hours ({policy['fail_hours']})"
            )

    def test_expected_policy_keys(self):
        """예상되는 정책 키 목록 확인."""
        from nuri.core.freshness import FRESHNESS_POLICIES

        # `factors` 는 #1071 에서 추가 — 정책이 없어서 2026-04-14 → 08-18 넉 달간 낡은 채로도
        # 어떤 화면에도 안 떴다. BUY 점수의 가중치 0.40 짜리 최대 입력이다.
        # `signals` 는 #1101 에서 추가 — 커버리지가 40종목(가격 753 대비)으로 넉 달을
        # 가고 오늘 run 이 무엇을 남기든 어떤 화면에도 안 떴다. RSI 가 BUY 점수의
        # 0.15 가중치인데 결측이라 전 종목 중립 상수 50 이었다.
        expected = {
            "prices",
            "factors",
            "signals",
            "macro_vix",
            "macro_fear_greed",
            "consensus",
            "certification",
            "portfolio",
        }
        assert expected == set(FRESHNESS_POLICIES.keys())


class TestParseTimestamp:
    """_parse_timestamp() 날짜/시간 파싱 검증."""

    def test_date_only(self):
        from nuri.core.freshness import _parse_timestamp

        result = _parse_timestamp("2024-06-15")
        assert result == datetime(2024, 6, 15, tzinfo=KST)

    def test_datetime_space(self):
        from nuri.core.freshness import _parse_timestamp

        result = _parse_timestamp("2024-06-15 14:30:00")
        assert result == datetime(2024, 6, 15, 14, 30, 0, tzinfo=KST)

    def test_datetime_t_separator(self):
        from nuri.core.freshness import _parse_timestamp

        result = _parse_timestamp("2024-06-15T14:30:00")
        assert result == datetime(2024, 6, 15, 14, 30, 0, tzinfo=KST)

    def test_strips_whitespace(self):
        from nuri.core.freshness import _parse_timestamp

        result = _parse_timestamp("  2024-06-15  ")
        assert result == datetime(2024, 6, 15, tzinfo=KST)

    def test_unsupported_format_raises(self):
        from nuri.core.freshness import _parse_timestamp

        with pytest.raises(ValueError, match="지원하지 않는 날짜 형식"):
            _parse_timestamp("15/06/2024")

    def test_empty_string_raises(self):
        from nuri.core.freshness import _parse_timestamp

        with pytest.raises(ValueError):
            _parse_timestamp("")

    def test_result_has_kst_timezone(self):
        from nuri.core.freshness import _parse_timestamp

        result = _parse_timestamp("2024-01-01")
        assert result.tzinfo is KST


class TestCheckFreshness:
    """check_freshness() — 단일 소스 신선도 체크."""

    def test_pass_when_data_is_recent(self, db_path):
        """최근 데이터 → PASS."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        # SPY 가격 삽입 (오늘 날짜)
        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, 100, 100, 100, 100, 1000)",
                ("SPY", today),
            )

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "PASS"
        assert result["key"] == "prices"
        assert result["label"] == "주가 데이터"
        assert result["age_hours"] is not None
        assert result["age_hours"] >= 0

    def test_warn_when_data_is_stale(self, db_path):
        """warn_hours 초과, fail_hours 이하 → WARN."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        # 3일 전 데이터 (prices warn_hours=48, fail_hours=120)
        stale_date = (kst_now() - timedelta(hours=72)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, 100, 100, 100, 100, 1000)",
                ("SPY", stale_date),
            )

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "WARN"

    def test_fail_when_data_is_very_old(self, db_path):
        """fail_hours 초과 → FAIL."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        # 6일 전 데이터 (prices fail_hours=120)
        old_date = (kst_now() - timedelta(hours=150)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, 100, 100, 100, 100, 1000)",
                ("SPY", old_date),
            )

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "FAIL"
        assert "오래됨" in result["message"]

    def test_fail_when_no_data(self, db_path):
        """데이터가 없으면 FAIL (데이터 없음)."""
        from nuri.core.freshness import check_freshness

        result = check_freshness("prices", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["last_updated"] is None
        assert "데이터 없음" in result["message"]

    def test_stale_factors_surface_instead_of_going_unnoticed(self, db_path):
        """낡은 팩터가 FAIL 로 뜬다 (#1071).

        프로덕션에서 `factors` 는 2026-04-14 → 08-18 넉 달간 낡아 있었는데 정책이 없어서
        어떤 화면에도 안 떴다. 그 사이 BUY 후보 점수는 가중치 0.40 짜리 4월 값으로 계산됐다.

        Mutation lock: `FRESHNESS_POLICIES` 에서 `factors` 를 빼면 KeyError 로 FAIL.
        """
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        old = (kst_now() - timedelta(days=40)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, 0.7)",
                ("AAA", old),
            )

        result = check_freshness("factors", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["label"] == "멀티팩터 스코어"

    def test_stale_signals_surface_instead_of_going_unnoticed(self, db_path):
        """낡은 기술 지표가 FAIL 로 뜬다 (#1101).

        프로덕션에서 `signals` 는 40종목(가격 753 대비)으로 넉 달을 갔고 정책이 없어서
        어떤 화면에도 안 떴다. RSI 는 BUY 점수의 0.15 가중치인데 99.1% 결측이라 전 종목
        중립 상수였다 — 틀린 값이 아니라 변별력 0 인 값이라 아무것도 이상해 보이지 않았다.

        Mutation lock: `FRESHNESS_POLICIES` 에서 `signals` 를 빼면 KeyError 로 FAIL.
        """
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        old = (kst_now() - timedelta(days=40)).strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO signals (ticker, date, rsi_14) VALUES (?, ?, 55.0)",
                ("AAA", old),
            )

        result = check_freshness("signals", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["label"] == "기술 지표"

    def test_recent_factors_pass(self, db_path):
        """정상 갱신은 통과 — 가드가 상시 FAIL 이면 아무도 안 본다.

        `prices` 와 같은 48h/120h 를 쓴다: `factors.date` 가 시장 데이터 날짜라서
        주말이면 금요일에 머무는 게 정상이기 때문이다.
        """
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO factors (ticker, date, composite_score) VALUES (?, ?, 0.7)",
                ("AAA", kst_now().strftime("%Y-%m-%d")),
            )

        assert check_freshness("factors", db_path=db_path)["status"] == "PASS"

    def test_emitter_rows_do_not_make_consensus_look_fresh(self, db_path):
        """오늘 emitter 행이 있어도 합의가 낡았으면 FAIL 이어야 한다 (#1078 Codex P2).

        `buy_candidate_emitter` 가 같은 `recommendations` 테이블에 쓰기 시작한 뒤로는
        `MAX(date)` 만 보면 합의 job 이 죽은 날에도 브리핑이 낸 후보 한 줄이 "합의 신선함"
        으로 읽힌다. 관측이 거짓말하면 고장을 아무도 못 본다.

        Mutation lock: `WHERE source IS NULL` 을 빼면 PASS 로 뒤집혀 FAIL.
        """
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        stale = (kst_now() - timedelta(days=5)).strftime("%Y-%m-%d")
        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, source) VALUES (?, ?, 'BUY', NULL)",
                (stale, "AAA"),
            )
            conn.execute(
                "INSERT INTO recommendations (date, ticker, action, source) "
                "VALUES (?, ?, 'BUY', 'buy_candidate_emitter')",
                (today, "BBB"),
            )

        assert check_freshness("consensus", db_path=db_path)["status"] == "FAIL"

    def test_thresholds_match_prices_because_the_date_is_a_market_date(self):
        """`factors` 와 `prices` 임계가 같아야 한다 (#1071 Codex P1).

        `factors.date` 는 쓴 날이 아니라 **시장 데이터 날짜**다. 그래서 주말이면 금요일에
        머무는 게 정상이고, `prices` 와 같은 주말 여유가 필요하다. 24h/72h 로 좁히면
        월요일 아침마다(금→월 = 72h) 상시 발화한다.
        """
        from nuri.core.freshness import FRESHNESS_POLICIES

        assert FRESHNESS_POLICIES["factors"]["warn_hours"] == FRESHNESS_POLICIES["prices"]["warn_hours"]
        assert FRESHNESS_POLICIES["factors"]["fail_hours"] == FRESHNESS_POLICIES["prices"]["fail_hours"]

    def test_fail_on_query_exception(self, db_path):
        """쿼리 실행 실패 → FAIL."""
        from nuri.core.freshness import check_freshness

        with patch("nuri.core.freshness.query", side_effect=Exception("DB error")):
            result = check_freshness("prices", db_path=db_path)

        assert result["status"] == "FAIL"
        assert "쿼리 실행 실패" in result["message"]

    def test_fail_on_unparseable_date(self, db_path):
        """파싱 불가능한 날짜 형식 → FAIL."""
        from nuri.core.freshness import check_freshness

        with patch("nuri.core.freshness.query", return_value=[{"max_date": "bad-date"}]):
            result = check_freshness("prices", db_path=db_path)

        assert result["status"] == "FAIL"
        assert "날짜 파싱 실패" in result["message"]

    def test_unknown_key_raises_keyerror(self, db_path):
        """정의되지 않은 키 → KeyError."""
        from nuri.core.freshness import check_freshness

        with pytest.raises(KeyError):
            check_freshness("nonexistent_key", db_path=db_path)

    def test_macro_vix_freshness(self, db_path):
        """VIX 데이터 신선도 체크."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO macro (indicator, date, value) VALUES (?, ?, ?)",
                ("vix", today, 20.5),
            )

        result = check_freshness("macro_vix", db_path=db_path)
        assert result["status"] == "PASS"
        assert result["label"] == "VIX"

    def test_result_dict_shape(self, db_path):
        """반환 딕셔너리의 필수 키 구조 검증."""
        from nuri.core.freshness import check_freshness

        result = check_freshness("prices", db_path=db_path)
        expected_keys = {"key", "label", "status", "last_updated", "age_hours", "message"}
        assert set(result.keys()) == expected_keys


class TestCheckAllFreshness:
    """check_all_freshness() — 전체 정책 일괄 체크."""

    def test_returns_list(self, db_path):
        from nuri.core.freshness import check_all_freshness

        results = check_all_freshness(db_path=db_path)
        assert isinstance(results, list)

    def test_returns_one_entry_per_policy(self, db_path):
        from nuri.core.freshness import FRESHNESS_POLICIES, check_all_freshness

        results = check_all_freshness(db_path=db_path)
        assert len(results) == len(FRESHNESS_POLICIES)

    def test_all_fail_on_empty_db(self, db_path):
        """빈 DB에서는 모든 결과가 FAIL."""
        from nuri.core.freshness import check_all_freshness

        results = check_all_freshness(db_path=db_path)
        for r in results:
            assert r["status"] == "FAIL"


class TestGetFreshnessSummary:
    """get_freshness_summary() — 요약 통계."""

    def test_summary_structure(self, db_path):
        from nuri.core.freshness import get_freshness_summary

        summary = get_freshness_summary(db_path=db_path)
        assert "pass" in summary
        assert "warn" in summary
        assert "fail" in summary
        assert "details" in summary
        assert isinstance(summary["details"], list)

    def test_counts_sum_to_total_policies(self, db_path):
        from nuri.core.freshness import FRESHNESS_POLICIES, get_freshness_summary

        summary = get_freshness_summary(db_path=db_path)
        total = summary["pass"] + summary["warn"] + summary["fail"]
        assert total == len(FRESHNESS_POLICIES)

    def test_all_fail_on_empty_db(self, db_path):
        """빈 DB → fail 카운트가 전체 정책 수와 동일."""
        from nuri.core.freshness import FRESHNESS_POLICIES, get_freshness_summary

        summary = get_freshness_summary(db_path=db_path)
        assert summary["fail"] == len(FRESHNESS_POLICIES)
        assert summary["pass"] == 0
        assert summary["warn"] == 0

    def test_mixed_statuses(self, db_path):
        """일부 데이터만 최신인 경우 혼합 상태."""
        from nuri.core.db import get_db
        from nuri.core.freshness import get_freshness_summary
        from nuri.core.timezone import kst_now

        today = kst_now().strftime("%Y-%m-%d")
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, 100, 100, 100, 100, 1000)",
                ("SPY", today),
            )

        summary = get_freshness_summary(db_path=db_path)
        # prices should PASS, others should FAIL
        assert summary["pass"] >= 1
        assert summary["fail"] >= 1


class TestCertificationFreshnessE4_0a:
    """E4-0a post-merge fix — certification freshness 가 certifications 테이블을 조회.

    E4-0a 전: pipeline_events 'certification_result' 이벤트 기대했으나 emitter 없어 항상 FAIL.
    E4-0a 후: certify() 가 certifications 테이블에 직접 persist → freshness 가 거기 조회.
    추가로 _parse_timestamp 가 kst_now().isoformat() 의 microseconds+tz 형식 파싱해야 함.
    """

    def test_policy_points_to_certifications_table(self):
        """FRESHNESS_POLICIES['certification'] 이 certifications 테이블을 source 로."""
        from nuri.core.freshness import FRESHNESS_POLICIES

        q = FRESHNESS_POLICIES["certification"]["query"]
        assert "FROM certifications" in q, f"expected 'FROM certifications', got: {q}"
        assert "pipeline_events" not in q, "pipeline_events 조회는 E4-0a 이후 deprecated"

    def test_pass_when_recent_certification_exists(self, db_path):
        """certifications 테이블에 최신 row 존재 → PASS."""
        from nuri.core.db import get_db
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        now_iso = kst_now().isoformat()  # microseconds + +09:00 timezone
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO certifications "
                "(timestamp, certified, score, total_conditions, passed, failed, warnings, conditions_json) "
                "VALUES (?, 1, 100.0, 11, 11, 0, 0, '[]')",
                (now_iso,),
            )

        r = check_freshness("certification", db_path=db_path)
        assert r["status"] == "PASS", f"expected PASS, got {r}"
        assert r["last_updated"] == now_iso
        assert r["age_hours"] is not None and r["age_hours"] < 1.0

    def test_fail_when_certifications_empty(self, db_path):
        """빈 certifications 테이블 → FAIL (데이터 없음)."""
        from nuri.core.freshness import check_freshness

        r = check_freshness("certification", db_path=db_path)
        assert r["status"] == "FAIL"
        assert r["last_updated"] is None

    def test_parse_timestamp_handles_microseconds_timezone(self):
        """_parse_timestamp 가 kst_now().isoformat() 형식 (microseconds + +09:00) 파싱.

        이전 strptime 세 포맷은 이 형식 미지원 → '날짜 파싱 실패' 로 FAIL 이던 회귀 lock.
        """
        from nuri.core.freshness import _parse_timestamp

        # E4-0a certifications.timestamp 실제 포맷
        dt = _parse_timestamp("2026-04-20T22:31:56.191762+09:00")
        assert dt.tzinfo is not None, "timezone 보존"
        assert dt.year == 2026 and dt.month == 4 and dt.day == 20
        assert dt.hour == 22 and dt.minute == 31

    def test_parse_timestamp_backward_compat_short_formats(self):
        """기존 strptime 포맷 (date-only, date-time no-tz) 여전히 작동."""
        from nuri.core.freshness import _parse_timestamp

        # date-only
        dt1 = _parse_timestamp("2026-04-20")
        assert dt1.year == 2026 and dt1.tzinfo is not None
        # datetime no-tz space separator
        dt2 = _parse_timestamp("2026-04-20 12:00:00")
        assert dt2.hour == 12 and dt2.tzinfo is not None
        # datetime no-tz T separator
        dt3 = _parse_timestamp("2026-04-20T12:00:00")
        assert dt3.hour == 12 and dt3.tzinfo is not None

    def test_strptime_fallback_for_non_iso_dash_format(self):
        """fromisoformat 실패 → strptime fallback 성공 분기 (line 82).

        '2026-4-1' (zero-padded 아님) 은 Python fromisoformat 거부 → strptime '%Y-%m-%d' 통과.
        """
        from nuri.core.freshness import _parse_timestamp

        dt = _parse_timestamp("2026-4-1")
        assert dt.year == 2026 and dt.month == 4 and dt.day == 1
        assert dt.tzinfo is not None  # KST 부착됨
