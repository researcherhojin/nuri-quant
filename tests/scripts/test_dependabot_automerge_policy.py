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


def _policy_source() -> str:
    """정책 분기(`shouldMerge` 결정부)의 JS 본문 — **주석을 걷어낸 것**.

    주석을 남기면 테스트가 코드가 아니라 **산문에서 값을 읽는다.** 가설이 아니라
    실제로 일어났다: 이 워크플로의 주석에 "shouldMerge=false 면 재부착을 안 하므로"
    라는 문장이 있어서 minor 분기 조각에 `false` 가 하나 더 잡혔다. `hits[-1]` 이
    코드 쪽 대입을 집어 **우연히** 통과했을 뿐, 주석을 대입문 뒤에 썼다면 판정이
    뒤집혔다. 같은 이유로 주석 안의 `} else` 는 분기 절단도 망가뜨린다.

    라인 단위 `//` 제거가 안전한 근거: 이 본문에는 `://` 가 없다 — 문자열 리터럴
    안의 `//` 를 자를 위험이 없다. URL 이 들어오면 이 전제가 깨지므로
    `test_the_policy_body_has_no_url_that_line_stripping_would_break` 가 잠근다.
    """
    source = AUTOMERGE_WORKFLOW.read_text()
    start = source.index("let shouldMerge = false;")
    end = source.index('core.setOutput("should-merge"', start)
    body = source[start:end]
    return "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())


def _verdict_for(branch_marker: str) -> bool:
    """해당 분기가 `shouldMerge` 를 무엇으로 두는지 읽는다.

    분기 본문을 **다음 `} else` 까지**로 잘라 그 안의 마지막 `shouldMerge = X` 를 본다.
    주석은 `_policy_source()` 가 이미 걷어냈다.
    """
    body = _policy_source()
    i = body.index(branch_marker)
    tail = body[i + len(branch_marker) :]
    nxt = tail.find("} else")
    tail = tail[: nxt if nxt != -1 else len(tail)]
    hits = re.findall(r"shouldMerge\s*=\s*(true|false)", tail)
    assert hits, f"{branch_marker!r} 분기에서 shouldMerge 대입을 못 찾았다:\n{tail}"
    assert len(hits) == 1, (
        f"{branch_marker!r} 분기에 shouldMerge 대입이 {len(hits)}개다 — 어느 것이 "
        f"최종인지 위치로 추정하게 된다. 분기당 하나로 유지할 것:\n{tail}"
    )
    return hits[0] == "true"


