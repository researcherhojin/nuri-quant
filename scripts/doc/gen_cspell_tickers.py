"""config/universe.yaml 티커 → cspell 사전 자동생성.

수동으로 `.cspell.json` 에 티커를 하나씩 추가하는 whack-a-mole 제거. universe 의
모든 ticker 의 알파 토큰을 `.cspell/tickers.txt` 로 뽑아 cspell dictionary 로
참조한다. universe-sync 로 신규 티커가 들어오면 `make cspell-tickers` 한 번이면
모든 신규 심볼이 자동 인식 (사전 수동편집 0).

주의: 티커(데이터)만 allowlist. prose 오타는 계속 cspell 이 잡는다.
Usage: python scripts/doc/gen_cspell_tickers.py
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ROOT / "config" / "universe.yaml"
OUT = ROOT / ".cspell" / "tickers.txt"


def extract_ticker_words(universe_path: Path = UNIVERSE) -> set[str]:
    """universe 의 모든 그룹 tickers 에서 알파 토큰(≥2자) 추출.

    'AAPL' → {'AAPL'}, '005930.KS' → {'KS'} (숫자 코드는 cspell 이 무시),
    'BRK-B' → {'BRK', 'B'}. 길이 1 토큰은 제외 (오탐 방지).
    """
    data = yaml.safe_load(universe_path.read_text(encoding="utf-8")) or {}
    words: set[str] = set()
    for group in data.values():
        if isinstance(group, dict) and isinstance(group.get("tickers"), list):
            for ticker in group["tickers"]:
                for tok in re.split(r"[.\-]", str(ticker)):
                    if tok.isalpha() and len(tok) >= 2:
                        words.add(tok.upper())
    return words


def main() -> int:
    words = extract_ticker_words()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"{len(words)} ticker words → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
