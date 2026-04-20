"""E4-0a post-deploy — 전체 API endpoint GET smoke.

openapi.json 에서 모든 GET path 를 enumerate → required path/query param 이 없는
endpoint 만 호출 → status/latency/response shape 검증 → JSON 리포트.

사용: .venv/bin/python scripts/e4_0a_api_smoke.py
전제: `make start` 로 backend :8001 구동 중
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

BASE = "http://localhost:8001"


@dataclass
class EndpointReport:
    path: str
    method: str
    required_params: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    status: int | None = None
    latency_ms: float | None = None
    error: str | None = None
    response_size: int | None = None
    response_shape: str = ""  # "dict:N keys" / "list:N items" / ...
    sample: str = ""  # 처음 200자


def _get(url: str, timeout: float = 15.0) -> tuple[int, bytes, float]:
    t0 = time.time()
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            latency = (time.time() - t0) * 1000
            return resp.status, body, latency
    except HTTPError as e:
        latency = (time.time() - t0) * 1000
        return e.code, e.read() or b"", latency
    except URLError as e:
        latency = (time.time() - t0) * 1000
        raise RuntimeError(f"URLError: {e.reason}") from e


def _fetch_openapi() -> dict:
    status, body, _ = _get(f"{BASE}/openapi.json")
    assert status == 200, f"openapi.json returned {status}"
    return json.loads(body)


def _path_has_required_segment(path: str) -> bool:
    return "{" in path


def _extract_required_query_params(op: dict) -> list[str]:
    return [
        p["name"]
        for p in op.get("parameters", [])
        if p.get("in") == "query" and p.get("required")
    ]


def run() -> int:
    print(f"Fetching OpenAPI from {BASE}/openapi.json")
    spec = _fetch_openapi()
    paths = spec.get("paths", {})

    reports: list[EndpointReport] = []

    for path, methods in sorted(paths.items()):
        get_spec = methods.get("get")
        if not get_spec:
            continue

        rep = EndpointReport(path=path, method="GET")

        # Skip endpoints with required path parameters (can't fabricate values)
        if _path_has_required_segment(path):
            rep.skipped = True
            rep.skip_reason = "path has required template segment"
            reports.append(rep)
            continue

        required_q = _extract_required_query_params(get_spec)
        rep.required_params = required_q
        if required_q:
            rep.skipped = True
            rep.skip_reason = f"required query params: {','.join(required_q)}"
            reports.append(rep)
            continue

        # Fetch
        try:
            status, body, latency = _get(f"{BASE}{path}")
            rep.status = status
            rep.latency_ms = round(latency, 1)
            rep.response_size = len(body)
            if body:
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        rep.response_shape = f"dict:{len(parsed)} keys"
                    elif isinstance(parsed, list):
                        rep.response_shape = f"list:{len(parsed)} items"
                    else:
                        rep.response_shape = type(parsed).__name__
                    rep.sample = json.dumps(parsed, ensure_ascii=False)[:200]
                except json.JSONDecodeError:
                    rep.response_shape = "non-json"
                    rep.sample = body[:200].decode(errors="replace")
        except Exception as e:
            rep.error = f"{type(e).__name__}: {e}"

        reports.append(rep)

    # Summary
    ok = [r for r in reports if not r.skipped and r.status and 200 <= r.status < 400 and not r.error]
    fail = [r for r in reports if not r.skipped and (r.error or (r.status and r.status >= 400))]
    skipped = [r for r in reports if r.skipped]

    print()
    print("═" * 80)
    print(f"  E4-0a API Smoke Report — {len(reports)} GET endpoints")
    print("═" * 80)
    print(f"  ✅ PASS    : {len(ok)}")
    print(f"  ❌ FAIL    : {len(fail)}")
    print(f"  ⏭  SKIPPED : {len(skipped)}  (required path/query params)")
    print()

    if fail:
        print("FAILED endpoints:")
        print("─" * 80)
        for r in fail:
            marker = f"{r.status}" if r.status else "ERR"
            print(f"  ❌ [{marker}] {r.path}")
            if r.error:
                print(f"      error: {r.error}")
            if r.status and r.status >= 400:
                print(f"      latency: {r.latency_ms}ms | size: {r.response_size}B")
                print(f"      sample: {r.sample[:150]}")
        print()

    if ok:
        print("PASS endpoints (status / latency / shape):")
        print("─" * 80)
        for r in sorted(ok, key=lambda x: x.latency_ms or 0, reverse=True):
            print(f"  ✅ [{r.status}] {(r.latency_ms or 0):>6.0f}ms  {r.response_shape:<20}  {r.path}")
        print()

    if skipped:
        print(f"Skipped (require params — not auto-tested, {len(skipped)}):")
        print("─" * 80)
        for r in skipped:
            print(f"  ⏭  {r.path:<55}  ({r.skip_reason})")
        print()

    print(f"Total: {len(reports)} GET endpoints inventoried.")
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(run())
