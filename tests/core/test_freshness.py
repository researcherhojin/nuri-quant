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
                f"Policy '{key}': warn_hours ({policy['warn_hours']}) "
                f">= fail_hours ({policy['fail_hours']})"
            )

    def test_expected_policy_keys(self):
        """예상되는 정책 키 목록 확인."""
        from nuri.core.freshness import FRESHNESS_POLICIES

        expected = {"prices", "macro_vix", "macro_fear_greed", "consensus", "certification"}
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
