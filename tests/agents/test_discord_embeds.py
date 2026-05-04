"""Discord embed builder tests (#529 Phase 2 polish).

Builders are pure functions — no Discord SDK / network. Bot slash handlers
remain `# pragma: no cover` (Interaction mock cost > value, established convention).

검증:
- 4 builder 의 title / color / footer 기본값
- body > 4000 → truncate + ellipsis
- fields > 25 → 24 + "(+N more)" 요약 (raise X — 알림 손실 방지)
- freshness PASS/WARN/FAIL color routing
- actor outcome → color 매핑 4종 (pass/warn/block/error) + unknown fallback
- field/footer 길이 제약
"""

from __future__ import annotations

from nuri.agents.discord.embeds import (
    COLOR_AMBER,
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_RED,
    DESCRIPTION_MAX,
    FIELD_NAME_MAX,
    FIELD_VALUE_MAX,
    FOOTER_MAX,
    MAX_FIELDS,
    TITLE_MAX,
    build_actor_outcome_embed,
    build_freshness_embed,
    build_status_embed,
    build_warn_embed,
)


class TestBuildStatusEmbed:
    def test_success_is_green(self):
        e = build_status_embed("Hi", success=True, body="ok", fields=None)
        assert e["title"] == "Hi"
        assert e["color"] == COLOR_GREEN
        assert e["description"] == "ok"
        assert e["footer"]["text"]  # 기본 footer 채워짐

    def test_failure_is_red(self):
        e = build_status_embed("Bad", success=False, body="boom", fields=None)
        assert e["color"] == COLOR_RED

    def test_fields_become_inline(self):
        e = build_status_embed("T", success=True, body="b", fields={"k1": "v1", "k2": "v2"})
        assert len(e["fields"]) == 2
        assert e["fields"][0]["name"] == "k1"
        assert e["fields"][0]["value"] == "v1"
        assert e["fields"][0]["inline"] is True

    def test_custom_footer(self):
        e = build_status_embed("T", success=True, body="b", fields=None, footer="custom")
        assert e["footer"]["text"] == "custom"

    def test_body_truncated_when_over_limit(self):
        big = "x" * (DESCRIPTION_MAX + 500)
        e = build_status_embed("T", success=True, body=big, fields=None)
        assert len(e["description"]) == DESCRIPTION_MAX
        assert e["description"].endswith("…")

    def test_title_truncated(self):
        e = build_status_embed("y" * (TITLE_MAX + 50), success=True, body="b", fields=None)
        assert len(e["title"]) == TITLE_MAX
        assert e["title"].endswith("…")

    def test_footer_truncated(self):
        e = build_status_embed("T", success=True, body="b", fields=None, footer="z" * (FOOTER_MAX + 20))
        assert len(e["footer"]["text"]) == FOOTER_MAX
        assert e["footer"]["text"].endswith("…")

    def test_field_value_truncated(self):
        long_val = "v" * (FIELD_VALUE_MAX + 10)
        e = build_status_embed("T", success=True, body="b", fields={"k": long_val})
        assert len(e["fields"][0]["value"]) == FIELD_VALUE_MAX
        assert e["fields"][0]["value"].endswith("…")

    def test_field_name_truncated(self):
        long_name = "n" * (FIELD_NAME_MAX + 5)
        e = build_status_embed("T", success=True, body="b", fields={long_name: "v"})
        assert len(e["fields"][0]["name"]) == FIELD_NAME_MAX

    def test_empty_fields_dict_yields_no_fields(self):
        e = build_status_embed("T", success=True, body="b", fields={})
        assert e["fields"] == []


class TestBuildWarnEmbed:
    def test_color_amber(self):
        e = build_warn_embed("Stale", "120h old", fields={"k": "v"})
        assert e["color"] == COLOR_AMBER
        assert e["title"] == "Stale"
        assert e["description"] == "120h old"

    def test_default_footer_present(self):
        e = build_warn_embed("T", "b")
        assert e["footer"]["text"]


