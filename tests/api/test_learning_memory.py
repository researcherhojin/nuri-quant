"""Tests for /api/learning-memory/readiness — #468 codex Round 1 #6."""


class TestLearningMemoryReadiness:
    """Per-agent source surface API."""

    def test_endpoint_returns_200_with_per_agent_list(self, client):
        """GET /api/learning-memory/readiness 응답 200 + per-agent 배열."""
        # 캐시 reset
        import nuri.api.routes.learning_memory as lm_mod
        lm_mod._cache["data"] = None
        lm_mod._cache["ts"] = 0.0

        resp = client.get("/api/learning-memory/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "summary" in data
        assert isinstance(data["agents"], list)
        assert len(data["agents"]) == 10  # DEFAULT_WEIGHTS 등재 agent 수

    def test_response_shape_includes_per_horizon_breakdown(self, client):
        """각 agent 응답에 canonical_30d / provisional_21d 분리 정보 포함."""
        import nuri.api.routes.learning_memory as lm_mod
        lm_mod._cache["data"] = None
        lm_mod._cache["ts"] = 0.0

        resp = client.get("/api/learning-memory/readiness")
        data = resp.json()
        first = data["agents"][0]
        assert "name" in first
        assert "default_weight" in first
        assert "final_weight" in first
        assert "source" in first
        assert "canonical_30d" in first
        assert "provisional_21d" in first
        assert "sample_count" in first["canonical_30d"]
        assert "eligible" in first["canonical_30d"]

    def test_summary_categories_match_codex_taxonomy(self, client):
        """summary 카테고리 4개 (canonical / provisional / default / unsaturating)."""
        import nuri.api.routes.learning_memory as lm_mod
        lm_mod._cache["data"] = None
        lm_mod._cache["ts"] = 0.0

        resp = client.get("/api/learning-memory/readiness")
        summary = resp.json()["summary"]
        assert set(summary.keys()) == {
            "canonical_30d", "provisional_21d", "default", "structurally_unsaturating",
        }
        # 카운트 합 = 10 agents
        assert sum(summary.values()) == 10

    def test_cache_hit_returns_cached_payload(self, client):
        """5분 in-memory 캐시 — TTL 내 재호출은 캐시된 응답 반환."""
        import time as _time

        import nuri.api.routes.learning_memory as lm_mod

        lm_mod._cache["data"] = {"cached": True, "agents": [], "summary": {}}
        lm_mod._cache["ts"] = _time.time()

        resp = client.get("/api/learning-memory/readiness")
        assert resp.json().get("cached") is True

        # cleanup
        lm_mod._cache["data"] = None
        lm_mod._cache["ts"] = 0.0
