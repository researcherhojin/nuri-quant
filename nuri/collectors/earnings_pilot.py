"""Manual R01 provider capability probe; isolated JSON snapshots only (#1885).

No scheduler registration, portfolio lookup, performance calculation or DB writes.
Yahoo quoteSummary is accessed through yfinance's private authenticated transport;
the adapter is deliberately a pilot and records the installed library version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from nuri.collectors.base import BaseCollector
from nuri.core.timezone import kst_now

MODULES = "earningsTrend,calendarEvents,earningsHistory,price,summaryDetail"


def _utc() -> str:
    return kst_now().astimezone(timezone.utc).isoformat()


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def _fetch_payload(ticker: str) -> dict:
    import yfinance as yf

    # 공개 getter는 분기 종료일과 시각을 버리므로 원 응답 구조를 보존한다.
    return yf.Ticker(ticker)._data.get_raw_json(
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
        params={"modules": MODULES, "formatted": "false"},
        timeout=20,
    )


def _has_estimate(payload: dict) -> bool:
    """응답 존재와 분석 가능한 예상치를 구분한다; 발표 전 여부는 판정하지 않는다."""
    try:
        if payload["quoteSummary"].get("error"):
            return False
        trends = payload["quoteSummary"]["result"][0]["earningsTrend"]["trend"]
        for row in trends:
            avg = row.get("earningsEstimate", {}).get("avg", {}).get("raw")
            if (
                row.get("period") in ("0q", "+1q")
                and row.get("endDate")
                and isinstance(avg, (int, float))
                and not isinstance(avg, bool)
                and math.isfinite(avg)
            ):
                return True
    except (KeyError, IndexError, TypeError, AttributeError):
        return False
    return False


class EarningsPilotCollector(BaseCollector):
    def __init__(self, tickers: list[str], output: Path):
        super().__init__("earnings_pilot")
        if not tickers or any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", t) for t in tickers):
            raise ValueError("Explicit uppercase public symbols required")
        self.tickers = list(dict.fromkeys(tickers))
        self.output = output
        self.last_artifact: Path | None = None

    def collect(self, **kwargs) -> dict:
        observations = []
        for ticker in self.tickers:
            start = _utc()
            payload = None
            error = None
            try:
                payload = _fetch_payload(ticker)
                _encode(payload)
                summary = payload.get("quoteSummary") if isinstance(payload, dict) else None
                if isinstance(summary, dict) and summary.get("error") is not None:
                    status = "provider_error"
                    error = "ProviderResponseError"
                else:
                    status = "estimate_observed" if _has_estimate(payload) else "no_usable_estimate"
            except Exception as exc:
                # URL 인증정보가 예외 문자열에 섞일 수 있어 오류 종류만 기록한다.
                payload = None
                error = type(exc).__name__
                status = "request_failed"
            end = _utc()
            observations.append(
                {
                    "ticker": ticker,
                    "request_started_at_utc": start,
                    "response_observed_at_utc": end,
                    "published_at_utc": None,
                    "preannouncement_verified": False,
                    "status": status,
                    "error_type": error,
                    "payload_sha256": hashlib.sha256(_encode(payload)).hexdigest(),
                    "payload": payload,
                }
            )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return {
            "schema_version": 1,
            "experiment_id": "R01-provider-pilot",
            "capture_id": uuid4().hex,
            "provider": "Yahoo Finance via yfinance",
            "provider_url": "https://query2.finance.yahoo.com/v10/finance/quoteSummary/",
            "modules": MODULES,
            "yfinance_version": version("yfinance"),
            "code_rev": revision,
            "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "pilot_symbols": self.tickers,
            "pilot_symbols_sha256": hashlib.sha256(_encode(self.tickers)).hexdigest(),
            "observations": observations,
            "r01_launch_ready": False,
            "limitations": [
                "Capture time is local observation time, not provider publication time.",
                "Scheduled earnings dates do not prove actual publication or preannouncement availability.",
                "Payload is parsed provider JSON, not original HTTP bytes; transport headers are not archived.",
                "Earlier provider revisions, accounting basis and historical universe are unverified.",
                "Pilot symbols are a capability sample, not the R01 investment universe.",
                "Quotes are unverified snapshots, not executable fills or a transaction cost model.",
                "No performance or launch verdict; source rights and full data contract remain unresolved.",
            ],
        }

    def save(self, data: dict) -> int:
        self.output.mkdir(parents=True, exist_ok=True)
        artifact = self.output / f"capture-{data['capture_id']}.json"
        # 재실행/동시 실행 시 이전 캡처 덮어쓰기를 파일 생성 단계에서 거부한다.
        with artifact.open("xb") as handle:
            handle.write(_encode(data))
        self.last_artifact = artifact
        return sum(row["status"] == "estimate_observed" for row in data["observations"])

    def run(self, **kwargs) -> int:
        # BaseCollector.run의 재시도/실패 알림은 운영 outbox를 쓰므로 의도적으로 제외한다.
        return self.save(self.collect(**kwargs))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collector = EarningsPilotCollector(args.tickers, args.output)
    count = collector.run()
    print(
        json.dumps(
            {
                "artifact": str(collector.last_artifact),
                "estimates_observed": count,
                "requested_symbols": len(collector.tickers),
                "r01_launch_ready": False,
            }
        )
    )
    return 0 if count == len(collector.tickers) else 2


if __name__ == "__main__":
    raise SystemExit(main())
