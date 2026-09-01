"""CI 의 per-test DB 격리 사본이 tmpfs 를 타는지 잠근다 (#1414).

격리 사본(832KB)은 테스트마다 한 번 복사된다. ubuntu 러너의 `/tmp` 는 루트
디스크라, I/O 가 열화된 러너를 뽑으면 워커 8개의 복사가 줄을 서서 무관한
테스트들의 setup 이 9~16초로 부풀고 shard 하나가 361초까지 늘어졌다
(run 33556006779 실측 — 나머지 7개 shard 는 132~157초였다). 증상이 "가끔
느린 shard" 라 코드 결함으로 오인되기 쉽고, 지표는 setup 시간뿐이다.

경로가 conftest(fixture)와 workflow(env) **두 곳**에 걸쳐 있어 어느 한쪽이
사라져도 조용히 디스크로 회귀한다 — 그래서 양쪽을 따로 잠근다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.conftest import make_isolated_db_copy

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestMakeIsolatedDbCopy:
    def test_env_dir_branch_copies_there_and_cleanup_removes(self, tmp_path, tmp_path_factory, monkeypatch):
        schema = tmp_path / "schema.db"
        schema.write_bytes(b"stub")
        base = tmp_path / "shm"
        monkeypatch.setenv("NURI_TEST_DB_DIR", str(base))

        path, cleanup = make_isolated_db_copy(schema, tmp_path_factory)

        assert path.parent == base, "NURI_TEST_DB_DIR 이 설정됐는데 사본이 다른 곳에 생겼다"
        assert path.read_bytes() == b"stub"
        cleanup()
        assert not path.exists(), "cleanup 이 사본을 안 지웠다 — tmpfs(RAM) 에 세션 내내 쌓인다"

    def test_unset_env_keeps_the_tmp_path_factory_behavior(self, tmp_path, tmp_path_factory, monkeypatch):
        """로컬(macOS 등)은 기존 경로 그대로 — 세션 종료 시 pytest 가 청소한다."""
        schema = tmp_path / "schema.db"
        schema.write_bytes(b"stub")
        monkeypatch.delenv("NURI_TEST_DB_DIR", raising=False)

        path, cleanup = make_isolated_db_copy(schema, tmp_path_factory)

        assert path.name == "portfolio.db" and path.exists()
        cleanup()  # no-op 이어야 한다
        assert path.exists(), "env 미설정 경로에서 cleanup 이 파일을 지웠다 — tmp_path_factory 관할이다"


class TestWorkflowWiring:
    """env 가 workflow 에서 빠지면 fixture 는 멀쩡한 채 조용히 디스크로 회귀한다.

    **Test:** tests/test_db_isolation_tmpfs.py::TestWorkflowWiring::test_both_shard_jobs_point_the_isolation_at_tmpfs
    """

    def test_both_shard_jobs_point_the_isolation_at_tmpfs(self):
        wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "main-ci-cd.yml").read_text(encoding="utf-8"))

        for job in ("backend-tests-shard", "backend-tests-slow"):
            env = wf["jobs"][job].get("env") or {}
            assert str(env.get("NURI_TEST_DB_DIR", "")).startswith("/dev/shm"), (
                f"{job} 에 NURI_TEST_DB_DIR(/dev/shm/...) 이 없다 — per-test DB 복사가 러너 디스크로 회귀한다"
            )
