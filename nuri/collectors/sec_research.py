"""Manual, isolated SEC EPS capture for R02 feasibility (#1887)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import timezone
from pathlib import Path
from uuid import uuid4

import httpx

from nuri.core.timezone import kst_now


def _utc() -> str:
    return kst_now().astimezone(timezone.utc).isoformat()


def capture(cik: str, identity: str, output: Path) -> tuple[Path, bool]:
    """명시한 기업만 수집하고 실패도 보존한다. 운영 DB/알림/스케줄러를 호출하지 않는다."""
    if not re.fullmatch(r"[0-9]{1,10}", cik) or int(cik) == 0:
        raise ValueError("Expected a positive SEC CIK of up to ten digits")
    if not identity.strip() or "\n" in identity or "\r" in identity:
        raise ValueError("A single-line SEC user agent is required")
    cik = cik.zfill(10)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    directory = output / f"capture-{uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=False)
    sources = []
    endpoints = {
        "facts": f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json",
        "submissions": f"https://data.sec.gov/submissions/CIK{cik}.json",
    }
    # 두 요청을 순차 실행한다. 전송하는 연락처는 산출물에 저장하지 않는다.
    with httpx.Client(headers={"User-Agent": identity}, timeout=30) as client:
        for name, url in endpoints.items():
            start = _utc()
            body = b""
            status_code = None
            error = None
            try:
                response = client.get(url)
                body = response.content
                status_code = response.status_code
                response.raise_for_status()
                if not isinstance(json.loads(body), dict):
                    raise ValueError("Expected JSON object")
            except (httpx.HTTPError, ValueError) as exc:
                # 예외 메시지는 인증정보 등을 포함할 수 있어 종류만 기록한다.
                error = type(exc).__name__
            observed = _utc()
            filename = f"{name}.json"
            with (directory / filename).open("xb") as handle:
                handle.write(body)
            sources.append(
                {
                    "name": name,
                    "url": url,
                    "file": filename,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "request_started_at_utc": start,
                    "observed_at_utc": observed,
                    "http_status": status_code,
                    "error_type": error,
                    "status": "captured" if error is None else "failed",
                }
            )
    manifest = {
        "schema_version": 1,
        "experiment_id": "R02-sec-feasibility",
        "cik": cik,
        "code_rev": revision,
        "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": sources,
        "research_eligible": False,
        "limitations": [
            "Current responses are not historical snapshots.",
            "SEC acceptance is not the earliest issuer earnings release.",
            "Recent submissions only; historical pagination is not included.",
        ],
    }
    path = directory / "manifest.json"
    with path.open("x") as handle:
        json.dump(manifest, handle, indent=2, allow_nan=False)
    return path, all(source["status"] == "captured" for source in sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", required=True)
    parser.add_argument("--identity", required=True, help="SEC user agent with contact information")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path, complete = capture(args.cik, args.identity, args.output)
    print(json.dumps({"manifest": str(path), "capture_complete": complete, "research_eligible": False}))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
