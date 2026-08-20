"""`verify_factors` 는 값의 범위가 아니라 **변별력**을 본다 (#1102).

이 단계는 원래 종목 수와 1위 점수만 요약에 찍었다. 둘 다 붕괴 상태에서 멀쩡해 보인다 —
`value_score` 가 채점 대상 773종목 중 763에서, `quality_score` 가 766에서 정확히 0.5 이던
넉 달 내내 `[OK] 팩터: 773종목, Top 105560.KS (0.728)` 이 찍혔다. 틀린 숫자가 아니라
**순위를 만들지 못하는 숫자**라 화면 어디도 이상해 보이지 않았다.

합성 스코어의 존재 이유가 순위이므로, 게이트는 퍼짐을 봐야 한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _frame(composite, value=None, quality=None, momentum=None):
    n = len(composite)
    return pd.DataFrame(
        {
            "composite_score": composite,
            "value_score": value if value is not None else np.linspace(0.05, 0.95, n),
            "quality_score": quality if quality is not None else np.linspace(0.10, 0.90, n),
            "momentum_score": momentum if momentum is not None else np.linspace(0.15, 0.85, n),
        },
        index=[f"T{i:03d}" for i in range(n)],
    ).sort_values("composite_score", ascending=False)


@pytest.fixture
def run(tmp_path, monkeypatch):
    def _run(df):
        import nuri.quant.factors.composite as comp_mod
        from scripts.verify import verify as vmod

        # `verify_factors` 는 함수 **본문 안에서** import 하므로 매 호출마다 원본 모듈에서
        # 다시 바인딩한다 — vmod 에 패치하면 아무 효과가 없다 (실제로 밟았다).
        monkeypatch.setattr(comp_mod, "compute_composite", lambda: df)
        monkeypatch.setattr(comp_mod, "print_composite", lambda _df: None)
        summary: list[str] = []
        vmod.verify_factors(tmp_path, summary)
        return summary[0]

    return _run


class TestItMeasuresDiscriminationNotRange:
    def test_a_collapsed_composite_fails(self, run):
        """실측 붕괴 분포(p10~p90 = 0.0585)는 통과하면 안 된다.

        되돌리면 이 프레임에서도 `[OK]` 가 나온다 — 그게 넉 달 동안 있었던 일이다.
        """
        line = run(_frame(np.linspace(0.4011, 0.4596, 200)))

        assert line.startswith("[FAIL]"), line
        assert "변별력" in line

    def test_a_real_distribution_passes(self, run):
        """수정 후 시뮬레이션 분포(p10~p90 = 0.2127)는 통과한다."""
        line = run(_frame(np.linspace(0.3264, 0.5391, 200)))

        assert line.startswith("[OK]"), line

    def test_a_constant_component_fails_even_when_the_total_spread_looks_fine(self, run):
        """폭만 보면 절반을 놓친다 — momentum 이 떠받치고 성분 하나만 죽는 형태 (#1102).

        정확히 이 모양이었다: composite 는 momentum 덕에 퍼져 보였지만 value/quality 는
        상수였다. 폭 단독 검사였다면 유니버스만 넓히고 정규화를 안 고친 중간 상태가
        조용히 통과한다.
        """
        n = 200
        line = run(_frame(np.linspace(0.30, 0.60, n), value=np.full(n, 0.5), quality=np.full(n, 0.5)))

        assert line.startswith("[FAIL]"), line
        assert "value_score" in line and "quality_score" in line

    def test_an_empty_frame_is_skipped_not_failed(self, run):
        """데이터가 없는 것과 변별력이 없는 것은 다르다."""
        line = run(pd.DataFrame())

        assert line.startswith("[SKIP]"), line

    def test_a_single_ticker_does_not_trip_the_constant_check(self, run):
        """종목이 1개면 어떤 성분이든 nunique 는 1 이다 — 그건 상수화가 아니라 표본 부족이다."""
        line = run(_frame(np.array([0.42])))

        assert "사실상 상수" not in line, line
