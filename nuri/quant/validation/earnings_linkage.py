"""Offline R01 timing/period audit against manually reviewed issuer evidence.

Hashes bind artifacts, not source authenticity. The reviewer supplies the issuer
identity, fiscal period and publication semantics. EPS accounting equivalence is
not inferred, so this checker never grants R01 eligibility (#1886).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return result


def audit_link(observation: dict, release: dict, source: bytes) -> dict:
    """누락/오염/분기 불일치는 보류하며 원본 파일이나 DB를 변경하지 않는다."""
    reasons = []
    try:
        encoded = json.dumps(observation["payload"], sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        if hashlib.sha256(encoded).hexdigest() != observation["payload_sha256"]:
            reasons.append("CAPTURE_HASH_MISMATCH")
        if hashlib.sha256(source).hexdigest() != release["source_sha256"]:
            reasons.append("SOURCE_HASH_MISMATCH")
        if not release.get("source_url", "").startswith("https://"):
            reasons.append("SOURCE_URL_MISSING")
        if observation["ticker"] != release["ticker"]:
            reasons.append("ISSUER_MISMATCH")
        if observation.get("status") != "estimate_observed":
            reasons.append("NO_USABLE_ESTIMATE")
        end = date.fromisoformat(release["fiscal_period_end"]).isoformat()
        summary = observation["payload"]["quoteSummary"]
        if summary.get("error") is not None:
            reasons.append("PROVIDER_ERROR")
        trends = summary["result"][0]["earningsTrend"]["trend"]
        matches = [r for r in trends if r.get("endDate") == end and r.get("period") in ("0q", "+1q")]
        if len(matches) != 1:
            reasons.append("PERIOD_NOT_UNIQUELY_MATCHED")
        else:
            avg = matches[0].get("earningsEstimate", {}).get("avg", {}).get("raw")
            if isinstance(avg, bool) or not isinstance(avg, (int, float)):
                reasons.append("MATCHED_ESTIMATE_MISSING")
        if release.get("publication_kind") != "issuer_release":
            reasons.append("ACTUAL_RELEASE_TIME_UNVERIFIED")
        excerpt = release.get("publication_excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt.encode() not in source:
            reasons.append("PUBLICATION_EXCERPT_UNVERIFIED")
        published = _timestamp(release["published_at_utc"])
        started = _timestamp(observation["request_started_at_utc"])
        observed = _timestamp(observation["response_observed_at_utc"])
        if started > observed:
            reasons.append("INVALID_CAPTURE_INTERVAL")
        if observed >= published:
            reasons.append("NOT_PREANNOUNCEMENT")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        reasons.append("MISSING_OR_INVALID_EVIDENCE")
    return {
        "ticker": observation.get("ticker"),
        "fiscal_period_end": release.get("fiscal_period_end"),
        "timing_and_period_verified": not reasons,
        "timing_reasons": reasons,
        "accounting_basis_status": "unverified",
        "research_eligible": False,
        "limitations": [
            "Issuer identity, fiscal period and publication semantics are manually reviewed assertions.",
            "Hashes and excerpt presence bind evidence; they do not prove source authenticity or earliest disclosure.",
            "Captured Yahoo EPS has no verified accounting basis; equal EPS values do not establish equivalence.",
            "No surprise, performance, trade signal or T0 decision is computed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text())
    release = json.loads(args.release.read_text())
    rows = [r for r in capture["observations"] if r["ticker"] == release["ticker"]]
    if len(rows) != 1:
        parser.error("Expected exactly one capture observation for issuer")
    print(json.dumps(audit_link(rows[0], release, args.source.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
