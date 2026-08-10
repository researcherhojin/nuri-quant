"""매크로 종합 점수 — 결측 성분을 지어내지 않는다 (#1026).

`compute_macro_score` 는 입력이 없는 성분에 **50.0(중립)을 채워 그대로 가중합**했다.
50 은 중립이라 무해해 보이지만 총점을 가운데로 끌어당기는 방향성 있는 힘이다.

2026-08-11 프로덕션 실측: `FRED_API_KEY` 미설정으로 FRED 전용 지표 **8개 전부 0행** (#1025)
(`cpi_yoy` · `unemployment` · `us_3m_yield` 등). 9개 성분 중 3개가 결측이라 가중치
0.324 만큼 50 이 들어갔고 총점은 **64.4 "Neutral"** — 재정규화하면 **71.3 "Favorable"**
로 해석 경계를 넘는다. 지어낸 중립이 우호적 판독을 눌러 온 것이다.

코드는 이미 결측을 감지해 `warnings` 에 담고 있었는데 **읽는 소비처가 0개**였고 로그도
debug 레벨이었다. 감지가 있어도 아무 데도 안 닿으면 없는 것과 같다.

정책은 STRATEGY §2.6 의 **점수 성분** 조항(#1019 선례): 값을 지어내지 말고 성분을 빼고
나머지를 비례 재정규화. 여기에 coverage 를 함께 내보내 얇은 표본이 확신 라벨로 읽히지
않게 한다.
"""

from __future__ import annotations

import pytest

from nuri.core.db import upsert_macro
from nuri.core.timezone import today_kst
from nuri.quant.regime.macro_score import WEIGHTS, compute_macro_score


def _seed(db_path, **indicators):
    today = today_kst()
    upsert_macro(
        [{"indicator": k, "date": today, "value": v, "source": "test"} for k, v in indicators.items()],
        db_path,
    )


class TestMissingComponentsAreDroppedNotInvented:
    def test_absent_component_is_excluded_from_the_weighting(self, db_path):
        """결측 성분이 50.0 으로 가중되면 안 된다 — coverage 가 그 사실을 드러낸다."""
        _seed(db_path, vix=15.0)
        score = compute_macro_score(db_path=db_path)
        assert score.coverage < 1.0, "결측이 있는데 coverage 가 1.0 이면 지어낸 값을 세고 있는 것"
        # 측정된 건 vix 와 event 뿐 — 나머지는 빠져야 한다.
        assert score.coverage == pytest.approx(WEIGHTS["vix"] + WEIGHTS["event"], abs=1e-6)

    def test_coverage_is_one_when_everything_is_present(self, db_path):
        _seed(
            db_path,
            us_10y_yield=4.5,
            us_2y_yield=3.7,
            us_3m_yield=4.0,
            vix=15.0,
            put_call_ratio=1.0,
            fear_greed=60.0,
            unemployment=4.0,
            cpi_yoy=2.1,
            fed_funds_rate=3.5,
        )
        score = compute_macro_score(db_path=db_path)
        assert score.coverage == pytest.approx(1.0, abs=1e-6)
        assert score.interpretation != "Insufficient"

    def test_thin_coverage_is_labelled_insufficient(self, db_path):
        """얇은 표본은 'Favorable' 같은 확신 라벨을 달지 못한다."""
        _seed(db_path, vix=10.0)  # VIX 10 → 성분 점수 100, 재정규화하면 총점이 매우 높다
        score = compute_macro_score(db_path=db_path)
        assert score.coverage < 0.6
        assert score.interpretation == "Insufficient", (
            f"커버리지 {score.coverage:.0%} 인데 '{score.interpretation}' 로 표기했다 — "
            "두 성분짜리 점수가 확신 라벨을 달면 안 된다"
        )

    def test_renormalized_total_is_not_dragged_toward_fifty(self, db_path):
        """결측 성분에 50 을 채우던 시절의 실제 사고를 재현한다.

        측정된 성분이 전부 100 점이면 총점도 100 이어야 한다. 예전엔 결측분에 50 이
        들어가 총점이 그만큼 끌려 내려갔다.
        """
        _seed(db_path, vix=10.0, fear_greed=50.0)  # 둘 다 최고점 구간
        score = compute_macro_score(db_path=db_path)
        measured = [score.vix_score, score.sentiment_score]
        assert all(m > 95 for m in measured), f"픽스처가 최고점 구간이 아니다: {measured}"
        # event 성분이 섞여 정확히 100 은 아니지만, 50 폴백이 살아있다면 60 대로 눌린다.
        assert score.total_score > 80, (
            f"총점 {score.total_score} — 결측 성분이 여전히 50 으로 가중되고 있다 (coverage={score.coverage})"
        )

    def test_missing_inputs_are_reported(self, db_path):
        """감지가 로그에만 남고 아무 데도 안 닿던 상태를 배제."""
        _seed(db_path, vix=15.0)
        score = compute_macro_score(db_path=db_path)
        assert score.warnings, "결측이 있는데 warnings 가 비어 있다"
        assert any("cpi_yoy" in w or "inflation" in w for w in score.warnings)


class TestDashboardSurfacesCoverage:
    def test_macro_payload_carries_coverage(self, db_path, monkeypatch):
        """대시보드가 점수만 보내고 커버리지를 숨기면 68% 가 100% 처럼 읽힌다."""
        import nuri.api.routes.dashboard as dash

        monkeypatch.setattr(dash, "compute_macro_score", None, raising=False)
        _seed(db_path, vix=15.0)
        payload = dash._get_macro()
        assert "coverage" in payload, "macro payload 에 coverage 가 없다"

    def test_failure_is_not_labelled_neutral(self, monkeypatch):
        """계산 실패를 'Neutral' 로 적으면 장애가 정상 판독으로 둔갑한다."""
        import nuri.api.routes.dashboard as dash

        def boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr("nuri.quant.regime.macro_score.compute_macro_score", boom)
        payload = dash._get_macro()
        assert payload["interpretation"] == "Unavailable"
        assert payload["coverage"] == 0.0
