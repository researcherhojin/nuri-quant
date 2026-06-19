"""#763 회귀: Makefile phase2-chain 타깃이 참조하는 스크립트 경로가 실재해야 한다.

#557 에서 run_phase2_chain.py 가 scripts/ → scripts/ops/ 로 이동했으나 Makefile 이
옛 경로(scripts/run_phase2_chain.py)를 참조해 `make phase2-chain` 이 즉시 실패했다.
"""

import importlib.util
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_makefile_phase2_chain_paths_exist():
    """Makefile 의 run_phase2_chain.py 참조 경로가 모두 실재."""
    mk = (_REPO / "Makefile").read_text()
    refs = re.findall(r"(\S*run_phase2_chain\.py)", mk)
    assert refs, "Makefile 에 run_phase2_chain.py 참조가 없음"
    for ref in refs:
        assert (_REPO / ref).exists(), f"Makefile 참조 경로 부재: {ref}"


def test_run_phase2_chain_importable_with_main():
    """스크립트가 import 되고 main(argv) 진입점을 노출 (dry-run smoke)."""
    p = _REPO / "scripts" / "ops" / "run_phase2_chain.py"
    assert p.exists()
    spec = importlib.util.spec_from_file_location("_run_phase2_chain", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.main)
