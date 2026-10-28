"""README 가 짧고, 처음 온 사람이 찾는 순서를 유지한다 (#2020).

#918 에서 standard-readme 규격(ToC · Background · Install · Usage · Maintainers …)을 잠갔다.
그 규격은 지켜졌지만 README 는 214줄로 자라 내부 레퍼런스가 됐다 — 7행 작업 표, 스테이지 표,
수치 표, 뱃지 32개. #2020 에서 상세를 `docs/ARCHITECTURE.md` 로 넘기고, 잠금도 바꿨다:
섹션 이름보다 **길이**와 **읽는 순서**(무엇인가 → 어떻게 돌리나 → 더 읽을 곳 → License)를 지킨다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

# 상대 순서. 사이에 다른 섹션이 끼는 건 허용하므로 동등성이 아니라 부분순서로 검사한다.
REQUIRED_ORDER = ["How it works", "Quick start", "Documentation", "Contributing", "License"]

# 이 줄 수를 넘으면 목차가 필요해진다 — 그 전에 상세를 docs/ 로 옮긴다.
MAX_LINES = 100


def _headings() -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", README.read_text(), re.M)]


class TestRequiredSections:
    def test_all_required_sections_present(self):
        missing = set(REQUIRED_ORDER) - set(_headings())
        assert not missing, f"필수 섹션 누락: {sorted(missing)}"

    def test_license_is_last(self):
        assert _headings()[-1] == "License", _headings()[-1]


class TestSectionOrder:
    def test_sections_appear_in_reading_order(self):
        """다른 섹션이 사이에 끼는 건 허용, 상대 순서가 뒤집히면 FAIL.

        Gotcha-Test Pair: Quick start 를 How it works 앞으로 옮기거나 License 를 위로 올리면 FAIL.
        """
        present = [h for h in _headings() if h in REQUIRED_ORDER]
        expected = [h for h in REQUIRED_ORDER if h in present]
        assert present == expected, f"섹션 순서가 다름:\n  실제   {present}\n  기대   {expected}"


class TestStaysShort:
    def test_readme_fits_without_a_table_of_contents(self):
        """214줄짜리 README 로 돌아가는 경로를 막는다 (#2020).

        넘으면 두 길 중 하나다: 늘어난 내용을 docs/ 로 옮기거나, 목차를 다시 들이고 이 상한을 올린다.
        """
        n = len(README.read_text().splitlines())
        assert n <= MAX_LINES, f"README 가 {n}줄 — 상세는 docs/ARCHITECTURE.md 로"


class TestShortDescription:
    def test_short_description_is_under_120_chars(self):
        """short description 은 120자 미만, 자기 줄에."""
        body = README.read_text()
        m = re.search(r"^\*\*(.+?)\*\*$", body, re.M)
        assert m, "굵은 한 줄 요약을 찾지 못함"
        assert len(m.group(1)) < 120, f"{len(m.group(1))}자: {m.group(1)}"


# ── Mermaid 다이어그램 (#1288) ──────────────────────────────────────────────

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)

# 엣지 문법 — 이 레포 다이어그램이 쓰는 형태만 읽는다: 사슬(`A --> B --> C`), 그룹(`A & B --> C`),
# `-->` · `==>` · `-.->` 와 뒤에 붙는 `|라벨|`(앞 공백 허용). 화살표처럼 보이는데 이 문법에 안 맞는
# 줄(`A -- 글 --> B`, 인라인 노드 정의 등)은 **실패시킨다** — 못 읽은 줄을 건너뛰면 그 줄의 화살표가
# 조용히 검사에서 빠진다 (codex 리뷰: `& CON` 그룹이 통과했고, `--> |라벨|` 은 오탐났다).
# 화살표는 정규식이 아니라 문자열 치환으로 읽는다 — `-->` 를 담은 정규식은 CodeQL 이 HTML 주석
# 필터로 오인해 high 경고(py/bad-tag-filter)를 낸다 (#1774).
_ARROWS = ("-.->", "-->", "==>")
_MARK = "\x00"
_LABEL = re.compile(r"\x00\s*\|[^|]*\|")
_GROUP = r"\w+(?:\s*&\s*\w+)*"
_EDGE_LINE = re.compile(rf"^\s*{_GROUP}(?:\s*\x00\s*{_GROUP})+\s*$")
_LINKISH = re.compile(r"--|==|-\.|\.-|~~~")


def _edges(diagram: str) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for line in diagram.splitlines():
        bare = re.sub(r'"[^"]*"', '""', line)  # 따옴표 라벨 안의 글자는 화살표가 아니다
        if not _LINKISH.search(bare):
            continue
        for arrow in _ARROWS:
            bare = bare.replace(arrow, _MARK)
        bare = _LABEL.sub(_MARK, bare)
        assert _EDGE_LINE.match(bare), f"읽을 수 없는 엣지 줄 — 파서를 넓히기 전엔 통과시키지 않는다: {line.strip()!r}"
        groups = [re.findall(r"\w+", g) for g in bare.split(_MARK)]
        for left, right in zip(groups, groups[1:]):
            edges += [(a, b) for a in left for b in right]
    return edges


# 아키텍처 상세 다이어그램 3개는 #1595 에서 ARCHITECTURE 로 옮겼다. 테마 규칙은 GitHub 이
# 렌더하는 모든 마크다운에 똑같이 적용되므로 두 파일을 같이 본다.
ARCHITECTURE = REPO_ROOT / "docs" / "ARCHITECTURE.md"
DIAGRAM_FILES = (README, ARCHITECTURE)


def _diagrams() -> list[str]:
    return [d for f in DIAGRAM_FILES for d in MERMAID.findall(f.read_text(encoding="utf-8"))]


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

    def test_every_diagram_is_still_there(self):
        """`>= 3` 은 너무 헐거웠다 — 넷 중 하나를 지워도 통과했다 (codex 리뷰 P3).

        각 다이어그램이 답하는 질문을 **이름으로** 고정한다. 개수만 세면 어느 것이
        사라졌는지 알 수 없고, 개수를 맞추려고 아무거나 넣어도 통과한다.
        """
        # README 는 개요 하나만, 상세는 ARCHITECTURE 에 (#1595). System Flow 는 #1770.
        placement = {
            README: ("Your holdings<br/>+ public market data",),  # 무엇을 하는가
            ARCHITECTURE: (
                "30-day outcomes, 21-day provisional: the only learning edge",  # 데이터가 어디로 흐르는가
                "no job calls another",  # 무엇이 그것을 돌리는가
                "premarket_brief<br/>09:00 US/Eastern",  # 하루의 시계
                "Should this position exist?",  # 두 축
            ),
        }
        for path, anchors in placement.items():
            diagrams = MERMAID.findall(path.read_text(encoding="utf-8"))
            for anchor in anchors:
                assert any(anchor in d for d in diagrams), f"{path.name}: 다이어그램이 사라졌거나 바뀌었다: {anchor!r}"
            assert len(diagrams) == len(anchors), f"{path.name}: 다이어그램 수 {len(diagrams)} ≠ {len(anchors)}"

    def test_no_diagram_asserts_a_dependency_the_code_lacks(self):
        """의미 검사 — 구조만 보면 **틀린 화살표**가 통과한다 (codex 리뷰 P3).

        실제로 이 PR 초안이 `consensus ==> certify` 를 그렸는데, 합의 잡은 `certify()`
        를 부르지 않는다 (`record_decisions()` 를 부른다). 그 한 줄이 이 테스트의 이유다.
        """
        text = ARCHITECTURE.read_text(encoding="utf-8")
        assert "JD ==> RD" in text, "합의 → record_decisions 인메모리 인계가 사라졌다"
        assert "JD ==> CERT" not in text, (
            "합의 잡이 certify() 를 부른다고 그렸다 — scheduler.py 는 record_decisions() 를 부른다"
        )

    def test_system_flow_draws_only_the_edges_the_code_has(self):
        """System Flow 의 화살표 세 개는 코드에서 반대로 오해되기 쉬운 것들이다 (#1770).

        - 학습 경로는 하나다: `learning_memory.py` 는 `recommendations.outcome_30d`(21d 폴백)를
          읽는다. `decision_outcomes` 는 가중치에 들어가지 않는다 — 그쪽에서 합의로 화살표를
          그리면 "알파 원장이 학습한다" 는 거짓이 된다.
        - 어떤 합의 에이전트도 `factors` 를 읽지 않는다. factors → consensus 를 그리면 08:10 에
          도는 잡이 07:05 합의에 들어간다는 뜻이 된다.
        - 합의 → 결정 기록은 테이블이 아니라 메모리 인계다 (`record_decisions()`).
        """
        flow = next(d for d in MERMAID.findall(ARCHITECTURE.read_text(encoding="utf-8")) if "REC -.->" in d)
        assert 'REC -.->|"30-day outcomes, 21-day provisional: the only learning edge"| CON' in flow
        assert "CON ==>|in memory| DEC" in flow
        edges = _edges(flow)
        assert ("SRC", "COL") in edges and ("COL", "TAB") in edges, "사슬을 못 읽었다 — 파서가 눈이 멀었다"
        into_consensus = sorted({src for src, dst in edges if dst == "CON"})
        assert into_consensus == ["PF", "REC", "TAB"], f"합의로 들어가는 입력이 코드와 다르다: {into_consensus}"

    def test_the_edge_parser_has_eyes(self):
        """카나리아 — 파서가 사슬·그룹·라벨을 읽고, 못 읽는 줄은 통과시키지 않는다."""
        assert ("FAC", "CON") in _edges("TAB --> FAC --> BUY & CON"), "그룹 끝의 화살표를 놓친다"
        assert _edges('PF --> |"holdings"| CON') == [("PF", "CON")], "라벨 앞 공백에서 눈이 먼다"
        assert _edges("A & B -.->|x| C") == [("A", "C"), ("B", "C")]
        for unreadable in ("A -- text --> B", 'X["inline"] --> CON', "FAC ~~~ CON"):
            with pytest.raises(AssertionError, match="읽을 수 없는 엣지 줄"):
                _edges(unreadable)

    def test_the_sweep_has_eyes(self):
        """카나리아 — 정규식이 조용히 아무것도 안 잡으면 위 검사들이 공허해진다."""
        assert MERMAID.findall("```mermaid\nflowchart LR\n  A --> B\n```"), "정규식이 눈이 멀었다"
        assert not MERMAID.findall("```python\nx = 1\n```"), "mermaid 아닌 블록을 잡는다"
