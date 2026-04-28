# pyright: reportMissingImports=false
"""KR analyst-opinion collector via KIS Open API `invest_opinion` endpoint.

NOT a research-report scraper (the original Playwright skeleton was deleted in
favor of this REST collector — issue #418, 2026-04-28).

Endpoint: `/uapi/domestic-stock/v1/quotations/invest-opinion` (tr_id `FHKST663300C0`).
Returns broker-level opinion history per KR ticker (date, current opinion,
previous opinion, target price, broker name `mbcr_name`) with date range filter.
Each call covers a 6-month rolling window; weekly Sunday cron upserts to
`analyst_ratings` with `INSERT OR IGNORE` keyed on `(ticker, date, firm)`.

Scope (Round 2 codex consult):
- DB + UI only. KR rows write through to `analyst_ratings` and surface in the
  ticker detail UI. **Not yet wired to consensus** — `WallStreetAgent` still
  hard-skips `.KS` tickers (line 40), and `analyst_ratings` remains in
  `nuri/core/coverage.py::US_ONLY_TABLES`. Both are explicit follow-ups; this
  collector only fills the data layer.
- `invest_opinion` only. `estimate_perform` (earnings estimates) needs a
  separate schema and is deferred to a Tier 2 follow-up PR.
- Korean broker names (e.g. raw `mbcr_name` from the KIS payload) are stored
  unchanged. Test fixtures use synthetic broker names to stay clear of the
  privacy scanner (`scripts/check_privacy_leak.py BROKER_NAMES_KO`).

Sample row (live probe 2026-04-28, Samsung 005930):
    {
        'stck_bsop_date': '20260421',
        'invt_opnn': '매수', 'invt_opnn_cls_code': '2',
        'rgbf_invt_opnn': '매수', 'rgbf_invt_opnn_cls_code': '3',
        'mbcr_name': '<broker name in Korean>',
        'hts_goal_prc': '300000',
        ...
    }

`cls_code` is **not** a reliable cross-broker rank — same code maps to
different opinion text across brokers (probe: code 3 seen as Buy / HOLD /
Outperform / Neutral). Action derivation normalizes the **text** instead.

Failure model (STRATEGY §2.6 Surface):
- No KIS creds  → `pipeline_events.step_blocked` + return [].
- Token failure → `pipeline_events.step_failed` + return [].
- Per-ticker HTTP/non-zero rt_cd → skip + debug log + continue (no raise).
- Pagination depth approaches max → `kis_analyst_opinion_truncation_risk`
  surface event so the caller can widen the window or split the call.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from nuri.collectors.base import BaseCollector
from nuri.core.db import get_db
from nuri.core.events import emit_event
from nuri.core.timezone import kst_now

logger = logging.getLogger(__name__)

# KIS Open API endpoint constants
KIS_INVEST_OPINION_PATH = "/uapi/domestic-stock/v1/quotations/invest-opinion"
KIS_INVEST_OPINION_TR_ID = "FHKST663300C0"
KIS_INVEST_OPINION_SCR = "16633"

# Pagination — official sample uses max_depth=10. Surface a truncation_risk
# event when we approach the cap so callers know to widen/split the window.
KIS_INVEST_OPINION_MAX_DEPTH = 10
KIS_INVEST_OPINION_TRUNCATION_DEPTH = 8

# Default lookback window — 6 months rolling. Codex Round 1: "idempotent
# overlap is safer than watermark logic; strict T-7d would silently create
# holes after scheduler misses or API hiccups."
DEFAULT_LOOKBACK_DAYS = 180

# Opinion text normalization for action derivation.
# `cls_code` is broker-inconsistent (live probe 2026-04-28: code 3 maps to
# Buy / HOLD / Outperform / Neutral across brokers). Use canonical category
# from the human-readable text instead.
_BUY_TOKENS = frozenset(
    {
        "매수",
        "buy",
        "strong buy",
        "outperform",
        "overweight",
        "trading buy",
        "accumulate",
    }
)
_HOLD_TOKENS = frozenset({"보유", "hold", "neutral", "marketperform", "market perform", "equal-weight"})
_SELL_TOKENS = frozenset({"매도", "sell", "underperform", "underweight", "reduce"})

# Action vocabulary — matches existing `analyst_ratings.action` values
# already in DB ('main', 'init', 'up', 'reit', 'down').
_ACTION_INIT = "init"
_ACTION_MAINTAIN = "main"
_ACTION_UPGRADE = "up"
_ACTION_DOWNGRADE = "down"

# Canonical bucket → ordinal rank for upgrade/downgrade comparison.
_BUCKET_RANK = {"sell": 1, "hold": 2, "buy": 3}

# Fallback firm value when KIS returns an empty `mbcr_name`. Stable string
# so `INSERT OR IGNORE` on (ticker, date, firm) deduplicates correctly
# (codex Round 1: NULL!=NULL would break uniqueness).
_FIRM_UNKNOWN = "KIS_UNKNOWN"


def _normalize_opinion(text: str | None) -> str | None:
    """Map raw KIS opinion text to canonical bucket {buy, hold, sell} or None."""
    if not text:
        return None
    key = text.strip().lower()
    if key in _BUY_TOKENS:
        return "buy"
    if key in _HOLD_TOKENS:
        return "hold"
    if key in _SELL_TOKENS:
        return "sell"
    return None


def _derive_action(curr_text: str | None, prev_text: str | None) -> str:
    """Compare current vs previous opinion → init / main / up / down."""
    curr = _normalize_opinion(curr_text)
    prev = _normalize_opinion(prev_text)

    if not prev:
        # No prior opinion known → first surfaced rating.
        return _ACTION_INIT
    if not curr:
        # We have a prior but current is unparsable — surface it as init for
        # the current row rather than guessing a direction.
        return _ACTION_INIT
    if curr == prev:
        return _ACTION_MAINTAIN
    return _ACTION_UPGRADE if _BUCKET_RANK[curr] > _BUCKET_RANK[prev] else _ACTION_DOWNGRADE


def _parse_target_price(raw: Any) -> float | None:
    """KIS returns target price as string (KRW). Empty / non-numeric → None."""
    if raw in (None, "", "0"):
        return None
    try:
        val = float(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _format_yyyymmdd(date_str: str) -> str:
    """KIS returns `stck_bsop_date` as YYYYMMDD; analyst_ratings.date stores YYYY-MM-DD."""
    if len(date_str) != 8 or not date_str.isdigit():
        return date_str  # Pass through; downstream UPSERT will tolerate odd values.
    return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"


def _safe_str(raw: Any) -> str:
    """Coerce a KIS field to a stripped string. Tolerates None / non-str / numeric drift —
    one malformed payload row must not abort the per-ticker loop (codex Round 1 review P1)."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        try:
            raw = str(raw)
        except Exception:
            return ""
    return raw.strip()


