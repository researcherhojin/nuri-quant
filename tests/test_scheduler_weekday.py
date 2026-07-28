"""스케줄러 요일 규약을 crontab 의미로 고정한다 (#929).

`CronTrigger.from_crontab()` 은 요일 필드를 **변환 없이** APScheduler 의
`day_of_week`(Mon=0…Sun=6)로 넘긴다. crontab 은 0=Sun 이라 그대로 쓰면 모든 job 이
하루씩 밀린다. 이 함정은 #432 리뷰에서 이미 발견돼 `scheduler.py` 에 경고 주석까지
있었는데, 변환은 `tz` 있는 job 1개에만 걸려 있었고 나머지 22개는 밀린 채였다.

실제 피해 (2026-07-29 프로덕션 실측): `stock_us_freshness` 의 `2-6` 이 화–토가
아니라 수–일로 fire → **화요일에 안 돌아** 미국 월요일 종가가 수요일에야 들어왔다.
그 결과 §3.11 US 판정의 벤치마크인 SPY 가 매주 월·화 stale (07-24 금 → 07-28 화
동안 갱신 없음, 같은 기간 KOSPI 는 정상). `period=5d` 가 뒤늦게 메꿔 영구 결손이
아니었던 탓에 아무 알림도 울리지 않았다.

여기서 두 가지를 잠근다:
  1. 변환 함수가 crontab 의미를 정확히 옮긴다 (step 형식 포함)
  2. SCHEDULES 의 **모든** job 이 crontab 의미대로 fire 한다 — tz 유무와 무관하게
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytz

from nuri.scheduler import SCHEDULES, _crontab_dow, create_scheduler

KST = pytz.timezone("Asia/Seoul")

# 손으로 적은 crontab 규약 표 — 검사 대상 코드와 독립적이어야 의미가 있다.
_CRONTAB_DAY = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
_ALL_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def _intended_weekdays(dow_field: str) -> set[str]:
    """crontab 요일 필드가 **의도한** 요일 집합 (독립 참조 구현).

    SCHEDULES 는 `*` / 단일 숫자 / 단순 범위만 쓴다. step 형식이 들어오면 이 참조가
    조용히 틀리는 대신 실패하게 둔다 — 그때는 이 함수부터 고쳐야 한다.
    """
    dow_field = dow_field.strip()
    if dow_field == "*":
        return set(_ALL_DAYS)
    out: set[str] = set()
    for part in dow_field.split(","):
        assert "/" not in part, f"참조 구현이 step 형식을 모른다: {dow_field!r}"
        if "-" in part:
            lo, _, hi = part.partition("-")
            out |= {_CRONTAB_DAY[n] for n in range(int(lo), int(hi) + 1)}
        else:
            out.add(_CRONTAB_DAY[int(part)])
    return out


def _actual_weekdays(trigger) -> set[str]:
    """트리거가 실제로 fire 하는 요일 — APScheduler 에게 직접 물어본다.

    2주를 훑어 어느 요일에 한 번이라도 fire 하는지 모은다 (문서 해석이 아니라 실측).
    """
    now = KST.localize(datetime(2026, 6, 1))  # 월요일
    end = now + timedelta(days=14)
    days: set[str] = set()
    while True:
        nxt = trigger.get_next_fire_time(None, now)
        if nxt is None or nxt > end:
            return days
        days.add(nxt.strftime("%a"))
        now = nxt + timedelta(minutes=1)


class TestCrontabDowConversion:
    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("*", "*"),
            ("0", "sun"),
            ("7", "sun"),  # crontab 은 0 과 7 을 모두 일요일로 본다
            ("6", "sat"),
            ("1-5", "mon,tue,wed,thu,fri"),
            ("2-6", "tue,wed,thu,fri,sat"),
            ("0,6", "sat,sun"),
            ("mon-fri", "mon,tue,wed,thu,fri"),  # 이름은 두 규약이 일치 — 통과만
        ],
    )
    def test_field_conversion(self, field, expected):
        assert _crontab_dow(field) == expected

    def test_step_form_is_enumerated_not_rewritten(self):
        """`*/2` 를 문자열 그대로 넘기면 조용히 다른 요일이 된다.

        crontab `*/2` = 0,2,4,6 = 일·화·목·토. APScheduler 가 `*/2` 를 그대로 받으면
        월부터 세어 월·수·금·일이 된다 — 겹치는 요일이 있어 더 알아채기 어렵다.

        Gotcha-Test Pair: 열거를 문자열 치환으로 되돌리면 FAIL.
        """
        assert set(_crontab_dow("*/2").split(",")) == {"sun", "tue", "thu", "sat"}
        assert set(_crontab_dow("0-6/3").split(",")) == {"sun", "wed", "sat"}

    @pytest.mark.parametrize("bad", ["8", "-1", "fri-mon", "nonday", "1-5/0"])
    def test_invalid_field_raises(self, bad):
        """조용히 통과시키느니 기동 때 죽는 게 낫다 — 이 이슈가 조용해서 오래갔다."""
        with pytest.raises(ValueError):
            _crontab_dow(bad)


def _registered_triggers() -> dict[str, object]:
    """`create_scheduler()` 가 **실제로 등록한** 트리거.

    helper 를 직접 부르면 배선을 못 잠근다 — `create_scheduler` 안의 호출을
    `from_crontab` 으로 되돌려도 helper 테스트는 그대로 통과한다. 실측으로
    확인한 구멍이라 등록 결과를 본다.
    """
    return {j.id: j.trigger for j in create_scheduler().get_jobs()}


class TestEverySchedulesJobFiresOnIntendedDays:
    def test_all_jobs_match_crontab_semantics(self):
        """등록된 전 job 의 실제 fire 요일 == crontab 이 뜻하는 요일.

        Gotcha-Test Pair: `create_scheduler` 의 트리거 생성을
        `CronTrigger.from_crontab()` 으로 되돌리면 요일 필드가 `*` 가 아닌 22개
        job 이 전부 하루씩 밀려 FAIL.
        """
        triggers = _registered_triggers()
        drift = []
        for job in SCHEDULES:
            want = _intended_weekdays(job["cron"].split()[4])
            got = _actual_weekdays(triggers[job["name"]])
            if want != got:
                drift.append(f"{job['name']} ({job['cron']}): 기대 {sorted(want)} != 실제 {sorted(got)}")
        assert not drift, "요일이 밀린 job:\n  " + "\n  ".join(drift)

    def test_every_scheduled_job_is_registered(self):
        """SCHEDULES 항목이 전부 등록되는지 — 빠지면 위 sweep 이 그 job 을 못 본다.

        `heartbeat` 는 SCHEDULES 밖에서 interval 트리거로 직접 등록되므로 cron
        요일 검사 대상이 아니다 (초과분 1건 허용).
        """
        registered = set(_registered_triggers())
        missing = {j["name"] for j in SCHEDULES} - registered
        assert not missing, f"등록되지 않은 SCHEDULES job: {sorted(missing)}"
        assert registered - {j["name"] for j in SCHEDULES} == {"heartbeat"}

    def test_the_sweep_actually_covers_non_wildcard_jobs(self):
        """요일 필드가 전부 `*` 면 위 테스트가 공허하게 통과한다."""
        specific = [j for j in SCHEDULES if j["cron"].split()[4] != "*"]
        assert len(specific) >= 20, f"요일 지정 job 이 {len(specific)}개뿐 — sweep 무력화 의심"


class TestFreshnessJobRegression:
    """#929 의 증상 자체 — SPY 수집이 화요일에 돌아야 한다."""

    def _freshness_job(self):
        jobs = [s for s in SCHEDULES if (s.get("kwargs") or {}).get("source") == "freshness"]
        assert jobs, "source=freshness job 이 사라짐 (#860 회귀)"
        return jobs[0]

    def test_freshness_runs_on_tuesday(self):
        """화요일 아침에 돌아야 미국 **월요일** 종가가 당일 들어온다.

        Gotcha-Test Pair: 요일 변환을 되돌리면 화요일이 빠져 FAIL — 그게 SPY 가
        월·화 stale 이던 이유다.
        """
        job = self._freshness_job()
        days = _actual_weekdays(_registered_triggers()[job["name"]])
        assert "Tue" in days, f"{job['name']} 이 화요일에 안 돈다 (실제 {sorted(days)})"

    def test_freshness_covers_every_us_trading_day_plus_one(self):
        """미국 월–금 종가는 KST 화–토 아침에 수집된다 — 하루도 비면 안 된다."""
        job = self._freshness_job()
        days = _actual_weekdays(_registered_triggers()[job["name"]])
        missing = {"Tue", "Wed", "Thu", "Fri", "Sat"} - days
        assert not missing, f"{job['name']} 이 {sorted(missing)} 에 안 돈다 — 그날 벤치마크가 stale"
