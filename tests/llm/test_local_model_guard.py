"""로컬 모델 가드 (#1969) — 루프백 URL 뒤의 Ollama cloud 모델 거부.

전역 conftest 가 가드를 통과로 바꿔 두므로, 여기서는 import 시점에 잡은 진짜 함수를 부른다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from nuri.llm import local_model_guard as guard

REAL = guard.refuse_reason
URL = "http://127.0.0.1:11434"


class FakeSession:
    def __init__(self, status=200, payload=None, exc=None):
        self.status, self.payload, self.exc = status, payload, exc
        self.trust_env = True
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw, self.trust_env))
        if self.exc:
            raise self.exc

        def js():
            if isinstance(self.payload, Exception):
                raise self.payload
            return self.payload

        return SimpleNamespace(status_code=self.status, json=js)


def run(model, *, require_ollama=True, url=URL, **session_kw):
    s = FakeSession(**session_kw)
    with patch.object(guard.requests, "Session", lambda: s):
        return REAL(url, model, require_ollama=require_ollama), s


LOCAL = {"models": [{"name": "gemma4:26b-a4b-it-qat", "digest": "d"}, {"name": "bge-m3:latest", "digest": "e"}]}


@pytest.mark.parametrize("model", ["kimi-k3:cloud", "gemma4:31b-cloud", "glm-5.3:CLOUD", "cloud", ""])
def test_cloud_names_are_refused_without_a_request(model):
    reason, s = run(model, payload=LOCAL)
    assert reason == "cloud or empty model name" and s.calls == []


def test_an_installed_local_model_passes_and_the_lookup_skips_proxies_and_redirects():
    reason, s = run("gemma4:26b-a4b-it-qat", url=URL + "/v1/chat/completions", payload=LOCAL)
    assert reason is None
    (url, kw, trust_env) = s.calls[0]
    assert url == URL + "/api/tags" and kw["allow_redirects"] is False and trust_env is False


def test_an_untagged_name_means_latest():
    assert run("bge-m3", payload=LOCAL)[0] is None


@pytest.mark.parametrize(
    ("entry", "want"),
    [
        ({"name": "glm-5.3", "remote_model": "glm-5.3", "remote_host": "https://ollama.com:443"}, "remote model"),
        ({"name": "glm-5.3", "remote_host": "https://ollama.com:443"}, "remote model"),
        ({"model": "glm-5.3", "remote_model": "glm-5.3"}, "remote model"),
    ],
)
def test_a_remote_entry_is_refused_even_with_a_plain_name(entry, want):
    """docs.ollama.com/api/tags: 원격 모델은 remote_model · remote_host 를 가진다 — 이름 규칙이 없어도 잡는다."""
    assert run("glm-5.3", payload={"models": [entry]})[0] == want


def test_a_model_not_installed_is_refused():
    assert run("qwen3.8:27b", payload=LOCAL)[0] == "model not installed locally"


@pytest.mark.parametrize(
    ("kw", "want"),
    [
        ({"exc": requests.ConnectionError("down")}, "model list unavailable (ConnectionError)"),
        ({"status": 500}, "model list unavailable (HTTP 500)"),
        ({"status": 404}, "model list unavailable (HTTP 404)"),
        ({"payload": ValueError("not json")}, "model list unreadable"),
        ({"payload": {}}, "model not installed locally"),
    ],
)
def test_it_fails_closed(kw, want):
    assert run("gemma4:26b-a4b-it-qat", **kw)[0] == want


def test_a_non_ollama_server_gets_the_name_check_only_when_allowed():
    """Strata(OpenAI 호환 전용)는 /api/tags 가 404 다 (2026-10-27 실측)."""
    assert run("qwen3.8-flash", require_ollama=False, status=404)[0] is None
    assert run("x:cloud", require_ollama=False, status=404)[0] == "cloud or empty model name"
    assert run("qwen3.8-flash", require_ollama=False, status=500)[0] == "model list unavailable (HTTP 500)"


def test_the_reason_never_contains_the_url():
    reason, _ = run("m", url="http://127.0.0.1:9999", exc=requests.ConnectionError("http://127.0.0.1:9999 refused"))
    assert reason is not None and "9999" not in reason
