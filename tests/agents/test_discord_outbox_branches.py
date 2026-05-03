"""Branch coverage tests for nuri.agents.discord.outbox.

Targets residual branches uncovered by test_discord_outbox.py:
- L83: _truncate(None) → "" (defensive — caller passes Discord-coerced None).
- L86: _truncate over-limit appends ellipsis sentinel.
- L118 / L138 / L158: stage_ops / stage_incident / stage_rollout helpers must
  route to their channels (sibling of stage_brief). Lock-test ensures channel
  collision regression caught.
- L230-233: privacy gate raise → fail-closed (return None) + WARNING log.
- L289 / L292-293: _format_price_levels fmt fallback for None and unparseable
  values — surfaces "—" instead of crashing.
- L306: all price_levels keys None → return None.
- L312-313: invalid trailing_pct (non-numeric) silently dropped.
- L420 / L489: bucket digest stops adding fields once _MAX_FIELDS hit.
- L450: empty events list to bucket_generic_digest yields no-op embed.
- L476-478: generic digest enforces FIELD_VALUE_MAX truncation with overflow
  marker.

Privacy: synthetic ticker TST_*. No broker/PnL.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from nuri.agents.discord.outbox import (
    _MAX_FIELDS,
    _format_price_levels,
    _truncate,
    bucket_brief_digest,
    bucket_generic_digest,
    stage_agent_dev_log,
    stage_incident,
    stage_ops,
    stage_rollout,
)
from nuri.core.db import claim_pending_outbox, init_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "outbox_branches.db"
    init_db(path)
    return path


# ════════════════════════════════════════════════════════════
# L83 / L86 — _truncate edge cases
# ════════════════════════════════════════════════════════════


class TestTruncateDefensive:
    def test_none_returns_empty_string(self):
        """L82-83: None 입력 → "". Discord embed builder가 None 도 던져 들어올 수 있음.

        Regression: 이 가드 제거 시 `len(None)` TypeError.
        """
        assert _truncate(None, 100) == ""  # type: ignore[arg-type]

    def test_overflow_appends_ellipsis(self):
        """L86: text 길이 > limit → 잘리고 명시적 ellipsis (…) 첨부.

        Regression: 잘못된 슬라이스 한계 시 limit 초과 또는 marker 누락.
        """
        out = _truncate("x" * 50, 10)
        assert len(out) == 10
        assert out.endswith("…")
        assert out.count("x") == 9


# ════════════════════════════════════════════════════════════
# L118 / L138 / L158 — stage_* routing lock-tests
# ════════════════════════════════════════════════════════════


class TestStageHelpersRouting:
    def test_stage_ops_routes_to_ops_channel_only(self, db_path):
        """L117-118: stage_ops payload 가 ops 채널에만 들어감.

        Regression: channel string 오타 시 다른 채널로 누설.
        """
        stage_ops({"kind": "alert", "summary": "x"}, db_path=db_path)
        _, ops_rows = claim_pending_outbox("ops", db_path=db_path)
        assert len(ops_rows) == 1 and ops_rows[0]["payload"]["kind"] == "alert"
        # 다른 채널 누설 검증.
        for c in ("brief", "incidents", "rollout"):
            _, leak = claim_pending_outbox(c, db_path=db_path)
            assert leak == [], f"누설 detected on {c}"

    def test_stage_incident_routes_to_incidents_channel(self, db_path):
        """L137-138: stage_incident → incidents 채널 정확."""
        stage_incident({"kind": "db_lock", "severity": "critical"}, db_path=db_path)
        _, rows = claim_pending_outbox("incidents", db_path=db_path)
        assert rows[0]["payload"]["kind"] == "db_lock"

    def test_stage_rollout_routes_to_rollout_channel(self, db_path):
        """L157-158: stage_rollout → rollout 채널 정확."""
        stage_rollout({"kind": "deploy", "version": "1.2.3"}, db_path=db_path)
        _, rows = claim_pending_outbox("rollout", db_path=db_path)
        assert rows[0]["payload"]["version"] == "1.2.3"


# ════════════════════════════════════════════════════════════
# L230-233 — privacy gate fail-closed on raise
# ════════════════════════════════════════════════════════════


class TestPrivacyGateFailClosed:
    def test_gate_raise_blocks_publish_and_logs_warning(self, db_path, caplog):
        """L230-233: _privacy_gate_payload 가 raise 하면 fail-closed (None 반환) + WARNING.

        Regression: fail-open 시 gate 일시 장애가 ticker+PnL leak 통과 가능.
        """
        caplog.set_level(logging.WARNING)
        with patch(
            "nuri.agents.discord.outbox._privacy_gate_payload",
            side_effect=RuntimeError("scanner offline"),
        ):
            rc = stage_agent_dev_log({"step": "spec", "summary": "ok"}, db_path=db_path)
        assert rc is None  # 차단
        _, rows = claim_pending_outbox("agent_dev_log", db_path=db_path)
        assert rows == []  # outbox 에 안 들어감
        # WARNING 로그 — fail-closed 사유 명시.
        assert any("privacy gate raised" in rec.message for rec in caplog.records)


# ════════════════════════════════════════════════════════════
# L289 / L292-293 / L306 / L312-313 — _format_price_levels edge cases
# ════════════════════════════════════════════════════════════


class TestFormatPriceLevelsEdges:
    def test_none_entry_omitted_partial_render(self):
        """entry=None → "entry" 절 자체가 omit (None pre-check at L297).

        Regression: pre-check 누락 시 _fmt_price(None) 분기 reach.
        """
        out = _format_price_levels({"entry": None, "stop": 90, "tp1": 110, "tp2": 130})
        assert out is not None
        assert "entry" not in out  # entry 자체 omit
        assert "$90.00" in out  # stop 은 정상

    def test_zero_value_under_1000_uses_two_decimal(self):
        """L294: f < 1000 → ${:,.2f} 포맷, ≥ 1000 → ${:,.0f}.

        BUY/SELL recommendation 표기 일관성 — KR 70000 는 .0f, US 132.14 는 .2f.
        Regression: 분기 inversion 시 큰 가격에 소수점 두 자리 noise.
        """
        small = _format_price_levels({"entry": 50.5, "stop": 47.3, "tp1": None, "tp2": None})
        big = _format_price_levels({"entry": 70000, "stop": 65000, "tp1": None, "tp2": None})
        assert small is not None and big is not None
        assert "$50.50" in small
        assert "$70,000" in big
        assert "$70,000.00" not in big  # 큰 값은 소수점 0자리

    def test_unparseable_value_renders_em_dash(self):
        """L290-293: float() 실패 (e.g. 'N/A') → '—'.

        Regression: 잘못된 직렬화 (TypeError/ValueError) 가 publish 전체 abort.
        """
        out = _format_price_levels({"entry": "N/A", "stop": 90, "tp1": 110, "tp2": 130})
        assert out is not None
        assert "entry —" in out

    def test_all_none_returns_none(self):
        """L305-306: 모든 entry/stop/tp1/tp2 None → 전체 None (caller omit).

        Regression: 빈 head ('  ↳ ') 가 embed 에 새서 사용자 noise.
        """
        out = _format_price_levels({"entry": None, "stop": None, "tp1": None, "tp2": None})
        assert out is None

    def test_invalid_trailing_pct_dropped_silently(self):
        """L308-313: trailing_pct 가 non-numeric 이면 trail 절 제거 + 다른 필드 정상.

        Regression: trailing 파싱 실패가 전체 line 을 None 으로 만들면 안 됨.
        """
        out = _format_price_levels({"entry": 100, "stop": 93, "tp1": 120, "tp2": 140, "trailing_pct": "bad"})
        assert out is not None
        assert "entry $100" in out
        assert "trail" not in out  # trail 절 omit


# ════════════════════════════════════════════════════════════
# L420 / L489 — _MAX_FIELDS breakout
# ════════════════════════════════════════════════════════════


class TestMaxFieldsBreakout:
    def test_brief_digest_caps_at_max_fields(self):
        """L419-420: bucket count 가 _MAX_FIELDS 초과 시 cap.

        Regression: cap 제거 시 Discord 25-field 한계 초과로 publish 실패.
        실제로는 brief 가 3 bucket 만 만드므로 _MAX_FIELDS=25 cap 도달 어려움 —
        그래도 fields ≤ _MAX_FIELDS 성질 자체를 검증.
        """
        events = [{"kind": "BUY", "ticker": f"TST_{i}", "conviction": 0.8} for i in range(50)]
        embed = bucket_brief_digest(events)
        assert len(embed["fields"]) <= _MAX_FIELDS

    def test_generic_digest_caps_at_max_fields(self):
        """L488-489: generic digest 도 _MAX_FIELDS 캡 적용 (group 종류 폭주 방지).

        많은 distinct kind → _MAX_FIELDS+1 그룹이라도 결과 fields ≤ cap.
        """
        events = [{"kind": f"k_{i}", "summary": f"s {i}"} for i in range(_MAX_FIELDS + 5)]
        embed = bucket_generic_digest(events, channel_label="Test")
        assert len(embed["fields"]) <= _MAX_FIELDS


# ════════════════════════════════════════════════════════════
# L450 — empty generic digest
# ════════════════════════════════════════════════════════════


class TestGenericDigestEmpty:
    def test_empty_events_returns_no_op_embed(self):
        """L449-450: events=[] → no-op embed (title 'Digest | 0 events')."""
        embed = bucket_generic_digest([], channel_label="Ops")
        assert "0 events" in embed["title"]
        assert embed["fields"] == []
        assert embed["description"] == "(no pending events)"


# ════════════════════════════════════════════════════════════
# L476-478 — generic digest field-value truncation
# ════════════════════════════════════════════════════════════


class TestGenericDigestTruncation:
    def test_field_value_capped_with_overflow_marker(self):
        """L475-478: 한 group 내 라인 합계가 _FIELD_VALUE_MAX 초과 시 잘리고 '… (+N more)'.

        Regression: 누적 길이 무체크 시 Discord 의 1024-char field-value 한계 위반
        → publish 실패.
        """
        # 한 그룹에 같은 kind 이벤트 다수 — 길이 200+ 로 빠르게 축적.
        events = [{"kind": "noise", "summary": "x" * 200} for _ in range(20)]
        embed = bucket_generic_digest(events, channel_label="Ops")
        assert len(embed["fields"]) >= 1
        for field in embed["fields"]:
            assert len(field["value"]) <= 1024
        # 적어도 하나의 field 에 overflow 마커 존재.
        joined = " ".join(f["value"] for f in embed["fields"])
        assert "more)" in joined  # "… (+N more)" 마커
