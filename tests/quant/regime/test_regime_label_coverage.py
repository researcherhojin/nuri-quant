"""분류기가 낼 수 있는 모든 레짐에 화면 라벨이 있어야 한다 (#1676).

`frontend/src/lib/strings.ts` 의 `REGIME_LABEL` 은 기본 6종만 담고 있었고, 특수 레짐
(`sector_rotation` 등)은 Overview Preview 시장 카드에 원문 키 그대로 나갔다. 라벨 표는
TypeScript 이고 레짐 목록은 Python 이라 어느 한쪽 테스트만으로는 둘의 어긋남을 못 본다 —
그래서 여기서 소스 텍스트를 읽어 `ALL_REGIMES` 와 양방향으로 대조한다.
"""

import re
from pathlib import Path

from nuri.quant.regime.classifier import ALL_REGIMES

STRINGS_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "strings.ts"


def _regime_label_keys() -> set[str]:
    source = STRINGS_TS.read_text(encoding="utf-8")
    block = re.search(r"export const REGIME_LABEL = \{(.*?)\} satisfies", source, re.S)
    assert block, "strings.ts 에서 REGIME_LABEL 블록을 찾지 못했다 — 선언 형태가 바뀌었으면 이 파서도 고칠 것"
    return set(re.findall(r"^\s*([a-z_]+):\s*\"", block.group(1), re.M))


class TestRegimeLabelCoverage:
    def test_every_classifier_regime_has_a_label(self):
        missing = set(ALL_REGIMES) - _regime_label_keys()
        assert not missing, f"REGIME_LABEL 에 라벨이 없는 레짐: {sorted(missing)}"

    def test_no_label_for_a_regime_the_classifier_cannot_emit(self):
        stale = _regime_label_keys() - set(ALL_REGIMES)
        assert not stale, f"분류기가 내지 않는 레짐 라벨: {sorted(stale)}"
