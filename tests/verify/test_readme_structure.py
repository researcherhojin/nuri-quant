"""README 가 standard-readme 규격 구조를 유지한다.

규격: https://github.com/RichardLitt/standard-readme/blob/main/spec.md

순서는 취향이 아니라 계약이다 — 처음 온 사람이 Install 다음에 Usage 를, 맨 끝에서
License 를 찾는다는 전제로 씌어 있다. 이 레포의 README 는 한때 Usage(`Common
Commands`)가 14개 중 10번째에 있어 Install 과 7개 섹션 떨어져 있었고, 253줄인데
목차가 없었으며, 필수인 Contributing 이 다른 섹션 안 링크 한 줄로만 존재했다.

ToC 는 특히 조용히 썩는다 — 섹션을 하나 추가하고 목차를 잊어도 렌더링은 멀쩡하다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

# spec 이 요구하는 상대 순서. 사이에 커스텀(Extra) 섹션이 끼는 건 허용되므로
# 동등성이 아니라 **부분순서**로 검사한다.
REQUIRED_ORDER = [
    "Table of Contents",
    "Background",
    "Install",
    "Usage",
    "Maintainers",
    "Acknowledgements",
    "Contributing",
    "License",
]

# spec 이 필수로 못박은 섹션 (문서 저장소가 아니므로 Install/Usage 도 필수)
REQUIRED_SECTIONS = {"Table of Contents", "Install", "Usage", "Contributing", "License"}


def _headings() -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", README.read_text(), re.M)]


def _github_anchor(heading: str) -> str:
    a = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"\s+", "-", a.strip())


def _toc_links() -> list[tuple[str, str]]:
    body = README.read_text()
    start = body.index("## Table of Contents")
    end = body.index("\n## ", start + 1)
    return re.findall(r"^- \[([^\]]+)\]\(#([^)]+)\)$", body[start:end], re.M)


class TestRequiredSections:
    def test_all_required_sections_present(self):
        missing = REQUIRED_SECTIONS - set(_headings())
        assert not missing, f"standard-readme 필수 섹션 누락: {sorted(missing)}"

    def test_license_is_last(self):
        """spec: License must be last section."""
        assert _headings()[-1] == "License", _headings()[-1]

    def test_toc_is_required_because_readme_exceeds_100_lines(self):
        """spec: ToC 는 100줄 넘는 README 에서 필수. 짧아졌다면 이 테스트를 지워도 된다."""
        n = len(README.read_text().splitlines())
        assert n > 100, f"README 가 {n}줄로 줄었다 — ToC 필수 조건 재검토"
        assert "## Table of Contents" in README.read_text()


class TestSectionOrder:
    def test_spec_sections_appear_in_prescribed_order(self):
        """Extra 섹션이 사이에 끼는 건 허용, 상대 순서가 뒤집히면 FAIL.

        Gotcha-Test Pair: Usage 를 Install 앞으로 옮기거나 License 를 위로 올리면 FAIL.
        """
        present = [h for h in _headings() if h in REQUIRED_ORDER]
        expected = [h for h in REQUIRED_ORDER if h in present]
        assert present == expected, f"섹션 순서가 규격과 다름:\n  실제   {present}\n  기대   {expected}"

    def test_usage_directly_follows_install_ignoring_nothing_between(self):
        """spec 순서상 Install → Usage 사이에는 다른 spec 섹션이 없어야 한다.

        과거 이 둘 사이에 7개 섹션이 있었다 — 설치한 사람이 다음에 뭘 치는지 찾으려면
        Tech Stack 과 Project Stats 를 지나쳐야 했다.
        """
        heads = _headings()
        gap = heads[heads.index("Install") + 1 : heads.index("Usage")]
        assert not gap, f"Install 과 Usage 사이에 {gap}"


class TestTableOfContents:
    def test_every_toc_link_resolves_to_a_heading(self):
        anchors = {_github_anchor(h) for h in _headings()}
        broken = [(t, a) for t, a in _toc_links() if a not in anchors]
        assert not broken, f"가리키는 헤딩이 없는 ToC 링크: {broken}"

    def test_every_section_is_listed_in_the_toc(self):
        """섹션을 추가하고 목차를 잊는 게 가장 흔한 부패 경로 — 렌더링은 멀쩡하다.

        Gotcha-Test Pair: `## ` 섹션을 추가하고 ToC 에 안 넣으면 FAIL.
        """
        listed = {a for _, a in _toc_links()}
        missing = [h for h in _headings() if h != "Table of Contents" and _github_anchor(h) not in listed]
        assert not missing, f"ToC 에 없는 섹션: {missing}"

    def test_toc_order_matches_document_order(self):
        """목차 순서가 본문 순서와 다르면 목차가 지도 역할을 못 한다."""
        listed = [a for _, a in _toc_links()]
        doc = [_github_anchor(h) for h in _headings() if h != "Table of Contents"]
        assert listed == doc, f"ToC 순서 불일치:\n  ToC  {listed}\n  본문 {doc}"


class TestShortDescription:
    def test_short_description_is_under_120_chars(self):
        """spec: short description 은 120자 미만, 자기 줄에."""
        body = README.read_text()
        m = re.search(r"^\*\*(.+?)\*\*$", body, re.M)
        assert m, "굵은 한 줄 요약을 찾지 못함"
        assert len(m.group(1)) < 120, f"{len(m.group(1))}자: {m.group(1)}"


# ── Mermaid 다이어그램 (#1288) ──────────────────────────────────────────────

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def _diagrams() -> list[str]:
    return MERMAID.findall(README.read_text(encoding="utf-8"))


class TestMermaidRendersInBothThemes:
    """GitHub 는 **읽는 사람의 테마**로 렌더한다 — 밝은 팔레트를 박으면 다크에서 깨진다.

    2026-08-29 실측(mermaid 11.17, `mmdc -t dark`): 다이어그램 안의
    `%%{init: {"theme":"base", ...}}%%` 는 **호스트 테마를 이긴다.** 밝은 fill 을 박은
    다이어그램은 다크 모드에서도 밝게 렌더돼 `#0d1117` 배경 위의 흰 판때기가 된다.

    그래서 이 레포의 규약은 **stroke 전용 classDef** 다: fill 을 지정하지 않으면
    mermaid 가 테마에 맞는 배경을 고르고, 글자색도 따라온다.
    """

    def test_no_diagram_pins_a_theme(self):
        """Mutation lock: 어떤 다이어그램에든 `%%{init:` 테마 블록을 넣으면 FAIL."""
        offenders = [i for i, d in enumerate(_diagrams(), 1) if "%%{init:" in d]
        assert not offenders, f"다이어그램 {offenders} 가 테마를 고정한다 — 다크 모드에서 밝은 판때기가 된다"

    def test_classdefs_never_hardcode_a_fill(self):
        """`fill:` 을 박으면 글자색까지 같이 박아야 하고, 그러면 테마를 따라가지 못한다.

        `fill:none` 은 예외 — 배경을 지우는 것이지 색을 고르는 게 아니다.
        """
        bad: list[str] = []
        for i, d in enumerate(_diagrams(), 1):
            for line in d.splitlines():
                if "classDef" not in line:
                    continue
                m = re.search(r"fill:\s*([^,\s]+)", line)
                if m and m.group(1) != "none":
                    bad.append(f"#{i}: {line.strip()}")
        assert not bad, "테마를 따라가지 못하는 fill 이 있다:\n" + "\n".join(bad)

    def test_subgraph_titles_stay_short(self):
        """긴 subgraph 제목은 클러스터 폭을 그만큼 벌려 다이어그램 전체를 축소시킨다.

        README 컬럼 폭(약 830-900px)을 넘기면 mermaid 가 통째로 축소해 글자가 6-7px 가
        된다 — 본문이 16px 인데. 문장은 캡션으로 내린다.
        """
        long_titles = []
        for i, d in enumerate(_diagrams(), 1):
            for m in re.finditer(r'subgraph\s+\w+\["([^"]+)"\]', d):
                if len(m.group(1)) > 60:
                    long_titles.append(f"#{i}: {m.group(1)[:70]}... ({len(m.group(1))}자)")
        assert not long_titles, "subgraph 제목이 너무 길다:\n" + "\n".join(long_titles)

    def test_the_sweep_has_eyes(self):
        """카나리아 — 다이어그램을 하나도 못 찾으면 위 셋은 영원히 공허하게 통과한다."""
        assert len(_diagrams()) >= 3, "README 에서 mermaid 블록을 찾지 못했다"
        assert MERMAID.findall("```mermaid\nflowchart LR\n  A --> B\n```"), "정규식이 눈이 멀었다"
