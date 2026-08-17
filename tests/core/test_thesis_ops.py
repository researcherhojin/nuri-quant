"""논지 원장 — writer 검증 · point-in-time 부착 · 버전 체인 (#1083).

이 파일이 잠그는 것은 스키마가 아니라 **설계 결정 셋**이다:

1. `decisions.thesis_id` 컬럼이 아니라 **PIT 조인** — 컬럼이면 기존 결정이 영원히 NULL,
   조인이면 첫 논지를 쓰는 순간 그 티커의 기존 결정 전부가 논지를 갖는다.
2. 조인 축은 `effective_date` (KST) 이지 `created_at` (UTC) 이 아니다.
3. writer 가 내용을 본다 — NOT NULL 로는 부족하다는 게 `rationale_json` 851/851 의 교훈.
"""

import pytest

from nuri.core.db import (
    ThesisValidationError,
    get_active_thesis,
    get_db,
    get_decision_with_evidence,
    get_thesis_history,
    init_db,
    upsert_decision,
    upsert_thesis,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


def _evidence(side="bull"):
    return [
        {
            "side": side,
            "claim": "데이터센터 매출이 4분기 연속 증가",
            "source_type": "filing",
            "source_key": "10-Q",
            "source_url": "https://example.invalid/q",
            "as_of": "2026-05-01",
            "quote": "revenue grew",
        }
    ]


def _write(db_path, **over):
    kwargs = {
        "ticker": "ZZZZ",
        "author": "user",
        "stance": "bullish",
        "bull_case": "가속기 수요가 공급을 앞선다",
        "bear_case": "고객사 자체 칩 전환이 점유율을 깎는다",
        "evidence": _evidence(),
        "effective_date": "2026-05-01",
        "status": "active",
        "db_path": db_path,
    }
    kwargs.update(over)
    return upsert_thesis(**kwargs)


class TestWriterValidation:
    """NOT NULL 은 규율이 아니다 — `agent_decisions.rationale_json` 851/851 이 그 증거."""

    def test_empty_bull_case_is_rejected(self, db_path):
        """상승 논리도 필수다 — bear 만 검사하면 한쪽만 빈 논지가 통과한다."""
        with pytest.raises(ThesisValidationError, match="bull_case"):
            _write(db_path, bull_case="")

    def test_empty_bear_case_is_rejected(self, db_path):
        """하락 논리 없는 논지는 기록이 아니라 응원가다."""
        with pytest.raises(ThesisValidationError, match="bear_case"):
            _write(db_path, bear_case="   ")

    def test_bear_case_identical_to_bull_is_rejected(self, db_path):
        """공백 검사만 있으면 bull 을 복사해 붙이는 것으로 우회된다."""
        with pytest.raises(ThesisValidationError, match="동일"):
            _write(db_path, bear_case="가속기 수요가 공급을 앞선다")

    def test_empty_evidence_is_rejected(self, db_path):
        """출처 없는 주장은 사후에 되짚을 수 없다."""
        with pytest.raises(ThesisValidationError, match="근거"):
            _write(db_path, evidence=[])

    def test_a_rejected_thesis_writes_nothing(self, db_path):
        """검증이 INSERT 앞에 있어야 한다 — 뒤면 반쪽 논지가 남는다."""
        with pytest.raises(ThesisValidationError):
            _write(db_path, evidence=[])
        assert get_thesis_history("ZZZZ", db_path=db_path) == []


class TestPointInTimeAttachment:
    """조인이지 컬럼이 아니다 — 이게 이 PR 의 설계 핵심이다."""

    def test_a_new_thesis_attaches_to_decisions_that_already_existed(self, db_path):
        """논지를 처음 쓰는 순간 그 티커의 **기존** 결정이 논지를 갖는다.

        `decisions.thesis_id` 컬럼이었다면 기존 333행이 영원히 NULL 이었을 자리다.
        Mutation lock: `get_decision_with_evidence` 의 조인 한 줄을 지우면 FAIL.
        """
        decision_id = upsert_decision(
            {"date": "2026-06-01", "ticker": "ZZZZ", "action": "BUY", "confidence": 70.0},
            db_path=db_path,
        )
        thesis_id = _write(db_path)  # 결정보다 나중에 작성

        got = get_decision_with_evidence(decision_id, db_path=db_path)
        assert got is not None
        assert got["thesis"] is not None, "기존 결정에 논지가 안 붙으면 조인이 죽은 것이다"
        assert got["thesis"]["id"] == thesis_id
        assert len(got["thesis"]["evidence"]) == 1

    def test_a_thesis_written_after_the_decision_date_does_not_attach(self, db_path):
        """`effective_date > 결정일` 이면 붙지 않는다 — 사후 논지를 사전 논지로 읽으면 안 된다."""
        decision_id = upsert_decision(
            {"date": "2026-04-01", "ticker": "ZZZZ", "action": "BUY", "confidence": 70.0},
            db_path=db_path,
        )
        _write(db_path, effective_date="2026-05-01")

        got = get_decision_with_evidence(decision_id, db_path=db_path)
        assert got is not None
        assert got["thesis"] is None, "결정 이후에 쓴 논지가 그 결정에 붙었다 — lookahead"

    def test_the_join_axis_is_effective_date_not_created_at(self, db_path):
        """`created_at` 은 UTC(`datetime('now')`) 라 KST 오전에 쓴 논지가 당일 결정에 안 붙는다.

        `created_at` 을 `effective_date` 와 어긋나게 심어 축을 직접 확인한다.
        Mutation lock: 조인을 `created_at` 으로 바꾸면 논지가 안 붙어 FAIL.
        """
        decision_id = upsert_decision(
            {"date": "2026-06-01", "ticker": "ZZZZ", "action": "BUY", "confidence": 70.0},
            db_path=db_path,
        )
        thesis_id = _write(db_path, effective_date="2026-05-01")
        with get_db(db_path) as conn:
            conn.execute("UPDATE theses SET created_at = ? WHERE id = ?", ("2026-12-31 00:00:00", thesis_id))

        got = get_decision_with_evidence(decision_id, db_path=db_path)
        assert got is not None
        assert got["thesis"] is not None, "조인이 created_at 을 보고 있다"

    def test_draft_does_not_attach_but_active_does(self, db_path):
        """LLM 초안이 사람 승격 없이 결정 화면에 사실처럼 실리면 안 된다 (§7.1 Surface 전용)."""
        _write(db_path, ticker="WWWW", status="draft")
        assert get_active_thesis("WWWW", as_of="2026-06-01", db_path=db_path) is None

        _write(db_path, ticker="VVVV", status="active")
        assert get_active_thesis("VVVV", as_of="2026-06-01", db_path=db_path) is not None

    def test_picks_the_latest_thesis_that_was_in_force(self, db_path):
        """as_of 이전 것 중 가장 늦은 것 — 최신 논지가 과거 결정을 소급 설명하면 안 된다."""
        _write(db_path, effective_date="2026-03-01", bull_case="v1 강세", bear_case="v1 약세")
        _write(db_path, effective_date="2026-07-01", bull_case="v2 강세", bear_case="v2 약세")

        got = get_active_thesis("ZZZZ", as_of="2026-06-01", db_path=db_path)
        assert got is not None
        assert got["bull_case"] == "v1 강세"


class TestVersionChain:
    """논지가 언제 어떻게 바뀌었는지가 사후 채점의 재료다 — 덮어쓰지 않는다."""

    def test_a_second_thesis_stacks_a_version_and_supersedes_the_first(self, db_path):
        first = _write(db_path, effective_date="2026-03-01")
        second = _write(db_path, effective_date="2026-07-01")

        history = get_thesis_history("ZZZZ", db_path=db_path)
        assert [h["version"] for h in history] == [2, 1]
        assert history[0]["id"] == second
        assert history[0]["supersedes_id"] == first
        assert history[1]["status"] == "superseded", "직전 active 가 안 내려가면 화면이 낡은 논지를 보여준다"

    def test_history_survives_supersession(self, db_path):
        """UPDATE 로 덮으면 v1 이 사라진다 — 반증 채점이 무엇을 채점할지 잃는다."""
        _write(db_path, effective_date="2026-03-01", bull_case="v1 강세", bear_case="v1 약세")
        _write(db_path, effective_date="2026-07-01", bull_case="v2 강세", bear_case="v2 약세")

        cases = {h["bull_case"] for h in get_thesis_history("ZZZZ", db_path=db_path)}
        assert cases == {"v1 강세", "v2 강세"}
