#!/usr/bin/env python3
"""CI shard 별 duration 파일을 fail-closed 로 병합한다 (#1414).

`.test_durations` 는 pytest-split 의 shard 균형 입력인데, M5 직렬 실측치는 CI
(4코어 xdist + branch coverage) 런타임을 예측하지 못한다 — 예측 spread 0.0s 에
실측 spread 89s (#1414 실측). 그래서 push-to-main CI 가 shard 마다
`--store-durations --clean-durations` 로 **자기 shard 의 관측치만** 남기고,
이 스크립트가 run 단위로 합쳐 CI 실측 ledger 를 만든다.

**fail-closed 원칙** (codex consult 2026-09-02, `--clean-durations` 없는
snapshot merge 가 stale 값을 조용히 살리는 함정 — pytest-split#20):

- shard 파일 개수가 기대치와 다르면 실패 (하나 빠져도 그 그룹 테스트가 통째 누락)
- 같은 node ID 가 두 shard 에 있으면 실패 (clean 이 빠졌거나 split 이 겹친 것)
- ``--expect-count`` 가 주어지면 union 크기와 대조해 다르면 실패

여러 run 의 병합본에 대해서는 per-test **median** 을 취한다 (단일 run 의
러너 노이즈 평활 — 3-5 run 권장).

Usage:
    # run 하나의 shard 파일들 → 병합
    merge_test_durations.py merge --expect-shards 8 [--expect-count N] out.json shard1.json shard2.json ...
    # 병합본 여러 개 → per-test median
    merge_test_durations.py median out.json run1.json run2.json run3.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path


def load(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise SystemExit(f"FAIL: {path} 가 비어 있거나 dict 가 아니다 — 부분 실행/손상 의심")
    return data


def merge(out: Path, shards: list[Path], expect_shards: int, expect_count: int | None) -> None:
    if len(shards) != expect_shards:
        raise SystemExit(
            f"FAIL: shard 파일 {len(shards)}개 ≠ 기대 {expect_shards}개 — 누락된 그룹의 테스트가 ledger 에서 통째로 빠진다"
        )
    merged: dict[str, float] = {}
    for path in shards:
        part = load(path)
        dup = merged.keys() & part.keys()
        if dup:
            sample = sorted(dup)[:3]
            raise SystemExit(
                f"FAIL: node ID 중복 {len(dup)}건 (예: {sample}) — "
                "--clean-durations 가 빠져 full snapshot 이 섞였거나 split 이 겹쳤다"
            )
        merged.update(part)
    if expect_count is not None and len(merged) != expect_count:
        raise SystemExit(f"FAIL: union {len(merged)}개 ≠ 수집 기대 {expect_count}개 — 부분 실행이 섞였다")
    out.write_text(json.dumps(dict(sorted(merged.items())), indent=2) + "\n", encoding="utf-8")
    print(f"OK: {len(shards)} shards → {len(merged)} tests → {out}")


def median(out: Path, runs: list[Path]) -> None:
    """runs[0] 이 **최신** run 이다 — 순서가 계약이다.

    node 소속(membership)은 최신 run 에 앵커한다: 삭제·개명된 테스트가 옛 run 을
    타고 ledger 에 좀비로 남으면 pytest-split 이 존재하지 않는 항목에 시간을
    배정한다 (codex P3-c). 옛 run 은 최신 run 에 있는 테스트의 표본만 보탠다 —
    새 테스트는 표본 1개(최신 run)로 들어오는 게 정상이다.
    """
    if len(runs) < 2:
        raise SystemExit("FAIL: median 은 run 2개 이상 필요 — 단일 run 은 러너 노이즈를 그대로 싣는다")
    newest = load(runs[0])
    samples: dict[str, list[float]] = {node: [dur] for node, dur in newest.items()}
    dropped: set[str] = set()
    for path in runs[1:]:
        for node, dur in load(path).items():
            if node in samples:
                samples[node].append(dur)
            else:
                dropped.add(node)
    result = {node: statistics.median(vals) for node, vals in sorted(samples.items())}
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    counts = [len(v) for v in samples.values()]
    print(
        f"OK: {len(runs)} runs → {len(result)} tests (표본수 min {min(counts)} / max {max(counts)}, "
        f"최신 run 에 없어 제외된 stale node {len(dropped)}개) → {out}"
    )


def parse_fast_splits(workflow: Path) -> int:
    """워크플로에서 fast shard 의 `--splits N` 을 읽는다.

    첫 번째 `--splits` 가 fast job 이다 (backend-tests-shard 가 backend-tests-slow
    보다 먼저 정의됨 — tests/scripts/test_ci_shard_balance.py 의 parity lock 이
    같은 순서 가정을 쓴다). 다운로드된 artifact 개수에서 기대치를 도출하면
    누락이 조용히 통과하고(fail-open), 하드코딩하면 #1413 의 ci-cov 버그를
    재생산한다 — 그래서 워크플로가 유일한 출처다.
    """
    m = re.search(r"--splits (\d+)", workflow.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"FAIL: {workflow} 에서 --splits 를 못 찾았다")
    return int(m.group(1))


def refresh(workflow: Path, out: Path, rundirs: list[Path]) -> None:
    """run 디렉토리들(최신 먼저)에서 ledger 를 재생성한다 — Makefile 의 실행부.

    각 rundir 은 `durations-fast-*/​.test_durations` 를 담는다 (gh run download 결과).
    최신 run 은 현재 워크플로의 --splits 와 정확히 일치해야 한다(fail-closed 앵커).
    옛 run 은 shard 수가 달라도 좋다 — membership 은 어차피 최신 run 이 정하고,
    옛 run 은 값 표본만 보탠다 (shard 수 전환기에 refresh 가 마비되지 않게, codex P3-b).
    """
    splits = parse_fast_splits(workflow)
    merged_paths: list[Path] = []
    for i, rundir in enumerate(rundirs):
        shard_files = sorted(rundir.glob("durations-fast-*/.test_durations"))
        merged = rundir / "merged.json"
        if i == 0:
            merge(merged, shard_files, expect_shards=splits, expect_count=None)
        else:
            if not shard_files:
                raise SystemExit(f"FAIL: {rundir} 에 shard 파일이 없다")
            merge(merged, shard_files, expect_shards=len(shard_files), expect_count=None)
        merged_paths.append(merged)
    median(out, merged_paths)
    # full-precision float 은 privacy 스캐너의 7자리 룰에 걸린다 — 커밋 전 반올림.
    # 직접 실행(`python scripts/ci/...py`) 시 sys.path[0] 이 scripts/ci 라 레포 루트를 얹는다.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.doc.round_test_durations import round_file

    entries, before, after = round_file(out)
    print(f"OK: 4자리 반올림 {entries} entries ({before} → {after} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--expect-shards", type=int, required=True)
    m.add_argument("--expect-count", type=int, default=None)
    m.add_argument("out", type=Path)
    m.add_argument("shards", type=Path, nargs="+")
    d = sub.add_parser("median")
    d.add_argument("out", type=Path)
    d.add_argument("runs", type=Path, nargs="+")
    r = sub.add_parser("refresh")
    r.add_argument("--workflow", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("rundirs", type=Path, nargs="+", help="최신 run 먼저")
    args = parser.parse_args(argv)
    if args.cmd == "merge":
        merge(args.out, args.shards, args.expect_shards, args.expect_count)
    elif args.cmd == "median":
        median(args.out, args.runs)
    else:
        refresh(args.workflow, args.out, args.rundirs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
