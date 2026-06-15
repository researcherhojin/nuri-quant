"""cSpell 티커 사전 생성 (.cspell/tickers.txt).

universe.yaml 의 티커 심볼들을 cSpell custom dictionary 로 추출 → 코드/문서에 등장하는
티커가 맞춤법 오류로 플래그되지 않게 한다. universe-sync 로 종목이 바뀌면 신규 티커가
오류로 떠서 매뉴얼로 추가해야 했던 것을 재현 가능한 generator 로 자동화한다 (gen_kr_names
와 동일 패턴 — scripts/ops 생성기 + make 타깃 + universe-sync-apply 체이닝).

추출 규칙: 각 티커를 `.`/`-` 로 split 해 alpha 파트(길이 ≥ 2)만 대문자로 수집.
- "BRK-B" → BRK (B 는 단일문자 제외 — cSpell 은 단일문자 미플래그)
- "005930.KS" → KS (숫자 코드는 cSpell 미플래그라 자동 제외)
정렬·중복제거 후 한 줄에 하나씩 기록.

파일은 gitignored 가 아님 — US 티커는 공개 정보(privacy 무관)라 추적 대상.
신규 clone 은 `make cspell-tickers`, universe 변경 시 universe-sync-apply 가 자동 갱신.

사용:
  make cspell-tickers                          # 재생성
  python scripts/ops/gen_cspell_tickers.py     # 동일
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = _REPO_ROOT / "config" / "universe.yaml"
TICKERS_PATH = _REPO_ROOT / ".cspell" / "tickers.txt"


def build_ticker_words(universe: dict) -> list[str]:
    """universe.yaml dict → 정렬된 cSpell 단어 목록.

    각 티커를 `.`/`-` 로 분해해 alpha 파트(len >= 2)만 대문자 수집 (중복제거·정렬).
    """
    words: set[str] = set()
    for group in universe.values():
        if isinstance(group, dict) and "tickers" in group:
            for ticker in group["tickers"]:
                for part in re.split(r"[.-]", str(ticker)):
                    if part.isalpha() and len(part) >= 2:
                        words.add(part.upper())
    return sorted(words)


def write_ticker_words(words: list[str], path: Path | None = None) -> int:
    """단어 목록을 한 줄에 하나씩 저장 (trailing newline). 반환: 단어 수.

    path 기본값은 호출 시점에 모듈 전역 TICKERS_PATH 를 읽는다 (테스트 monkeypatch 안전).
    """
    path = path if path is not None else TICKERS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(words) + "\n", encoding="utf-8")
    return len(words)


def regenerate(universe_path: Path | None = None, out_path: Path | None = None) -> int:
    """universe.yaml 로드 → 단어 빌드 → 저장. 반환: 단어 수."""
    universe_path = universe_path if universe_path is not None else UNIVERSE_PATH
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8")) or {}
    count = write_ticker_words(build_ticker_words(universe), out_path)
    logger.info("cSpell 티커 사전 %d개 저장 → %s", count, out_path or TICKERS_PATH)
    return count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    count = regenerate()
    print(f".cspell/tickers.txt: {count}개 저장")


if __name__ == "__main__":  # pragma: no cover - main() 자체는 TestMain 커버, runpy 는 실제 사전 덮어쓰기 위험
    main()
