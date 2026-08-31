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

import re
from pathlib import Path

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
