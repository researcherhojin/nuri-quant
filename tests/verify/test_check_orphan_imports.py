"""`scripts/verify/check_orphan_imports.py` 계약 (#902).

이전 구현(옛 경로 하드코딩 grep)은 `nuri/agents/` actor fleet 처럼 나중에 생긴 1급
패키지를 제외 목록에 못 넣어 정당한 import 353 건을 orphan 으로 잡았고, 그 결과
`make verify-all` 이 **구조적으로 통과 불가**였다 — 5단계가 항상 빨간불이라 1~4단계의
진짜 신호까지 함께 묻혔다.

그래서 두 방향을 다 잠근다: 진짜 orphan 을 잡는가(민감도) + 현재 레포를 통과시키는가
(특이도). 특이도 쪽이 원래 결함이므로 그게 핵심이다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify" / "check_orphan_imports.py"

sys.path.insert(0, str(SCRIPT.parent))
import check_orphan_imports as coi  # noqa: E402


class TestResolution:
    """`_resolve` — dotted name → 파일시스템. import 를 실행하지 않는다."""

    @pytest.mark.parametrize(
        "mod",
        [
            "nuri",  # 패키지 __init__
            "nuri.scheduler",  # 단일 모듈
            "nuri.core.db",  # 서브패키지 __init__
            "nuri.core.db.connection",  # 서브패키지 내 모듈
            "nuri.agents.actors.sre_incident_agent",  # 예전 구현이 orphan 으로 오탐하던 경로
            "nuri.quant.factors.composite",  # 마찬가지
        ],
    )
    def test_existing_modules_resolve(self, mod):
        assert coi._resolve(mod), f"{mod} 는 실존하는데 미해석"

    @pytest.mark.parametrize(
        "mod",
        ["nuri.regime.classifier", "nuri.strategy.longshort", "nuri.does_not_exist"],
    )
    def test_moved_or_absent_modules_do_not_resolve(self, mod):
        assert not coi._resolve(mod), f"{mod} 는 없는데 해석됨"


class TestRepoIsClean:
    def test_no_orphans_in_current_tree(self):
        """현재 레포는 통과해야 한다 — 이게 #902 의 본질(오탐 353건).

        Gotcha-Test Pair: 옛 하드코딩 grep 으로 되돌리면 353 을 반환해 FAIL.
        """
        orphans = coi.find_orphans()
        assert orphans == [], f"orphan import {len(orphans)}건:\n" + "\n".join(orphans[:10])

    def test_cli_exits_zero_and_prints_count(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=120, check=False)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "0"


class TestDetectsRealOrphans:
    def test_import_of_missing_module_is_flagged(self, tmp_path, monkeypatch):
        """존재하지 않는 `nuri.*` 를 import 하면 잡힌다 (민감도)."""
        root = tmp_path
        (root / "nuri").mkdir()
        (root / "nuri" / "__init__.py").write_text("")
        (root / "nuri" / "real.py").write_text("X = 1\n")
        (root / "scripts").mkdir()
        (root / "scripts" / "bad.py").write_text(
            "from nuri.real import X\nfrom nuri.ghost import Y\nimport nuri.also_missing\n"
        )
        monkeypatch.setattr(coi, "REPO_ROOT", root)

        orphans = coi.find_orphans()
        found = {o.split(": ")[1] for o in orphans}
        assert found == {"nuri.ghost", "nuri.also_missing"}, orphans

    def test_relative_and_thirdparty_imports_are_ignored(self, tmp_path, monkeypatch):
        """상대 import 와 서드파티는 검사 대상이 아니다 (오탐 방지)."""
        root = tmp_path
        (root / "nuri").mkdir()
        (root / "nuri" / "__init__.py").write_text("")
        (root / "nuri" / "mod.py").write_text(
            "from . import sibling\nfrom .deep import thing\nimport pandas\nfrom yfinance import Ticker\n"
        )
        monkeypatch.setattr(coi, "REPO_ROOT", root)

        assert coi.find_orphans() == []

    def test_syntax_error_file_does_not_crash_the_check(self, tmp_path, monkeypatch):
        """문법 오류는 lint/test 담당 — 여기서 중복 실패시키지 않는다."""
        root = tmp_path
        (root / "nuri").mkdir()
        (root / "nuri" / "__init__.py").write_text("")
        (root / "nuri" / "broken.py").write_text("def f(:\n")
        monkeypatch.setattr(coi, "REPO_ROOT", root)

        assert coi.find_orphans() == []
