"""Agent loop orchestrator skeleton — Codex (spec) → Claude (patch, stub) → Qwen (review).

epic #577 / E2 (#578). Discord 미연결, file-based transcript. Claude builder
는 본 PR 에서 stub — 별 issue 에서 backend 결정 (API 직접 vs Claude Code subprocess).

Usage:
    .venv/bin/python scripts/dev/agent_loop.py --issue 575
    .venv/bin/python scripts/dev/agent_loop.py --issue 575 --budget-tokens 50000 --budget-usd 0.50

산출물:
    data/agent_loop/<issue>/
      spec.md       # Codex 의 spec breakdown (Step 1)
      patch.diff    # Claude 자리 (Step 2 stub — TODO 주석만)
      review.md     # Qwen adversarial review (Step 3)
      cost.json     # 누적 token + USD / 단계별 사용량

Cost budget: token (Codex char-proxy + Qwen server usage) 와 USD 동시 추적.
어느 한쪽이라도 budget 초과 시 다음 단계 abort.

Exit codes:
  0 success / 1 LLM ok=False / 2 budget exceeded
  3 dependency error — I/O 또는 subprocess 의존성 (network/filesystem/external CLI)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# llm_consult.py 의 헬퍼 재사용. scripts/dev/ 자체 모듈이라 sys.path 조작 불필요.
# requests 는 직접 import 하지 않음 — RequestException 은 OSError 상속이므로
# main() 의 except 가 자동 포착.
sys.path.insert(0, str(Path(__file__).parent))
from llm_consult import consult_codex, consult_qwen  # noqa: E402

DEFAULT_BUDGET_TOKENS = 100_000
DEFAULT_BUDGET_USD = 1.00

# Pricing (USD per 1M tokens). Codex CLI 는 gpt-5.4 기준.
# Source: https://openai.com/api/pricing/ (2026-05-03 confirmed).
# 가격 정책 변경 시 본 상수만 갱신. Qwen 은 local LLM 이라 비용 0.
CODEX_INPUT_USD_PER_M = 2.50
CODEX_OUTPUT_USD_PER_M = 15.00
QWEN_USD_PER_M = 0.0


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class CostTracker:
    """누적 토큰 + USD 추적. 어느 한쪽이라도 초과 시 raise BudgetExceeded."""

    budget_tokens: int
    budget_usd: float
    used_tokens: int = 0
    used_usd: float = 0.0
    by_step_tokens: dict[str, int] = field(default_factory=dict)
    by_step_usd: dict[str, float] = field(default_factory=dict)

    def charge(self, step: str, tokens: int, usd_per_m: float) -> None:
        usd = tokens * usd_per_m / 1_000_000
        self.used_tokens += tokens
        self.used_usd += usd
        self.by_step_tokens[step] = self.by_step_tokens.get(step, 0) + tokens
        self.by_step_usd[step] = round(self.by_step_usd.get(step, 0.0) + usd, 6)
        if self.used_tokens > self.budget_tokens:
            raise BudgetExceeded(f"누적 {self.used_tokens} tokens > budget {self.budget_tokens} (마지막: {step})")
        if self.used_usd > self.budget_usd:
            raise BudgetExceeded(f"누적 ${self.used_usd:.4f} > budget ${self.budget_usd:.2f} (마지막: {step})")

    def to_dict(self) -> dict:
        return {
            "budget_tokens": self.budget_tokens,
            "budget_usd": self.budget_usd,
            "used_tokens": self.used_tokens,
            "used_usd": round(self.used_usd, 6),
            "by_step_tokens": self.by_step_tokens,
            "by_step_usd": self.by_step_usd,
        }


def estimate_tokens(text: str) -> int:
    """Mitigation char-proxy: 2 char ≈ 1 token. NOT a hard upper bound.

    Heuristic: Korean (Hangul) tokenizers (Qwen/Claude/GPT-style BPE) typically
    emit ~1.5-2 chars/token; English ~4. Mixed Korean + Markdown 가정해 2 채택.
    Codex usage API 미반환 — 본 proxy 가 step1 budget 의 유일 근거.

    한계: code-fence / 짙은 punctuation / 비-ASCII symbol 이 많은 prompt 에서
    real token count 가 len//2 를 초과할 수 있음. budget 가 발화하지 않는
    case 에서도 실제 cost 가 약간 더 들 수 있다는 점을 caller 가 인지해야 함.
    Mitigation 강화 방안 (별 issue): tiktoken / Qwen tokenizer 직접 사용.
    """
    return max(1, len(text) // 2)


def fetch_issue_body(issue_num: int) -> tuple[str, str]:
    """gh issue view 로 title + body 조회. (title, body) 반환."""
    proc = subprocess.run(
        ["gh", "issue", "view", str(issue_num), "--json", "title,body"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data["title"], data["body"]


def build_spec_prompt(issue_num: int, title: str, body: str) -> str:
    return f"""# Issue #{issue_num} — spec breakdown

본 task 를 patch-ready spec 으로 분해. 구현은 다음 단계 (Claude builder) 가
담당하므로 본 응답은 **명세** 만 작성 — 코드 직접 작성 금지.

## Issue
**Title:** {title}

**Body:**
{body}

## Output 형식
1. **Goal** (1 sentence)
2. **Touched files** (예상, 경로만)
3. **Acceptance criteria** (bullet, ≤5)
4. **Risks / open questions** (bullet, ≤3)
5. **Out-of-scope** — 의도적 제외 항목

