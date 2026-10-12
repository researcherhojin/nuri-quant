"""`make migrate` 와, 수집·스캔 타깃이 그걸 먼저 도는지 (#1828).

수집기는 `init_db()` 를 부르지 않는다. 그래서 migration 이 뒤처진 dev DB 에서 `make collect` 를 돌리면
새 컬럼을 쓰는 수집기가 실패했다 — 2026-10-12 전체 사이클에서 가격 수집기가 `prices.source` 없음으로
죽었다. 프로덕션은 스케줄러가 기동할 때 `init_db()` 를 부르므로 해당이 없다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nuri.core.db import get_schema_version

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make(*args: str, env: dict[str, str] | None = None) -> list[str]:
    out = subprocess.run(
        ["make", "--no-print-directory", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


@pytest.mark.parametrize("target", ["collect", "quick-scan", "full-scan"])
def test_the_target_migrates_before_any_collector_runs(target):
    # `make -n` 은 실행 없이 명령만 펼친다.
    cmds = _make("-n", target)
    collector = next((i for i, c in enumerate(cmds) if "-m nuri.collectors." in c), None)
    migrate = next((i for i, c in enumerate(cmds) if "scripts/db/migrate.py" in c), None)
    assert collector is not None, f"{target} 가 수집기를 돌지 않는다 — 이 테스트의 전제가 바뀌었다"
    assert migrate is not None and migrate < collector, "\n".join(cmds)


def test_make_migrate_brings_a_fresh_database_to_the_current_schema(tmp_path):
    db = tmp_path / "fresh.db"
    lines = _make("migrate", env={**os.environ, "NURI_DB_PATH": str(db)})

    version = get_schema_version(db)
    assert version > 0
    # make 는 실행하는 명령 줄도 찍는다 — 마지막 줄이 스크립트의 한 줄 출력이다.
    assert lines[-1].startswith(f"DB schema version {version} ("), lines


def test_the_maintenance_auditor_still_reads_the_collect_recipe():
    """prerequisite 를 `collect:` 줄에 붙이면 auditor 의 `^collect:\\n` 이 레시피를 놓친다.

    그러면 프로덕션 auditor 가 스캔마다 "collect 타깃을 찾을 수 없음" 을 낸다. 실제 Makefile 로
    이 스캐너를 돌리는 테스트는 이것 하나다.
    """
    from nuri.agents.actors import maintenance_auditor as ma

    ctx = ma.ScanContext(repo_root=REPO_ROOT, tracker=ma._CapTracker(caps=ma.AuditCaps()), db_path=None)
    titles = [f["title"] for f in ma.scan_scheduler_wiring(ctx)]
    assert "Makefile collect: 타깃을 찾을 수 없음" not in titles, titles
