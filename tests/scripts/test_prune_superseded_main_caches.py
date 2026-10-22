"""main 의 대체된 캐시만 지우는가 — 스크립트를 stub `gh` 로 실행해서 본다 (#1901).

**막으려는 것**: 2026-10-22 에 repo 캐시 10GB 한도 중 8.1GB 가 찼고, 그중 ~5.3GB 가 7일 미사용 축출
창 안에 있는 대체된 main 캐시(이전 uv.lock 해시 · CodeQL overlay 50개)였다. 정기 청소는 계열별 최신만
남기고, 현재 쓰는 캐시와 해시 접미사가 없는 고정 키, main 외 ref 는 건드리면 안 된다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "prune_superseded_main_caches.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cache-cleanup.yml"
LIST_CALL = "api --paginate repos/o/r/actions/caches?per_page=100&ref=refs/heads/main "

UV_OLD, UV_NEW = "a25db5e6" * 8, "eb254fbd" * 8


@pytest.fixture()
def gh(tmp_path: Path):
    """argv 를 기록하는 가짜 gh — 캐시 목록(id, key, created_at)을 TSV 파일로 받는다."""
    binz = tmp_path / "bin"
    binz.mkdir()
    calls, rows = tmp_path / "calls.txt", tmp_path / "rows.tsv"
    (binz / "gh").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'case "$*" in\n'
        f'    "{LIST_CALL}"*) [ -f "{rows}" ] || exit 1; cat "{rows}" ;;\n'
        '    "api -X DELETE "*) exit 0 ;;\n'
        "    *) exit 97 ;;\n"
        "esac\n"
    )
    (binz / "gh").chmod(0o755)

    def run(caches: list[tuple[int, str, str]] | None):
        if caches is not None:
            rows.write_text("".join(f"{i}\t{k}\t{c}\n" for i, k, c in caches))
        env = {**os.environ, "PATH": f"{binz}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "o/r"}
        r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
        return r, (calls.read_text().splitlines() if calls.exists() else [])

    return run


def _deleted(calls: list[str]) -> set[int]:
    return {int(c.rsplit("/", 1)[1]) for c in calls if c.startswith("api -X DELETE ")}


class TestPruneKeepsTheNewestPerFamily:
    def test_an_older_lock_hash_goes_and_the_current_one_stays(self, gh):
        r, calls = gh(
            [
                (1, f"venv-v2-Linux-ubuntu24-py3.12-{UV_OLD}", "2026-10-22T09:00:00Z"),
                (2, f"venv-v2-Linux-ubuntu24-py3.12-{UV_NEW}", "2026-10-22T13:00:00Z"),
                (3, f"uv-tool-Linux-ubuntu24-py3.12-{UV_NEW}", "2026-10-22T13:00:00Z"),
                (4, f"uv-tool-Linux-ubuntu24-py3.12-{UV_OLD}", "2026-10-22T09:00:00Z"),
            ]
        )
        assert r.returncode == 0, r.stderr
        assert _deleted(calls) == {1, 4}
        assert "pruned 2" in r.stdout

    def test_dated_keys_form_one_family(self, gh):
        r, calls = gh(
            [
                (1, "cache-trivy-2026-10-12", "2026-10-12T00:00:00Z"),
                (2, "cache-trivy-2026-10-19", "2026-10-19T00:00:00Z"),
                (3, "cache-trivy-2026-10-22", "2026-10-22T00:00:00Z"),
            ]
        )
        assert r.returncode == 0, r.stderr
        assert _deleted(calls) == {1, 2}

    def test_codeql_overlays_keep_the_newest_five(self, gh):
        base = "codeql-overlay-base-database-1-d953d79b74456ce0-python-2.27.3-"
        caches = [(i, f"{base}{i:07x}a", f"2026-10-22T{i:02d}:00:00Z") for i in range(1, 8)]
        r, calls = gh(caches)
        assert r.returncode == 0, r.stderr
        assert _deleted(calls) == {1, 2}

    def test_keys_without_a_hash_or_date_suffix_are_never_deleted(self, gh):
        r, calls = gh(
            [
                (1, "talib-0.4.0-Linux-ubuntu24-v5", "2026-10-01T00:00:00Z"),
                (2, "trivy-binary-v0.70.0-Linux-X64", "2026-10-02T00:00:00Z"),
                (3, "trivy-binary-v0.69.0-Linux-X64", "2026-09-02T00:00:00Z"),
                # 짧은 hex 처럼 보이는 끝 단어는 해시가 아니다 — 7자 이상만 해시로 본다.
                (4, "setup-node-v1-cafe", "2026-10-01T00:00:00Z"),
                (5, "setup-node-v1-beef", "2026-10-02T00:00:00Z"),
            ]
        )
        assert r.returncode == 0, r.stderr
        assert _deleted(calls) == set()


class TestPruneScope:
    def test_only_main_caches_are_listed(self, gh):
        r, calls = gh([])
        assert r.returncode == 0, r.stderr
        assert [c for c in calls if c.startswith("api --paginate")] == [
            f"{LIST_CALL}--jq .actions_caches[] | [.id, .key, .created_at] | @tsv"
        ]
        assert "pruned 0" in r.stdout

    def test_a_failed_listing_deletes_nothing(self, gh):
        r, calls = gh(None)
        assert r.returncode != 0
        assert _deleted(calls) == set()


class TestWorkflowWiring:
    def test_the_daily_sweep_runs_the_prune(self):
        wf = yaml.safe_load(WORKFLOW.read_text())
        steps = wf["jobs"]["sweep"]["steps"]
        runs = [s["run"].strip() for s in steps if "run" in s]
        assert "bash scripts/ci/prune_superseded_main_caches.sh" in runs
        prune = next(s for s in steps if s.get("run", "").strip() == "bash scripts/ci/prune_superseded_main_caches.sh")
        assert prune["env"]["GH_TOKEN"] == "${{ github.token }}"
