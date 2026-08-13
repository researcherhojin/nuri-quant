"""저장된 A/B 원문을 **다시 채점**한다 — 모델 호출 없이.

왜 필요한가
-----------
모델 호출은 비싸고(50x2 런이 4-5 시간) 채점은 공짜다. 그런데 이 프로젝트에서
실제로 자주 틀린 건 모델이 아니라 **채점기** 였다 (2026-08-12~13 사이에만
채점기 결함 13건). 채점기를 고칠 때마다 4 시간짜리 런을 다시 도는 건 낭비고,
무엇보다 **같은 원문에 대해 신·구 채점 결과를 비교**할 수 없어 수정이 옳았는지
확인할 방법이 없어진다.

이 스크립트는 `llm_ab_eval.py` 가 남긴 JSON(완료본 또는 `_partial_` 체크포인트)의
`output` 을 읽어 현재 채점기로 다시 채점하고,

  1. 저장된 판정과 **달라진 항목**을 나열하고 (채점기 수정의 영향),
  2. 현재 기준 실패 건의 **원문을 함께 출력**한다 (사람이 오탐/진짜를 판정),
  3. `--subset` 으로 프롬프트 부분집합만 집계한다 (표본 크기가 결론을
     바꾸는지 확인).

사용법
------
    # 최신 결과 전부 재채점
    .venv/bin/python scripts/dev/llm_ab_rescore.py

    # 특정 파일 + 실패 원문 보기
    .venv/bin/python scripts/dev/llm_ab_rescore.py --file data/llm_eval/xxx.json --show-failures

    # 32개 부분집합만 (v1 10 + 계열별 2 + a/f 계열 1 추가)
    .venv/bin/python scripts/dev/llm_ab_rescore.py --subset core32

**이 스크립트는 원본 JSON 을 수정하지 않는다.** 읽기 전용이다 — 원문은 유일한
1 차 자료이므로 덮어쓰지 않는다.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

_SPEC = importlib.util.spec_from_file_location("llm_ab_eval", Path(__file__).resolve().parent / "llm_ab_eval.py")
assert _SPEC and _SPEC.loader
ab = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ab)


def core32(prompt_ids: list[str]) -> list[str]:
    """32개 부분집합 — v1 10개 + 계열별 2개 + 가격 검사 계열(a, f) 1개씩 추가.

    계열이 하나도 빠지지 않게 유지하는 게 조건이다. `a`(레벨 unavailable 인데
    요구)와 `f`(달러 기호 빼고 요구)는 `invented_price` / `phantom_levels` 를
    직접 자극하는 유일한 계열이라 3개씩 둔다.
    """
    keep = [p for p in prompt_ids if p.startswith("p")]  # v1 전체
    per_family: dict[str, list[str]] = {}
    for pid in prompt_ids:
        if pid.startswith("p"):
            continue
        per_family.setdefault(pid[0], []).append(pid)
    for fam, ids in sorted(per_family.items()):
        n = 3 if fam in ("a", "f") else 2
        keep.extend(sorted(ids)[:n])
    return keep


SUBSETS = {"core32": core32, "v1": lambda ids: [p for p in ids if p.startswith("p")]}


def load_rows(path: Path) -> list[tuple[str, dict]]:
    """(model, row) 목록. 완료본과 `_partial_` 체크포인트 양쪽을 읽는다."""
    d = json.loads(path.read_text(encoding="utf-8"))
    if "results" in d:  # 완료본
        return [(r["model"], row) for r in d["results"] for row in r["rows"]]
    return [(d["model"], row) for row in d.get("rows", [])]  # 체크포인트


def summarize(model: str, scored: list[dict], n_infra: int) -> dict:
    n = len(scored)
    if not n:
        return {"model": model, "n_scored": 0, "n_infra_failures": n_infra, "hard_fail_rate": None}
    return {
        "model": model,
        "n_scored": n,
        "n_infra_failures": n_infra,
        "hard_fail_rate": round(sum(s["hard_fail"] for s in scored) / n, 3),
        "mean_overlap": round(sum(s["numeric_overlap"] for s in scored) / n, 3),
        "invented_total": sum(len(s["invented_money"]) for s in scored),
        # 1차 안전 지표 — 이 하네스의 존재 이유
        "unsafe_n": sum(s["unsafe_price_level"] for s in scored),
        "unsafe_rate": round(sum(s["unsafe_price_level"] for s in scored) / n, 3),
    }


def _fmt(v: Any) -> str:
    return "—" if v is None else str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, action="append", help="결과 JSON. 생략 시 data/llm_eval/*.json 전부")
    ap.add_argument("--prompts", type=Path, default=ab.PROMPTS_FILE)
    ap.add_argument("--subset", choices=sorted(SUBSETS), help="프롬프트 부분집합만 집계")
    ap.add_argument("--show-failures", action="store_true", help="실패 건의 원문을 함께 출력")
    ap.add_argument("--excerpt", type=int, default=900, help="원문 출력 길이")
    args = ap.parse_args()

    cfg = ab.load_prompts(args.prompts)
    specs = {p["id"]: p for p in cfg["prompts"]}
    wanted: Optional[set[str]] = None
    if args.subset:
        wanted = set(SUBSETS[args.subset](list(specs)))
        print(f"부분집합 {args.subset}: {len(wanted)}개 프롬프트")

    files = args.file or [Path(p) for p in sorted(glob.glob("data/llm_eval/*.json"))]
    files = [f for f in files if f.exists()]
    if not files:
        print("재채점할 결과 파일이 없다.", file=sys.stderr)
        return 1

    per_model: dict[str, list[dict]] = {}
    infra: dict[str, int] = {}
    changed: list[tuple[str, str, list[str], list[str]]] = []
    failures: list[tuple[str, str, list[str], str]] = []

    for f in files:
        for model, row in load_rows(f):
            pid = row["id"]
            if pid not in specs or (wanted is not None and pid not in wanted):
                continue
            out = row.get("output")
            fl = row.get("failures", [])
            if not out:
                # `call_failed`(연결 거부)만 인프라다. `no_answer` 는 모델이
                # 예산 안에서 답을 못 낸 것이므로 실패로 센다 (codex 3차 [P1]).
                if "call_failed" in fl:
                    infra[model] = infra.get(model, 0) + 1
                else:
                    per_model.setdefault(model, []).append(
                        {"hard_fail": True, "unsafe_price_level": False, "numeric_overlap": 0.0, "invented_money": []}
                    )
                    failures.append((model, pid, fl or ["no_answer"], "(빈 응답 — 사고 블록만)"))
                continue
            new = ab.score(specs[pid], cfg, out, truncated=row.get("finish_reason") == "length")
            per_model.setdefault(model, []).append(new)
            old = sorted(row.get("failures", []))
            if old != sorted(new["failures"]):
                changed.append((model, pid, old, new["failures"]))
            if new["hard_fail"]:
                failures.append((model, pid, new["failures"], out))

    print(f"\n재채점 대상: {sum(len(v) for v in per_model.values())}건 (파일 {len(files)}개)")

    print(f"\n{'model':<32} {'scored':>7} {'infra':>6} {'unsafe':>7} {'hard_fail':>10} {'overlap':>8} {'invented':>9}")
    for model, scored in sorted(per_model.items()):
        s = summarize(model, scored, infra.get(model, 0))
        print(
            f"{model[:32]:<32} {s['n_scored']:>7} {s['n_infra_failures']:>6} "
            f"{_fmt(s.get('unsafe_rate')):>7} {_fmt(s['hard_fail_rate']):>10} "
            f"{_fmt(s.get('mean_overlap')):>8} {_fmt(s.get('invented_total')):>9}"
        )

    print(f"\n저장된 판정과 달라진 건: {len(changed)}")
    for model, pid, old, new in changed:
        print(f"  [{model[:20]}] {pid}\n      저장: {old}\n      현재: {new}")

    print(f"\n현재 기준 실패: {len(failures)}")
    for model, pid, fl, out in failures:
        print(f"  [{model[:20]}] {pid}: {fl}")
        if args.show_failures:
            print("      ── 원문 ──")
            for line in out[: args.excerpt].splitlines():
                print(f"      {line}")
            print("      ──────────\n")
    if failures and not args.show_failures:
        print("  (원문을 보려면 --show-failures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
