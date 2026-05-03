"""Universe sync — Wikipedia S&P 500 + KRX/FDR KOSPI 200 → universe.yaml diff.

#272 Phase 2a 구현. 원 SPEC 은 PR #276 에 shipped 기록 (TODO.md Tier 1 row 5).

사용법:
    python -m nuri.collectors.universe_sync                # dry-run (diff 출력만)
    python -m nuri.collectors.universe_sync --apply        # universe.yaml에 반영
    python -m nuri.collectors.universe_sync --market us    # US만 sync
    python -m nuri.collectors.universe_sync --market kr    # KR만 sync

전략:
- US S&P 500: Wikipedia (List_of_S%26P_500_companies, 503종목)
- KR KOSPI 200: pykrx (CLAUDE.md 알려진 깨짐) → FinanceDataReader fallback
- 변경 감지 시 STDOUT diff + (--apply 시) yaml 갱신
"""

from __future__ import annotations

import argparse
import logging
import urllib.request
from io import StringIO
from pathlib import Path
from typing import Any

import yaml

from nuri.collectors.base import DEFAULT_HEADERS, BaseCollector

logger = logging.getLogger(__name__)

UNIVERSE_PATH = Path("config/universe.yaml")
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# 95% 임계 (spec §2.1)
COVERAGE_THRESHOLD = 0.95


def _fetch_sp500_from_wikipedia() -> list[str]:
    """Wikipedia에서 S&P 500 ticker 503종목 fetch.

    Wikipedia 표 첫 컬럼 'Symbol'. BRK.B 같은 종목은 BRK-B로 변환 (yfinance 호환).
    """
    import pandas as pd

    req = urllib.request.Request(SP500_URL, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8")

    tables = pd.read_html(StringIO(html))
    df = tables[0]
    if "Symbol" not in df.columns:
        raise RuntimeError(f"Wikipedia S&P 500 표 형식 변경 감지 — Symbol 컬럼 없음. cols={df.columns.tolist()}")

    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))


def _fetch_kospi200() -> list[str]:
    """KOSPI 200 fetch — 시총 상위 200 by Marcap (KOSPI 200 index 근사치).

    FDR의 `SnapDataReader("KRX/INDEX/STOCK/KS200")` 는 2026-04 기준 깨짐 (KRX API 변경).
    대신 `StockListing("KOSPI")` — 이건 정상 작동하며 Marcap 컬럼 포함.
    시총 상위 200 ≈ 정식 KOSPI 200 index (95%+ overlap; spec §2.1 허용 범위).

    반환 형식: ["005930.KS", "000660.KS", ...] (yfinance suffix 포함)

    Raises:
        FileNotFoundError: FDR 미설치 (pip install finance-datareader 안내)
        RuntimeError: FDR 설치됐지만 데이터 못 받음 (KRX 변경 등)
    """
    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]
    except ImportError as e:
        raise FileNotFoundError(
            "KOSPI 200 sync requires finance-datareader. Install: `uv pip install finance-datareader`"
        ) from e

    try:
        df = fdr.StockListing("KOSPI")
    except Exception as e:
        raise RuntimeError(f"FinanceDataReader KOSPI listing fetch 실패: {e}") from e

    if df is None or df.empty or "Code" not in df.columns or "Marcap" not in df.columns:
        raise RuntimeError(
            f"FinanceDataReader returned unexpected KOSPI data. cols: {df.columns.tolist() if df is not None else 'None'}"
        )

    # 시총 상위 200 (보통주만 — 우선주 '005935' 같은 경우 제외하려면 Stocks/Market 필터 필요하지만
    # KRX Code가 중복 없이 유일하므로 그대로 사용. 실용상 충분).
    top200 = df.nlargest(200, "Marcap")
    tickers = sorted(set(f"{code}.KS" for code in top200["Code"].astype(str)))
    if len(tickers) < 100:
        raise RuntimeError(f"KOSPI 상위 ticker 수 {len(tickers)} < 100 minimum — 데이터 이상")
    return tickers


def _load_universe() -> dict[str, Any]:
    """current universe.yaml 로드.

    Raises:
        FileNotFoundError: universe.yaml 이 없으면 actionable error message 포함.
        ValueError: yaml 파싱 실패 시 원인 + 해결 방법 안내.
    """
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(
            f"{UNIVERSE_PATH} 가 없습니다. fresh clone 이면 `make setup` 실행, "
            f"또는 `git checkout main -- {UNIVERSE_PATH}` 로 복구."
        )
    try:
        with UNIVERSE_PATH.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(
            f"{UNIVERSE_PATH} YAML 파싱 실패: {e}. 편집 중 문법 오류 확인 또는 "
            f"`git checkout main -- {UNIVERSE_PATH}` 로 되돌리기."
        ) from e
    if data is None:
        raise ValueError(f"{UNIVERSE_PATH} 가 비어있음. 최소 us + kr 섹션 필요.")
    return data


def _save_universe(u: dict[str, Any]) -> None:
    """universe.yaml에 갱신 저장 (sort_keys=False 보존)."""
    with UNIVERSE_PATH.open("w") as f:
        yaml.safe_dump(u, f, allow_unicode=True, sort_keys=False, width=200)


