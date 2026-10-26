"""Dual-LLM consult helper — archive Codex + local-LLM verdicts side-by-side.

Codex sessions auto-log to ~/.codex/sessions/, but the local model has no
persistent log. Decision-rationale across sessions is lost when local verdicts
vanish with /tmp/.

This wraps both, saves prompt + both responses to data/llm_consults/{date}_{slug}.md
(gitignored — prompts may quote portfolio holdings). Use for any design
ambiguity where a single LLM verdict isn't enough (axis A vs B style decisions).

Local LLM: **Strata** at http://127.0.0.1:8081 (OpenAI-compatible, 서버는 별도 실행 —
`strata start`), 모델 qwen3.8-flash-next-unsloth-ud-q4_k_xl. 모델 파일(Metal GGUF 77GB)이
RAM 32GB 인 Mac mini 에는 올라가지 않아 MBP 전용이다 — Discord `/thesis` 는
`scripts/deploy/thesis_remote.sh` 로 MBP 에서 돈다. LM Studio backend 는 2026-10-26 제거했다
(더 이상 쓰지 않음).
Override via exported `NURI_LLM_LOCAL_URL` / `NURI_LLM_LOCAL_MODEL` (no dotenv loading).
구 이름 `NURI_LLM_QWEN_*` 도 계속 읽어 기존 `.env` 를 깨지 않는다. 우선순위는
**새 이름 > 구 이름 > 기본값** — 둘 다 설정돼 있으면 새 이름이 이긴다.

Usage:
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> --prompt-file <path>
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> < prompt.md
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> --codex-only --prompt-file <path>
    .venv/bin/python scripts/dev/llm_consult.py --slug <slug> --local-only < private.md   # 비공개 맥락

The slug becomes the filename suffix; keep it kebab-case + descriptive
(e.g. `e3-phase2-shelve-decision`).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests

from nuri.core.timezone import kst_now, today_kst

LOCAL_URL = os.environ.get("NURI_LLM_LOCAL_URL") or os.environ.get(
    "NURI_LLM_QWEN_URL", "http://127.0.0.1:8081/v1/chat/completions"
)
# Strata 서버 `/v1/models` 의 id 와 같아야 한다 (2026-10-26 실측 일치). 예전 LM Studio 기본
# 모델(muse-glimmer-30b)의 2026-08-13 A/B 근거는 git log 와 data/llm_eval/ 에 있다.
LOCAL_MODEL = os.environ.get("NURI_LLM_LOCAL_MODEL") or os.environ.get(
    "NURI_LLM_QWEN_MODEL", "qwen3.8-flash-next-unsloth-ud-q4_k_xl"
)
LOCAL_TIMEOUT_S = 600
CODEX_TIMEOUT_S = 600
# Codex 리뷰 모델은 여기서 명시한다. 예전에는 `-m` 없이 불러 머신의 `~/.codex/config.toml`
# 기본값을 따랐고, 아카이브 머리말에는 "gpt-5.4" 가 고정 문자열로 박혀 실제 모델과 달랐다.
CODEX_MODEL = os.environ.get("NURI_LLM_CODEX_MODEL", "gpt-6.1-sol")

# Some OpenAI-compatible servers inline reasoning into `content` (no separate
# `reasoning_content` field); llama.cpp splits them. Strip <think>...</think> blocks if the model
# emits them despite /no_think directive. Pattern is non-greedy + DOTALL.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

DEFAULT_SYSTEM_PROMPT = (
    "You are a rigorous quant systems architect. Be ruthlessly honest. "
    "Pick ONE option (where applicable) and defend with 3-5 sentences. "
    "Flag architectural smells. Output the verdict directly without thinking blocks."
)


def is_loopback_url(url: str) -> bool:
    """URL 의 host 가 이 머신(loopback)인가. 파싱 실패·host 없음은 False.

    `--local-only` 는 env 로 바꿀 수 있는 `LOCAL_URL` 이 다른 머신을 가리키면 거부한다 —
    `--qwen-only` 만으로는 `NURI_LLM_LOCAL_URL` 하나로 비공개 prompt 가 밖으로 나간다.
    """
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def consult_codex(prompt: str) -> dict:
    """Pipe prompt to `codex exec`, return verdict text + metadata."""
    proc = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", "--color", "never", "-m", CODEX_MODEL],
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


def consult_qwen(prompt: str, system: str = DEFAULT_SYSTEM_PROMPT, *, trust_env: bool = True) -> dict:
    """Hit the local LLM endpoint (Strata), return verdict + metadata.

    이름이 `consult_qwen` 인 것은 역사적 잔재다 — 한동안 기본 모델이 qwen 이 아니었다. `scripts/dev/agent_loop.py` 와 그 테스트 6곳이 이 이름으로 patch
    하고 있어, 이름만 바꾸면 이 PR 의 스코프가 다른 모듈로 번진다. 별도 이슈.

    Backend-agnostic: works with Strata, llama.cpp, Ollama, or any OpenAI-compatible
    server (`/v1/chat/completions`). Override via NURI_LLM_LOCAL_URL.

    `trust_env=False` (`--local-only`): `HTTP_PROXY` / `ALL_PROXY` 를 무시한다. requests 는
    loopback 요청도 환경 프록시로 보내므로, 그대로 두면 loopback 검사를 통과한 prompt 가
    프록시를 거쳐 기기 밖으로 나간다. 키별 `None` override 는 `all` 같은 키를 놓쳐 쓰지 않는다.
    """
    post = requests.post
    if not trust_env:
        session = requests.Session()
        session.trust_env = False
        post = session.post
    resp = post(
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
    resp.raise_for_status()
    result = resp.json()
    msg = result["choices"][0]["message"]
    raw_content = (msg.get("content") or "").strip()
    # llama.cpp surfaces a `reasoning_content` field; some servers inline reasoning
    # into `content` instead. Strip <think>...</think> blocks if present so the
    # archived verdict stays clean across backends.
    stripped_inline = _THINK_BLOCK_RE.sub("", raw_content).strip()
    reasoning_inline = "\n".join(_THINK_BLOCK_RE.findall(raw_content)).strip()
    reasoning_field = (msg.get("reasoning_content") or "").strip()
    reasoning = reasoning_inline or reasoning_field
    content = stripped_inline
    finish = result["choices"][0].get("finish_reason")
    usage = result.get("usage", {})
    return {
        "ok": resp.status_code == 200 and bool(content) and finish == "stop",
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
                f"## Codex ({CODEX_MODEL})",
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
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="private context: local model only, refuse unless the local URL is loopback",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("data/llm_consults"))
    args = parser.parse_args()

    if args.codex_only and (args.qwen_only or args.local_only):
        parser.error("--codex-only excludes --qwen-only / --local-only")
    if args.local_only:
        if not is_loopback_url(LOCAL_URL):
            # URL 은 찍지 않는다 — env 값이 로그·Discord 로 새지 않게
            print("refused: --local-only requires a loopback local LLM URL (NURI_LLM_LOCAL_URL)", file=sys.stderr)
            return 2
        args.qwen_only = True

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
        qwen_future = None if args.codex_only else ex.submit(consult_qwen, prompt, trust_env=not args.local_only)
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
    return 0 if all(r["ok"] for r in (codex_result, qwen_result) if r is not None) else 1


if __name__ == "__main__":
    sys.exit(main())