def _parse_kis_row(row: dict, ticker_full: str) -> dict | None:
    """Map one KIS `invest_opinion` row → analyst_ratings record dict.

    Defensive against None/non-string field values (codex review P1).
    """
    if not isinstance(row, dict):
        return None
    bsop_date = _safe_str(row.get("stck_bsop_date"))
    if not bsop_date:
        return None
    curr_text = _safe_str(row.get("invt_opnn")) or None
    prev_text = _safe_str(row.get("rgbf_invt_opnn")) or None
    firm = _safe_str(row.get("mbcr_name")) or _FIRM_UNKNOWN
    return {
        "ticker": ticker_full,
        "date": _format_yyyymmdd(bsop_date),
        "firm": firm,
        "to_grade": curr_text,  # Raw KIS text (Korean or English as provided).
        "from_grade": prev_text,
        "action": _derive_action(curr_text, prev_text),
        "target_price": _parse_target_price(row.get("hts_goal_prc")),
    }


def _upsert_analyst_ratings(records: list[dict], db_path=None) -> int:
    """INSERT OR IGNORE keyed on (ticker, date, firm). Returns rowcount, not
    len(records) — see CLAUDE.md gotcha "SQLite upsert 반환값은 cursor.rowcount"."""
    if not records:
        return 0
    with get_db(db_path) as conn:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO analyst_ratings (ticker, date, firm, to_grade, from_grade, action, target_price) "
            "VALUES (:ticker, :date, :firm, :to_grade, :from_grade, :action, :target_price)",
            records,
        )
        return cur.rowcount or 0