def compute_diff(current_us: set[str], current_kr: set[str], fetched_us: set[str], fetched_kr: set[str]) -> dict:
    """universe diff 계산.

    Returns:
        {
            'us_added': [ticker, ...],     # fetched에 있고 current에 없음
            'us_removed': [ticker, ...],   # current에 있고 fetched에 없음
            'kr_added': [...],
            'kr_removed': [...],
            'us_coverage_pct': float,      # current / fetched
            'kr_coverage_pct': float,
        }
    """
    return {
        "us_added": sorted(fetched_us - current_us),
        "us_removed": sorted(current_us - fetched_us),
        "kr_added": sorted(fetched_kr - current_kr),
        "kr_removed": sorted(current_kr - fetched_kr),
        "us_coverage_pct": len(current_us & fetched_us) / max(len(fetched_us), 1),
        "kr_coverage_pct": len(current_kr & fetched_kr) / max(len(fetched_kr), 1),
    }


class UniverseSyncCollector(BaseCollector):
    """Universe definition sync collector.

    BaseCollector 패턴이지만 collect()는 diff dict, save()는 yaml 쓰기 (또는 dry-run).
    """

    def __init__(self):
        super().__init__("universe_sync")
        self._dry_run = True
        self._market_filter: str | None = None  # None | 'us' | 'kr'
        self._allow_removal = False  # 기본적으로 자동 제거 금지 (manual ETF 보호)
        self._kr_skipped = False  # KR fetch 건너뜀 플래그 (UX용)

    def collect(self, **kwargs) -> dict:
        """Wikipedia + KRX fetch → diff 계산.

        Args:
            market: 'us' | 'kr' | None (전체)
            dry_run: True (default) — yaml 안 건드림. False — apply.
            allow_removal: False (default) — added만 반영, removed는 무시 (manual ETF 보호).
        """
        self._dry_run = kwargs.get("dry_run", True)
        self._market_filter = kwargs.get("market")
        self._allow_removal = kwargs.get("allow_removal", False)

        current = _load_universe()
        current_us = set(current.get("us_core", {}).get("tickers", [])) | set(
            current.get("us_sp500_extended", {}).get("tickers", [])
        )
        current_kr = set(current.get("kr_kospi200", {}).get("tickers", []))

        # 필터된 시장 외에는 current를 그대로 사용 → diff 0건 보장
        fetched_us: set[str] = current_us
        fetched_kr: set[str] = current_kr

        # 재시도 비활성: universe_sync 는 영구 실패가 일반적 (FDR 미설치 등). transient retry 무의미.
        # base.py는 _expected_count==0이면 실패율 체크 안 함. 그러나 raise시 3회 retry — 그래서 raise 최소화.
        self._expected_count = 0

        if self._market_filter in (None, "us"):
            self.logger.info("Wikipedia에서 S&P 500 fetch...")
            try:
                fetched_us = set(_fetch_sp500_from_wikipedia())
                self.logger.info("S&P 500: %d종목 fetched", len(fetched_us))
            except Exception as e:
                self.logger.error("S&P 500 fetch 실패: %s", e)
                if self._market_filter == "us":
                    raise

        if self._market_filter in (None, "kr"):
            self.logger.info("KOSPI 200 fetch (FinanceDataReader)...")
            try:
                fetched_kr = set(_fetch_kospi200())
                self.logger.info("KOSPI 200: %d종목 fetched", len(fetched_kr))
            except (FileNotFoundError, RuntimeError) as e:
                # 영구 실패 (FDR 미설치 / KRX upstream 장애) — 절대 raise 안 함:
                # BaseCollector retry 3회로 동일 traceback 3개 발생 방지.
                # 명시적 --market kr 호출자는 _kr_skipped 플래그로 실패 감지 가능.
                self.logger.warning("KR sync 건너뜀: %s", e)
                self._kr_skipped = True

        return compute_diff(current_us, current_kr, fetched_us, fetched_kr)

    def run(self, **kwargs) -> int:
        """Override BaseCollector.run() — universe_sync 실패는 transient 아니므로 retry 비활성.

        BaseCollector는 모든 Exception에 3회 retry. 이는 network blip 같은 transient용.
        Universe sync 실패는 영구적 (FDR 미설치 / KRX API 변경 / Wikipedia 404):
        retry해도 같은 traceback 3개만 더 출력. 따라서 1회만 시도.
        """
        from nuri.core.timezone import kst_now

        self.logger.info("[%s] 수집 시작", self.name)
        start = kst_now()
        try:
            data = self.collect(**kwargs)
            count = self.save(data)
            elapsed = (kst_now() - start).total_seconds()
            self.logger.info("[%s] 완료: %d건, %.1f초", self.name, count, elapsed)
            return count
        except Exception as e:
            self.logger.error("[%s] 실행 실패: %s", self.name, e)
            raise

    def save(self, data: dict) -> int:
        """diff 출력 + (apply 시) universe.yaml 갱신.

        Returns: 변경된 ticker 총 수 (added + removed, US + KR 합산).
        """
        total_changes = (
            len(data["us_added"]) + len(data["us_removed"]) + len(data["kr_added"]) + len(data["kr_removed"])
        )

        # diff 출력
        print()
        print("=" * 70)
        print(f"  Universe Sync — {'DRY RUN' if self._dry_run else 'APPLYING'}")
        print("=" * 70)
        if self._market_filter in (None, "us"):
            print(f"\n  US S&P 500 (current coverage: {data['us_coverage_pct']:.1%})")
            print(
                f"    + 추가될 종목 ({len(data['us_added'])}): {', '.join(data['us_added'][:10])}"
                + (f" ... 외 {len(data['us_added']) - 10}개" if len(data["us_added"]) > 10 else "")
            )
            print(
                f"    - 제거될 종목 ({len(data['us_removed'])}): {', '.join(data['us_removed'][:10])}"
                + (f" ... 외 {len(data['us_removed']) - 10}개" if len(data["us_removed"]) > 10 else "")
            )

        if self._market_filter in (None, "kr"):
            if self._kr_skipped:
                print("\n  KR KOSPI 200: ⏭️  건너뜀 — 위 WARNING 로그 참조")
                print("     • FDR 미설치: `uv pip install finance-datareader`")
                print("     • FDR 설치됐는데 fetch 실패: KRX upstream 일시 장애 (재시도 또는 cache 필요)")
            else:
                print(f"\n  KR KOSPI 200 (current coverage: {data['kr_coverage_pct']:.1%})")
                print(
                    f"    + 추가될 종목 ({len(data['kr_added'])}): {', '.join(data['kr_added'][:10])}"
                    + (f" ... 외 {len(data['kr_added']) - 10}개" if len(data["kr_added"]) > 10 else "")
                )
                print(
                    f"    - 제거될 종목 ({len(data['kr_removed'])}): {', '.join(data['kr_removed'][:10])}"
                    + (f" ... 외 {len(data['kr_removed']) - 10}개" if len(data["kr_removed"]) > 10 else "")
                )

        print()

        # 자동 제거 보호 안내
        if not self._allow_removal and (data["us_removed"] or data["kr_removed"]):
            print(
                f"  ⚠️  manual ETF 보호: removed {len(data['us_removed']) + len(data['kr_removed'])}건 무시 "
                f"(--allow-removal로 명시적 허용)"
            )

        # apply
        if not self._dry_run and total_changes > 0:
            current = _load_universe()
            applied = 0
            if self._market_filter in (None, "us") and data["us_added"]:
                core = set(current["us_core"]["tickers"])
                ext = set(current["us_sp500_extended"]["tickers"])
                ext = ext | set(data["us_added"])
                if self._allow_removal:
                    ext = ext - set(data["us_removed"])
                ext = ext - core  # core 중복 제거
                current["us_sp500_extended"]["tickers"] = sorted(ext)
                current["us_sp500_extended"]["description"] = (
                    f"미국 S&P 500 + extras — us_core에 없는 추가 종목 ({len(ext)}개)"
                )
                applied += len(data["us_added"])
                if self._allow_removal:
                    applied += len(data["us_removed"])
                self.logger.info("us_sp500_extended 갱신: %d종목", len(ext))

            if self._market_filter in (None, "kr") and data["kr_added"]:
                kr = set(current["kr_kospi200"]["tickers"])
                kr = kr | set(data["kr_added"])
                if self._allow_removal:
                    kr = kr - set(data["kr_removed"])
                current["kr_kospi200"]["tickers"] = sorted(kr)
                current["kr_kospi200"]["description"] = f"한국 KOSPI 200 — 시가총액 상위 ({len(kr)}개)"
                applied += len(data["kr_added"])
                if self._allow_removal:
                    applied += len(data["kr_removed"])
                self.logger.info("kr_kospi200 갱신: %d종목", len(kr))

            if applied > 0:
                _save_universe(current)
                print(f"  ✅ universe.yaml 갱신 완료 ({applied}건 반영, removed 보호 {total_changes - applied}건)")
            else:
                print("  ℹ️  반영 가능 변경 없음 (모두 removed인데 --allow-removal 미설정)")
        elif self._dry_run and total_changes > 0:
            print(f"  ℹ️  dry-run — 실제 변경 없음 (총 {total_changes}건). --apply 옵션으로 반영.")
        else:
            print("  ✅ 변경 없음 (universe.yaml = upstream)")

        return total_changes


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Nuri-Quant Universe Sync (#272 Phase 2a)")
    parser.add_argument("--apply", action="store_true", help="universe.yaml에 변경 반영 (기본: dry-run)")
    parser.add_argument("--market", choices=["us", "kr"], help="특정 시장만 sync (기본: 전체)")
    parser.add_argument(
        "--allow-removal",
        action="store_true",
        help="upstream에서 제거된 종목을 universe에서도 자동 제거 (기본: manual ETF 보호 OFF)",
    )
    args = parser.parse_args()

    collector = UniverseSyncCollector()
    collector.run(dry_run=not args.apply, market=args.market, allow_removal=args.allow_removal)
