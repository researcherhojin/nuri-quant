"""KOSPI 200 종목코드 → 한글명 맵 생성 (config/kr_ticker_names.json).

`nuri.core.ticker_names` 의 2차 tier(network-free 로컬 맵)를 채운다. 맵이 없으면
`get_ticker_name` 이 `/tickers/search` 요청당 live pykrx 호출로 회귀(검색 경로 느려짐)
→ 재현성을 위한 재생성 도구. 런타임 collector(daily collect 사이클) 가 아니라 on-demand
생성 유틸이라 nuri/collectors/ 가 아닌 scripts/ops/ 에 둔다.

소스: FinanceDataReader `StockListing("KOSPI")` 시총 상위 200 (universe_sync.
`_fetch_kospi200` 과 **동일 기준**). 리스팅에 `Name` 컬럼이 이미 포함돼 추가 네트워크
없음 (pykrx per-ticker 호출 불필요). universe membership 과 거의 일치하나, universe-sync
와 별개 fetch 라 marcap 경계(200위 근처) 종목이 시점차로 미세하게 다를 수 있다 — 맵에
없는 종목은 ticker_names 가 live pykrx 로 self-healing fallback 하므로 무해.

파일은 gitignored — KOSPI200 구성종목에 증권사 상호가 포함돼 privacy 스캐너가
차단하기 때문. 따라서 신규 clone/머신은 `make kr-names` 로 1회 생성하고,
`make universe-sync-apply` 가 멤버십 변경 후 자동으로 뒤이어 갱신한다.

사용:
  make kr-names                          # 재생성
  python scripts/ops/gen_kr_names.py     # 동일
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# nuri.core.ticker_names._KR_NAMES_PATH 와 동일 파일 (config/kr_ticker_names.json)
KR_NAMES_PATH = Path(__file__).resolve().parents[2] / "config" / "kr_ticker_names.json"
_TOP_N = 200


def _fetch_kospi_listing():
    """FDR `StockListing("KOSPI")` df 반환. Code/Name/Marcap 컬럼 필요.

    Raises:
        FileNotFoundError: FDR 미설치.
        RuntimeError: 설치됐지만 데이터 못 받음 / 컬럼 이상.
    """
    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]
    except ImportError as e:
        raise FileNotFoundError(
            "KR 종목명 맵 생성에는 finance-datareader 필요: `uv pip install finance-datareader`"
        ) from e

    try:
        df = fdr.StockListing("KOSPI")
    except Exception as e:
        raise RuntimeError(f"FinanceDataReader KOSPI listing fetch 실패: {e}") from e

    if df is None or df.empty or not {"Code", "Name", "Marcap"}.issubset(df.columns):
        cols = df.columns.tolist() if df is not None else None
        raise RuntimeError(f"FinanceDataReader returned unexpected KOSPI data. cols: {cols}")
    return df


def build_name_map(df) -> dict[str, str]:
    """시총 상위 _TOP_N 의 {code.KS: 한글명} (key 정렬). 빈 이름은 제외."""
    top = df.nlargest(_TOP_N, "Marcap")
    mapping = {
        f"{str(code)}.KS": str(name).strip() for code, name in zip(top["Code"], top["Name"]) if str(name).strip()
    }
    return dict(sorted(mapping.items()))


def write_name_map(mapping: dict[str, str], path: Path | None = None) -> int:
    """맵을 json 으로 저장 (UTF-8, key 정렬). 반환: 항목 수.

    path 기본값은 호출 시점에 모듈 전역 KR_NAMES_PATH 를 읽는다 (테스트 monkeypatch 안전 —
    def-time 바인딩 회피).
    """
    path = path if path is not None else KR_NAMES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return len(mapping)


def regenerate(path: Path | None = None) -> int:
    """KOSPI200 listing fetch → 맵 빌드 → 저장. 반환: 저장 항목 수."""
    path = path if path is not None else KR_NAMES_PATH
    df = _fetch_kospi_listing()
    count = write_name_map(build_name_map(df), path)
    logger.info("KR 종목명 맵 %d건 저장 → %s", count, path)
    return count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    count = regenerate()
    print(f"config/kr_ticker_names.json: {count}건 저장")


if __name__ == "__main__":  # pragma: no cover - main() 자체는 TestMain 커버, runpy 는 실제 캐시 덮어쓰기 위험
    main()
