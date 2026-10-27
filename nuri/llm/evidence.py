"""근거 묶음 (evidence packet) — 다단계 thesis 의 알파 단계 입력 (#1955).

LLM 을 부르지 않는다. 역할(technical / fundamentals / flows / market)별로 DB 에서 근거를 모아
항목마다 ID · 관측일 · 기준 시점 대비 나이를 붙이고, 소스마다 상태 하나를 남긴다:

- `ok` / `stale` (최신 행이 max_age_days 를 넘음) / `missing` (조회는 됐고 행이 없음)
- `failed` (조회가 예외를 냈음) / `excluded` (커버리지 게이트에 걸림 — 아래)

**알파 묶음은 보유 여부를 드러내면 안 된다.** 보유 종목은 수집 범위와 주기가 다르다 — 뉴스 ·
내부자 · 애널리스트 등급은 보유 위주로 모이고, 미국 보유 종목은 가격도 하루 더 신선하다
(2026-10-27 replica 실측: US 가격 최신일이 대부분 10-23, 소수만 10-26). 그대로 넣으면 소스의
"있음" 이나 날짜만으로 보유가 새어 나가 알파 판정에 포트폴리오 축이 섞인다. 그래서 같은 스냅샷에서:

1. **커버리지 게이트** — 소스가 그 시장 유니버스(`config/universe.yaml`)의 `min_universe_share`
   이상을 덮지 못하면 모든 종목에서 `excluded`. 수집이 보유와 무관하다고 config 에 선언된 소스만
   (`holdings_independent`) 게이트를 건너뛴다.
2. **공통 기준일** — 유니버스의 그 비율이 도달한 가장 늦은 날짜까지만 쓴다. 어떤 종목도 자기
   시장 대부분보다 신선한 행을 보지 못한다.

내부자 · 애널리스트 등급 · 종목 이벤트 · consensus · price_targets · 보유 뉴스(`news`)는 소스 목록에
없다 — 모두 보유 위주 수집이거나 포트폴리오를 읽는다. 종목 뉴스는 DB 가 아니라 분석 직전 실시간
조회 결과를 인자로 받는다(`news=`, `nuri/llm/live_news.py`, #1958). 시장 묶음은 고정 지표 · 고정 키워드 뉴스 ·
고정 ETF 목록만 쓴다.

**한 스냅샷**: 묶음 하나의 모든 읽기는 읽기 전용 연결 하나의 한 트랜잭션 안에서 한다 —
`query()` 를 여러 번 부르면 호출마다 연결이 열려 읽기 사이에 수집기가 끼어들 수 있다.

**미래 정보**: 묶음은 실행 시점에 운영 DB 에서 만들고 그대로 보관하는 전제다(forward-only).
그 시점 DB 에 있는 행은 전부 그 전에 수집됐다. 과거 DB 사본으로 다시 만들면 이 보장은 없다 —
수집 시각을 행마다 남기는 `macro_events` 만 발행 · 수집 시각을 둘 다 기준 시점과 비교하고, 실시간
종목 뉴스는 조회 완료 시각이 기준 시점 뒤면 거부한다.

`packet_hash` 는 정렬된 JSON 의 SHA-256 — 뒤 단계가 어떤 입력을 봤는지 증명하는 값이다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from nuri.core.coverage import _load_universe
from nuri.core.db import DatabaseError, OperationalError, get_db
from nuri.core.ticker_names import is_kr_ticker
from nuri.core.timezone import kst_now
from nuri.llm import live_news

CONFIG_PATH = Path("config/evidence.yaml")
SCHEMA = "evidence_packet/v1"


@dataclass(frozen=True)
class Source:
    name: str
    role: str
    table: str
    date_col: Optional[str]  # None = 날짜 컬럼 없음 (나이를 잴 수 없다)
    date_meaning: str
    fields: tuple[str, ...]
    where: str = ""  # 소스 정의에 속하는 고정 필터 (사용자 입력 아님)
    order_col: str = "id"  # 날짜 컬럼이 없을 때 최신을 고르는 기준 — id 는 upsert 재삽입에 흔들린다


TICKER_SOURCES: tuple[Source, ...] = (
    Source("prices", "technical", "prices", "date", "trading session date", ("open", "high", "low", "close", "volume")),
    Source(
        "signals",
        "technical",
        "signals",
        "date",
        "computation date (as of that session's close)",
        (
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "sma_20",
            "sma_50",
            "sma_200",
        ),
    ),
    Source(
        "factors",
        "technical",
        "factors",
        "date",
        "computation date",
        ("momentum_score", "value_score", "quality_score", "sentiment_score", "composite_score"),
    ),
    Source(
        "fundamentals",
        "fundamentals",
        "fundamentals",
        "date",
        "snapshot date (when vendor values were read, not the reporting period)",
        (
            "market_cap",
            "pe_ratio",
            "forward_pe",
            "price_to_book",
            "peg_ratio",
            "roe",
            "roa",
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "revenue_growth",
            "earnings_growth",
            "debt_to_equity",
            "current_ratio",
            "dividend_yield",
            "beta",
        ),
    ),
    Source(
        "estimates",
        "fundamentals",
        "estimates",
        "date",
        "snapshot date of the analyst consensus",
        ("recommendation", "target_high", "target_low", "target_mean", "target_median", "num_analysts"),
    ),
    Source(
        "earnings_surprises",
        "fundamentals",
        "earnings_surprises",
        None,
        "fiscal quarter; publication date is not recorded",
        ("quarter", "eps_actual", "eps_estimate", "surprise_pct"),
        order_col="quarter",  # 분기 말일(YYYY-MM-DD) — 문자열 정렬이 시간 순서다
    ),
    Source(
        "superinvestors",
        "flows",
        "superinvestors",
        "filing_date",
        "13F filing date (holdings are as of the prior quarter end)",
        ("investor", "shares", "market_value", "portfolio_pct"),
        where="investor_class = 'conviction'",
    ),
)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _seal(packet: dict[str, Any]) -> dict[str, Any]:
    packet["packet_hash"] = hashlib.sha256(_canonical(packet).encode()).hexdigest()
    return packet


def _age(observed: Optional[str], cutoff_day: date) -> Optional[int]:
    if not observed:
        return None
    return (cutoff_day - date.fromisoformat(str(observed)[:10])).days


def _as_cutoff(cutoff: Optional[datetime]) -> datetime:
    c = cutoff or kst_now()
    if c.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware (use kst_now())")
    return c


def _snapshot(db_path: Optional[Path]):
    """읽기 전용 연결 하나 + BEGIN — 첫 읽기부터 끝까지 같은 스냅샷을 본다."""
    return get_db(db_path, readonly=True)


def _market_cut(
    conn: Any, src: Source, universe: set[str], cutoff_day: str, share: float
) -> tuple[Optional[str], float, bool]:
    """(공통 기준일, 커버리지, 게이트 통과) — 유니버스의 `share` 가 도달한 가장 늦은 날짜."""
    where = f" AND {src.where}" if src.where else ""
    if src.date_col is None:
        rows = conn.execute(f"SELECT DISTINCT ticker FROM {src.table} WHERE 1=1{where}").fetchall()
        covered = {r["ticker"] for r in rows} & universe
        cov = len(covered) / len(universe) if universe else 0.0
        return None, cov, cov >= share
    rows = conn.execute(
        f"SELECT ticker, MAX({src.date_col}) AS m FROM {src.table} WHERE {src.date_col} <= ?{where} GROUP BY ticker",
        (cutoff_day,),
    ).fetchall()
    latest = sorted((str(r["m"])[:10] for r in rows if r["ticker"] in universe and r["m"]), reverse=True)
    cov = len(latest) / len(universe) if universe else 0.0
    need = math.ceil(share * len(universe))
    if not universe or len(latest) < need:
        return None, cov, False
    return latest[need - 1], cov, True


def _price_summary(rows: list[Any], recent: int) -> dict[str, Any]:
    """가격 요약 — 수익률 · 52주 위치는 코드가 계산한다 (LLM 이 셈하지 않게)."""
    closes = [r["close"] for r in rows]  # 최신 → 과거
    last = closes[0]

    def ret(n: int) -> Optional[float]:
        return round((last / closes[n] - 1.0) * 100.0, 2) if len(closes) > n and closes[n] else None

    window = closes[:252]
    vols = [r["volume"] or 0 for r in rows]
    v20 = sum(vols[:20]) / min(20, len(vols))
    v60 = sum(vols[:60]) / min(60, len(vols))
    return {
        "last_close": last,
        "ret_5d_pct": ret(5),
        "ret_20d_pct": ret(20),
        "ret_60d_pct": ret(60),
        "ret_250d_pct": ret(250),
        "high_window": max(window),
        "low_window": min(window),
        "pct_from_high": round((last / max(window) - 1.0) * 100.0, 2),
        "window_sessions": len(window),
        "volume_20d_vs_60d": round(v20 / v60, 3) if v60 else None,
        "recent_closes": [[str(r["date"])[:10], r["close"]] for r in rows[:recent]],
    }


def _ticker_source(
    conn: Any, src: Source, ticker: str, cut: Optional[str], cfg: dict[str, Any], cutoff_day: date
) -> tuple[str, list[dict[str, Any]]]:
    where = f" AND {src.where}" if src.where else ""
    limit = int(cfg.get("rows", 1))
    if src.date_col is None:
        sql = f"SELECT * FROM {src.table} WHERE ticker = ?{where} ORDER BY {src.order_col} DESC, id DESC LIMIT ?"
        rows = conn.execute(sql, (ticker, limit)).fetchall()
    else:
        sql = (
            f"SELECT * FROM {src.table} WHERE ticker = ? AND {src.date_col} <= ?{where} "
            f"ORDER BY {src.date_col} DESC, id DESC LIMIT ?"
        )
        rows = conn.execute(sql, (ticker, cut, limit)).fetchall()
    if not rows:
        return "missing", []

    def observed(r: Any) -> Optional[str]:
        return str(r[src.date_col])[:10] if src.date_col else None

    if src.name == "prices":
        items = [
            {
                "id": f"prices:{rows[0]['id']}",
                "source": "prices",
                "observed": observed(rows[0]),
                "age_days": _age(observed(rows[0]), cutoff_day),
                "fields": _price_summary(rows, int(cfg.get("recent_closes", 10))),
            }
        ]
    else:
        items = [
            {
                "id": f"{src.name}:{r['id']}",
                "source": src.name,
                "observed": observed(r),
                "age_days": _age(observed(r), cutoff_day),
                "fields": {f: r[f] for f in src.fields},
            }
            for r in rows
        ]
    age = items[0]["age_days"]
    max_age = cfg.get("max_age_days")
    status = "stale" if age is not None and max_age is not None and age > max_age else "ok"
    return status, items


def _utc_time(text: str) -> datetime:
    """UTC 로 적힌 "YYYY-MM-DD HH:MM:SS[.ffffff]" → aware datetime."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _ticker_news(
    news: Optional[dict[str, Any]], ticker: str, c: datetime, cfg: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """종목 뉴스 (#1958) — 분석 직전 실시간 조회 결과(`nuri.llm.live_news.fetch`)를 거른다. DB 는 읽지 않는다.

    발행 시각이 없거나 기준 시점 뒤인 기사, lookback 창 밖 기사는 버리고 최신순 `rows` 개만 남긴다.
    조회가 기준 시점 뒤에 끝났으면 거부한다 — 그 결과에는 기준 시점 뒤에 나온 기사가 섞일 수 있다.
    """
    info: dict[str, Any] = {
        "role": "news",
        "date_meaning": "publication time (UTC); fetched live before the cutoff; Yahoo search returns a sample",
    }
    if news is None:
        info["status"], info["reason"] = "missing", "not fetched"
        return info, []
    if news["ticker"] != ticker:
        raise ValueError(f"news fetched for {news['ticker']}, packet is for {ticker}")
    # 문자열이 아니라 aware datetime 으로 비교한다 — 초 단위로 자르면 같은 초의 조회가 거부되거나 통과한다 (#1973)
    if _utc_time(news["fetched_at"]) > c:
        raise ValueError(f"news fetched at {news['fetched_at']} UTC, after the cutoff {c.isoformat()}")
    info["fetched_at"] = news["fetched_at"]
    info["status"] = news["status"]
    if news["status"] != "ok":
        if news.get("reason"):
            info["reason"] = news["reason"]
        return info, []
    oldest = c - timedelta(days=int(cfg["lookback_days"]))
    window = {
        a["link"]: a for a in news["articles"] if a["pub_date"] is not None and oldest < _utc_time(a["pub_date"]) <= c
    }
    kept = sorted(
        window.values(),
        key=lambda a: (a["pub_date"], a["link"]),
        reverse=True,
    )[: int(cfg["rows"])]
    if not kept:
        info["note"] = "no tagged article in the window; the search is a sample, so this is not an absence of news"
    items = [
        {
            # URL 해시 — 같은 기사는 어느 실행에서든 같은 ID 다 (주장이 가리키는 대상)
            "id": "ticker_news:" + hashlib.sha256(a["link"].encode()).hexdigest()[:16],
            "source": "ticker_news",
            "observed": a["pub_date"],
            # 시각끼리 뺀다 — KST 기준일에서 UTC 날짜를 빼면 몇 분 전 기사가 하루 묵은 것으로 나온다
            "age_days": (c - _utc_time(a["pub_date"])).days,
            # 원본 News Analyst 프롬프트가 받는 것과 같은 필드 (`_format_articles`: 제목 · 출처 · 요약)
            "fields": {"publisher": a["publisher"], "title": a["title"], "summary": a["summary"]},
        }
        for a in kept
    ]
    return info, items


