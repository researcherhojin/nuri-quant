"""NURI_DB_PATH 코어 오버라이드 (#1240) — import 시점 해석이라 subprocess 로 잠근다."""

import subprocess
import sys


def _resolve_db_path(env: dict | None) -> str:
    """자식 프로세스에서 DB_PATH 를 해석해 돌려받는다 (부모의 import 캐시 회피)."""
    import os

    child_env = dict(os.environ)
    child_env.pop("NURI_DB_PATH", None)
    if env:
        child_env.update(env)
    out = subprocess.run(
        [sys.executable, "-c", "from nuri.core.db.connection import DB_PATH; print(DB_PATH)"],
        capture_output=True,
        text=True,
        env=child_env,
        check=True,
    )
    return out.stdout.strip()


class TestNuriDbPathEnvOverride:
    def test_env_set_overrides_the_default(self, tmp_path):
        target = tmp_path / "seeded.db"
        assert _resolve_db_path({"NURI_DB_PATH": str(target)}) == str(target)

    def test_env_unset_keeps_the_default(self):
        # 프로덕션(launchd, env 미설정) 무영향 계약 — 기본 경로 그대로
        resolved = _resolve_db_path(None)
        assert resolved.endswith("data/portfolio.db")
