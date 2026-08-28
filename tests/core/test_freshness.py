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

    def test_macro_market_fail_threshold_absorbs_t1_publication(self):
        """macro_market fail 임계는 소스 T+1 발행 리듬의 정상 최대 나이(~127h)를 흡수한다 (#1242).

        FRED H.15·CBOE 는 영업일 D 관측을 D+1 늦은 오후 ET 에 공개한다. 금요일 관측이
        다음 주 수요일 새벽 KST 까지 최신인 게 정상이라, 날짜 문자열 00:00 KST 앵커
        기준 정상 최대 나이가 ~127h 다 (2026-08-26 02:00 KST 실측: FAIL 122h 상태에서
        FRED 직접 조회로 금요일 이후 관측 부재 확증 — 수집기는 건강했다). prices(120h)와
        "동일 임계"로 되돌리면 매주 수요일 00:00~새벽 KST 에 구조적 false-FAIL 이 난다.
        """
        from nuri.core.freshness import FRESHNESS_POLICIES

        macro_market = FRESHNESS_POLICIES["macro_market"]["fail_hours"]
        assert macro_market >= 127, (
            f"macro_market fail_hours ({macro_market}) 가 T+1 발행의 정상 최대 나이(~127h) 미만 — "
            "매주 수요일 새벽 건강한 파이프라인이 FAIL 한다 (#1242)"
        )
        # prices 와의 '동일 임계' consistency-fix 회귀 축도 잠근다 — 소스 리듬이 다르다.
        assert macro_market > FRESHNESS_POLICIES["prices"]["fail_hours"]

    def test_expected_policy_keys(self):
        """예상되는 정책 키 목록 확인."""
        from nuri.core.freshness import FRESHNESS_POLICIES

        # `factors` 는 #1071 에서 추가 — 정책이 없어서 2026-04-14 → 08-18 넉 달간 낡은 채로도
        # 어떤 화면에도 안 떴다. BUY 점수의 가중치 0.40 짜리 최대 입력이다.
        # `signals` 는 #1101 에서 추가 — 커버리지가 40종목(가격 753 대비)으로 넉 달을
        # 가고 오늘 run 이 무엇을 남기든 어떤 화면에도 안 떴다. RSI 가 BUY 점수의
        # 0.15 가중치인데 결측이라 전 종목 중립 상수 50 이었다.
        # `fundamentals` 는 #1109 에서 추가 — composite 가중치 1.00 중 0.50(value+quality)이
        # 이 테이블에서 나오는데 정책이 없어서, 주간 잡이 보유 18종목만 갱신하는 동안
        # 나머지 ~728 종목이 얼마나 낡든 어떤 화면에도 안 떴다 (#1102 의 재료 쪽 절반).
        # `ark` 는 #1145 에서 추가 — 소스가 **200 인 채로 내용만 언다**. ARKF 가 7.5개월 전
        # 보유를 담은 CSV 를 정상 서빙하는 동안 다운로드·파싱이 다 성공해 수집기 실패율에도
        # `collector_runs` 에도 안 걸렸다. 정책 쿼리는 맨 `MAX(date)` 가 아니라 **펀드별
        # 최신 날짜의 최소값**이다 — 전자는 멀쩡한 펀드 4개가 죽은 펀드 하나를 가려 초록이
        # 된다 (`signals` 가 KR/US 를 안 합치는 것과 같은 축).
        expected = {
            "prices",
            "factors",
            "signals",
            "signals_kr",
            "fundamentals",
            "fundamentals_kr",
            "macro_vix",
            "macro_fear_greed",
            # `macro_market`/`macro_monthly` 는 #1180 에서 추가 — verdict stale gate 가
            # vix/fear_greed 만 보면 금리·put/call·고용·CPI 가 낡은 채로 macro 점수에
            # 들어가 "공격 가능" 이 선다 (Codex P1). 결측 지표는 macro_score 가 coverage
            # 재정규화로 이미 제외하므로(#1026) present-only MIN — 낡음만 잡는다.
            "macro_market",
            "macro_monthly",
            "consensus",
            # `decisions_context` 는 #1261 에서 추가 — `consensus` 정책이 **형제 테이블**
            # (`recommendations`)을 봐서, 같은 job 이 쓰는 `decisions` 가 67 거래일 통째로
            # 비었을 때(#897/#898)도, `regime`·`scoring_detail` 이 591/591 NULL 로 4.5개월
            # 얼어 있을 때(#1247/#1256)도 내내 초록이었다. 완결성 술어를 신선도 쿼리 안에 두어
            # "행이 쓰였다" 와 "쓸모있게 쓰였다" 를 한 쿼리로 구분한다.
            "decisions_context",
            "certification",
            "portfolio",
            "ark",
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

    #: 멤버 기반 픽스처 universe — 검사가 **구성된 멤버만** 세므로 시드도 멤버 이름으로.
    _US = [f"U{i:04d}" for i in range(500)]
    _KR = [f"K{i:04d}.KS" for i in range(150)] + [f"Q{i:04d}.KQ" for i in range(50)]

    @pytest.fixture(autouse=True)
    def _fixture_universe(self, monkeypatch):
        import nuri.core.coverage as cov

        monkeypatch.setattr(cov, "_load_universe", lambda path=None: {"us": set(self._US), "kr": set(self._KR)})

    def _seed_signals(self, db_path, date: str, tickers):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.executemany(
                "INSERT INTO signals (ticker, date, rsi_14) VALUES (?, ?, 55.0)",
                [(t, date) for t in tickers],
            )

    def test_stale_signals_surface_instead_of_going_unnoticed(self, db_path):
        """낡은 기술 지표가 FAIL 로 뜬다 (#1101).

        프로덕션에서 `signals` 는 40종목(가격 753 대비)으로 넉 달을 갔고 정책이 없어서
        어떤 화면에도 안 떴다. RSI 는 BUY 점수의 0.15 가중치인데 99.1% 결측이라 전 종목
        중립 상수였다 — 틀린 값이 아니라 변별력 0 인 값이라 아무것도 이상해 보이지 않았다.

        Mutation lock: `FRESHNESS_POLICIES` 에서 `signals` 를 빼면 KeyError 로 FAIL.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        old = (kst_now() - timedelta(days=40)).strftime("%Y-%m-%d")
        self._seed_signals(db_path, old, self._US)

        result = check_freshness("signals", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["label"] == "기술 지표 (US)"

    def test_partial_coverage_cannot_keep_signals_green(self, db_path):
        """보유 18종목만 갱신된 날은 신선한 것으로 안 친다 (#1101 Codex 1차).

        맨 `MAX(date)` 였다면 이 18행이 날짜를 끌어올려 초록이 됐다 — 이 정책이 잡으려는
        부분 커버리지 퇴행(40종목으로 넉 달)을 정확히 못 보는 형태다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed_signals(db_path, today_kst(), self._US[:18])

        result = check_freshness("signals", db_path=db_path)
        assert result["status"] == "FAIL", "부분 커버리지가 신선함으로 통했다"

    def test_a_dead_kr_slice_cannot_hide_behind_fresh_us_rows(self, db_path):
        """US 가 신선해도 KR 이 죽었으면 `signals_kr` 은 FAIL (#1101 Codex 2차).

        정책이 하나였다면 US 슬라이스 단독으로 floor 를 넘겨 KR 계산이 전면 정지해도
        초록이었다 — 한 시장의 outage 가 다른 시장 뒤에 숨는 형태다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now, today_kst

        self._seed_signals(db_path, today_kst(), self._US)  # US 신선
        old = (kst_now() - timedelta(days=40)).strftime("%Y-%m-%d")
        self._seed_signals(db_path, old, self._KR)  # KR 40일 정지

        assert check_freshness("signals", db_path=db_path)["status"] == "PASS"
        assert check_freshness("signals_kr", db_path=db_path)["status"] == "FAIL"

    def test_off_universe_holdings_cannot_prop_up_the_floor(self, db_path):
        """universe 밖 보유 종목은 커버리지에 안 센다 (#1101 Codex 7차).

        전 행을 세는 방식이면 비상장·개인 보유 이름이 floor 를 떠받쳐 "구성된 채점
        universe 가 낡았는데 PASS" 가 된다. 멤버 IN 제한이 그 경로를 막는다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        outsiders = [f"X{i:04d}" for i in range(400)]  # universe 밖 400행
        self._seed_signals(db_path, today_kst(), outsiders)

        assert check_freshness("signals", db_path=db_path)["status"] == "FAIL", "universe 밖 행이 floor 를 떠받쳤다"

    def test_kosdaq_members_count_as_kr(self, db_path):
        """`.KQ` 멤버도 KR 커버리지에 센다 — `.KS` 만 세면 KOSDAQ 몫이 영구 결손이 된다."""
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed_signals(db_path, today_kst(), self._KR)  # .KS 150 + .KQ 50 전부

        assert check_freshness("signals_kr", db_path=db_path)["status"] == "PASS"

    def test_the_floor_tracks_the_configured_universe(self, monkeypatch, db_path):
        """floor 는 상수가 아니라 config 도출이다 (Codex 6차).

        400/150 을 박으면 universe 를 줄인 설치(us_core 만 쓰는 환경, KR 슬리브 없는 레포)
        에서 잡이 멀쩡해도 영구 FAIL 이다. universe 를 30종목으로 줄이면 그 30종목
        커버리지가 통과해야 한다.
        """
        import nuri.core.coverage as cov
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        small = [f"S{i:03d}" for i in range(30)]
        monkeypatch.setattr(cov, "_load_universe", lambda path=None: {"us": set(small), "kr": set()})
        self._seed_signals(db_path, today_kst(), small)

        assert check_freshness("signals", db_path=db_path)["status"] == "PASS"

    def test_the_floor_rounds_up_not_down(self, monkeypatch, db_path):
        """floor 는 올림이다 (Codex 7차) — 내림이면 3종목 universe 에서 1행(33%)이 통과한다."""
        import nuri.core.coverage as cov
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        tiny = ["A1", "A2", "A3"]
        monkeypatch.setattr(cov, "_load_universe", lambda path=None: {"us": set(tiny), "kr": set()})
        self._seed_signals(db_path, today_kst(), tiny[:1])  # 1/3 = 33% < 60%

        assert check_freshness("signals", db_path=db_path)["status"] == "FAIL", (
            "33% 커버리지가 통과했다 — floor 가 내림이다"
        )

    def test_an_unconfigured_market_is_skipped_not_red_forever(self, monkeypatch, db_path):
        """universe 미구성 시장은 검사 생략 (Codex 6차) — KR 슬리브 없는 설치가 영구
        빨강이면 아무도 안 본다. '신선' 이 아니라 '해당 없음' 이라 메시지로 구분한다."""
        import nuri.core.coverage as cov
        from nuri.core.freshness import check_freshness

        monkeypatch.setattr(cov, "_load_universe", lambda path=None: {"us": {"A1"}, "kr": set()})

        result = check_freshness("signals_kr", db_path=db_path)
        assert result["status"] == "PASS"
        assert "미구성" in result["message"]

    def _seed_fundamentals(self, db_path, date: str, tickers):
        from nuri.core.db import get_db

        with get_db(db_path) as conn:
            conn.executemany(
                "INSERT INTO fundamentals (ticker, date, pe_ratio, roe) VALUES (?, ?, 20.0, 0.15)",
                [(t, date) for t in tickers],
            )

    def test_stale_fundamentals_surface_instead_of_going_unnoticed(self, db_path):
        """낡은 펀더멘탈이 FAIL 로 뜬다 (#1109).

        정책이 없던 시절엔 이 테이블이 100일 넘게 낡아도 아무 화면에 안 떴다. value·quality
        는 여기서만 나오고 둘이 합쳐 composite 가중치의 **절반**이다 — 낡은 PE/PBR 로 만든
        점수는 없는 것보다 나쁘다. 상수 0.5 는 변별력이 없다는 게 보이기라도 하지만, 100일
        전 숫자로 만든 순위는 진짜 신호와 구분되지 않는다.

        Mutation lock: `FRESHNESS_POLICIES` 에서 `fundamentals` 를 빼면 KeyError 로 FAIL.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        old = (kst_now() - timedelta(days=40)).strftime("%Y-%m-%d")
        self._seed_fundamentals(db_path, old, self._US)

        result = check_freshness("fundamentals", db_path=db_path)
        assert result["status"] == "FAIL"
        assert result["label"] == "펀더멘탈 (US)"

    def test_holding_only_writes_cannot_keep_fundamentals_green(self, db_path):
        """보유 18종목만 갱신된 날은 신선한 것으로 안 친다 (#1109).

        이게 이 정책의 존재 이유다. 맨 `MAX(date)` 였다면 프로덕션에서 실제로 벌어진 일 —
        주간 잡이 18행을 쓰고 나머지 728 종목은 손도 안 댄 상태 — 이 초록으로 보고됐다.
        커버리지 floor 가 그 18행을 신선함으로 세지 않는다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed_fundamentals(db_path, today_kst(), self._US[:18])

        result = check_freshness("fundamentals", db_path=db_path)
        assert result["status"] == "FAIL", "보유 종목만 갱신된 날이 신선함으로 통했다"

    def test_a_dead_kr_slice_cannot_hide_behind_fresh_us_fundamentals(self, db_path):
        """KR 이 통째로 비어도 US 가 신선하면 가려진다 — 그래서 시장별로 나눈다 (#1109).

        KR 은 KIS 순차 경로라 자격 증명 만료 하나로 전면 실패할 수 있다. 합산 floor(멤버
        746 의 60% = 448)는 US 543 만으로 넘으므로, 하나로 합쳤다면 KR 전멸이 PASS 로 보인다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed_fundamentals(db_path, today_kst(), self._US)

        assert check_freshness("fundamentals", db_path=db_path)["status"] == "PASS"
        assert check_freshness("fundamentals_kr", db_path=db_path)["status"] == "FAIL"

    def test_thresholds_allow_a_full_weekly_cycle(self):
        """임계가 주간 케이던스에 맞는다 (#1109).

        이 잡은 일요일 00:00 주 1회다. 다음 실행 직전 **정상** 나이가 168h 이므로 48h WARN
        이면 매주 6일이 빨갛고, 빨간 게 정상이면 아무도 안 본다 — 정책이 있으나 마나가 된다.
        """
        from nuri.core.freshness import FRESHNESS_POLICIES

        for key in ("fundamentals", "fundamentals_kr"):
            assert FRESHNESS_POLICIES[key]["warn_hours"] > 168, f"{key}: 주 1회 잡인데 WARN 이 한 주기보다 짧다"

    def test_full_coverage_today_passes(self, db_path):
        """정상 갱신은 통과 — 가드가 상시 FAIL 이면 아무도 안 본다."""
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed_signals(db_path, today_kst(), self._US)

        result = check_freshness("signals", db_path=db_path)
        assert result["status"] == "PASS"

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


class TestFreshnessConfig:
    """임계는 config/freshness.yaml 이 정본 (#1180, config-over-code)."""

    def test_thresholds_come_from_config(self):
        """로드된 정책 임계 == yaml 값 — 코드 하드코딩이 되살아나면 여기서 어긋난다."""
        import yaml as _yaml

        from nuri.core.freshness import _CONFIG_PATH, FRESHNESS_POLICIES

        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = _yaml.safe_load(f)

        assert set(cfg["thresholds"]) == set(FRESHNESS_POLICIES)
        for key, hours in cfg["thresholds"].items():
            assert FRESHNESS_POLICIES[key]["warn_hours"] == hours["warn_hours"], key
            assert FRESHNESS_POLICIES[key]["fail_hours"] == hours["fail_hours"], key

    def test_config_key_mismatch_raises(self, tmp_path, monkeypatch):
        """config 누락/잉여 키는 기동 시 ValueError — 조용한 기본값 폴백 금지."""
        import nuri.core.freshness as fresh_mod

        bad = tmp_path / "freshness.yaml"
        bad.write_text("thresholds:\n  prices: { warn_hours: 1, fail_hours: 2 }\n", encoding="utf-8")
        monkeypatch.setattr(fresh_mod, "_CONFIG_PATH", bad)
        with pytest.raises(ValueError, match="불일치"):
            fresh_mod._load_config()

    def test_verdict_gate_unknown_key_raises(self, tmp_path, monkeypatch):
        import yaml as _yaml

        import nuri.core.freshness as fresh_mod

        with open(fresh_mod._CONFIG_PATH, encoding="utf-8") as f:
            cfg = _yaml.safe_load(f)
        cfg["verdict_gate"] = ["nonexistent_policy"]
        bad = tmp_path / "freshness.yaml"
        bad.write_text(_yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(fresh_mod, "_CONFIG_PATH", bad)
        with pytest.raises(ValueError, match="verdict_gate"):
            fresh_mod._load_config()

    def test_verdict_gate_keys_are_registered_policies(self):
        from nuri.core.freshness import FRESHNESS_POLICIES, VERDICT_GATE_KEYS

        assert VERDICT_GATE_KEYS, "verdict_gate 가 비어 있으면 stale gate 가 무력하다"
        assert set(VERDICT_GATE_KEYS) <= set(FRESHNESS_POLICIES)

    def test_stale_verdict_inputs_flags_fail_only(self, db_path):
        """빈 DB → gate 입력 전부 FAIL 로 표면화. 반환 항목은 FAIL 만."""
        from nuri.core.freshness import VERDICT_GATE_KEYS, stale_verdict_inputs

        stale = stale_verdict_inputs(db_path)
        assert {s["key"] for s in stale} == set(VERDICT_GATE_KEYS)
        assert all(s["status"] == "FAIL" for s in stale)


class TestDecisionsContextPolicy:
    """`decisions_context` 정책 잠금 (#1261).

    `consensus` 정책은 **형제 테이블**(`recommendations`)을 본다. 같은 job 이 쓰는
    `decisions` 는 두 번 죽었는데 두 번 다 그 정책이 초록이었다 — writer 사망
    67 거래일(#897/#898)과 컬럼 동결 4.5개월(#1247/#1256). 그래서 이 정책은
    "가장 최근에 **완전한** 행이 나온 날" 을 본다.
    """

    def _seed(self, db_path, date: str, *, regime, scoring_detail, ticker="AAA"):
        from nuri.core.db import upsert_decision

        upsert_decision(
            {
                "date": date,
                "ticker": ticker,
                "action": "HOLD",
                "confidence": 50.0,
                "regime": regime,
                "scoring_detail": scoring_detail,
            },
            db_path,
        )

    def test_frozen_context_columns_cannot_keep_the_policy_green(self, db_path):
        """행은 매일 쓰이는데 컨텍스트 컬럼이 얼어 있으면 FAIL 이다.

        프로덕션에서 정확히 이 모양이었다 — `decisions` 는 매일 18행씩 쌓이는데
        `regime`·`scoring_detail` 이 591/591 NULL 이었고, 행 수를 보는 어떤 검사도
        4.5개월간 아무 신호를 내지 않았다.

        Mutation lock: 쿼리에서 완결성 술어(`WHERE regime IS NOT NULL AND
        scoring_detail IS NOT NULL`)를 지우면 `MAX(date)` 가 오늘을 집어 PASS 로 뒤집힌다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now, today_kst

        old = (kst_now() - timedelta(days=5)).strftime("%Y-%m-%d")
        self._seed(db_path, old, regime="bull_low_vol", scoring_detail='{"x":1}')
        # 오늘 행은 있지만 컨텍스트가 비었다 — "쓰였다" 는 "쓸모있게 쓰였다" 가 아니다.
        self._seed(db_path, today_kst(), regime=None, scoring_detail=None)

        result = check_freshness("decisions_context", db_path=db_path)
        assert result["status"] == "FAIL", result
        assert result["last_updated"].startswith(old), result

    def test_one_complete_row_cannot_hide_an_incomplete_batch(self, db_path):
        """배치 18행 중 한 행만 완전해도 초록이 되면 안 된다 (Codex P2).

        `record_decisions()` 가 배치 중간에 죽거나 일부 티커만 컨텍스트를 잃으면,
        행 단위 `WHERE ... IS NOT NULL` + `MAX(date)` 는 **첫 완전한 행이 들어오는 순간**
        오늘을 집어 초록이 된다 — 나머지가 빈 컨텍스트인 채로. `signals` 가 "보유
        18종목만 갱신돼도 날짜가 올라간다" 를 막은 것과 같은 축이다.

        Mutation lock: 쿼리를 `GROUP BY date HAVING SUM(...) = COUNT(*)` 에서
        행 단위 `WHERE ... IS NOT NULL` 로 되돌리면 PASS 로 뒤집힌다.
        """
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now, today_kst

        old = (kst_now() - timedelta(days=5)).strftime("%Y-%m-%d")
        self._seed(db_path, old, regime="bull_low_vol", scoring_detail='{"x":1}', ticker="AAA")
        # 오늘 배치: 한 행만 완전, 나머지는 빈 컨텍스트.
        self._seed(db_path, today_kst(), regime="bull_low_vol", scoring_detail='{"x":1}', ticker="AAA")
        self._seed(db_path, today_kst(), regime=None, scoring_detail=None, ticker="BBB")
        self._seed(db_path, today_kst(), regime=None, scoring_detail=None, ticker="CCC")

        result = check_freshness("decisions_context", db_path=db_path)
        assert result["status"] == "FAIL", result
        assert result["last_updated"].startswith(old), result

    def test_a_complete_row_today_passes(self, db_path):
        """술어가 과하게 좁아 아무것도 매칭 못 하는 회귀를 막는다."""
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import today_kst

        self._seed(db_path, today_kst(), regime="bull_low_vol", scoring_detail='{"x":1}')

        assert check_freshness("decisions_context", db_path=db_path)["status"] == "PASS"

    def test_thresholds_absorb_one_degraded_day_but_fail_before_the_third_run(self):
        """임계는 시계 없이 산술로 잠근다 — 이 정책의 설계 지점이 여기다 (Codex P2 라운드 2).

        `date` 가 00:00 KST 앵커이고 cron 이 매일 07:05 이므로:
          - 하루 degradation 이 회복되기 **직전** 나이 = 55.08h  (월 00:00 → 수 07:05)
          - 2차 연속 실패 시점 나이도 = 55.08h  ← **같은 순간 같은 나이다**
        두 시나리오를 나이로 구분할 수 없으므로, 55.08 이하 임계는 건강한 하루 회복을
        FAIL 로 만든다 (48 도 55 도 오탐). 그래서 하한이 55.08 이다.

        상한은 3차 예정 실행(목 07:05) = 79.08h — 그 전에는 FAIL 이어야 두 번 연속
        실패가 다음 실행 전에 표면화된다.

        Mutation lock: 48 이나 55 로 낮추면 하한에서 FAIL, 80 이상으로 올리면 상한에서 FAIL.
        """
        from nuri.core.freshness import FRESHNESS_POLICIES

        fail_h = FRESHNESS_POLICIES["decisions_context"]["fail_hours"]
        assert fail_h > 55.08, (
            f"fail_hours({fail_h}) 가 하루 degradation 최대 나이(55.08h) 이하 — "
            "건강한 파이프라인이 하루 걸렀다는 이유로 FAIL 한다"
        )
        assert fail_h < 79.08, (
            f"fail_hours({fail_h}) 가 3차 예정 실행 나이(79.08h) 이상 — "
            "두 번 연속 실패가 다음 실행 전에 표면화되지 않는다"
        )

    def test_a_day_old_complete_row_is_warn_not_fail(self, db_path):
        """하루 지난 완전 행은 WARN 이지 FAIL 이 아니다 (시계 무관 — 나이 24~48h)."""
        from nuri.core.freshness import check_freshness
        from nuri.core.timezone import kst_now

        yesterday = (kst_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._seed(db_path, yesterday, regime="bull_low_vol", scoring_detail='{"x":1}')

        result = check_freshness("decisions_context", db_path=db_path)
        assert 24 <= result["age_hours"] < 48, result
        assert result["status"] == "WARN", result
