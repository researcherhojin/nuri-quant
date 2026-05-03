"""Tests for scripts/dev/agent_loop.py — orchestrator skeleton (#578).

Network-free: subprocess (gh issue view) + LLM consult helpers 모두 mock.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/dev/ 는 패키지가 아니라 직접 import.
SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts" / "dev"
sys.path.insert(0, str(SCRIPT_DIR))

spec = importlib.util.spec_from_file_location("agent_loop", SCRIPT_DIR / "agent_loop.py")
assert spec is not None and spec.loader is not None
agent_loop = importlib.util.module_from_spec(spec)
sys.modules["agent_loop"] = agent_loop  # @dataclass 가 cls.__module__ lookup 함 — 사전 등록 필요
spec.loader.exec_module(agent_loop)


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "agent_loop"


def _mock_subprocess_gh(title="Test issue", body="Fix the foo when bar."):
    """gh issue view --json mock — agent_loop.fetch_issue_body 가 호출."""
    proc = MagicMock()
    proc.stdout = json.dumps({"title": title, "body": body})
    return proc


def test_run_loop_writes_artifacts_with_token_and_usd(out_dir):
    """정상 path: spec/patch/review/cost.json 생성, cost.json 에 token + USD 모두 기록."""
    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": True, "verdict": "spec contents", "stderr": ""},
        ),
        patch(
            "agent_loop.consult_qwen",
            return_value={
                "ok": True,
                "verdict": "review verdict: PASS",
                "tokens_out": 200,
            },
        ),
        patch("agent_loop.stage_agent_dev_log") as mock_dev_log,
        patch("agent_loop.stage_agent_control") as mock_hitl,
    ):
        rc = agent_loop.run_loop(issue_num=999, budget_tokens=100_000, budget_usd=1.0, out_root=out_dir)

    assert rc == 0
    issue_dir = out_dir / "999"
    assert (issue_dir / "spec.md").read_text() == "spec contents"
    assert "TODO E2 #578" in (issue_dir / "patch.diff").read_text()
    assert "PASS" in (issue_dir / "review.md").read_text()
    cost = json.loads((issue_dir / "cost.json").read_text())
    assert cost["used_tokens"] > 0
    assert cost["used_usd"] >= 0  # local Qwen 만이면 0 가능; Codex out 은 비용 발생
    assert "step1_codex_in" in cost["by_step_tokens"]
    assert "step1_codex_out" in cost["by_step_usd"]
    # Codex output 가격 적용 확인 ($15.00/M tokens — agent_loop.CODEX_OUTPUT_USD_PER_M 와 동기)
    assert cost["by_step_usd"]["step1_codex_out"] > 0
    # E1 #582 — Discord stage 호출 검증.
    # spec / patch / review 3 단계 #agent-dev-log 에 stage.
    assert mock_dev_log.call_count == 3
    kinds = {call.kwargs["payload"]["kind"] for call in mock_dev_log.call_args_list}
    assert kinds == {"spec", "patch", "review"}
    # HITL gate (verdict=PASS) #agent-control 에 stage.
    assert mock_hitl.call_count == 1
    hitl_payload = mock_hitl.call_args.kwargs["payload"]
    assert hitl_payload["verdict"] == "PASS"
    assert hitl_payload["issue"] == 999


def test_budget_tokens_exceeded_aborts_before_qwen(out_dir):
    """token budget 초과 시 step3 skip, rc=2."""
    huge_spec = "x" * 200_000

    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": True, "verdict": huge_spec, "stderr": ""},
        ),
        patch("agent_loop.consult_qwen") as mock_qwen,
    ):
        rc = agent_loop.main(
            ["--issue", "999", "--budget-tokens", "5000", "--budget-usd", "100", "--out-dir", str(out_dir)]
        )

    mock_qwen.assert_not_called()
    assert rc == 2


def test_budget_usd_exceeded_aborts(out_dir):
    """USD budget 가 token 보다 먼저 초과될 때도 rc=2."""
    big_codex_out = "x" * 50_000  # ~25k tokens proxy → step1_codex_out 비용 ~$0.25

    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": True, "verdict": big_codex_out, "stderr": ""},
        ),
        patch("agent_loop.consult_qwen") as mock_qwen,
    ):
        rc = agent_loop.main(
            [
                "--issue",
                "999",
                "--budget-tokens",
                "10_000_000",
                "--budget-usd",
                "0.05",
                "--out-dir",
                str(out_dir),
            ]
        )

    mock_qwen.assert_not_called()
    assert rc == 2


def test_codex_failure_returns_rc_1(out_dir):
    """Codex 가 ok=False 반환하면 step3 skip, rc=1."""
    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": False, "verdict": "", "stderr": "auth error"},
        ),
        patch("agent_loop.consult_qwen") as mock_qwen,
    ):
        rc = agent_loop.run_loop(issue_num=999, budget_tokens=100_000, budget_usd=1.0, out_root=out_dir)

    mock_qwen.assert_not_called()
    assert rc == 1


def test_dependency_error_returns_rc_3(out_dir):
    """gh issue view CalledProcessError → rc=3, traceback 노출 안 됨."""
    with patch(
        "agent_loop.subprocess.run",
        side_effect=subprocess.CalledProcessError(returncode=1, cmd=["gh"], stderr="not found"),
    ):
        rc = agent_loop.main(["--issue", "999", "--out-dir", str(out_dir)])
    assert rc == 3


def test_qwen_transport_error_returns_rc_3(out_dir):
    """consult_qwen 이 RequestException raise → rc=3."""
    import requests

    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": True, "verdict": "spec ok", "stderr": ""},
        ),
        patch("agent_loop.consult_qwen", side_effect=requests.ConnectionError("server down")),
    ):
        rc = agent_loop.main(["--issue", "999", "--budget-usd", "10", "--out-dir", str(out_dir)])
    assert rc == 3


def test_gh_binary_missing_returns_rc_3(out_dir):
    """gh CLI 미설치 시 FileNotFoundError → rc=3 (Codex Round 3)."""
    with patch("agent_loop.subprocess.run", side_effect=FileNotFoundError("gh: not found")):
        rc = agent_loop.main(["--issue", "999", "--out-dir", str(out_dir)])
    assert rc == 3


def test_codex_subprocess_timeout_returns_rc_3(out_dir):
    """consult_codex 가 subprocess.TimeoutExpired raise → rc=3 (Codex Round 3).

    subprocess.TimeoutExpired 는 built-in TimeoutError 상속 안 함 — 별도 catch 필요."""
    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=600),
        ),
    ):
        rc = agent_loop.main(["--issue", "999", "--out-dir", str(out_dir)])
    assert rc == 3


def test_filesystem_write_permission_error_returns_rc_3(out_dir):
    """out_dir write 가 PermissionError raise → rc=3 (Codex Round 4).

    --out-dir 가 public CLI input 이라 unwritable 케이스 cover 필요."""
    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch(
            "agent_loop.consult_codex",
            return_value={"ok": True, "verdict": "spec ok", "stderr": ""},
        ),
        patch.object(Path, "write_text", side_effect=PermissionError("denied")),
    ):
        rc = agent_loop.main(["--issue", "999", "--out-dir", str(out_dir)])
    assert rc == 3


def test_estimate_tokens_proxy_basic():
    # 2 char ≈ 1 token mitigation proxy. Mitigation 이지 hard upper bound 아님.
    assert agent_loop.estimate_tokens("") == 1
    assert agent_loop.estimate_tokens("x" * 2) == 1
    assert agent_loop.estimate_tokens("x" * 200) == 100


def test_estimate_tokens_korean_input():
    # 한국어 + Markdown 혼합 sample 이 nonzero + len/2 에 일치하는지.
    # 실제 tokenizer 와는 다를 수 있어 정확도 보장 안 함 — proxy 동작만 검증.
    sample = "## 한국어 prompt 예시\n- 항목 하나\n- 항목 둘"
    estimated = agent_loop.estimate_tokens(sample)
    assert estimated == max(1, len(sample) // 2)
    assert estimated > 1


def test_programmer_bug_propagates_not_swallowed(out_dir):
    """rc=3 catch tuple 이 narrow — KeyError 같은 programmer bug 는 propagate.
    swallow 하면 디버깅이 어려워짐 (Codex Round 2 #2)."""
    with (
        patch("agent_loop.subprocess.run", return_value=_mock_subprocess_gh()),
        patch("agent_loop.consult_codex", side_effect=KeyError("missing_field")),
    ):
        with pytest.raises(KeyError):
            agent_loop.main(["--issue", "999", "--out-dir", str(out_dir)])


def test_codex_pricing_constants_match_openai_2026_05():
    """Pricing constant 가 GPT-5.4 공식가 (2026-05-03) 와 일치.
    가격 변경 시 본 테스트 + 상수 + 주석 동기 갱신 (Codex Round 2 #1)."""
    assert agent_loop.CODEX_INPUT_USD_PER_M == 2.50
    assert agent_loop.CODEX_OUTPUT_USD_PER_M == 15.00
    assert agent_loop.QWEN_USD_PER_M == 0.0