class TestFieldOverflow:
    def test_fields_over_25_truncates_with_summary(self):
        # 30 fields → 24 kept + 1 "(+6 more)" summary = 25 total
        many = {f"k{i}": f"v{i}" for i in range(30)}
        e = build_status_embed("T", success=True, body="b", fields=many)
        assert len(e["fields"]) == MAX_FIELDS
        # 마지막 field 가 overflow 요약
        last = e["fields"][-1]
        assert "more" in last["value"]
        assert "+6" in last["value"]

    def test_fields_exactly_25_no_truncation(self):
        many = {f"k{i}": f"v{i}" for i in range(MAX_FIELDS)}
        e = build_status_embed("T", success=True, body="b", fields=many)
        assert len(e["fields"]) == MAX_FIELDS
        # 마지막 값에 "more" overflow 요약 없음
        assert "more" not in e["fields"][-1]["value"]


class TestBuildFreshnessEmbed:
    def _result(self, key: str, status: str, age: float = 12.5) -> dict:
        return {"key": key, "status": status, "age_hours": age, "label": key}

    def test_all_pass_is_green(self):
        results = [self._result("prices", "PASS"), self._result("vix", "PASS")]
        e = build_freshness_embed(results)
        assert e["color"] == COLOR_GREEN
        assert "2/2 PASS" in e["title"]

    def test_any_warn_is_amber(self):
        results = [self._result("prices", "PASS"), self._result("vix", "WARN")]
        e = build_freshness_embed(results)
        assert e["color"] == COLOR_AMBER
        assert "1/2 PASS" in e["title"]

    def test_any_fail_is_red_dominates_warn(self):
        results = [
            self._result("prices", "PASS"),
            self._result("vix", "WARN"),
            self._result("recs", "FAIL"),
        ]
        e = build_freshness_embed(results)
        assert e["color"] == COLOR_RED
        assert "1/3 PASS" in e["title"]

    def test_field_format_status_age(self):
        results = [self._result("prices", "PASS", 24.0)]
        e = build_freshness_embed(results)
        assert len(e["fields"]) == 1
        assert e["fields"][0]["name"] == "prices"
        assert "PASS" in e["fields"][0]["value"]
        assert "24.0h" in e["fields"][0]["value"]

    def test_missing_age_renders_na(self):
        results = [{"key": "x", "status": "PASS", "age_hours": None}]
        e = build_freshness_embed(results)
        assert "n/a" in e["fields"][0]["value"]

    def test_empty_results(self):
        e = build_freshness_embed([])
        assert e["color"] == COLOR_GREEN  # 0/0 → 모든 PASS 로 간주 (no FAIL/WARN)
        assert "0/0 PASS" in e["title"]
        assert e["fields"] == []


class TestBuildActorOutcomeEmbed:
    def test_pass_is_green(self):
        e = build_actor_outcome_embed("freshness-gatekeeper", "pass", "all checks ok", "run-1")
        assert e["color"] == COLOR_GREEN
        assert "freshness-gatekeeper" in e["title"]
        assert "PASS" in e["title"]
        assert "run-1" in e["footer"]["text"]

    def test_warn_is_amber(self):
        e = build_actor_outcome_embed("actor", "warn", "soft penalty", "r2")
        assert e["color"] == COLOR_AMBER
        assert "WARN" in e["title"]

    def test_block_is_red(self):
        e = build_actor_outcome_embed("actor", "block", "veto fired", "r3")
        assert e["color"] == COLOR_RED
        assert "BLOCK" in e["title"]

    def test_error_is_red(self):
        e = build_actor_outcome_embed("actor", "error", "exception raised", "r4")
        assert e["color"] == COLOR_RED
        assert "ERROR" in e["title"]

    def test_unknown_outcome_falls_back_to_blue(self):
        e = build_actor_outcome_embed("actor", "weird", "?", "r5")
        assert e["color"] == COLOR_BLUE
        assert "WEIRD" in e["title"]

    def test_uppercases_outcome_in_title(self):
        e = build_actor_outcome_embed("a", "pass", "s", "r")
        assert "→ PASS" in e["title"]

    def test_summary_truncated(self):
        big = "z" * (DESCRIPTION_MAX + 100)
        e = build_actor_outcome_embed("a", "pass", big, "r")
        assert len(e["description"]) == DESCRIPTION_MAX

    def test_run_id_in_footer(self):
        e = build_actor_outcome_embed("a", "pass", "s", "abc-123")
        assert "abc-123" in e["footer"]["text"]


class TestTruncateNoneDefensive:
    """_truncate(None, ...) None-input defensive guard (line 70)."""

    def test_none_input_returns_empty_string(self):
        from nuri.agents.discord.embeds import _truncate

        # Coverage: line 70 — None 입력 시 빈 문자열 반환
        assert _truncate(None, 100) == ""
