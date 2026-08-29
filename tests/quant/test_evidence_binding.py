"""Mixed-sample → not-measurable 잠금 (#1305) — Gotcha-Test Pair.

바인딩 유무가 섞인 표본으로 primary metric 을 계산할 수 없다는 규칙은 호출자
선택이 아니다 — "바인딩 있는 행만 필터" 가 과거 패배 증거를 떨어뜨리는 내장 편향
경로라서다 (Codex challenge P1). `require_measurable` 의 MIXED 예외를 걷어내면 FAIL.
#1307 champion-challenger 게이트가 이 모듈을 소비한다.
"""

from __future__ import annotations

import pytest

from nuri.quant.validation.evidence_binding import (
    BOUND,
    MIXED,
    UNBOUND,
    MixedEvidenceBindingError,
    binding_status,
    require_measurable,
)


class TestBindingStatus:
    def test_all_bound(self):
        assert binding_status(["abc1234", "def5678"]) == BOUND

    def test_all_unbound_is_uniform_legacy_history(self):
        """전-#1305 히스토리만으로 구성된 표본은 균질하다 — 행 간 비교가 성립한다."""
        assert binding_status([None, None]) == UNBOUND

    def test_mixed(self):
        assert binding_status(["abc1234", None]) == MIXED

    def test_empty_sample_is_unbound(self):
        """빈 표본 = 바인딩된 행 없음의 사실 서술. 표본 크기 검정은 이 모듈 소관이 아니다."""
        assert binding_status([]) == UNBOUND

    def test_generator_input(self):
        # #1307 은 쿼리 결과를 제너레이터로 흘릴 수 있다 — 1회 순회로 판정돼야 한다.
        assert binding_status(v for v in ["a", None, "b"]) == MIXED


class TestRequireMeasurable:
    def test_mixed_raises_and_names_the_forbidden_recovery(self):
        """예외 메시지가 "필터로 재시도" 를 명시적으로 금지한다 — 그게 이 규칙이 막는 편향."""
        with pytest.raises(MixedEvidenceBindingError, match="필터"):
            require_measurable(["abc1234", None], context="alpha 7d")

    def test_uniform_samples_pass_through_with_status(self):
        assert require_measurable(["a", "b"]) == BOUND
        assert require_measurable([None]) == UNBOUND

    def test_the_error_is_a_value_error(self):
        """소비자가 기존 ValueError 처리 경로로 잡을 수 있다 — 단, 삼켜서 필터로 우회하면
        그건 코드 리뷰가 막을 일이다 (invariants.md mixed-sample 규칙)."""
        assert issubclass(MixedEvidenceBindingError, ValueError)
