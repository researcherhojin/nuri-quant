"""로컬 전용 경로의 모델 검사 (#1969) — 루프백 URL 뒤의 Ollama Cloud 모델을 거부한다.

Ollama 앱의 Cloud 설정이 켜져 있으면 cloud 모델은 `127.0.0.1:11434` 로 불러도 Ollama 서버에서 돈다
("Ollama processes cloud prompts and responses", docs.ollama.com/cloud). URL 이 루프백인지만 보는 검사는
이걸 통과시킨다 — 비공개 맥락이 기기 밖으로 나간다.

판정 (공식 문서 근거):
- `/api/tags` 의 모델 항목은 원격일 때 `remote_model` · `remote_host` 를 가진다(docs.ollama.com/api/tags).
  목록에 없거나 이 필드가 있으면 거부한다.
- 이름 규칙 `:cloud`(docs.ollama.com/cloud) 와 앱에 보이는 `-cloud` 접미사도 거부한다 — 목록 검사가 깨져도
  남는 두 번째 겹.
- 목록을 못 읽으면 거부한다(실패 시 닫힘). 단 `/api/tags` 가 없는 서버(Strata 등 OpenAI 호환 전용)는 Ollama 가
  아니므로 이름 검사만 한다 — `require_ollama=False` 일 때.

로컬 서버를 끄는 대신 cloud 자체를 끄려면 `OLLAMA_NO_CLOUD=1` 또는 `~/.ollama/server.json` 의
`"disable_ollama_cloud": true` (docs.ollama.com/faq) — 기기 설정이라 코드가 강제하지 않는다.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlsplit

import requests

_CLOUD_NAME = re.compile(r"(?:^|[:\-])cloud$", re.IGNORECASE)


def _root(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _same(name: str, model: str) -> bool:
    # 태그 없는 이름은 Ollama 에서 `:latest` 다
    def norm(n: str) -> str:
        return n if ":" in n else f"{n}:latest"

    return norm(name) == norm(model)


def refuse_reason(base_url: str, model: str, *, require_ollama: bool = True, timeout: float = 5.0) -> Optional[str]:
    """거부 사유, 통과면 None. 사유 문자열에 URL 은 넣지 않는다(로그 · Discord 로 env 값이 새지 않게)."""
    if not model or _CLOUD_NAME.search(model):
        return "cloud or empty model name"
    session = requests.Session()
    session.trust_env = False  # 루프백 요청도 환경 프록시로 나간다 (llm_consult 의 같은 이유)
    try:
        resp = session.get(_root(base_url) + "/api/tags", timeout=timeout, allow_redirects=False)
    except requests.RequestException as e:
        return f"model list unavailable ({type(e).__name__})"
    if resp.status_code == 404 and not require_ollama:
        return None  # Ollama 가 아닌 로컬 서버 — 이름 검사만
    if resp.status_code != 200:
        return f"model list unavailable (HTTP {resp.status_code})"
    try:
        models: list[dict[str, Any]] = resp.json().get("models") or []
    except ValueError:
        return "model list unreadable"
    entry = next((m for m in models if _same(str(m.get("name") or m.get("model") or ""), model)), None)
    if entry is None:
        return "model not installed locally"
    if entry.get("remote_model") or entry.get("remote_host"):
        return "remote model"
    return None
