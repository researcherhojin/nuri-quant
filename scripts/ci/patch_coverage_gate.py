"""PR 의 patch coverage 를 CI 안에서 계산해 `codecov.yml` 의 patch target 을 강제한다 (#1766).

`codecov/patch` 상태를 required 로 걸지 않는 이유 (2026-10-11 실측):

- 커버리지 업로드가 없는 PR(문서만, #1752)에는 상태가 아예 붙지 않는다 — required 면 영원히 대기한다.
- 붙는 PR 도 업로드를 처리한 뒤 비동기로 붙는다 — #1762 · #1765 는 상태가 붙기 전에 auto-merge 됐다.

그래서 Codecov 가 받는 것과 같은 입력(백엔드 `coverage.xml` · 프런트 `lcov.info`)과 PR diff 로 같은
판정을 동기적으로 낸다. 셈도 Codecov 와 같다: 바뀐 줄 가운데 리포트에 있는 줄만 세고,
patch coverage = hit / (hit + miss + partial). 부분 분기(partial)는 hit 이 아니다.

PR 의 백엔드 커버리지는 fast 샤드뿐이다(slow 는 push 에서만 돈다) — Codecov 의 PR patch 도 같은 입력을 본다.
"""

from __future__ import annotations

import argparse
import fnmatch
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