## 제약
- PR Discipline: 1 issue = 1 PR ≤ 3 commits
- nuri-quant CLAUDE.md invariants 준수 (sole-importer DB, kst_now, etc.)
- spec 자체는 ≤300 줄
"""


def build_review_prompt(issue_num: int, spec: str, patch_diff: str) -> str:
    return f"""# Issue #{issue_num} — adversarial review

본 task 의 spec 과 patch (stub 가능) 를 adversarial 관점으로 review.

## Spec
{spec}

## Patch
```diff
{patch_diff if patch_diff.strip() else "(stub — patch 미작성, spec 만 검토)"}
```

## Review 형식
1. **Spec gaps** — 누락된 acceptance criteria / edge case
2. **Hidden risk** — Codex 가 안 짚은 functional / security / privacy 위험
3. **PR scope sanity** — 1 PR 로 적정한가? 분리 권고?
4. **Verdict**: PASS / NEEDS_REWORK / ABSTAIN (이유 1 sentence)

ruthlessly honest. PASS 남발 금지.
"""


def write_outputs(out_dir: Path, name: str, content: str) -> Path:
    path = out_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def run_loop(issue_num: int, budget_tokens: int, budget_usd: float, out_root: Path) -> int:
    out_dir = out_root / str(issue_num)
    out_dir.mkdir(parents=True, exist_ok=True)
    cost = CostTracker(budget_tokens=budget_tokens, budget_usd=budget_usd)

    # Step 0: 이슈 fetch
    title, body = fetch_issue_body(issue_num)
    print(f"[step 0] issue #{issue_num}: {title}")

    # Step 1: Codex spec
    print("[step 1] Codex spec ...")
    spec_prompt = build_spec_prompt(issue_num, title, body)
    cost.charge("step1_codex_in", estimate_tokens(spec_prompt), CODEX_INPUT_USD_PER_M)
    codex_result = consult_codex(spec_prompt)
    if not codex_result["ok"]:
        print(f"  codex failed: {codex_result.get('stderr', '')[:200]}")
        return 1
    spec = codex_result["verdict"]
    cost.charge("step1_codex_out", estimate_tokens(spec), CODEX_OUTPUT_USD_PER_M)
    spec_path = write_outputs(out_dir, "spec.md", spec)
    print(f"  saved {spec_path} ({len(spec)} chars)")

    # Step 2: Claude builder = stub
    patch_diff = (
        "# TODO E2 #578: Claude builder 자리.\n"
        "# 별 issue 에서 backend 결정 (Anthropic API 직접 vs Claude Code subprocess).\n"
        "# 현재는 사용자 수동으로 채움.\n"
    )
    patch_path = write_outputs(out_dir, "patch.diff", patch_diff)
    print(f"[step 2] Claude builder (stub) → {patch_path}")

    # Step 3: Qwen review
    print("[step 3] Qwen review ...")
    review_prompt = build_review_prompt(issue_num, spec, patch_diff)
    cost.charge("step3_qwen_in", estimate_tokens(review_prompt), QWEN_USD_PER_M)
    qwen_result = consult_qwen(review_prompt)
    if not qwen_result["ok"]:
        print(f"  qwen failed: {qwen_result['verdict'][:200]}")
        return 1
    review = qwen_result["verdict"]
    # Qwen 은 server side usage 반환 — 정확 값 우선 사용
    qwen_out_tokens = qwen_result.get("tokens_out") or estimate_tokens(review)
    cost.charge("step3_qwen_out", qwen_out_tokens, QWEN_USD_PER_M)
    review_path = write_outputs(out_dir, "review.md", review)
    print(f"  saved {review_path} ({len(review)} chars)")

    # cost.json
    cost_path = write_outputs(out_dir, "cost.json", json.dumps(cost.to_dict(), indent=2))
    print(
        f"\n총 사용: {cost.used_tokens} tokens / ${cost.used_usd:.4f} "
        f"(budget {budget_tokens} / ${budget_usd:.2f}) → {cost_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", type=int, required=True, help="GitHub issue 번호")
    parser.add_argument("--budget-tokens", type=int, default=DEFAULT_BUDGET_TOKENS)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--out-dir", type=Path, default=Path("data/agent_loop"))
    args = parser.parse_args(argv)

    try:
        return run_loop(args.issue, args.budget_tokens, args.budget_usd, args.out_dir)
    except BudgetExceeded as e:
        print(f"BUDGET_EXCEEDED: {e}", file=sys.stderr)
        return 2
    except (
        # OSError 상속: FileNotFoundError (gh missing), PermissionError (out_dir
        # write 실패), ConnectionError, TimeoutError (built-in), requests.
        # RequestException (Connection/Timeout/HTTPError 등 — IOError 상속).
        OSError,
        # SubprocessError 상속: CalledProcessError (non-zero exit), TimeoutExpired
        # (codex hang — built-in TimeoutError 상속 안 하므로 별도 필요).
        subprocess.SubprocessError,
        # ValueError 상속: gh stdout malformed JSON.
        json.JSONDecodeError,
    ) as e:
        # Narrow tuple — I/O / subprocess / parse 의존성 오류만 rc=3 으로 표면화.
        # KeyError/TypeError/AttributeError 등 programmer bug 는 의도적으로
        # propagate (traceback 으로 디버깅).
        print(f"DEPENDENCY_ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
