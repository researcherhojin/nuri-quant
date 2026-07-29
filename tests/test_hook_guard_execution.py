r"""PreToolUse 훅이 **실제로 차단하는지** 실행으로 검증 (Gotcha-Test Pair).

2026-07-29 실측: `.claude/settings.json` 의 sqlite3 / privacy 훅 2개가 도입
(#229, 2026-04-13) 이래 3.5개월간 **무력**이었다. 원인은 등가로 보이는 한 단어:

    INPUT=$(cat); FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path')

macOS `/bin/sh` 는 `xpg_echo` 가 켜진 bash 3.2 다 — `echo` 가 **JSON 안의 `\n`
이스케이프를 실제 개행으로 펼친다**. 훅 payload 의 `new_string` 은 거의 항상 개행을
품으므로 JSON 이 깨지고, jq 가 실패하고, `$FILE` 이 빈 문자열이 되고, 가드는
**exit 0 으로 통과**한다. 차단이 아니라 침묵이다 — `.claude/rules/enforcement.md`
가 "PreToolUse hook blocks ..." 라고 적어둔 내내 아무것도 안 막고 있었다.

`printf '%s'` 는 이스케이프를 해석하지 않는다. 그게 유일한 수정이고, 그래서
누군가 "`echo` 랑 같잖아" 하며 되돌리기 쉽다. 이 테스트가 그걸 막는다.

훅을 **문자열로 grep 하지 않고 셸로 실행**한다 — grep 은 `printf` 존재만 보고
"통과"라 말하지만, 파이프라인이 다른 이유로 깨져도 똑같이 통과한다 (#910 의 rc=127
= 실패와 구분 불가 교훈). 여기서 유일하게 믿는 신호는 **exit code** 다.

세 축을 다 잠근다:
- 위반 → exit 2 (차단이 실제로 발화)
- 허용 파일 → exit 0 (오탐 없음 — 이게 없으면 "전부 차단"도 통과한다)
- **개행을 품은 payload → 여전히 exit 2** (원래 버그의 카나리아)

⚠️ privacy 픽스처는 ticker 를 **런타임 조립**한다. 리터럴로 적으면 이 파일을
저장하는 순간 privacy 훅과 CI `privacy-scan` 이 자기 자신을 차단한다 (실제로 그렇게
막혔다 — 가드가 살아있다는 증거이기도 하다).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def _hook_command(status_message: str) -> str:
    """settings.json 에서 statusMessage 로 훅 명령 1개를 집어온다."""
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    for matcher in data["hooks"]["PreToolUse"]:
        for hook in matcher["hooks"]:
            if hook.get("statusMessage") == status_message:
                return hook["command"]
    raise AssertionError(
        f"PreToolUse 훅 {status_message!r} 를 못 찾았다 — settings.json 이 바뀌었으면 이 테스트를 갱신할 것"
    )


# 훅이 돌아야 하는 셸 두 종. 하나만으로는 각각 다른 실패를 못 본다.
#
# - `bash -O xpg_echo` — macOS `/bin/sh` 등가(이스케이프 펼치는 echo + `[[` 지원).
#   `echo` 회귀(원래 버그)를 잡는 축. 평범한 `bash` 로 돌리면 escape 가 안 펼쳐져
#   **mutation 검출력이 0** 이 된다.
# - dash — bashism(`[[ ]]`) 을 잡는 축. dash 는 `[[` 를 모르므로 조건절이 통째로
#   죽고 훅이 조용히 exit 0 한다 — 차단 실패와 구분되지 않는다 (PR #954 1차 푸시에서
#   Linux CI 가 실제로 이걸 뱉었다). **`/bin/sh` 를 쓰면 안 된다**: Linux 에선 dash
#   지만 macOS 에선 bash 라, 개발 머신에서 이 축이 조용히 no-op 이 되고 bashism 회귀가
#   로컬 green 인 채 CI 에서만 터진다. dash 를 명시하면 양쪽에서 같은 걸 본다.
_POSIX_SH = shutil.which("dash") or "/bin/sh"

_SHELLS = [
    pytest.param(["/bin/bash", "-O", "xpg_echo", "-c"], id="macos-sh-equivalent"),
    pytest.param([_POSIX_SH, "-c"], id="posix-sh"),
]


def _run(shell: list[str], command: str, payload: dict) -> int:
    proc = subprocess.run(
        [*shell, command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return proc.returncode


pytestmark = [
    pytest.mark.skipif(shutil.which("jq") is None, reason="훅이 jq 에 의존 — 미설치 환경에선 판정 불가"),
    pytest.mark.parametrize("shell", _SHELLS),
]


class TestSqlite3ImportGuard:
    """`import sqlite3` 를 nuri/ 편집에서 차단 (invariants.md DB sole importer)."""

    @pytest.fixture(scope="class")
    def command(self) -> str:
        return _hook_command("sqlite3 import guard...")

    def test_blocks_import_in_nuri_module(self, shell, command):
        rc = _run(
            shell,
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/nuri/analysis/foo.py", "new_string": "import sqlite3"}},
        )
        assert rc == 2, "nuri/ 안의 `import sqlite3` 가 안 막혔다 — 가드가 무력하다"

    def test_blocks_when_payload_contains_newlines(self, shell, command):
        r"""원래 버그의 카나리아 — `echo` 가 `\n` 을 펼쳐 JSON 을 깨뜨렸다.

        위 단행 테스트만으로는 부족하다: 개행 없는 payload 는 `echo` 로도 살아남아
        회귀가 조용히 통과한다. 실제 편집은 거의 항상 여러 줄이다.
        """
        content = 'import os\nimport sqlite3\n\ndef f():\n    return "tab\there"\n'
        rc = _run(
            shell,
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/nuri/analysis/foo.py", "new_string": content}},
        )
        assert rc == 2, "여러 줄 payload 에서 가드가 통과했다 — `echo` 회귀 (2026-07-29 실측 형태)"

    def test_allows_the_sole_importer(self, shell, command):
        rc = _run(
            shell,
            command,
            {
                "tool_input": {
                    "file_path": f"{REPO_ROOT}/nuri/core/db/connection.py",
                    "new_string": "import sqlite3\n",
                }
            },
        )
        assert rc == 0, "유일한 허용 모듈이 차단됐다"

    def test_allows_non_nuri_file(self, shell, command):
        rc = _run(
            shell,
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/scripts/ops/x.py", "new_string": "import sqlite3\n"}},
        )
        assert rc == 0, "nuri/ 밖 파일까지 차단하면 오탐이다"


class TestPrivacyGuard:
    """ticker+PnL 인라인 작성을 차단 (STRATEGY §4.4.1, PR #202 시그니처)."""

    @pytest.fixture(scope="class")
    def command(self) -> str:
        return _hook_command("privacy ticker+pnl check...")

    @pytest.fixture(autouse=True)
    def _needs_venv(self):
        # 훅 자체가 .venv 부재 시 exit 0 으로 빠진다 — skip 하지 않으면 조용한 통과가 된다
        if not (REPO_ROOT / ".venv" / "bin" / "python").exists():
            pytest.skip(".venv 부재 — 훅이 no-op 로 빠져 판정 불가")

    def test_blocks_ticker_pnl_across_newlines(self, shell, command):
        """개행 포함 — 이게 `echo` 회귀를 잡는 축이다."""
        ticker = "TS" + "LA"  # 리터럴 금지 — 위 docstring ⚠️ 참조
        content = f"## holdings\n\n- {ticker} +47.3%\n"
        rc = _run(shell, command, {"tool_input": {"file_path": f"{REPO_ROOT}/docs/x.md", "new_string": content}})
        assert rc == 2, "ticker+PnL 조합이 안 막혔다 — privacy 가드가 무력하다"

    def test_allows_clean_content(self, shell, command):
        rc = _run(
            shell,
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/docs/x.md", "new_string": "# 제목\n\n평범한 문장.\n"}},
        )
        assert rc == 0, "무해한 내용이 차단됐다 — 오탐"
