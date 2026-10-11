"""`docs/*.md` 의 영어 공식판과 `docs/ko/*.md` 한국어판이 같은 문서인지 구조로 잠근다 (#1771).

번역은 한쪽만 고치는 순간 조용히 갈라진다 — 렌더링은 양쪽 다 멀쩡하다. 내용 대조는 사람·Codex
몫이고, 여기서는 **갈라지면 반드시 같이 움직이는 것**만 본다: 헤딩(수·레벨·절 번호), 코드 블록
(수·언어·줄 수), 표(표마다 행 수·열 수), 링크 목적지(앵커는 가리키는 헤딩으로 풀어서), 그리고 두
판을 잇는 에디션 줄.

마크다운은 정규식이 아니라 markdown-it(CommonMark + GFM 표)로 읽는다. 줄 단위 정규식은 들여쓴
헤딩·`~~~` 펜스·앞 파이프 없는 표 행·제목 붙은 링크를 놓쳤다 (Codex 리뷰). markdown-it-py 는
rich ← yfinance · edgartools 를 거쳐 설치되는 전이 의존성이라, 빠지면 import 에서 시끄럽게 실패한다.

수치 문구는 여기 소관이 아니다 — `verify_doc_counts.sh` 가 ko 사이트를 따로 검사한다.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

import pytest
from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
KO = DOCS / "ko"

# 한국어 전용으로 남기는 문서 — 역사 기록이라 번역하지 않는다 (#1771).
KOREAN_ONLY = {"UX_REDESIGN_PLAN.md"}

MD = MarkdownIt("commonmark").enable("table")


@lru_cache(maxsize=64)
def _parse(text: str) -> tuple:
    """같은 문서를 테스트마다 다시 파싱하지 않는다 (토큰은 읽기만 한다)."""
    return tuple(MD.parse(text))


SECTION_NO = re.compile(r"^(§?\d+(?:\.\d+)*\.?)\s")
EXTERNAL = ("http://", "https://", "mailto:")


def _pairs() -> list[str]:
    return sorted(p.name for p in DOCS.glob("*.md") if p.name not in KOREAN_ONLY)


def _plain(inline) -> str:
    """헤딩 inline 토큰의 렌더된 글자 — 백틱·링크 문법은 빠지고 글자만 남는다."""
    return "".join(c.content for c in (inline.children or []) if c.type in ("text", "code_inline"))


def _headings(text: str) -> list[tuple[int, str]]:
    tokens = _parse(text)
    return [(int(t.tag[1]), _plain(tokens[i + 1])) for i, t in enumerate(tokens) if t.type == "heading_open"]


def _slug(text: str) -> str:
    """GitHub 앵커 — 소문자, 글자·숫자·`_`·`-`·공백만 남기고 공백 하나당 `-` 하나."""
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def _anchor_index(text: str) -> dict[str, int]:
    """앵커 → 몇 번째 헤딩인가. 같은 slug 가 반복되면 GitHub 처럼 `-1`, `-2` 를 붙인다."""
    seen: Counter[str] = Counter()
    index = {}
    for i, (_, title) in enumerate(_headings(text)):
        base = _slug(title)
        slug = base if not seen[base] else f"{base}-{seen[base]}"
        seen[base] += 1
        index[slug] = i
    return index


def _structure(text: str) -> dict[str, list]:
    tokens = _parse(text)
    fences = [
        (t.info.strip() if t.type == "fence" else "<indented>", t.content.count("\n"))
        for t in tokens
        if t.type in ("fence", "code_block")
    ]
    tables, rows = [], None
    for t in tokens:
        if t.type == "table_open":
            rows = []
        elif t.type == "tr_open" and rows is not None:
            rows.append(0)
        elif t.type in ("th_open", "td_open") and rows:
            rows[-1] += 1
        elif t.type == "table_close":
            tables.append(tuple(rows or ()))
            rows = None
    headings = [(level, (m.group(1) if (m := SECTION_NO.match(title)) else None)) for level, title in _headings(text)]
    return {"headings": headings, "fences": fences, "tables": tables}


def _links(path: Path) -> list[str]:
    """문서의 모든 링크·이미지 목적지 (인라인·참조·제목 붙은 링크 전부).

    markdown-it 는 href 의 비 ASCII 를 퍼센트 인코딩한다 — 한국어 앵커를 헤딩 slug 와 대조하려면 푼다.
    """
    out = []
    for t in _parse(path.read_text(encoding="utf-8")):
        for c in t.children or []:
            if c.type == "link_open":
                out.append(unquote(str(c.attrs.get("href", ""))))
            elif c.type == "image":
                out.append(unquote(str(c.attrs.get("src", ""))))
    return out


def _destination(path: Path, raw: str) -> str:
    """링크 목적지를 판과 무관한 이름으로 푼다: (레포 경로, 몇 번째 헤딩).

    한국어판 형제 문서는 영어판 경로로 접는다 — 같은 문서를 가리키면 같다. 앵커는 철자가 아니라
    가리키는 헤딩의 순번으로 비교한다 — 헤딩을 번역하면 철자는 달라지지만 순번은 같아야 한다.
    """
    if raw.startswith(EXTERNAL):
        return raw
    rel, _, frag = raw.partition("#")
    dest = (path.parent / rel).resolve() if rel else path
    name = dest.relative_to(REPO_ROOT).as_posix().replace("docs/ko/", "docs/")
    if not frag:
        return name
    heading = _anchor_index(dest.read_text(encoding="utf-8")).get(frag) if dest.is_file() else None
    return f"{name}#<heading {heading}>"


@pytest.mark.parametrize("name", _pairs())
class TestEditionPair:
    def test_both_editions_exist(self, name):
        assert (KO / name).is_file(), f"docs/ko/{name} 가 없다 — 한국어판을 쓰거나 KOREAN_ONLY 에 이유와 함께 등재"

    def test_edition_lines_point_at_each_other(self, name):
        en = (DOCS / name).read_text(encoding="utf-8").splitlines()
        ko = (KO / name).read_text(encoding="utf-8").splitlines()
        assert en[0].startswith("# ") and en[1] == "", en[:2]
        assert en[2] == f"*Korean edition: [ko/{name}](ko/{name})*", en[2]
        assert ko[0].startswith("# ") and ko[1] == "", ko[:2]
        assert ko[2] == f"*English (official) edition: [../{name}](../{name})*", ko[2]

    @pytest.mark.parametrize("part", ["headings", "fences", "tables"])
    def test_same_structure(self, name, part):
        en, ko = (_structure((d / name).read_text(encoding="utf-8"))[part] for d in (DOCS, KO))
        assert en == ko, f"{part} 가 다르다:\n  en {en}\n  ko {ko}"

    def test_same_link_destinations(self, name):
        en = Counter(_destination(DOCS / name, raw) for raw in _links(DOCS / name))
        ko = Counter(_destination(KO / name, raw) for raw in _links(KO / name))
        assert en == ko, f"en 에만: {sorted((en - ko).elements())}\nko 에만: {sorted((ko - en).elements())}"

    def test_every_relative_link_resolves(self, name):
        """파일과 앵커 둘 다 — 헤딩을 번역하면 같은 문서 안 `#앵커` 가 조용히 깨진다."""
        broken = []
        for path in (DOCS / name, KO / name):
            for raw in _links(path):
                if raw.startswith(EXTERNAL):
                    continue
                rel, _, frag = raw.partition("#")
                dest = path.parent / rel if rel else path
                if not dest.exists():
                    broken.append(f"{path.relative_to(REPO_ROOT)} → {raw}")
                elif frag and dest.suffix == ".md" and frag not in _anchor_index(dest.read_text(encoding="utf-8")):
                    broken.append(f"{path.relative_to(REPO_ROOT)} → {raw} (앵커 없음)")
        assert not broken, "\n".join(broken)


class TestTheSweepHasEyes:
    """카나리아 — 파서가 조용히 아무것도 못 읽으면 위 대조가 공허하게 통과한다 (Codex 변이 사례 포함)."""

    def test_the_pair_list_is_not_empty(self):
        assert len(_pairs()) >= 7, _pairs()

    def test_no_stray_korean_edition(self):
        stray = sorted(p.name for p in KO.glob("*.md") if not (DOCS / p.name).is_file())
        assert not stray, f"영어판이 없는 한국어판: {stray}"

    def test_parsers_read_a_known_document(self):
        s = _structure((DOCS / "STRATEGY.md").read_text(encoding="utf-8"))
        assert len(s["headings"]) >= 50 and any(n and n.startswith("3.11") for _, n in s["headings"])
        assert sum(len(t) for t in s["tables"]) >= 100

    def test_indented_headings_and_tilde_fences_count(self):
        s = _structure("# T\n\n  ## 들여쓴 절\n\n~~~python\nx = 1\n~~~\n")
        assert s["headings"] == [(1, None), (2, None)]
        assert s["fences"] == [("python", 1)]

    def test_tables_keep_their_boundaries_and_pipeless_rows(self):
        one = _structure("| a | b |\n|---|---|\n| 1 | 2 |\n3 | 4\n")["tables"]
        two = _structure("| a | b |\n|---|---|\n| 1 | 2 |\n\n| a | b |\n|---|---|\n")["tables"]
        assert one == [(2, 2, 2)], one
        assert two == [(2, 2), (2,)], two

    def test_titled_and_reference_links_are_read(self):
        text = '[a](#x "title") [b][r]\n\n[r]: ../README.md\n'
        hrefs = [str(c.attrs["href"]) for t in MD.parse(text) for c in (t.children or []) if c.type == "link_open"]
        assert hrefs == ["#x", "../README.md"], hrefs
        assert _destination(DOCS / "STRATEGY.md", "../README.md") == "README.md"

    def test_anchors_follow_github_including_duplicates(self):
        assert _slug("Regime Classifier (6 base + 4 special)") == "regime-classifier-6-base--4-special"
        assert _slug("레짐 분류기 (기본 6 + 특수 4)") == "레짐-분류기-기본-6--특수-4"
        assert _anchor_index("# A\n## Endpoint\n## Endpoint\n") == {"a": 0, "endpoint": 1, "endpoint-1": 2}

    def test_an_anchor_resolves_to_its_heading_not_just_any_heading(self):
        doc = DOCS / "ARCHITECTURE.md"
        index = _anchor_index(doc.read_text(encoding="utf-8"))
        assert _destination(doc, "#daily-schedule") != _destination(doc, "#scoring-model")
        assert _destination(doc, "#daily-schedule") == f"docs/ARCHITECTURE.md#<heading {index['daily-schedule']}>"