class TestMergePolicyBySemver:
    """판정표를 잠근다 (#1549).

    지금까지 이 파일은 **생태계 매핑만** 잠갔고 판정 로직 자체는 무방비였다. 그래서
    `&& isGrouped` 같은 조건이 붙거나 빠져도 아무 테스트가 안 울었다.

    정책의 근거: 진짜 위험축인 **전이 major** 는 `lockVerdict`(#1364)가 따로 잡는다.
    #1355 가 그 사례 — 제목은 "scipy minor" 인데 lock 에서는 numpy 가 major 로 움직였고
    manifest 기반 semver 는 그걸 **볼 수 없다**. 그 게이트가 살아 있는 한 minor 라벨
    자체는 게이트로서 값이 없고, 실제로도 그랬다: 2026-07-13~09-28 머지된 100건 중
    단독 minor 43건이 전부 사람 손을 거쳤지만 사람이 더 본 것은 초록불뿐이다.
    """

    def test_patch_auto_merges(self):
        assert _verdict_for('updateType === "version-update:semver-patch"') is True

    def test_minor_auto_merges_even_when_not_grouped(self):
        """`&& isGrouped` 를 되살리면 FAIL.

        group 패턴이 좁아(ruff*/pytest*/pandas*/numpy*/scipy*/fastapi*/uvicorn*/httpx*)
        대부분의 minor 가 단독으로 도착한다 — 11주 실측으로 grouped 5건 vs 단독 minor
        43건. `isGrouped` 를 요구하면 그 43건이 **영영 자동머지되지 않는다.**

        더 나쁜 2차 효과: dependabot 의 force-push 는 GitHub auto-merge 를 끄는데,
        워크플로는 `synchronize` 에 다시 돌아도 shouldMerge=false 면 재부착을 안 한다.
        사람이 손으로 켜도 rebase 한 번에 풀린다.
        """
        body = _policy_source()
        minor = 'updateType === "version-update:semver-minor"'
        assert minor in body, "minor 분기가 사라졌다"
        assert f"{minor} && isGrouped" not in body, (
            "minor 분기에 `&& isGrouped` 가 다시 붙었다 — 단독 minor 가 영영 "
            "자동머지되지 않는 수동 큐로 돌아간다 (실측 43건/11주)."
        )
        assert _verdict_for(minor) is True

    def test_major_still_requires_a_human(self):
        """major 는 자동머지하지 않는다 — 여기를 열면 FAIL."""
        assert _verdict_for('updateType === "version-update:semver-major"') is False

    def test_a_dirty_lock_verdict_blocks_regardless_of_semver(self):
        """lock 게이트가 semver 판정보다 **먼저** 그리고 무조건 막는다 (#1364).

        이게 minor 를 열 수 있는 근거다. 이 분기가 사라지거나 뒤로 밀리면 #1355
        (minor 제목 아래 numpy major 무인 머지)가 그대로 재발한다.
        """
        body = _policy_source()
        assert 'lockVerdict !== "clean"' in body, "lock verdict 분기가 사라졌다"
        assert body.index('lockVerdict !== "clean"') < body.index('updateType === "version-update:semver-patch"'), (
            "lock 게이트가 semver 판정보다 뒤로 밀렸다 — #1355 가 재발한다"
        )
        assert _verdict_for('lockVerdict !== "clean"') is False

    def test_the_policy_body_has_no_url_that_line_stripping_would_break(self):
        """`_policy_source()` 의 라인 단위 `//` 제거가 안전하다는 **전제**를 잠근다.

        전제가 깨지면 파서가 문자열 리터럴을 잘라 먹고, 그 결과는 예외가 아니라
        **조용한 오판**이다 — 이 파일의 모든 판정이 의미를 잃는다.
        """
        raw_start = AUTOMERGE_WORKFLOW.read_text()
        start = raw_start.index("let shouldMerge = false;")
        end = raw_start.index('core.setOutput("should-merge"', start)
        raw_body = raw_start[start:end]

        offenders = [ln.strip() for ln in raw_body.splitlines() if "://" in ln]
        assert not offenders, (
            "정책 본문에 `://` 가 들어왔다 — 라인 단위 `//` 제거가 문자열을 훼손한다.\n"
            f"{offenders}\n"
            "URL 이 필요하면 `_policy_source()` 를 제대로 된 토크나이저로 바꿀 것."
        )

    def test_the_parser_ignores_values_written_in_comments(self):
        """주석 안의 `shouldMerge = ...` 를 판정으로 읽지 않는다.

        회귀 방지: 실제로 이 워크플로 주석에 "shouldMerge=false 면" 이라는 문장이
        있었고, 주석을 안 걷어냈을 때 minor 분기에서 대입이 2개로 잡혔다.
        """
        assert "//" not in _policy_source(), "주석이 안 걷혔다 — 파서가 산문을 코드로 읽는다"

        # 주석에 판정값을 심어도 읽히지 않아야 한다. 걷어내기 전 원문에는 잡히고,
        # `_policy_source()` 를 거친 뒤에는 안 잡혀야 파서가 제 역할을 한 것이다.
        raw = AUTOMERGE_WORKFLOW.read_text()
        start = raw.index("let shouldMerge = false;")
        end = raw.index('core.setOutput("should-merge"', start)
        raw_body = raw[start:end]

        pattern = r"shouldMerge\s*=\s*(?:true|false)"
        in_comments = [
            ln.strip() for ln in raw_body.splitlines() if re.search(pattern, ln) and ln.strip().startswith("//")
        ]
        if in_comments:
            # 실제로 이런 줄이 있다 — 그렇다면 파서가 그걸 지웠는지가 진짜 검사다.
            assert not [
                ln
                for ln in _policy_source().splitlines()
                if re.search(pattern, ln) and not ln.strip().startswith(("shouldMerge", "let"))
            ], f"주석의 판정값이 파서를 통과했다: {in_comments}"
