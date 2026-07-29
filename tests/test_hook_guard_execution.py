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


def _run(command: str, payload: dict) -> int:
    """훅을 **macOS `/bin/sh` 등가 셸** + stdin JSON 으로 실행.

    셸 선택이 이 테스트의 전부다. 세 후보 중 하나만 맞다:

    - `/bin/sh` — macOS 에선 정확하지만 **Linux 에선 dash** 라 훅의 `[[ ]]` 가
      죽어 조건절이 통째로 건너뛰어진다. CI 에서 rc=0 이 나와 "가드 무력"으로
      오판한다 (2026-07-29 PR #954 에서 실제로 밟았다).
    - `bash` — `[[` 는 되지만 `echo` 가 이스케이프를 **안** 펼친다. 그래서
      `printf`→`echo` 회귀가 **통과해버린다** — mutation 검출력이 0 이 된다.
    - `bash -O xpg_echo` — 둘 다 만족. macOS `/bin/sh` 는 xpg_echo 가 켜진
      bash 이므로 이게 등가이고, 플랫폼과 무관하게 결정론적이다.
    """
    proc = subprocess.run(
        ["/bin/bash", "-O", "xpg_echo", "-c", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return proc.returncode


pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="훅이 jq 에 의존 — 미설치 환경에선 판정 불가")


class TestSqlite3ImportGuard:
    """`import sqlite3` 를 nuri/ 편집에서 차단 (invariants.md DB sole importer)."""

    @pytest.fixture(scope="class")
    def command(self) -> str:
        return _hook_command("sqlite3 import guard...")

    def test_blocks_import_in_nuri_module(self, command):
        rc = _run(
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/nuri/analysis/foo.py", "new_string": "import sqlite3"}},
        )
        assert rc == 2, "nuri/ 안의 `import sqlite3` 가 안 막혔다 — 가드가 무력하다"

    def test_blocks_when_payload_contains_newlines(self, command):
        r"""원래 버그의 카나리아 — `echo` 가 `\n` 을 펼쳐 JSON 을 깨뜨렸다.

        위 단행 테스트만으로는 부족하다: 개행 없는 payload 는 `echo` 로도 살아남아
        회귀가 조용히 통과한다. 실제 편집은 거의 항상 여러 줄이다.
        """
        content = 'import os\nimport sqlite3\n\ndef f():\n    return "tab\there"\n'
        rc = _run(
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/nuri/analysis/foo.py", "new_string": content}},
        )
        assert rc == 2, "여러 줄 payload 에서 가드가 통과했다 — `echo` 회귀 (2026-07-29 실측 형태)"

    def test_allows_the_sole_importer(self, command):
        rc = _run(
            command,
            {
                "tool_input": {
                    "file_path": f"{REPO_ROOT}/nuri/core/db/connection.py",
                    "new_string": "import sqlite3\n",
                }
            },
        )
        assert rc == 0, "유일한 허용 모듈이 차단됐다"

    def test_allows_non_nuri_file(self, command):
        rc = _run(
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

    def test_blocks_ticker_pnl_across_newlines(self, command):
        """개행 포함 — 이게 `echo` 회귀를 잡는 축이다."""
        ticker = "TS" + "LA"  # 리터럴 금지 — 위 docstring ⚠️ 참조
        content = f"## holdings\n\n- {ticker} +47.3%\n"
        rc = _run(command, {"tool_input": {"file_path": f"{REPO_ROOT}/docs/x.md", "new_string": content}})
        assert rc == 2, "ticker+PnL 조합이 안 막혔다 — privacy 가드가 무력하다"

    def test_allows_clean_content(self, command):
        rc = _run(
            command,
            {"tool_input": {"file_path": f"{REPO_ROOT}/docs/x.md", "new_string": "# 제목\n\n평범한 문장.\n"}},
        )
        assert rc == 0, "무해한 내용이 차단됐다 — 오탐"
