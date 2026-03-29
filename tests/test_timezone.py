"""nuri/core/timezone.py 테스트 — UTC/KST 타임존 유틸리티."""
from datetime import datetime, timedelta

from nuri.core.timezone import ET, KST, UTC, kst_now, to_kst, today_kst, today_utc, utc_now


class TestTimezoneConstants:
    def test_kst_offset(self):
        """KST는 UTC+9."""
        assert KST.utcoffset(None) == timedelta(hours=9)

    def test_et_offset(self):
        """ET는 UTC-5 (EST)."""
        assert ET.utcoffset(None) == timedelta(hours=-5)

    def test_utc_offset(self):
        """UTC는 오프셋 0."""
        assert UTC.utcoffset(None) == timedelta(0)


class TestUtcNow:
    def test_returns_aware_datetime(self):
        """utc_now()는 timezone-aware datetime을 반환."""
        dt = utc_now()
        assert dt.tzinfo is not None
        assert dt.tzinfo == UTC

    def test_close_to_real_time(self):
        """utc_now()는 실제 현재 시간과 거의 동일."""
        dt = utc_now()
        ref = datetime.now(UTC)
        diff = abs((ref - dt).total_seconds())
        assert diff < 1.0


class TestKstNow:
    def test_returns_aware_datetime(self):
        """kst_now()는 timezone-aware datetime을 반환."""
        dt = kst_now()
        assert dt.tzinfo is not None

    def test_kst_offset_from_utc(self):
        """kst_now()는 utc_now()보다 9시간 앞."""
        utc = utc_now()
        kst = kst_now()
        # 같은 시점이므로 UTC timestamp 기준 1초 이내 차이
        diff = abs(utc.timestamp() - kst.timestamp())
        assert diff < 1.0
        # KST 시간은 UTC보다 9시간 큰 값
        kst_as_utc = kst.astimezone(UTC)
        assert abs((kst_as_utc - utc).total_seconds()) < 1.0


class TestTodayFunctions:
    def test_today_utc_format(self):
        """today_utc()는 YYYY-MM-DD 형식."""
        result = today_utc()
        assert len(result) == 10
        datetime.strptime(result, "%Y-%m-%d")

    def test_today_kst_format(self):
        """today_kst()는 YYYY-MM-DD 형식."""
        result = today_kst()
        assert len(result) == 10
        datetime.strptime(result, "%Y-%m-%d")


class TestToKst:
    def test_naive_datetime_treated_as_utc(self):
        """tzinfo 없는 datetime은 UTC로 간주."""
        naive = datetime(2026, 1, 1, 0, 0, 0)
        kst = to_kst(naive)
        assert kst.tzinfo is not None
        assert kst.hour == 9  # UTC 0시 -> KST 9시

    def test_utc_to_kst_conversion(self):
        """UTC datetime -> KST 변환."""
        utc_dt = datetime(2026, 3, 15, 15, 0, 0, tzinfo=UTC)
        kst = to_kst(utc_dt)
        assert kst.hour == 0  # UTC 15시 -> KST 다음날 0시
        assert kst.day == 16

    def test_already_kst_no_change(self):
        """이미 KST인 datetime은 값 유지."""
        kst_dt = datetime(2026, 1, 1, 9, 0, 0, tzinfo=KST)
        result = to_kst(kst_dt)
        assert result.hour == 9
        assert result.day == 1

    def test_et_to_kst_conversion(self):
        """ET -> KST 변환 (14시간 차이)."""
        et_dt = datetime(2026, 3, 15, 10, 0, 0, tzinfo=ET)
        kst = to_kst(et_dt)
        # ET 10:00 = UTC 15:00 = KST 00:00 (다음날)
        assert kst.hour == 0
        assert kst.day == 16
