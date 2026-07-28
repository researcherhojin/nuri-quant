"""`verify_doc_counts.sh` 는 한 클레임의 **모든** 등장 위치를 검사한다.

README 는 같은 수치를 두 번 말한다 — mermaid 노드의 `SQLite WAL · 51 tables` 와
Project Stats 표의 같은 문구. 예전 `extract_num` 은 `head -1` 로 **첫 번째만** 읽어서,
두 번째 site 가 틀려도 게이트가 초록으로 통과했다. 문서에 박힌 숫자의 절반이
사실상 검사되지 않는 상태였고, 그건 "게이트가 있다" 는 인상만 주는 쪽이 더 나쁘다.

Gotcha-Test Pair: `extract_nums` 를 `head -1` 로 되돌리면 두 번째 테스트가 FAIL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify" / "verify_doc_counts.sh"


def _db_tables_line(cwd: Path) -> str:
    """스크립트를 돌리고 `db_tables` 결과 줄만 뽑는다.

    종료 코드가 아니라 이 한 줄만 본다 — 얕은 사본에는 다른 체크의 입력이 없어서
    전체 exit code 로 판정하면 이 테스트가 무관한 이유로 흔들린다.
    """
    # `scripts/_common.sh` 는 스크립트 자신의 레포 루트로 cd 하므로 cwd 만으로는
    # 사본을 가리킬 수 없다. 그 파일이 제공하는 REPO_ROOT override 를 쓴다.
    r = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=cwd,
        env={**os.environ, "REPO_ROOT": str(cwd)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    lines = [ln for ln in r.stdout.splitlines() if "db_tables" in ln]
    assert lines, f"db_tables 체크가 실행되지 않음:\n{r.stdout}{r.stderr}"
    return lines[0]


@pytest.fixture
def repo_copy(tmp_path):
    """README + 검사에 필요한 파일만 복사한 얕은 레포 사본.

    `.venv` 는 심볼릭 링크로 빌려온다 — `live_db_tables` 가 `[ -x .venv/bin/python ]`
    를 요구하고, 없으면 그 체크가 통째로 skip 돼 검증 대상이 사라진다. 링크된 venv 는
    실제 스키마(51)를 측정하고, 대조 대상인 README 는 사본 것이 쓰인다.
    """
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in (
        "README.md",
        "CLAUDE.md",
        "docs/ARCHITECTURE.md",
        "docs/STRATEGY.md",
        "config/CLAUDE.md",
        "nuri/api/CLAUDE.md",
        "nuri/collectors/CLAUDE.md",
        ".claude/rules/architecture.md",
        "nuri/core/db_migrations.py",
        "nuri/scheduler.py",
        "config/rules.yaml",
    ):
        src = REPO_ROOT / rel
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    (dst / "nuri" / "collectors").mkdir(parents=True, exist_ok=True)
    for p in (REPO_ROOT / "nuri" / "collectors").glob("*.py"):
        shutil.copy2(p, dst / "nuri" / "collectors" / p.name)
    (dst / "nuri" / "api" / "routes").mkdir(parents=True, exist_ok=True)
    for p in (REPO_ROOT / "nuri" / "api" / "routes").glob("*.py"):
        shutil.copy2(p, dst / "nuri" / "api" / "routes" / p.name)
    for sub in ("tests", "frontend/src", "frontend/e2e"):
        (dst / sub).mkdir(parents=True, exist_ok=True)
    (dst / "pyproject.toml").write_text("")  # _common.sh 의 레포 루트 판별 마커
    (dst / ".venv").symlink_to(REPO_ROOT / ".venv")
    return dst


class TestMultiSiteVerification:
    def test_unmodified_copy_reports_two_sites(self, repo_copy):
        """대조군 — 손대지 않으면 통과하고, 검사한 site 수를 보고한다."""
        line = _db_tables_line(repo_copy)
        assert "✓" in line, line
        assert "2 sites" in line, f"다중 site 검사가 꺼졌다: {line}"

    def test_drift_at_the_second_site_is_caught(self, repo_copy):
        """두 번째 등장 위치만 틀려도 DRIFT.

        `head -1` 시절에는 이 변조가 통과했다 — 그게 이 테스트의 존재 이유다.
        """
        readme = repo_copy / "README.md"
        text = readme.read_text()
        marker = "51 tables"
        assert text.count(marker) >= 2, "README 가 이 수치를 한 번만 말하면 다중 site 계약이 사라진 것"

        head, sep, tail = text.partition(marker)  # 첫 번째는 그대로 두고
        readme.write_text(head + sep + tail.replace(marker, "99 tables", 1))  # 두 번째만 변조

        line = _db_tables_line(repo_copy)
        assert "DRIFT" in line, f"두 번째 site 의 drift 가 통과함 — head -1 회귀: {line}"
        assert "99" in line, line

    def test_drift_at_the_first_site_is_caught(self, repo_copy):
        """첫 번째 위치 검사는 회귀하지 않았는지 (기존 동작 보존)."""
        readme = repo_copy / "README.md"
        readme.write_text(readme.read_text().replace("51 tables", "99 tables", 1))
        assert "DRIFT" in _db_tables_line(repo_copy)
