"""tests/llm/ — shared fixtures for LLM tests.

Context
-------
After the 2026-04-14 OpenAI-primary refactor (§4.4.3 Tier 2), `_generate_ollama`
returns "" immediately when `OLLAMA_HOST` is empty. Most pre-existing Ollama
success-path tests were written assuming the helper would always contact the
mocked `requests.post`, so on CI (where `.env` has no OLLAMA_HOST) those tests
bypass their mocks and see "".

Rather than patching ~8 individual tests, set a non-empty OLLAMA_HOST for the
entire `tests/llm/` module. The actual HTTP call is mocked in every test, so
the value is never used for real network traffic.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_ollama_host(monkeypatch):
    """Ensure _generate_ollama's OLLAMA_HOST guard is satisfied under CI.

    Tests that need to assert the guard behavior (empty host → empty output)
    can still override via monkeypatch.setattr("nuri.llm.report.OLLAMA_HOST", "").
    """
    monkeypatch.setattr("nuri.llm.report.OLLAMA_HOST", "http://localhost:11434")