HIT, MISS, PARTIAL = "hit", "miss", "partial"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def load_policy(config: Path) -> tuple[float, float, list[str]]:
    """codecov.yml → (patch target %, threshold %, ignore globs). 숫자가 아닌 target(`auto`)은 거부한다."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    patch = ((cfg.get("coverage") or {}).get("status") or {}).get("patch") or {}
    default = patch.get("default") or {}

    def percent(value: object, key: str) -> float:
        text = str(value).strip().rstrip("%")
        try:
            return float(text)
        except ValueError:
            raise SystemExit(f"::error::codecov.yml patch {key} must be a percentage, got {value!r}") from None

    return (
        percent(default.get("target", "100%"), "target"),
        percent(default.get("threshold", "0%"), "threshold"),
        [str(glob) for glob in cfg.get("ignore") or []],
    )


def load_cobertura(path: Path) -> dict[str, dict[int, str]]:
    """coverage.py 의 Cobertura XML → {레포 경로: {줄: 상태}}.

    `relative_files = true` 여도 `filename` 은 `<source>`(`--cov=nuri` 면 `nuri`) 기준이다 —
    `scheduler.py` 는 `nuri/scheduler.py` 다. Codecov 처럼 source 와 이어 붙이고, 여럿이면 실제로
    있는 파일을 고른다.
    """
    root = ET.parse(path).getroot()
    sources = [Path(s.text.strip()) for s in root.iter("source") if s.text and s.text.strip()]

    def repo_path(filename: str) -> str:
        candidates = [source / filename for source in sources] or [Path(filename)]
        chosen = next((c for c in candidates if c.is_file()), candidates[0])
        return Path(os.path.relpath(chosen)).as_posix() if chosen.is_absolute() else chosen.as_posix()

    report: dict[str, dict[int, str]] = {}
    for cls in root.iter("class"):
        lines = report.setdefault(repo_path(cls.get("filename", "")), {})
        for line in cls.iter("line"):
            number, hits = int(line.get("number", "0")), int(line.get("hits", "0"))
            if hits == 0:
                lines[number] = MISS
            elif line.get("branch") == "true" and not line.get("condition-coverage", "").startswith("100%"):
                lines[number] = PARTIAL
            else:
                lines[number] = HIT
    return report


def load_lcov(path: Path) -> dict[str, dict[int, str]]:
    """vitest(v8) lcov → {파일: {줄: 상태}}.

    분기(BRDA)가 있는 줄은 **분기 비율이 결정한다** — 전부 탔으면 hit, 하나도 안 탔으면 miss, 그 사이면
    partial. DA 는 분기가 없는 줄에만 쓴다. Codecov 의 lcov 처리가 그렇다: #1735 재생에서 DA 가 0 인데
    분기 하나가 12번 탄 줄을 Codecov 는 partial 로 셌다(DA 만 보면 miss 13줄이 어긋났다).
    """
    report: dict[str, dict[int, str]] = {}
    current, hits, branches = "", {}, {}
    # `\n` 으로만 나눈다 — splitlines() 는 SF 경로 안의 U+2028 같은 문자에서도 끊는다 (Codex 리뷰)
    for raw in path.read_text(encoding="utf-8").split("\n"):
        raw = raw.rstrip("\r")
        tag, _, value = raw.partition(":")
        if tag == "SF":
            current, hits, branches = value, {}, {}
        elif tag == "DA" and current:
            line, count = value.split(",")[:2]
            hits[int(line)] = int(count)
        elif tag == "BRDA" and current:
            line, _block, _branch, count = value.split(",")
            branches.setdefault(int(line), []).append(count not in ("-", "0"))
        elif raw.strip() == "end_of_record" and current:
            lines = {number: HIT if count else MISS for number, count in hits.items()}
            for number, taken in branches.items():
                lines[number] = HIT if all(taken) else MISS if not any(taken) else PARTIAL
            report[current] = lines
            current = ""
    return report


ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote(path: str) -> str:
    """git 의 C 식 인용(`"b/a\\"b.ts"`, `"b/caf\\303\\251.ts"`)을 푼다.

    인용된 경로를 그대로 비교하면 리포트의 어떤 파일과도 안 맞아 그 파일의 miss 가 통째로 빠진다 —
    거짓 초록이다. `core.quotePath=false` 로 비 ASCII 는 날것으로 받지만, 따옴표·역슬래시·제어문자가
    든 경로는 여전히 인용된다.
    """
    if not (len(path) >= 2 and path[0] == path[-1] == '"'):
        return path
    raw, out, i = path[1:-1], bytearray(), 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            if raw[i + 1] in "01234567":
                out.append(int(raw[i + 1 : i + 4], 8))
                i += 4
            else:
                out.append(ESCAPES.get(raw[i + 1], ord(raw[i + 1])))
                i += 2
        else:
            out.extend(raw[i].encode("utf-8"))
            i += 1
    return out.decode("utf-8", errors="replace")


def changed_lines(base: str, head: str) -> dict[str, set[int]]:
    """base..head 에서 추가·수정된 줄 번호(새 쪽 기준). 삭제된 파일·순수 삭제 hunk 는 줄이 없다."""
    diff = subprocess.run(
        [
            # --text: NUL 이 든 소스도 바이너리로 접히지 않게 — 접히면 hunk 가 없어 그 파일의 줄이 통째로 빠진다
            *("git", "-c", "core.quotePath=false", "diff", "--text", "--unified=0", "--no-color", "--no-ext-diff"),
            *("--src-prefix=a/", "--dst-prefix=b/", base, head),
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8", errors="replace")
    changed: dict[str, set[int]] = {}
    path, in_header = "", False
    # 바이트로 받아 `\n` 으로만 나눈다 — git 의 줄 경계는 `\n` 뿐이다. 텍스트 모드는 홀로 선 `\r` 을
    # `\n` 으로 바꾸고 splitlines() 는 \x0b·\x0c·\u2028 에서도 끊어, 본문 한가운데에 가짜 `diff --git`
    # 줄을 만들 수 있었다 (Codex 리뷰 — 셋 다 재현됐다)
    for row in diff.split("\n"):
        # 파일 헤더는 `diff --git` 과 첫 `@@` 사이에만 있다. hunk 본문에서 `++ x` 를 더한 줄은 `+++ x` 로
        # 찍히는데, 그걸 헤더로 읽으면 그 파일의 남은 hunk 가 통째로 빠진다 — 거짓 초록 (Codex 리뷰).
        if row.startswith("diff --git "):
            path, in_header = "", True
        elif in_header and row.startswith("+++ "):
            # 공백이 든 경로 뒤에는 git 이 구분용 탭을 붙인다 — 남겨 두면 어떤 리포트 파일과도 안 맞는다.
            # 인용 여부와 무관하게 안전하다: 경로 안의 탭은 git 이 늘 `\t` 로 인용한다.
            target = unquote(row[4:].split("\t", 1)[0])
            path = target[2:] if target.startswith("b/") else ""
        elif row.startswith("@@"):
            in_header = False
            match = HUNK.match(row)
            if match and path:
                start, count = int(match.group(1)), int(match.group(2) or 1)
                changed.setdefault(path, set()).update(range(start, start + count))
    return changed


def evaluate(report: dict[str, dict[int, str]], changed: dict[str, set[int]], ignore: list[str]) -> dict[str, list]:
    """바뀐 줄 가운데 리포트에 있는 줄만 상태별로 모은다 — Codecov 의 patch 집계와 같은 범위."""
    tally: dict[str, list] = {HIT: [], MISS: [], PARTIAL: []}
    for path in sorted(changed):
        if any(fnmatch.fnmatch(path, glob) for glob in ignore):
            continue
        lines = report.get(path) or {}
        for number in sorted(changed[path]):
            state = lines.get(number)
            if state:
                tally[state].append((path, number))
    return tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce the codecov.yml patch target inside CI (#1766).")
    parser.add_argument("--coverage-xml", type=Path, help="backend Cobertura XML (Coverage Aggregate)")
    parser.add_argument("--lcov", type=Path, help="frontend lcov.info with repo-relative SF paths (Frontend Tests)")
    parser.add_argument("--base", default="HEAD^1", help="diff base — the first parent of a PR merge checkout")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", type=Path, default=Path("codecov.yml"))
    args = parser.parse_args(argv)

    target, threshold, ignore = load_policy(args.config)
    report: dict[str, dict[int, str]] = {}
    for path, loader, label in ((args.coverage_xml, load_cobertura, "backend"), (args.lcov, load_lcov, "frontend")):
        if path is None:
            continue
        if not path.is_file():
            print(f"::error::{label} coverage file missing: {path}")
            return 1
        files = loader(path)
        print(f"{label}: {path} — {len(files)} files, {sum(map(len, files.values()))} lines")
        report.update(files)
    if not report:
        print("::error::no coverage input — pass --coverage-xml and/or --lcov")
        return 1

    tally = evaluate(report, changed_lines(args.base, args.head), ignore)
    hits, misses, partials = len(tally[HIT]), len(tally[MISS]), len(tally[PARTIAL])
    total = hits + misses + partials
    if total == 0:
        print("✓ no changed line is in the coverage report — patch coverage not affected")
        return 0
    coverage = math.floor(10000 * hits / total) / 100  # Codecov 기본값(round: down, precision: 2)과 같게
    print(
        f"patch coverage {coverage:.2f}% — {hits} hit, {misses} miss, {partials} partial of {total} lines "
        f"(target {target:g}%, threshold {threshold:g}%)"
    )
    for state in (MISS, PARTIAL):
        for path, number in tally[state]:
            print(f"::error file={path},line={number}::changed line not covered ({state}) — patch target {target:g}%")
    if coverage >= target - threshold:
        print("✓ patch coverage meets the target")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