class KISAnalystOpinionCollector(BaseCollector):
    """KR analyst-opinion collector — wraps KIS `invest_opinion` REST endpoint."""

    def __init__(self, mode: str = "prod"):
        super().__init__("kis_analyst_opinion")
        self.mode = mode

    def collect(self, **kwargs) -> list[dict]:
        """Fetch KR analyst opinions for universe tickers. Returns parsed rows."""
        tickers = kwargs.get("tickers") or self._get_tickers(market="kr", source="universe")
        if not tickers:
            self.logger.info("No KR universe tickers — KIS analyst opinion skip")
            return []

        # 1. credentials (Surface §2.6 — infra issue, market interpretation separate)
        from nuri.collectors.kis_realtime import (
            KIS_RATE_LIMIT_RETRY_DELAY_SEC,
            KIS_REQUEST_INTERVAL_PROD,
            _is_rate_limit,
            get_access_token,
            load_credentials,
        )

        creds = load_credentials(self.mode)
        if creds is None or not creds.is_valid():
            self.logger.warning("KIS creds 미설정 — KR analyst opinion skip. see docs/KIS_INTEGRATION.md")
            try:
                emit_event(
                    event_type="step_blocked",
                    step="collect",
                    payload={
                        "collector": "kis_analyst_opinion",
                        "reason": "kis_creds_missing",
                        "affected_tickers": len(tickers),
                    },
                )
            except Exception:
                pass
            return []

        # 2. token
        token = get_access_token(creds)
        if not token:
            self.logger.error("KIS token 발급 실패 — KR analyst opinion skip")
            try:
                emit_event(
                    event_type="step_failed",
                    step="collect",
                    payload={"collector": "kis_analyst_opinion", "reason": "kis_token_failed"},
                )
            except Exception:
                pass
            return []

        # 3. iterate
        try:
            from tqdm import tqdm

            iterator = tqdm(tickers, desc="KIS invest_opinion (KR)", unit="ticker")
        except ImportError:
            iterator = tickers

        url = f"{creds.base_url}{KIS_INVEST_OPINION_PATH}"
        end_date = kst_now().strftime("%Y%m%d")
        start_date = (kst_now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y%m%d")
        results: list[dict] = []
        covered = 0
        empty = 0
        failed: list[str] = []

        # Rate-limit interval mirrors institutional.py (sequential per ticker).
        interval = KIS_REQUEST_INTERVAL_PROD

        for ticker_full in iterator:
            code = ticker_full.replace(".KS", "").replace(".KQ", "")
            try:
                rows, status = self._fetch_ticker_paginated(
                    url=url,
                    creds=creds,
                    token=token,
                    code=code,
                    start_date=start_date,
                    end_date=end_date,
                    is_rate_limit=_is_rate_limit,
                    rate_limit_retry_delay=KIS_RATE_LIMIT_RETRY_DELAY_SEC,
                )
            except Exception as e:
                self.logger.debug("%s: exception — %s", ticker_full, e)
                failed.append(ticker_full)
                time.sleep(interval)
                continue

            # Codex Round 1 review P1: HTTP non-200 / rt_cd != 0 must increment
            # `failed`, not `empty` — telemetry honesty about run health.
            if status == "failed":
                failed.append(ticker_full)
                time.sleep(interval)
                continue
            if not rows:
                empty += 1
                time.sleep(interval)
                continue

            covered += 1
            for raw in rows:
                try:
                    rec = _parse_kis_row(raw, ticker_full)
                except Exception as e:
                    # _parse_kis_row is defensive but a future-proof guard so a
                    # single malformed payload row never aborts the run.
                    self.logger.debug("%s: row parse error — %s", ticker_full, e)
                    continue
                if rec:
                    results.append(rec)
            time.sleep(interval)

        self._failed_tickers = failed
        try:
            emit_event(
                event_type="kis_analyst_opinion_run",
                step="collect",
                payload={
                    "collector": "kis_analyst_opinion",
                    "covered": covered,
                    "empty": empty,
                    "failed": len(failed),
                    "rows": len(results),
                    "window_days": DEFAULT_LOOKBACK_DAYS,
                },
            )
        except Exception:
            pass
        self.logger.info(
            "KR analyst opinion: %d rows from %d/%d tickers (%d empty, %d failed)",
            len(results),
            covered,
            len(tickers),
            empty,
            len(failed),
        )
        return results

    def _fetch_ticker_paginated(
        self,
        *,
        url: str,
        creds,
        token: str,
        code: str,
        start_date: str,
        end_date: str,
        is_rate_limit,
        rate_limit_retry_delay: float,
    ) -> tuple[list[dict], str]:
        """Fetch all pages for one ticker via tr_cont recursion.

        Returns `(rows, status)` where status ∈ {"ok", "empty", "failed"}.
        Codex Round 1 review P1: callers must distinguish empty (KIS returned
        no opinions) from failed (HTTP error / non-zero rt_cd) so the run-summary
        telemetry doesn't lie about health.
        """
        import requests

        accumulated: list[dict] = []
        tr_cont = ""  # First page sends empty tr_cont.
        had_failure = False
        truncation_emitted = False

        for depth in range(KIS_INVEST_OPINION_MAX_DEPTH):
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {token}",
                "appkey": creds.app_key,
                "appsecret": creds.app_secret,
                "tr_id": KIS_INVEST_OPINION_TR_ID,
                "custtype": "P",
                "tr_cont": tr_cont,
            }
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": KIS_INVEST_OPINION_SCR,
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
            }
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                self.logger.debug("%s page %d: HTTP %d", code, depth, resp.status_code)
                had_failure = True
                break
            body = resp.json()
            if is_rate_limit(body):
                self.logger.warning("%s page %d: rate limit — %ss 대기 후 재시도", code, depth, rate_limit_retry_delay)
                time.sleep(rate_limit_retry_delay)
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    had_failure = True
                    break
                body = resp.json()
            if body.get("rt_cd") != "0":
                self.logger.debug("%s page %d: rt_cd=%s msg=%s", code, depth, body.get("rt_cd"), body.get("msg1"))
                had_failure = True
                break
            output = body.get("output") or []
            if isinstance(output, dict):
                output = [output]
            accumulated.extend(output)

            # Pagination — tr_cont == "M" means "more pages exist".
            next_tr_cont = (resp.headers.get("tr_cont") or "").strip()
            if next_tr_cont == "M":
                tr_cont = "N"  # Continuation flag for subsequent pages (per official sample).
                # Codex review P2: surface truncation_risk **once per ticker**,
                # not once per continued page. Doc contract is "한 번 surface,
                # 계속 진행".
                if depth + 1 >= KIS_INVEST_OPINION_TRUNCATION_DEPTH and not truncation_emitted:
                    truncation_emitted = True
                    try:
                        emit_event(
                            event_type="kis_analyst_opinion_truncation_risk",
                            step="collect",
                            payload={
                                "collector": "kis_analyst_opinion",
                                "ticker_code": code,
                                "depth_reached": depth + 1,
                                "max_depth": KIS_INVEST_OPINION_MAX_DEPTH,
                            },
                        )
                    except Exception:
                        pass
                continue
            break

        if had_failure:
            return accumulated, "failed"
        return accumulated, "ok" if accumulated else "empty"

    def save(self, data: list[dict]) -> int:
        return _upsert_analyst_ratings(data)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="KIS Open API KR analyst opinion collector (#418)")
    parser.add_argument("--mode", default="prod", choices=["prod", "paper"])
    parser.add_argument("--ticker", default=None, help="Single ticker (e.g. 005930.KS)")
    args = parser.parse_args()

    collector = KISAnalystOpinionCollector(mode=args.mode)
    kwargs = {"tickers": [args.ticker]} if args.ticker else {}
    rows = collector.run(**kwargs)
    logger.info("Saved %d analyst opinion rows", rows)
