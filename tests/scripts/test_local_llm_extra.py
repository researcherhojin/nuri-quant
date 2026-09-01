"""Local llama.cpp fallback 의 설치 경계를 잠근다 (#1406).

PyPI 기본 인덱스의 ``llama-cpp-python`` 은 sdist 라, 기본 dependency 에 두면
GGUF 모델을 쓰지 않는 CI fast shard 6개와 E2E가 같은 C++ 소스를 각각 빌드한다.
반대로 production 배포에서 extra 를 빼면 ``LLAMA_MODEL_PATH`` fallback 이 조용히
ImportError 경로로 떨어진다. 두 경계를 함께 검사해야 한쪽 최적화가 다른 쪽 회귀가
되지 않는다.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class TestLocalLlmExtraPolicy:
    def test_llama_cpp_is_optional(self):
        config = tomllib.loads(_read("pyproject.toml"))
        runtime = config["project"]["dependencies"]
        local_llm = config["project"]["optional-dependencies"]["local-llm"]

        assert not any(dep.startswith("llama-cpp-python") for dep in runtime), (
            "llama-cpp-python 이 기본 dependency 로 돌아갔다 — CI 모든 job 이 native C++ 를 중복 빌드한다"
        )
        assert sum(dep.startswith("llama-cpp-python") for dep in local_llm) == 1, (
            "local-llm extra 에 llama-cpp-python 이 정확히 한 번 있어야 한다"
        )

    def test_ci_excludes_local_llm(self):
        action = _read(".github/actions/setup-backend-env/action.yml")
        sync_lines = [line for line in action.splitlines() if "run: uv sync" in line]
        assert sync_lines, "backend CI setup 에 uv sync 가 없다"
        assert all("--extra dev" in line for line in sync_lines)
        assert all("--extra local-llm" not in line for line in sync_lines), (
            "GGUF 없는 CI 가 local-llm extra 를 설치한다 — shard 마다 native build 가 반복된다"
        )

    def test_ci_keeps_one_linux_build_gate(self):
        """extra 가 test env 를 떠나면 Linux native 빌드 게이트 1개는 남아야 한다 (#1406 조건)."""
        workflow = _read(".github/workflows/main-ci-cd.yml")
        assert "local-llm-build-gate:" in workflow, (
            "local-llm extra 의 Linux 빌드/임포트 호환성을 검증하는 게이트 job 이 사라졌다"
        )
        assert "import llama_cpp" in workflow, (
            "빌드 게이트가 llama_cpp 를 실제로 import 하지 않는다 — 빌드 성공 ≠ 임포트 가능"
        )
        assert "run_local_llm_gate" in workflow, (
            "게이트가 changes job 의 deps 필터에 배선되지 않았다 — 항상 skip 되거나 항상 돈다"
        )

    def test_dev_setup_includes_local_llm(self):
        setup = _read("scripts/dev/setup.sh")
        sync_lines = [line for line in setup.splitlines() if line.startswith("uv sync")]
        assert sync_lines and all("--extra local-llm" in line for line in sync_lines), (
            "make setup 이 local-llm extra 를 빼 기존 로컬 GGUF fallback 설치 동작을 잃었다"
        )

    def test_deploy_paths_include_local_llm(self):
        for relative in (
            "scripts/deploy/autopull_receiver.sh",
            "scripts/deploy/deploy_to_mini.sh",
        ):
            sync_lines = [line for line in _read(relative).splitlines() if "sync --extra dev" in line]
            assert sync_lines and all("--extra local-llm" in line for line in sync_lines), (
                f"{relative} 가 local-llm extra 를 빼 production GGUF fallback 을 제거했다"
            )
