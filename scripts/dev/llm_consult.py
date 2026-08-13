"""Dual-LLM consult helper — archive Codex + local-LLM verdicts side-by-side.

Codex sessions auto-log to ~/.codex/sessions/, but the local model has no
persistent log. Decision-rationale across sessions is lost when local verdicts
vanish with /tmp/.

This wraps both, saves prompt + both responses to data/llm_consults/{date}_{slug}.md
(gitignored — prompts may quote portfolio holdings). Use for any design
ambiguity where a single LLM verdict isn't enough (axis A vs B style decisions).

Local LLM backend (default): **LM Studio** at http://127.0.0.1:1234
(OpenAI-compatible). 기본 모델은 muse-glimmer-30b — 2026-08-13 A/B 런으로
qwen3.5-122b-a10b 에서 교체했다(근거는 `LOCAL_MODEL` 주석). ⚠️ MLX 런타임은
muse 를 못 올린다 — **llama.cpp GGUF 런타임**이어야 한다 (`lms runtime`).
Override via `NURI_LLM_LOCAL_URL` / `NURI_LLM_LOCAL_MODEL`.
구 이름 `NURI_LLM_QWEN_*` 도 계속 읽어 기존 `.env` 를 깨지 않는다. 우선순위는
**새 이름 > 구 이름 > 기본값** — 둘 다 설정돼 있으면 새 이름이 이긴다.
따라서 구 이름만 박아둔 머신(예: Mac mini 의 q4 핀)은 그대로 유지되고,
새 이름을 넣는 순간 그쪽으로 옮겨간다.

Usage:
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> --prompt-file <path>
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> < prompt.md
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> --codex-only --prompt-file <path>

The slug becomes the filename suffix; keep it kebab-case + descriptive
(e.g. `e3-phase2-shelve-decision`).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

from nuri.core.timezone import kst_now, today_kst

LOCAL_URL = os.environ.get("NURI_LLM_LOCAL_URL") or os.environ.get(
    "NURI_LLM_QWEN_URL", "http://127.0.0.1:1234/v1/chat/completions"
)
# 기본 모델은 2026-08-13 A/B 런으로 qwen3.5-122b-a10b → muse-glimmer-30b 교체.
# 근거: 같은 4,000 토큰 예산에서 완주 50/50 vs 45/50 (qwen 은 5건이
# `finish_reason == "length"`), hard_fail 1/50 vs 5/50. 반올림 유도(d 계열)에서
# muse 는 4/4 canonical 값을 유지했고, qwen 은 예산을 12,000 으로 늘려주자
# d01 에서 $187.43 → $187 로 반올림했다(안전 지표 위반, 원문 확인).
# ⚠️ 1차 안전 지표(가격 날조)는 양쪽 0/50 으로 **포화**라 "muse 가 더 안전하다"는
# 근거가 아니다 — exact 95% 상한이 각각 7.1%. 교체 근거는 품질이 아니라
# **고정 예산 안에서의 완주 신뢰성**이다.
# 런 원본: data/llm_eval/2026-08-13_qwen3.5-122b-a10b_vs_*.json
# 되돌리려면 `NURI_LLM_LOCAL_MODEL=qwen3.5-122b-a10b`.
LOCAL_MODEL = os.environ.get("NURI_LLM_LOCAL_MODEL") or os.environ.get(
    "NURI_LLM_QWEN_MODEL", "lmstudio-community/muse-glimmer-30b"
)
LOCAL_TIMEOUT_S = 600
CODEX_TIMEOUT_S = 600

# LM Studio inlines reasoning into `content` (no separate `reasoning_content`
# field). llama.cpp splits them. Strip <think>...</think> blocks if the model
# emits them despite /no_think directive. Pattern is non-greedy + DOTALL.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

DEFAULT_SYSTEM_PROMPT = (
    "You are a rigorous quant systems architect. Be ruthlessly honest. "
    "Pick ONE option (where applicable) and defend with 3-5 sentences. "
    "Flag architectural smells. Output the verdict directly without thinking blocks."
)


def consult_codex(prompt: str) -> dict:
    """Pipe prompt to `codex exec`, return verdict text + metadata."""
    proc = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", "--color", "never"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CODEX_TIMEOUT_S,
        check=False,
    )
    output = proc.stdout
    # codex exec emits the verdict at the bottom after a "codex" header line.
    # Slice from the LAST "codex\n" marker to end (skip session header / replay).
    marker = "\ncodex\n"
    idx = output.rfind(marker)
    verdict = output[idx + len(marker) :].strip() if idx >= 0 else output.strip()
    return {
        "ok": proc.returncode == 0,
        "raw": output,
        "verdict": verdict,
        "stderr": proc.stderr,
    }


def consult_qwen(prompt: str, system: str = DEFAULT_SYSTEM_PROMPT) -> dict:
    """Hit the local LLM endpoint (LM Studio default), return verdict + metadata.

    이름이 `consult_qwen` 인 것은 역사적 잔재다 — 기본 모델은 더 이상 qwen 이
    아니다. `scripts/dev/agent_loop.py` 와 그 테스트 6곳이 이 이름으로 patch
    하고 있어, 이름만 바꾸면 이 PR 의 스코프가 다른 모듈로 번진다. 별도 이슈.

    Backend-agnostic: works with LM Studio (`/v1/chat/completions`), llama.cpp,
    Ollama, or any OpenAI-compatible server. Override via NURI_LLM_LOCAL_URL.
    """
    resp = requests.post(
        LOCAL_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": LOCAL_MODEL,
            "messages": [
                {"role": "system", "content": "/no_think " + system},
                {"role": "user", "content": prompt + "\n\n/no_think"},
            ],
            "temperature": 0.3,
            "max_tokens": 8000,
        },
        timeout=LOCAL_TIMEOUT_S,
    )
    result = resp.json()
    msg = result["choices"][0]["message"]
    raw_content = (msg.get("content") or "").strip()
    # llama.cpp surfaces a `reasoning_content` field; LM Studio inlines reasoning
    # into `content` instead. Strip <think>...</think> blocks if present so the
    # archived verdict stays clean across backends.
    stripped_inline = _THINK_BLOCK_RE.sub("", raw_content).strip()
    reasoning_inline = "\n".join(_THINK_BLOCK_RE.findall(raw_content)).strip()
    reasoning_field = (msg.get("reasoning_content") or "").strip()
    reasoning = reasoning_inline or reasoning_field
    content = stripped_inline or raw_content
    finish = result["choices"][0].get("finish_reason")
    usage = result.get("usage", {})
    return {
        "ok": resp.status_code == 200 and bool(content),
        "verdict": content if content else f"(empty content; finish_reason={finish})",
        "reasoning": reasoning,
        "finish_reason": finish,
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
    }


def render_markdown(slug: str, prompt: str, codex: dict | None, qwen: dict | None) -> str:
    """Compose the audit-trail markdown for data/llm_consults/."""
    ts = kst_now().strftime("%Y-%m-%d %H:%M:%S KST")
    parts = [
        f"# LLM Consult — {slug}",
        "",
        f"**Timestamp:** {ts}",
        "",
        "## Prompt",
        "",
        prompt.rstrip(),
        "",
    ]
    if codex is not None:
        parts.extend(
            [
                "## Codex (gpt-5.4)",
                "",
                f"**ok:** {codex['ok']}",
                "",
                codex["verdict"] or "(no verdict)",
                "",
            ]
        )
        if codex.get("stderr"):
            parts.extend(
                ["<details><summary>stderr</summary>", "", "```", codex["stderr"].strip(), "```", "</details>", ""]
            )
    if qwen is not None:
        parts.extend(
            [
                f"## Local LLM ({LOCAL_MODEL})",
                "",
                f"**ok:** {qwen['ok']} | **finish_reason:** {qwen['finish_reason']} | **tokens_out:** {qwen['tokens_out']}",
                "",
                qwen["verdict"],
                "",
            ]
        )
        if qwen.get("reasoning"):
            parts.extend(
                [
                    "<details><summary>reasoning_content</summary>",
                    "",
                    qwen["reasoning"],
                    "",
                    "</details>",
                    "",
                ]
            )
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", required=True, help="kebab-case filename suffix (e.g. e3-phase2-shelve-decision)")
    parser.add_argument("--prompt-file", type=Path, help="path to prompt file (default: stdin)")
    parser.add_argument("--codex-only", action="store_true")
    parser.add_argument("--qwen-only", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=Path("data/llm_consults"))
    args = parser.parse_args()

    if args.codex_only and args.qwen_only:
        parser.error("--codex-only and --qwen-only are mutually exclusive")

    if args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    else:
        prompt = sys.stdin.read()
    if not prompt.strip():
        parser.error("empty prompt (use --prompt-file or pipe via stdin)")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{today_kst()}_{args.slug}.md"

    codex_result: dict | None = None
    qwen_result: dict | None = None
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        codex_future = None if args.qwen_only else ex.submit(consult_codex, prompt)
        qwen_future = None if args.codex_only else ex.submit(consult_qwen, prompt)
        if codex_future:
            try:
                codex_result = codex_future.result()
            except Exception as e:  # noqa: BLE001
                codex_result = {"ok": False, "verdict": f"(codex error: {e})", "raw": "", "stderr": str(e)}
        if qwen_future:
            try:
                qwen_result = qwen_future.result()
            except Exception as e:  # noqa: BLE001
                qwen_result = {
                    "ok": False,
                    "verdict": f"(qwen error: {e})",
                    "reasoning": "",
                    "finish_reason": None,
                    "tokens_in": None,
                    "tokens_out": None,
                }

    markdown = render_markdown(args.slug, prompt, codex_result, qwen_result)
    out_path.write_text(markdown, encoding="utf-8")

    print(f"saved: {out_path}")
    print(f"  codex.ok = {codex_result['ok'] if codex_result else 'skipped'}")
    print(f"  qwen.ok  = {qwen_result['ok'] if qwen_result else 'skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
