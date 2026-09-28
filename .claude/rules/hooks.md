---
paths:
  - ".claude/settings.json"
  - "scripts/hooks/**"
---

# Hook Authoring (path-scoped)

`enforcement.md` 에서 옮겨왔다 (2026-09-28 /doctor). 훅 명령을 쓰거나 고칠 때 먼저 읽는다.

⚠️ 훅 안에서 stdin payload 를 다시 뱉을 땐 **`printf '%s' "$INPUT"` 만** — `echo` 금지.
macOS `/bin/sh` 는 `xpg_echo` 가 켜진 bash 3.2 라 `echo` 가 **JSON 안의 `\n` 을 실제
개행으로 펼친다**. `new_string` 은 거의 항상 여러 줄이므로 JSON 이 깨지고 → jq 실패 →
변수 공백 → 가드가 **exit 0 으로 통과**한다. 차단이 아니라 침묵이라 아무 신호가 없다:
이 한 단어 때문에 sqlite3 / privacy 훅 2개가 #229(2026-04-13)부터 **3.5개월간 무력**이었고,
그동안 이 문서의 "blocks" 문장은 거짓이었다 (2026-07-29 `/doctor` 발견). 나머지 훅 3개는
stdin 을 jq 로 직접 파이프해 왕복이 없어 영향 없었다.
같은 이유로 훅 본문은 **POSIX sh 만** 쓴다 — `[[ ]]` 는 dash 에서 조건절째 죽어 또 조용히
exit 0 이 된다. 파일 매칭은 `case ... in` 으로. (macOS `/bin/sh` 는 bash 라 로컬에선 안 터지고
Linux 에서만 터진다.)
**Test:** `tests/test_hook_guard_execution.py` — 훅 명령을 grep 하지 않고 **셸로 실행**해 exit
code 를 본다(위반 2 / 허용 0). 셸 2종을 돌린다: `bash -O xpg_echo`(macOS `/bin/sh` 등가 —
`echo` 회귀 축)와 `dash`(bashism 축). 카나리아는 *개행을 품은* payload 다 — 단행 payload 는
`echo` 로도 살아남아 회귀가 조용히 통과한다. mutation 실측: `printf`→`echo` 4 FAIL,
`case`→`[[ ]]` 3 FAIL, 단행 payload 는 양쪽 mutant 에서 PASS.
