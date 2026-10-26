"""고정 · 검사형 로컬 모델 클라이언트 — 다단계 thesis 단계 호출 (#1957).

Ollama 공식 API(`docs/api.md`)만 쓴다: `/api/version`, `/api/tags`, `/api/generate`(언로드 포함).
설정은 `config/llm_runtime.yaml` 이고 그 머리 주석이 근거(공식 문서 + 2026-10-27 실측)를 담는다.

호출 하나가 지키는 것:

1. **loopback 만** — 환경 프록시를 무시하고(`trust_env=False`) 리다이렉트를 따라가지 않는다.
   프롬프트가 비공개 맥락을 담을 수 있어서다(STRATEGY §4.4, `llm_consult.py --local-only` 와 같은 규칙).
2. **보내기 전 거부** — 공식 API 에 토큰 계산이 없어 UTF-8 바이트 + 템플릿 오버헤드를 토큰 상한으로
   쓴다. 상한 + num_predict 가 num_ctx 를 넘으면 요청 없이 거부한다. 서버는 넘친 프롬프트의 앞부분을
   오류 없이 잘라내기 때문이다.
3. **런타임 확인** — 버전 · 모델 digest 가 등록값과 다르면 호출 전에 거부한다.
4. **차가운 호출** — 공식 언로드 요청 뒤 `keep_alive: 0` 으로 부른다. 캐시 적중량이 출력을 바꾸므로
   `prompt_eval_cached_count == 0` 일 때만 결과를 채택한다.
5. **옵션 고정** — `options` 의 키가 하나라도 빠지면 서버 기본값이 끼어든다. 빠지면 거부한다.
6. **사후 검사** — 캐시 0, `done_reason == "stop"`, 평가 + 생성 토큰 ≤ num_ctx, 평가 토큰 ≤ 바이트 상한.
   마지막 것이 깨지면 상한 가정 자체가 틀린 것이다.
7. **기록** — 요청 · 응답 · 런타임 · 검사 결과를 archive 에 남긴다. `content_hash` 는 시각과 소요 시간을
   빼고 계산해 같은 입력의 차가운 호출 두 번이 같은 값을 낸다.

`canary` 는 버전 · digest 로 못 잡는 계산 경로 변화(OS 업데이트, KV 캐시 설정 등)를 잡는다.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
import yaml

from nuri.core.timezone import kst_now

CONFIG_PATH = Path("config/llm_runtime.yaml")
PINNED_OPTIONS: tuple[str, ...] = ("num_ctx", "num_predict", "temperature", "seed", "top_k", "top_p")
#: FAQ 에 문서화된 서버 환경변수 — 계산 경로를 바꿀 수 있어 런마다 기록한다.
OLLAMA_ENV: tuple[str, ...] = (
    "OLLAMA_CONTEXT_LENGTH",
    "OLLAMA_KV_CACHE_TYPE",
    "OLLAMA_FLASH_ATTENTION",
    "OLLAMA_NUM_PARALLEL",
    "OLLAMA_MAX_LOADED_MODELS",
    "OLLAMA_KEEP_ALIVE",
)
#: content_hash 에서 빼는 값 — 같은 입력이라도 매번 달라진다.
VOLATILE_RESPONSE_KEYS: frozenset[str] = frozenset(
    {"created_at", "total_duration", "load_duration", "prompt_eval_duration", "eval_duration", "context"}
)


class LocalModelError(RuntimeError):
    def __init__(self, code: str, detail: Any, record: Optional[dict[str, Any]] = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.record = record


@dataclass(frozen=True)
class Runtime:
    version: str
    digest: str
    os_version: str
    os_build: str
    ollama_env: dict[str, str]
    host: str  # 호스트명의 SHA-256 앞 12자 — 기기 식별자는 남기지 않는다


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def is_loopback(url: str) -> bool:
    host = urlsplit(url).hostname
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # HTTP_PROXY 등이 loopback 요청을 밖으로 보내지 못하게
    return s


def _get(s: Any, cfg: dict[str, Any], path: str) -> dict[str, Any]:
    r = s.get(cfg["base_url"] + path, timeout=30, allow_redirects=False)
    r.raise_for_status()
    return r.json()


def _post(s: Any, cfg: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    r = s.post(cfg["base_url"] + "/api/generate", json=body, timeout=cfg["timeout_s"], allow_redirects=False)
    r.raise_for_status()
    return r.json()


def _cmd(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def read_runtime(cfg: dict[str, Any], s: Any) -> Runtime:
    version = _get(s, cfg, "/api/version").get("version", "")
    models = _get(s, cfg, "/api/tags").get("models", [])
    digest = next((m.get("digest", "") for m in models if m.get("name") == cfg["model"]), "")
    return Runtime(
        version=version,
        digest=digest,
        os_version=_cmd(["sw_vers", "-productVersion"]),
        os_build=_cmd(["sw_vers", "-buildVersion"]),
        ollama_env={k: _cmd(["launchctl", "getenv", k]) for k in OLLAMA_ENV},
        host=hashlib.sha256(socket.gethostname().encode()).hexdigest()[:12],
    )


def check_runtime(rt: Runtime, cfg: dict[str, Any]) -> None:
    exp = cfg["expected"]
    if not rt.digest:
        raise LocalModelError("model_missing", cfg["model"])
    if rt.version != str(exp["version"]) or rt.digest != exp["digest"]:
        raise LocalModelError(
            "runtime_mismatch", {"version": rt.version, "digest": rt.digest[:12], "expected": exp["version"]}
        )


def byte_bound(prompt: str, cfg: dict[str, Any]) -> int:
    """토큰 수의 상한 — UTF-8 바이트 + 템플릿 오버헤드 (실측 근거는 config 주석)."""
    return len(prompt.encode("utf-8")) + int(cfg["template_overhead_tokens"])


def build_request(
    prompt: str, cfg: dict[str, Any], *, num_predict: Optional[int] = None, schema: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    opts = dict(cfg["options"])
    missing = [k for k in PINNED_OPTIONS if k not in opts]
    if missing:
        raise LocalModelError("unpinned_options", missing)
    if num_predict is not None:
        opts["num_predict"] = num_predict
    body: dict[str, Any] = {
        "model": cfg["model"],
        "prompt": prompt,
        "stream": False,
        "think": cfg["think"],
        "keep_alive": 0,
        "options": opts,
    }
    if schema is not None:
        body["format"] = schema
    return body


def verify_response(resp: dict[str, Any], *, bound: int, num_ctx: int, allow_length: bool = False) -> list[str]:
    failures: list[str] = []
    cached = resp.get("prompt_eval_cached_count")
    if cached is None:
        failures.append("cache_count_missing")
    elif cached != 0:
        failures.append(f"warm_cache:{cached}")
    reason = resp.get("done_reason")
    if reason != "stop" and not (allow_length and reason == "length"):
        failures.append(f"done_reason:{reason}")
    pe, ev = resp.get("prompt_eval_count"), resp.get("eval_count")
    if pe is None or ev is None:
        failures.append("token_counts_missing")
    else:
        if pe + ev > num_ctx:
            failures.append(f"context_exceeded:{pe + ev}>{num_ctx}")
        if pe > bound:
            failures.append(f"byte_bound_violated:{pe}>{bound}")
    return failures


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(record: dict[str, Any]) -> str:
    stable = {k: v for k, v in record.items() if k not in ("at", "content_hash")}
    stable["response"] = {k: v for k, v in record["response"].items() if k not in VOLATILE_RESPONSE_KEYS}
    return hashlib.sha256(_canonical(stable).encode()).hexdigest()


def _archive(record: dict[str, Any], cfg: dict[str, Any]) -> Path:
    now = kst_now()
    d = Path(cfg["archive_dir"]) / now.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.strftime('%H%M%S%f')}_{record['content_hash'][:16]}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return path


def generate(
    prompt: str,
    *,
    cfg: Optional[dict[str, Any]] = None,
    schema: Optional[dict[str, Any]] = None,
    num_predict: Optional[int] = None,
    allow_length: bool = False,
    archive: bool = True,
    session: Any = None,
) -> dict[str, Any]:
    """검사를 모두 통과한 차가운 호출 1회의 기록. 실패하면 `LocalModelError` (기록은 `.record`)."""
    cfg = cfg if cfg is not None else load_config()
    if not is_loopback(cfg["base_url"]):
        raise LocalModelError("not_loopback", cfg["base_url"])
    req = build_request(prompt, cfg, num_predict=num_predict, schema=schema)
    bound = byte_bound(prompt, cfg)
    need = bound + req["options"]["num_predict"]
    if need > req["options"]["num_ctx"]:
        raise LocalModelError("prompt_too_long", {"byte_bound": bound, "num_ctx": req["options"]["num_ctx"]})

    s = session if session is not None else _session()
    rt = read_runtime(cfg, s)
    check_runtime(rt, cfg)
    _post(s, cfg, {"model": cfg["model"], "keep_alive": 0})  # 공식 언로드 — 캐시 0 에서 시작
    resp = _post(s, cfg, req)
    failures = verify_response(resp, bound=bound, num_ctx=req["options"]["num_ctx"], allow_length=allow_length)
    record: dict[str, Any] = {
        "schema": "local_call/v1",
        "at": kst_now().isoformat(),
        "runtime": asdict(rt),
        "request": req,
        "byte_bound": bound,
        "response": resp,
        "failures": failures,
    }
    record["content_hash"] = content_hash(record)
    if archive:
        record["archive_path"] = str(_archive(record, cfg))
    if failures:
        raise LocalModelError("check_failed", failures, record)
    return record


def run_canary(cfg: Optional[dict[str, Any]] = None, *, session: Any = None) -> str:
    cfg = cfg if cfg is not None else load_config()
    c = cfg["canary"]
    rec = generate(c["prompt"], cfg=cfg, num_predict=int(c["num_predict"]), allow_length=True, session=session)
    return hashlib.sha256(rec["response"]["response"].encode()).hexdigest()


def check_canary(cfg: Optional[dict[str, Any]] = None, *, session: Any = None) -> str:
    """채점 배치 전 계산 경로 지문 확인. 미등록 · 불일치면 배치를 거부한다."""
    cfg = cfg if cfg is not None else load_config()
    registered = cfg["canary"].get("scored_sha256")
    if not registered:
        raise LocalModelError("canary_unregistered", "set canary.scored_sha256 from `--canary` on the scored host")
    got = run_canary(cfg, session=session)
    if got != registered:
        raise LocalModelError("canary_mismatch", {"got": got[:12], "registered": str(registered)[:12]})
    return got


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Pinned, overflow-checked local-model client (#1957).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--runtime", action="store_true", help="print the runtime identity and whether it matches")
    g.add_argument("--canary", action="store_true", help="run the canary and print its SHA-256")
    g.add_argument("--prompt-file", type=Path, help="run one checked call on this prompt")
    args = p.parse_args(argv)
    cfg = load_config()
    try:
        if args.runtime:
            rt = read_runtime(cfg, _session())
            print(json.dumps(asdict(rt), indent=2))
            check_runtime(rt, cfg)
            print("runtime: matches")
        elif args.canary:
            print(run_canary(cfg))
        else:
            rec = generate(args.prompt_file.read_text(), cfg=cfg)
            print(json.dumps({k: rec[k] for k in ("content_hash", "archive_path")}, indent=2))
    except LocalModelError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
