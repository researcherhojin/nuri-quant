"""Dependabot auto-merge 정책이 **실제로 설정된 생태계 전부**를 덮는지 잠근다.

`.github/workflows/dependabot-auto-merge.yml` 의 허용 목록에 들어가는 문자열은
`.github/dependabot.yml` 의 `package-ecosystem` 값이 **아니라** dependabot 내부 이름이다.
`dependabot/fetch-metadata` 가 그 내부 이름을 그대로 출력하기 때문이다:

| dependabot.yml    | fetch-metadata 출력 |
|-------------------|---------------------|
| `pip`             | `pip`               |
| `npm`             | `npm_and_yarn`      |
| `github-actions`  | `github_actions`    |

허용 목록에는 워크플로 도입(#328) 이래 `"npm"` 만 있었다. 그래서 **모든 npm PR 이
`unsupported ecosystem: npm_and_yarn` 으로 빠져 auto-merge 가 한 번도 켜진 적이 없다.**
실측 근거는 2026-08-17 의 5개 PR(#1055~#1059) 잡 로그 — 다섯 개 전부 `Skip notice` 로
끝났고, 같은 기간 `github_actions` 그룹 PR(#881)만 `app/github-actions` 가 머지했다.

이 결함이 조용했던 이유는 **잡이 성공으로 끝나기 때문**이다. 정책이 "머지 안 함"으로
판정하면 워크플로는 안내 문구만 찍고 exit 0 한다 — 체크는 green 이고 auto-merge 만 없다.
`.claude/rules/enforcement.md` 가 말하는 *green dead gate* 의 세 번째 사례다.

비용은 조용함에서 그치지 않는다: `.github/dependabot.yml` 의 `open-pull-requests-limit: 5`
때문에 머지되지 않은 PR 이 5개까지 쌓이면 dependabot 이 **새 PR 을 아예 열지 않는다** —
프론트엔드 보안 업데이트가 그 시점부터 막힌다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
AUTOMERGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"

# dependabot.yml 의 `package-ecosystem` → fetch-metadata 가 내보내는 내부 이름.
# 새 생태계를 dependabot.yml 에 추가하면 여기에도 등재해야 한다 (미등재 시 아래
# `test_every_configured_ecosystem_is_mapped` 가 FAIL — 조용히 통과하지 않는다).
METADATA_NAME = {
    # dependabot-core `uv/lib/dependabot/uv/package_manager.rb` 의
    # `ECOSYSTEM = "uv"` / `NAME = "uv"`. 같은 경로로 npm_and_yarn 을 보면
    # `ECOSYSTEM = "npm_and_yarn"` 이라 아래 npm 매핑과 일치한다 — 이 소스가
    # fetch-metadata 출력의 정본이 맞다는 교차확인 (#1349).
    "uv": "uv",
    "pip": "pip",
    "npm": "npm_and_yarn",
    "github-actions": "github_actions",
}


def _configured_ecosystems() -> set[str]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text())
    return {entry["package-ecosystem"] for entry in config["updates"]}


def _allowlisted_ecosystems() -> set[str]:
    """워크플로의 `supportedEcosystems` 집합 리터럴을 읽는다.

    YAML 로 파싱해도 정책 본문은 `script:` 아래의 통짜 JS 문자열이라 어차피 텍스트에서
    꺼내야 한다. 집합이 비어 파싱되면 호출부 단언이 전부 FAIL 하므로 공허하게 통과하지
    않는다.
    """
    source = AUTOMERGE_WORKFLOW.read_text()
    match = re.search(r"supportedEcosystems\s*=\s*new Set\(\[(.*?)\]\)", source, re.DOTALL)
    assert match, "`supportedEcosystems = new Set([...])` 리터럴을 못 찾았다 — 정책이 옮겨졌나?"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


class TestAutoMergeCoversEveryConfiguredEcosystem:
    def test_every_configured_ecosystem_is_mapped(self):
        """카나리아 — 새 생태계를 추가하고 매핑을 빠뜨리면 아래 테스트가 그걸 못 본다."""
        unmapped = _configured_ecosystems() - set(METADATA_NAME)
        assert not unmapped, (
            f"dependabot.yml 에 있는데 METADATA_NAME 에 없는 생태계: {sorted(unmapped)}\n"
            "fetch-metadata 가 그 생태계를 뭐라고 내보내는지 확인하고 등재할 것."
        )

    def test_allowlist_contains_the_metadata_name_of_each_ecosystem(self):
        """Gotcha-Test Pair: `npm_and_yarn` 을 빼면 FAIL.

        `"npm"` 만 남기는 것이 정확히 #328~#1059 동안의 상태였고, 그 상태에서 npm
        auto-merge 는 영영 켜지지 않는다.
        """
        allowlisted = _allowlisted_ecosystems()
        missing = {
            ecosystem: METADATA_NAME[ecosystem]
            for ecosystem in _configured_ecosystems()
            if METADATA_NAME[ecosystem] not in allowlisted
        }
        assert not missing, (
            "auto-merge 허용 목록에 빠진 생태계: "
            + ", ".join(f"{k} → {v!r}" for k, v in sorted(missing.items()))
            + f"\n현재 허용 목록: {sorted(allowlisted)}\n"
            "빠지면 해당 생태계 PR 은 `unsupported ecosystem` 으로 조용히 스킵된다 "
            "(잡은 성공하므로 체크는 green)."
        )

    def test_the_config_actually_declares_ecosystems(self):
        """카나리아 — dependabot.yml 파싱이 빈 집합을 내면 위 두 테스트가 공허해진다."""
        configured = _configured_ecosystems()
        assert len(configured) >= 3, f"dependabot.yml 에서 읽어낸 생태계가 {configured} 뿐이다"


def _policy_script() -> str:
    """`Evaluate merge policy` 스텝의 JS 본문을 YAML 에서 꺼낸다."""
    workflow = yaml.safe_load(AUTOMERGE_WORKFLOW.read_text())
    steps = workflow["jobs"]["enable-auto-merge"]["steps"]
    policy = [step for step in steps if step.get("id") == "policy"]
    assert policy, "`id: policy` 스텝을 못 찾았다 — 정책이 옮겨졌나?"
    return policy[0]["with"]["script"]


def run_policy(
    *,
    lock_verdict: str = "clean",
    ecosystem: str = "uv",
    update_type: str = "version-update:semver-patch",
    group: str = "",
    names: str = "somepkg",
) -> dict[str, str]:
    """정책 스텝을 **node 로 실제 실행**하고 출력을 돌려준다.

    텍스트를 긁지 않는 이유: 긁는 방식은 if/else 체인의 **모양**만 보므로 체인
    뒤에 후처리 가드 한 줄을 붙여 정책을 통째로 되돌려도 통과한다 (2026-09-28
    교차리뷰가 실제로 그 mutation 으로 구조 테스트 7개를 전부 초록으로 만들었다).
    실행하면 그 형태와 무관하게 최종 판정을 본다 — `tests/test_hook_guard_execution.py`
    · `tests/test_pre_push_hook.py` 가 훅을 grep 하지 않고 실행하는 것과 같은 이유다.

    node 부재는 skip 이 아니라 **실패**다. 조용히 건너뛴 게이트는 게이트가 아니고,
    이 레포가 반복해서 데인 형태다(green dead gate).
    """
    node = shutil.which("node")
    assert node, "node 를 찾을 수 없다 — 이 테스트는 skip 하지 않는다(dead gate 방지)"

    harness = (
        "const outputs = {};\n"
        "const core = {\n"
        # 실환경 `core` 가 가진 로깅 API 를 명시적으로 스텁한다. 전면 no-op Proxy 로
        # 덮으면 오타나 미지원 API 까지 숨어버린다 — 없는 메서드는 여기서 죽는 게 맞다.
        "  info: () => {}, debug: () => {}, warning: () => {}, notice: () => {}, error: () => {},\n"
        "  setOutput: (k, v) => { outputs[k] = String(v); },\n"
        # setFailed 는 실행을 멈추지 않는다(실환경도 그렇다) — 기록해두고 호출부가 거부한다.
        "  setFailed: (m) => { outputs.__failed = String(m); },\n"
        "};\n" + _policy_script() + "\nconsole.log(JSON.stringify(outputs));\n"
    )
    env = {
        **os.environ,
        "LOCK_VERDICT": lock_verdict,
        "PACKAGE_ECOSYSTEM": ecosystem,
        "UPDATE_TYPE": update_type,
        "DEPENDENCY_GROUP": group,
        "DEPENDENCY_NAMES": names,
    }
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "policy.mjs"
        script.write_text(harness)
        result = subprocess.run([node, str(script)], capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, f"정책 스크립트가 죽었다:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def _merges(**kwargs) -> bool:
    """정책이 이 입력에서 자동머지를 켜는가.

    `setFailed` 를 **거부**한다. 기록만 하고 넘어가면 fail-open 이다: 실환경에서
    policy 스텝이 빨개지면 `if: steps.policy.outputs.should-merge == 'true'` 인
    후속 스텝이 통째로 스킵돼 **자동머지가 안 켜지는데**, 하네스는 출력만 보고
    "머지된다" 고 초록을 준다. 2026-09-28 교차리뷰가 `core.setFailed("boom")` 한 줄로
    12개 전부를 통과시켰다.
    """
    out = run_policy(**kwargs)
    assert "__failed" not in out, f"정책이 core.setFailed 를 호출했다: {out['__failed']}"
    assert "should-merge" in out, f"should-merge 출력이 없다: {out}"
    assert out["should-merge"] in ("true", "false"), f"should-merge 가 불리언 문자열이 아니다: {out}"
    return out["should-merge"] == "true"


class TestMergePolicyBySemver:
    """판정표를 **실행해서** 잠근다 (#1549).

    지금까지 이 파일은 생태계 매핑만 잠갔고 판정 로직 자체는 무방비였다.

    정책의 근거: 진짜 위험축인 **전이 major** 는 `lockVerdict`(#1364)가 따로 잡는다.
    #1355 가 그 사례 — 제목은 "scipy minor" 인데 lock 에서는 numpy 가 major 로 움직였고
    manifest 기반 semver 는 그걸 **볼 수 없다**.

    다만 lock 게이트가 minor 라벨을 **완전히** 대체하지는 않는다. `clean` 의 뜻은
    "내가 보는 경계를 안 넘었다" 이지 "호환된다" 가 아니다 — 같은 major 안의 API 제거,
    yanked wheel, 아티팩트 교체는 그 스크립트도 못 본다(자기 독스트링이 자인한다).
    남는 방어선은 전체 테스트 스위트이고, 외부 SDK 처럼 mock 으로만 검증되는 축에는
    그 방어선이 얇다. 이 공백을 알고 여는 것이다.
    """

    def test_patch_auto_merges(self):
        assert _merges(update_type="version-update:semver-patch") is True

    @pytest.mark.parametrize("ecosystem", ["uv", "pip", "npm_and_yarn", "github_actions"])
    def test_single_minor_auto_merges_in_every_ecosystem(self, ecosystem):
        """`&& isGrouped` 를 어떤 형태로든 되살리면 FAIL — **생태계마다** 확인한다.

        group 패턴이 좁아(ruff*/pytest*/pandas*/numpy*/scipy*/fastapi*/uvicorn*/httpx*)
        대부분의 minor 가 단독으로 도착한다 — 11주 실측으로 grouped 5건 vs 단독 minor
        43건(**npm 29 · uv 14**).

        생태계를 고정하지 않으면 `updateType===minor && ecosystem==="npm_and_yarn"`
        같은 카브아웃이 조용히 통과한다(교차리뷰 M8 실측: 그 카브아웃에도 12개 전부
        통과했다). #1551 이 정확히 그 모양의 생태계별 minor 로직을 넣을 예정이라
        지금 앵커해 둔다. 메타데이터 이름은 **리터럴**로 적는다 — `METADATA_NAME`
        을 거치면 그 dict 가 틀렸을 때 테스트가 틀린 값으로 초록이 된다(M6).
        """
        assert _merges(ecosystem=ecosystem, update_type="version-update:semver-minor", group="", names="somepkg"), (
            f"{ecosystem} 의 단독 minor 가 자동머지되지 않는다"
        )

    @pytest.mark.parametrize("ecosystem", ["uv", "pip", "npm_and_yarn", "github_actions"])
    def test_major_is_blocked_in_every_ecosystem(self, ecosystem):
        """major 차단도 생태계별로 앵커한다 — 한 생태계만 열려도 잡힌다."""
        assert not _merges(ecosystem=ecosystem, update_type="version-update:semver-major")

    def test_the_reason_string_distinguishes_single_from_grouped(self):
        """`reason` 은 잡 로그에서 **왜 머지됐는지**를 읽는 유일한 단서다.

        교차리뷰 M5 실측: 삼항식을 `reason = "WRONG"` 으로 갈아치워도 아무 테스트가
        안 울었다 — 이 PR 이 바꾼 줄의 절반이 무잠금이었다.
        """
        single = run_policy(update_type="version-update:semver-minor", group="", names="onepkg")
        assert single["reason"] == "minor update", single

        grouped = run_policy(update_type="version-update:semver-minor", group="python-dev")
        assert "python-dev" in grouped["reason"], grouped

        multi = run_policy(update_type="version-update:semver-minor", group="", names="a,b,c")
        assert "3 dependencies" in multi["reason"], multi

        assert run_policy(update_type="version-update:semver-patch")["reason"] == "patch update"

    def test_grouped_minor_still_auto_merges(self):
        assert _merges(update_type="version-update:semver-minor", group="python-dev")

    def test_major_still_requires_a_human(self):
        assert _merges(update_type="version-update:semver-major") is False

    def test_a_dirty_lock_verdict_blocks_even_a_patch(self):
        """lock 게이트가 semver 판정을 이긴다 (#1364) — 이게 minor 를 열 수 있는 근거다."""
        assert _merges(lock_verdict="blocked", update_type="version-update:semver-patch") is False

    def test_a_missing_lock_verdict_blocks(self):
        """게이트 스텝이 죽거나 스킵돼 output 이 비면 **차단**이다 (#910/#953 계열)."""
        assert _merges(lock_verdict="", update_type="version-update:semver-patch") is False

    def test_an_unsupported_ecosystem_blocks(self):
        assert _merges(ecosystem="cargo", update_type="version-update:semver-patch") is False

    def test_an_unknown_update_type_blocks(self):
        assert _merges(update_type="") is False

    def test_every_configured_ecosystem_actually_merges_a_patch(self):
        """허용 목록이 문자열로는 맞는데 판정에서 빠지는 일이 없도록 **실행**으로 확인."""
        for ecosystem in sorted(_configured_ecosystems()):
            metadata_name = METADATA_NAME[ecosystem]
            assert _merges(ecosystem=metadata_name, update_type="version-update:semver-patch"), (
                f"{ecosystem} ({metadata_name}) 의 patch 가 자동머지되지 않는다"
            )
