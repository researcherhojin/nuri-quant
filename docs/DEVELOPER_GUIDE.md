# Developer Experience Guide

세션 중 반복되던 시간 낭비 패턴을 줄이기 위한 4개 script 와 PR template 을 정리한다. 도입 당시 약 120분의 누적 낭비를 기준으로 만든 도구다.

## TL;DR — 매 push 전

```bash
bash scripts/verify/pre_push_check.sh           # full (106s)
bash scripts/verify/pre_push_check.sh --quick   # smoke (6s)
```

`pre_push_check.sh` 는 drift, lint(ruff · shellcheck), doc count, spellcheck, pyright(변경 라인), 테스트, privacy scan, commit message 형식을 한 번에 검사한다. 아래 4개 패턴 중 앞의 3개를 이 명령이 잡고, atomicity 는 `check_atomic.sh` 를 따로 실행해야 한다.

| 패턴 | Detection | 미감지 시 비용 |
|---|---|---|
| Drift bug (working tree ≠ committed) | `check_drift.py --strict` | CI roundtrip 1회 ≈ 3 min |
| Lint stale config | `ruff check` (미커밋 `pyproject.toml` 은 drift check 가 감지) | CI roundtrip 1회 ≈ 3 min |
| Test isolation flake | `pytest -n auto` (CI 는 fast shard 에서 `-n 8`, #1414) | CI roundtrip 1+ 회 |
| Atomicity violation | `check_atomic.sh` (multi-commit, 별도 실행) | reset + re-stage cycle |

## 4 scripts + 1 PR template

| Script | 역할 | Quick mode |
|---|---|---|
| `scripts/dev/ci_local.sh` | CI parity (`ruff check` + `pytest -n auto --cov`) | `--quick` (6.4s), `--lint` (0.05s) |
| `scripts/verify/check_drift.py` | uncommitted 파일과 committed 파일 간 의존성 분석. 0 / 1-5 / 6-20 / >20 severity band. | `--strict` (exit 1), `--silent` |
| `scripts/verify/pre_push_check.sh` | drift + lint + doc count + tests + privacy + commit format 일괄 | `--quick`, `--skip-tests` |
| `scripts/verify/check_atomic.sh` | multi-commit branch 의 각 commit 을 독립 검증 (기본 범위 `origin/main..HEAD`) | `HEAD~3..HEAD` 같은 range 인자 |
| `.github/pull_request_template.md` | PR 생성 시 자동으로 채워지는 체크리스트 (drift · atomicity · scope) | — |

## git hook 설치

```bash
make setup-hooks     # `make setup` 에 포함 — pre-commit + pre-push 심볼릭 링크
```

`scripts/hooks/*` 를 `.git/hooks/` 에 심볼릭 링크로 설치한다(`scripts/dev/install_hooks.sh`). 훅 본문이 레포에 있으므로 갱신은 `git pull` 로 반영된다. 우회는 `git push --no-verify`.

`.git/hooks/pre-push` 를 손으로 만들지 않는다. 수동 설치는 새 clone 에 따라오지 않는다(#1070).

## Anti-patterns (5)

1. **Working tree drift accumulation**: 여러 세션에 걸쳐 uncommitted 파일이 20개 이상 쌓이면 CI 는 commit 만 보고 실패한다. **Fix**: 세션 시작 시 `python scripts/verify/check_drift.py`.
2. **Atomic commit violation**: commit 1 만으로는 suite 가 깨지고 commit 2-3 이 빠진 부분을 채우면 bisect 가 깨진다. **Fix**: 최종 push 전 `bash scripts/verify/check_atomic.sh`.
3. **CI roundtrip debugging**: push → 3분 대기 → 실패 → 수정의 반복. **Fix**: push 전 `bash scripts/dev/ci_local.sh`.
4. **Scope creep**: "fix X" 가 "fix X + refactor Y + cleanup Z" 로 커진다. **Fix**: 1 PR = 1 issue, ≤ 3 commits. 새 발견은 새 branch 로.
5. **Environment-only failures** (Linux CI vs macOS local): **Mitigation**: 로컬에서도 `pytest -n auto`, `tests/conftest.py` 의 `journal_mode=MEMORY` (PR #93), integration test 는 explicit fixture 사용.

## 이전 세션 ~120 min 낭비 매핑

| Category | Wasted | Tool |
|---|---|---|
| Drift bugs (2× hits) | ~30 min | `check_drift.py` + `pre_push_check.sh` |
| Linux-only test pollution | ~25 min | `ci_local.sh` (parallelism parity) |
| CI roundtrip waiting | ~15 min | `ci_local.sh` (catches locally) |
| Atomicity reset | ~10 min | `check_atomic.sh` |
| Scope accumulation | ~40 min | PR template + `check_drift.py` |
| **Total addressable** | **~120 min** | **4 scripts + 1 PR template** |

## Overview Preview 유지보수

별도 비교 화면 `/dashboard-next`의 구성, API 계약, 데이터 갱신 방법, 포트폴리오 평가와 반응형 검증은 [Overview Preview 구현 및 운영 안내](DASHBOARD_NEXT.md)에 정리되어 있다. 새 데이터 갱신 API는 백그라운드 수집·재계산을 수행하며 판정 원장 작업은 실행하지 않는다.