def build_packet(
    ticker: str,
    *,
    cutoff: Optional[datetime] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
    universe: Optional[dict[str, set[str]]] = None,
    news: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """종목 하나의 알파 단계 근거 묶음. 보유 테이블은 읽지 않는다.

    `news` 는 `live_news.fetch(ticker)` 결과 — 묶음은 네트워크를 쓰지 않는다. 비교하는 모든 팔이
    같은 묶음을 받아야 한다 (뉴스를 다시 받으면 다른 표본이 온다).
    """
    c = _as_cutoff(cutoff)
    cutoff_day = c.date()
    cfg = config if config is not None else load_config()
    uni = universe if universe is not None else _load_universe()
    market = "kr" if is_kr_ticker(ticker) else "us"
    share = float(cfg["coverage"]["min_universe_share"])
    sources: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []

    with _snapshot(db_path) as conn:
        conn.execute("BEGIN")
        for src in TICKER_SOURCES:
            src_cfg = cfg["sources"].get(src.name, {})
            info: dict[str, Any] = {"role": src.role, "date_meaning": src.date_meaning}
            try:
                if src_cfg.get("holdings_independent"):
                    cut, cov, passed = cutoff_day.isoformat(), None, True
                else:
                    cut, cov, passed = _market_cut(conn, src, uni.get(market, set()), cutoff_day.isoformat(), share)
                info["coverage"] = None if cov is None else round(cov, 4)
                info["as_of"] = cut
                if not passed:
                    info["status"] = "excluded"
                    info["reason"] = f"covers {cov:.1%} of the {market} universe; needs {share:.0%}"
                else:
                    info["status"], got = _ticker_source(conn, src, ticker, cut, src_cfg, cutoff_day)
                    items.extend(got)
            except (OperationalError, DatabaseError) as e:
                info["status"] = "failed"
                info["reason"] = type(e).__name__
            sources[src.name] = info
    sources["ticker_news"], got = _ticker_news(news, ticker, c, cfg["sources"]["ticker_news"])
    items.extend(got)

    return _seal(
        {
            "schema": SCHEMA,
            "kind": "ticker",
            "ticker": ticker,
            "market": market,
            # 유니버스 밖 종목은 데이터가 있다는 사실 자체가 보유 때문일 수 있다 — 위 보장이 성립하지 않는다.
            "in_universe": ticker in uni.get(market, set()),
            "cutoff": c.isoformat(),
            "sources": sources,
            "items": items,
        }
    )


def build_market_packet(
    *,
    cutoff: Optional[datetime] = None,
    db_path: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """그날 모든 종목이 공유하는 시장 묶음 — 고정 지표 · 고정 키워드 뉴스 · 일정 · ETF 흐름."""
    c = _as_cutoff(cutoff)
    cutoff_day = c.date()
    day = cutoff_day.isoformat()
    utc = c.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    m = (config if config is not None else load_config())["market"]
    monthly = set(m.get("macro_monthly", []))
    sources: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []

    def guarded(name: str, role: str, meaning: str, fn: Any) -> None:
        info: dict[str, Any] = {"role": role, "date_meaning": meaning}
        try:
            info["status"] = fn()
        except (OperationalError, DatabaseError) as e:
            info["status"], info["reason"] = "failed", type(e).__name__
        sources[name] = info

    with _snapshot(db_path) as conn:
        conn.execute("BEGIN")

        def macro(ind: str) -> str:
            rows = conn.execute(
                "SELECT id, date, value FROM macro WHERE indicator = ? AND date <= ? ORDER BY date DESC LIMIT ?",
                (ind, day, int(m["macro_rows"])),
            ).fetchall()
            if not rows:
                return "missing"
            vals = [r["value"] for r in rows]
            obs = str(rows[0]["date"])[:10]
            age = _age(obs, cutoff_day)
            items.append(
                {
                    "id": f"macro:{rows[0]['id']}",
                    "source": f"macro.{ind}",
                    "observed": obs,
                    "age_days": age,
                    "fields": {
                        "latest": vals[0],
                        "previous": vals[1] if len(vals) > 1 else None,
                        "window_first": vals[-1],
                        "window_change": round(vals[0] - vals[-1], 6),
                        "window_high": max(vals),
                        "window_low": min(vals),
                        "window_rows": len(vals),
                    },
                }
            )
            limit = m["macro_monthly_max_age_days"] if ind in monthly else m["macro_max_age_days"]
            return "stale" if age is not None and age > limit else "ok"

        for ind in m["macro_indicators"]:
            guarded(f"macro.{ind}", "market", "observation date", lambda ind=ind: macro(ind))

        def macro_events() -> str:
            # 발행 시각과 수집 시각이 둘 다 기준 시점 전이어야 한다 (이 테이블만 둘 다 있다).
            bound = (
                "datetime(published_at) <= datetime(?) AND datetime(fetched_at) <= datetime(?) "
                "AND datetime(published_at) > datetime(?, ?)"
            )
            args = (utc, utc, utc, f"-{int(m['macro_events_days'])} days")
            counts = conn.execute(
                f"SELECT category, COUNT(*) AS n FROM macro_events WHERE {bound} GROUP BY category ORDER BY category",
                args,
            ).fetchall()
            if not counts:
                return "missing"
            items.append(
                {
                    "id": f"macro_events:counts:{day}",
                    "source": "macro_events",
                    "observed": day,
                    "age_days": 0,
                    "fields": {"window_days": int(m["macro_events_days"]), **{r["category"]: r["n"] for r in counts}},
                }
            )
            for r in conn.execute(
                f"SELECT id, published_at, source, category, sentiment, headline FROM macro_events WHERE {bound} "
                "ORDER BY datetime(published_at) DESC, id DESC LIMIT ?",
                (*args, int(m["macro_events_headlines"])),
            ).fetchall():
                items.append(
                    {
                        "id": f"macro_events:{r['id']}",
                        "source": "macro_events",
                        "observed": str(r["published_at"]),
                        "age_days": _age(r["published_at"], cutoff_day),
                        "fields": {k: r[k] for k in ("source", "category", "sentiment", "headline")},
                    }
                )
            return "ok"

        guarded("macro_events", "market", "publication time (UTC) — fetch time also before cutoff", macro_events)

        def calendar() -> str:
            types = list(m["calendar_event_types"])
            end = (cutoff_day + timedelta(days=int(m["calendar_days_ahead"]))).isoformat()
            rows = conn.execute(
                f"SELECT id, date, event_type, description, importance FROM events "
                f"WHERE event_type IN ({','.join('?' * len(types))}) AND date >= ? AND date <= ? ORDER BY date, id",
                (*types, day, end),
            ).fetchall()
            for r in rows:
                items.append(
                    {
                        "id": f"events:{r['id']}",
                        "source": "calendar",
                        "observed": str(r["date"])[:10],
                        "age_days": _age(r["date"], cutoff_day),
                        "fields": {k: r[k] for k in ("event_type", "description", "importance")},
                    }
                )
            return "ok" if rows else "missing"

        guarded("calendar", "market", "scheduled event date (upcoming)", calendar)

        def etf_flows() -> str:
            tickers = [
                r["ticker"]
                for r in conn.execute(
                    "SELECT DISTINCT ticker FROM etf_flows WHERE date <= ? ORDER BY ticker", (day,)
                ).fetchall()
            ]
            if not tickers:
                return "missing"
            worst = 0
            for t in tickers:
                rows = conn.execute(
                    "SELECT id, date, total_assets, volume_avg, nav_price FROM etf_flows "
                    "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 2",
                    (t, day),
                ).fetchall()
                cur, prev = rows[0], rows[1] if len(rows) > 1 else None
                age = _age(cur["date"], cutoff_day) or 0
                worst = max(worst, age)
                change = (
                    round((cur["total_assets"] / prev["total_assets"] - 1.0) * 100.0, 3)
                    if prev and cur["total_assets"] and prev["total_assets"]
                    else None
                )
                items.append(
                    {
                        "id": f"etf_flows:{cur['id']}",
                        "source": f"etf_flows.{t}",
                        "observed": str(cur["date"])[:10],
                        "age_days": age,
                        "fields": {
                            "total_assets": cur["total_assets"],
                            "total_assets_change_pct": change,
                            "previous_date": str(prev["date"])[:10] if prev else None,
                            "volume_avg": cur["volume_avg"],
                            "nav_price": cur["nav_price"],
                        },
                    }
                )
            return "stale" if worst > int(m["etf_flows_max_age_days"]) else "ok"

        guarded("etf_flows", "market", "snapshot date", etf_flows)

    return _seal({"schema": SCHEMA, "kind": "market", "cutoff": c.isoformat(), "sources": sources, "items": items})


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Print the alpha-stage evidence packets for one ticker (no LLM).")
    p.add_argument("--ticker", required=True)
    p.add_argument("--db", type=Path, default=None, help="DB file (default: the configured DB)")
    p.add_argument("--no-news", action="store_true", help="skip the live ticker-news fetch (no network)")
    args = p.parse_args(argv)
    news = None if args.no_news else live_news.fetch(args.ticker)
    out = {
        "ticker": build_packet(args.ticker, db_path=args.db, news=news),
        "market": build_market_packet(db_path=args.db),
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
