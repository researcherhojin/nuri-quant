"""Offline SEC quarterly evidence audit, not a signal or backtest (#1887)."""

# cspell:words GAAP accn

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed


def _periods(start: str, end: str) -> list[tuple[str, str]]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    months = (last.year - first.year) * 12 + last.month - first.month
    if first.day != 1 or months != 2 or last.day != calendar.monthrange(last.year, last.month)[1]:
        raise ValueError("Only explicit three-calendar-month quarters are supported")
    previous_first = first.replace(year=first.year - 1)
    previous_last = date(last.year - 1, last.month, calendar.monthrange(last.year - 1, last.month)[1])
    return [(first.isoformat(), last.isoformat()), (previous_first.isoformat(), previous_last.isoformat())]


def audit(manifest_path: Path, accession: str, start: str, end: str, as_of: str) -> dict:
    """동일 공시의 당기/전년동기만 확인한다. 비교 가능성이나 투자 적격성은 승인하지 않는다."""
    result: dict = {
        "experiment_id": "R02-sec-feasibility",
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "accession": accession,
        "as_of": as_of,
        "evidence_linked": False,
        "research_eligible": False,
        "reasons": [],
        "accounting_comparability": "unverified",
        "periods": [],
        "limitations": [
            "This is a current capture, not a reconstruction of historical availability.",
            "SEC acceptance is not the first earnings announcement.",
            "Same GAAP tag and accession do not prove continuity, split treatment or absence of restatement.",
            "Review original filing, corporate actions and accounting changes before computing any signal.",
            "52/53-week quarters, derived fourth quarters and historical submission pages are unsupported.",
        ],
    }
    reasons = result["reasons"]
    try:
        cutoff = _timestamp(as_of)
        periods = _periods(start, end)
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
        result["manifest_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
        if manifest["schema_version"] != 1 or manifest["experiment_id"] != "R02-sec-feasibility":
            raise ValueError("Unsupported manifest")
        cik = int(manifest["cik"])
        if not 0 < cik < 10**10:
            raise ValueError("Invalid CIK")
        sources = manifest["sources"]
        if len(sources) != 2 or {s["name"] for s in sources} != {"facts", "submissions"}:
            raise ValueError("Expected both sources exactly once")
        expected_urls = {
            "facts": f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/EarningsPerShareDiluted.json",
            "submissions": f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
        }
        data = {}
        observed_times = []
        for source in sources:
            name = source["name"]
            if source["file"] != f"{name}.json" or source["url"] != expected_urls[name]:
                raise ValueError("Unexpected source path or URL")
            if source["status"] != "captured" or source["http_status"] != 200 or source["error_type"] is not None:
                reasons.append("SOURCE_CAPTURE_FAILED")
            body = (manifest_path.parent / source["file"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != source["sha256"]:
                reasons.append("SOURCE_HASH_MISMATCH")
            began = _timestamp(source["request_started_at_utc"])
            observed = _timestamp(source["observed_at_utc"])
            if began > observed:
                reasons.append("INVALID_CAPTURE_INTERVAL")
            if observed > cutoff:
                reasons.append("CAPTURE_AFTER_AS_OF")
            observed_times.append(observed)
            data[name] = json.loads(body)
        facts, submissions = data["facts"], data["submissions"]
        if int(facts["cik"]) != cik or int(submissions["cik"]) != cik:
            reasons.append("CIK_MISMATCH")
        if facts["taxonomy"] != "us-gaap" or facts["tag"] != "EarningsPerShareDiluted":
            reasons.append("EPS_TAG_MISMATCH")
        recent = submissions["filings"]["recent"]
        keys = ("accessionNumber", "acceptanceDateTime", "reportDate", "form")
        lengths = {len(recent[k]) for k in keys}
        if len(lengths) != 1:
            raise ValueError("Unaligned submission arrays")
        indices = [i for i, value in enumerate(recent["accessionNumber"]) if value == accession]
        if len(indices) != 1:
            reasons.append("ACCESSION_NOT_UNIQUE_OR_MISSING")
        else:
            index = indices[0]
            accepted = _timestamp(recent["acceptanceDateTime"][index])
            if accepted > cutoff:
                reasons.append("FILING_AFTER_AS_OF")
            if accepted > min(observed_times):
                reasons.append("FILING_AFTER_CAPTURE")
            if recent["reportDate"][index] != end or recent["form"][index] != "10-Q":
                reasons.append("NOT_ORIGINAL_QUARTERLY_REPORT")
            result["accepted_at"] = accepted.isoformat()
            result["available_at"] = max(accepted, *observed_times).isoformat()
        rows = facts["units"]["USD/shares"]
        for first, last in periods:
            matches = [
                r for r in rows if r.get("accn") == accession and r.get("start") == first and r.get("end") == last
            ]
            values = set()
            for row in matches:
                value = row.get("val")
                if (
                    row.get("form") != "10-Q"
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    reasons.append("INVALID_QUARTER_VALUE")
                else:
                    values.add(value)
            if len(values) != 1:
                reasons.append("QUARTER_VALUE_MISSING_OR_AMBIGUOUS")
            result["periods"].append(
                {
                    "start": first,
                    "end": last,
                    "source_rows": len(matches),
                    "eps": next(iter(values)) if len(values) == 1 else None,
                }
            )
    except (OSError, KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError):
        reasons.append("MISSING_OR_INVALID_EVIDENCE")
    result["reasons"] = list(dict.fromkeys(reasons))
    result["evidence_linked"] = not reasons
    # 부적합 자료의 수치가 후속 분석에 그대로 쓰이지 않도록 비운다.
    if reasons:
        result["periods"] = []
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--accession", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    result = audit(args.manifest, args.accession, args.start, args.end, args.as_of)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["evidence_linked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
