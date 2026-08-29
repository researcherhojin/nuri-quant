"""Maintenance-Auditor — 유지보수 백로그 발굴 루프, shadow mode (#1308 Phase 0).

## 무엇을 하고, 무엇을 절대 안 하나

지금까지 시스템 결함은 전부 사람이 수동 감사로 찾았다 (sqlite3 밀수입 · 훅 3.5개월
무력 · e2e 3.5개월 무신호 · 자동화 parity gap). 이 actor 는 그 발굴을 주간 루프로
만들되, 산출물은 **로컬 maintenance_candidates 원장에만** 남긴다:

- **GitHub 쓰기 0건** — gh 호출도, GitHub API 엔드포인트 참조도, HTTP 클라이언트 import 도 없다.
  자동 이슈 발행은 "proposal-only" 가 아니라 외부 쓰기다. (잠금: 구조 스윕 + 런타임 spy)
- **LLM 0** — 5축 전부 결정론적 검사다. USD 캡은 0 으로 존재한다 — 캡 플럼빙이
  있어야 Phase 1 에서 LLM 이 붙을 때 상한 없이 붙는 사고를 막는다.
- **전략·투자 룰(config 의 rules/agents/signals 계열)은 대상 밖** — #1307 champion-challenger 전용.
- 건수 목표 없음 (Goodhart) — 정직한 0건 run 이 저품질 5건보다 낫다. 지표는
  precision·novelty·검토 시간 (`maintenance_review_stats`).

## 하드 상한 4종 — 초과 시 그 자리에서 스캔 중단, outcome WARN

wall-clock · subprocess 호출 수 · 후보 staging 수 · USD. 이미 staged 된 행은 남는다
(원장은 durable). 어느 캡이 끊었는지 output 에 기록한다 — 조용한 절단은 절단이 아니라
거짓말이다.

## Privacy — 후보 생성 **전** 스캔

모든 후보의 title+detail 이 staging 전에 **전 범주** `gate_text` (broker명·의심
금액·ticker+PnL — `--message` CLI 모드는 마지막 것만 봐서 못 쓴다)를 통과해야 한다.
걸리면 원장에는 **아무것도** 남기지 않는다 — stub 후보는 precision/novelty 를
오염시킨다. 사건 자체는 output 의 `privacy_blocked` 카운터로 audit ledger 에
영속된다 (조용한 드롭 아님). 게이트 불능은 차단으로 취급한다 (fail-closed).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from nuri.agents.base import REGISTRY, Actor, ActorResult, Layer, Outcome, RunContext

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]


#: 재검출 판정 축 — fingerprint 는 axis+title 로만 만든다. detail 에는 날짜/카운트가
#: 들어가므로 fingerprint 에 섞으면 같은 발견이 매주 "새 후보" 가 된다 (novelty 오염).
def _fingerprint(axis: str, title: str) -> str:
    return hashlib.sha256(f"{axis}|{title}".encode()).hexdigest()[:16]


class CapExceeded(Exception):
    """하드 상한 초과 — 스캔 루프가 잡아서 중단 + WARN 으로 바꾼다."""

    def __init__(self, cap: str) -> None:
        self.cap = cap
        super().__init__(cap)


@dataclass
class AuditCaps:
    """하드 상한 — 이슈 본문의 4축. 값 조정은 리뷰 대상 (완화가 곧 반경 확대다)."""

    wall_clock_s: float = 120.0
    subprocess_calls: int = 16
    candidates: int = 20
    usd: float = 0.0  # Phase 0 은 LLM 0 — 0 초과는 곧 설계 위반이다


@dataclass
class _CapTracker:
    caps: AuditCaps
    started: float = field(default_factory=time.monotonic)
    subprocess_used: int = 0
    candidates_staged: int = 0
    usd_spent: float = 0.0

    def check_wall_clock(self) -> None:
        if time.monotonic() - self.started > self.caps.wall_clock_s:
            raise CapExceeded("wall_clock")

    def charge_subprocess(self) -> None:
        self.subprocess_used += 1
        if self.subprocess_used > self.caps.subprocess_calls:
            raise CapExceeded("subprocess_calls")

    def charge_candidate(self) -> None:
        self.candidates_staged += 1
        if self.candidates_staged > self.caps.candidates:
            raise CapExceeded("candidates")

    def charge_usd(self, amount: float) -> None:
        self.usd_spent += amount
        if self.usd_spent > self.caps.usd:
            raise CapExceeded("usd")


@dataclass
class ScanContext:
    """스캐너에 주입되는 실행 환경 — subprocess 는 반드시 이 helper 를 탄다 (캡 계상)."""

    repo_root: Path
    tracker: _CapTracker
    db_path: Optional[Path] = None

    def run(
        self, argv: list[str], timeout: float = 30.0, stdin_text: Optional[str] = None
    ) -> subprocess.CompletedProcess[str]:
        """캡 계상 subprocess — timeout 이 **남은 wall-clock 예산으로 잘린다**.

        "단계 사이 검사" 만으로는 단일 subprocess 하나가 예산 전체를 태울 수 있다
        (codex plan 리뷰 5). 예산은 실행 **전에** 차감·강제한다.
        """
        remaining = self.tracker.caps.wall_clock_s - (time.monotonic() - self.tracker.started)
        if remaining <= 0:
            raise CapExceeded("wall_clock")
        self.tracker.charge_subprocess()
        try:
            return subprocess.run(
                argv,
                cwd=self.repo_root,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=min(timeout, remaining),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CapExceeded("wall_clock") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 스캔 축 5종 — 전부 결정론. 각자는 (axis, title, detail) dict 목록을 낸다.
# title 은 **안정적**이어야 한다 (fingerprint 축) — 날짜·카운트는 detail 로.
# ─────────────────────────────────────────────────────────────────────────────


def scan_gate_liveness(ctx: ScanContext) -> list[dict[str, str]]:
    """설치된 git 훅의 생존 — absent gate (#1070) / broken symlink / 실행권 부재.

    grep 이 아니라 파일계 사실 + `bash -n` 문법 검사만 본다. 게이트 **실행** 잠금은
    tests/test_pre_push_hook.py 계열의 몫 — 여기는 "설치가 사라졌다" 를 잡는 축이다.
    """
    out: list[dict[str, str]] = []
    hooks_dir = ctx.repo_root / ".git" / "hooks"
    for hook in ("pre-push", "pre-commit"):
        installed = hooks_dir / hook
        source = ctx.repo_root / "scripts" / "hooks" / hook
        if not source.exists():
            out.append(
                {
                    "axis": "gate_liveness",
                    "title": f"훅 소스 부재: scripts/hooks/{hook}",
                    "detail": "설치기가 심을 파일이 없다 — #1070 absent-gate 그 자체.",
                }
            )
            continue
        if not installed.exists():
            out.append(
                {
                    "axis": "gate_liveness",
                    "title": f"훅 미설치: .git/hooks/{hook}",
                    "detail": "소스는 있으나 설치돼 있지 않다. `make setup-hooks` 미실행 또는 링크 파손.",
                }
            )
            continue
        rc = ctx.run(["bash", "-n", str(source)])
        if rc.returncode != 0:
            out.append(
                {
                    "axis": "gate_liveness",
                    "title": f"훅 문법 오류: scripts/hooks/{hook}",
                    "detail": f"bash -n rc={rc.returncode}: {rc.stderr.strip()[:300]}",
                }
            )
    gate = ctx.repo_root / "scripts" / "verify" / "pre_push_check.sh"
    if not gate.exists():
        out.append(
            {
                "axis": "gate_liveness",
                "title": "게이트 스크립트 부재: scripts/verify/pre_push_check.sh",
                "detail": "훅이 정직하게 차단은 하겠지만 (--no-verify 안내) 게이트 자체가 없다.",
            }
        )
    return out


def scan_doc_drift(ctx: ScanContext) -> list[dict[str, str]]:
    """doc↔code 카운트 드리프트 — red 뿐 아니라 **warn+exit0** 도 잡는다 (#1288 계열)."""
    rc = ctx.run(["bash", "scripts/verify/verify_doc_counts.sh"], timeout=60.0)
    out: list[dict[str, str]] = []
    if rc.returncode != 0:
        out.append(
            {
                "axis": "doc_drift",
                "title": "verify-doc-counts FAIL",
                "detail": (rc.stdout + rc.stderr).strip()[-500:],
            }
        )
    else:
        # warn 전부가 아니라 **죽은 검사 시그니처만** — 스크립트의 warn 은
        # `pattern not found`(등록 문자열 유실) / `missing`(대상 파일 부재) 두 형태가
        # 검증 공백이고, 나머지 warn 은 benign 하다 (codex plan 리뷰 8).
        dead_check_lines = [
            line.strip()
            for line in (rc.stdout + rc.stderr).splitlines()
            if "pattern not found" in line or ("missing" in line and "warn" in line.lower())
        ]
        if dead_check_lines:
            out.append(
                {
                    "axis": "doc_drift",
                    "title": "verify-doc-counts 죽은 검사 (warn + exit 0)",
                    "detail": "게이트 초록인데 검증이 비어 있다 — #1288 계열 (등록 패턴 유실/파일 부재).\n"
                    + "\n".join(dead_check_lines[:5]),
                }
            )
    return out


#: `_run_collector` args ↔ Makefile 모듈명이 1:1 이 아닌 알려진 별칭.
#: 항목마다 사유 — 스캐너 오탐을 리뷰가 아니라 코드가 걸러야 하는 건 이 정도뿐이다.
#: 낡은 별칭은 스캐너가 **스스로 후보로 신고한다** (아래 self-check) — 손으로 유지하는
#: 진실 사본이 조용히 썩는 것이 이 레포의 반복 사고라서다 (codex plan 리뷰 4).
_COLLECTOR_ALIASES: dict[str, tuple[str, ...]] = {
    # 야간/새벽 두 슬롯이 같은 모듈을 돈다
    "stock": ("stock_us_night", "stock_us_dawn", "stock"),
}


def scan_scheduler_wiring(ctx: ScanContext) -> list[dict[str, str]]:
    """`make collect` 의 수집기 vs SCHEDULES 배선 대조 — #900 (몇 달간 무배선) 패턴.

    오탐 가능성을 안고 가는 축이다 — 의도된 수동 전용 수집기는 리뷰에서 reject 되고,
    그 기각률이 precision 지표에 그대로 잡힌다 (오탐이 비싸지면 스캐너를 고친다).
    """
    makefile = (ctx.repo_root / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^collect:\n((?:\t.*\n)+)", makefile, re.M)
    if not m:
        return [
            {
                "axis": "scheduler_wiring",
                "title": "Makefile collect: 타깃을 찾을 수 없음",
                "detail": "스캐너의 전제가 무너졌다 — collect 타깃 이름/형태 변경 여부 확인.",
            }
        ]
    cli_modules = set(re.findall(r"-m nuri\.collectors\.([a-z_]+)", m.group(1)))

    from nuri.scheduler import SCHEDULES, _run_collector

    scheduled = {s["args"][0] for s in SCHEDULES if s.get("func") is _run_collector and s.get("args")}

    out: list[dict[str, str]] = []
    # 별칭 self-check — 별칭이 현실과 어긋나면 그 자체가 후보다 (양방향 allowlist 원칙)
    for module, aliases in _COLLECTOR_ALIASES.items():
        if module not in cli_modules or not (scheduled & set(aliases)):
            out.append(
                {
                    "axis": "scheduler_wiring",
                    "title": f"수집기 별칭 낡음: {module}",
                    "detail": f"_COLLECTOR_ALIASES[{module!r}]={aliases} 가 Makefile/SCHEDULES 현실과 "
                    "안 맞는다 — 별칭 지도를 갱신할 것 (진실 사본은 썩는다).",
                }
            )

    covered = set(scheduled)
    for module, aliases in _COLLECTOR_ALIASES.items():
        if covered & set(aliases):
            covered.add(module)

    out.extend(
        {
            "axis": "scheduler_wiring",
            "title": f"collect CLI 에만 있는 수집기: {name}",
            "detail": "`make collect` 는 돌리는데 SCHEDULES 에 없다 — #900 계열 (수개월 무갱신, "
            "헬스는 초록). 의도된 수동 전용이면 reject 하고 사유를 남길 것.",
        }
        for name in sorted(cli_modules - covered)
    )
    return out


def scan_stale_collectors(ctx: ScanContext) -> list[dict[str, str]]:
    """SCHEDULES 에 배선된 수집기의 14일 무완주 — '배선됐지만 침묵' 축.

    ⚠️ 한계를 그대로 적는다 (codex plan 리뷰 3): `finished` 는 "run 이 끝났다" 이지
    "데이터가 건강하다" 가 아니다 — cboe/fear_greed 류는 stale/빈 fallback 으로도
    finished 로 끝난다. 이 축이 잡는 것은 **완주 자체가 멎은** #900 계열의 침묵이고,
    건강한-척-완주는 freshness 정책(#1071 계열)의 몫이다.

    DB 는 readonly 로 읽는다 (#1306 facade) — 감사가 감사 대상을 변형하면 안 된다.
    """
    from nuri.core.db import query
    from nuri.scheduler import SCHEDULES, _run_collector

    scheduled = sorted({s["args"][0] for s in SCHEDULES if s.get("func") is _run_collector and s.get("args")})
    rows = query(
        "SELECT collector_name, MAX(started_at) AS last_finished FROM collector_runs"
        " WHERE status = 'finished' GROUP BY collector_name",
        db_path=ctx.db_path,
        readonly=True,
    )
    if not rows:
        # 기록이 통째로 없다 = 수집기별 N건이 아니라 **전면 침묵 1건**이다 — 빈/신규
        # DB 에서 후보가 캡까지 범람하는 것을 실측하고 고쳤다 (dev replica 포함).
        return [
            {
                "axis": "stale_collector",
                "title": "collector_runs 에 finished 기록이 전혀 없음",
                "detail": f"배선된 수집기 {len(scheduled)}종 전부 완주 이력 0 — 신규/복제 DB 이거나 "
                "수집 계층 전면 정지. 개별 수집기 축은 기록이 생긴 뒤에야 의미가 있다.",
            }
        ]
    last_finished = {r["collector_name"]: r["last_finished"] for r in rows}

    from datetime import timedelta

    from nuri.core.timezone import kst_now

    threshold = (kst_now() - timedelta(days=14)).isoformat()
    out: list[dict[str, str]] = []
    for name in scheduled:
        seen = last_finished.get(name)
        if seen is None or seen < threshold:
            out.append(
                {
                    "axis": "stale_collector",
                    "title": f"수집기 14일 무완주: {name}",
                    "detail": f"마지막 finished: {seen or '기록 없음'} — 배선은 있으나 완주가 멎었다 "
                    "(#900 계열). finished≠건강 — 데이터 품질은 freshness 정책 축이다. "
                    "주 1회 수집기의 정상 리듬이면 reject 로 기록.",
                }
            )
    return out


def scan_dependency(ctx: ScanContext) -> list[dict[str, str]]:
    """uv.lock ↔ pyproject 드리프트 — `--frozen` 배포(deploy-mini step 5)를 깨는 축."""
    import shutil

    uv = shutil.which("uv") or ("/opt/homebrew/bin/uv" if Path("/opt/homebrew/bin/uv").exists() else None)
    if uv is None:
        return [
            {
                "axis": "dependency",
                "title": "uv 부재 — lock 드리프트 검사 미실행",
                "detail": "'깨끗함' 이 아니라 '미확인' 이다. PATH 를 확인할 것.",
            }
        ]
    rc = ctx.run([uv, "lock", "--check"], timeout=60.0)
    if rc.returncode != 0:
        return [
            {
                "axis": "dependency",
                "title": "uv.lock 이 pyproject 와 어긋남",
                "detail": "`uv lock --check` 실패 — deploy-mini 의 `uv sync --frozen` 이 깨진다.\n"
                + (rc.stdout + rc.stderr).strip()[-300:],
            }
        ]
    return []


SCANNERS: tuple[Callable[[ScanContext], list[dict[str, str]]], ...] = (
    scan_gate_liveness,
    scan_doc_drift,
    scan_scheduler_wiring,
    scan_stale_collectors,
    scan_dependency,
)


@REGISTRY.register
class MaintenanceAuditor(Actor):
    """주간 발굴 스캔 → 로컬 원장 staging. 발행은 언제나 사람."""

    name = "maintenance-auditor"
    version = "0.1.0"
    layer = Layer.B

    VALID_ACTIONS = ("scan", "list", "review", "stats")

    def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult:
        action = input_data.get("action", "scan")
        db_path = input_data.get("db_path")
        if action == "scan":
            return self._scan(input_data, ctx, db_path)
        if action == "list":
            from nuri.core.db import list_maintenance_candidates

            rows = list_maintenance_candidates(status=input_data.get("status"), db_path=db_path)
            return ActorResult(output={"candidates": rows}, outcome=Outcome.PASS, sample_n=len(rows))
        if action == "review":
            from nuri.core.db import review_maintenance_candidate

            ok = review_maintenance_candidate(
                int(input_data["id"]), input_data["verdict"], input_data.get("note"), db_path=db_path
            )
            return ActorResult(
                output={"reviewed": ok, "id": input_data["id"], "verdict": input_data["verdict"]},
                outcome=Outcome.PASS if ok else Outcome.WARN,
            )
        if action == "stats":
            from nuri.core.db import maintenance_review_stats

            return ActorResult(output=maintenance_review_stats(db_path=db_path), outcome=Outcome.PASS)
        return ActorResult(output={"error": f"unknown action {action!r}"}, outcome=Outcome.ERROR)

    # ── scan ────────────────────────────────────────────────────────────────

    def _scan(self, input_data: dict[str, Any], ctx: RunContext, db_path: Optional[Path]) -> ActorResult:
        from nuri.core.db import stage_maintenance_candidate

        caps = AuditCaps(**input_data.get("caps", {}))
        tracker = _CapTracker(caps=caps)
        scan_ctx = ScanContext(repo_root=REPO_ROOT, tracker=tracker, db_path=db_path)

        staged = seen = privacy_blocked = 0
        scanner_errors: list[str] = []
        aborted: Optional[str] = None

        for scanner in SCANNERS:
            try:
                tracker.check_wall_clock()
                findings = scanner(scan_ctx)
                for f in findings:
                    tracker.check_wall_clock()
                    if not self._privacy_ok(f["title"] + "\n" + f["detail"]):
                        # 원장에 stub 도 남기지 않는다 (codex plan 리뷰 2) — 가짜 후보는
                        # precision/novelty 를 오염시키고, 민감 내용의 파생물을 남길 위험이
                        # 있다. 사건 자체는 output 카운터로 audit ledger 에 영속된다.
                        privacy_blocked += 1
                        continue
                    tracker.charge_candidate()
                    verdict, _ = stage_maintenance_candidate(
                        f["axis"],
                        f["title"],
                        f["detail"],
                        _fingerprint(f["axis"], f["title"]),
                        ctx.run_id,
                        db_path=db_path,
                    )
                    if verdict == "staged":
                        staged += 1
                    else:
                        seen += 1
            except CapExceeded as exc:
                aborted = exc.cap
                break
            except Exception as exc:  # 스캐너 하나가 죽어도 루프는 산다 (#894/#927 계열)
                scanner_errors.append(f"{scanner.__name__}: {str(exc)[:200]}")

        output = {
            "staged": staged,
            "seen_again": seen,
            "privacy_blocked": privacy_blocked,
            "aborted_by_cap": aborted,
            "scanner_errors": scanner_errors,
            "subprocess_used": tracker.subprocess_used,
            "usd_spent": tracker.usd_spent,
            "wall_clock_s": round(time.monotonic() - tracker.started, 1),
        }
        self._surface_summary(output)
        outcome = Outcome.WARN if (aborted or scanner_errors) else Outcome.PASS
        return ActorResult(output=output, outcome=outcome, sample_n=staged + seen)

    @staticmethod
    def _privacy_ok(text: str) -> bool:
        """staging 전 privacy 스캔 — **전 범주** `gate_text` (broker명·금액·ticker+PnL).

        `--message` CLI 모드는 ticker+PnL 만 본다 (codex plan 리뷰 1 — blocking 지적).
        in-process import 는 `stage_agent_dev_log` 가 이미 쓰는 런타임 게이트 선례
        (nuri/agents/discord/outbox.py:224) 그대로다. import/실행 실패는 **차단**으로
        취급한다 — 스캔 못 한 것은 깨끗한 것이 아니다 (fail-closed).
        """
        try:
            scripts_dir = REPO_ROOT / "scripts" / "verify"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from check_privacy_leak import gate_text  # type: ignore[import-not-found]

            return not gate_text(text, source="<maintenance_candidate>")
        except Exception:
            return False

    def _surface_summary(self, output: dict[str, Any]) -> None:
        """주간 한 줄을 #ops 로 — 정직한 0건도 표면화한다 (quiet-by-design 금지).

        관측이 본 작업을 게이트하면 안 된다 — 실패는 삼키고 로그만 남긴다 (#894).
        """
        try:
            from nuri.agents.discord.outbox import stage_ops

            line = (
                f"🔧 maintenance audit: 신규 {output['staged']} · 재검출 {output['seen_again']}"
                f" · privacy차단 {output['privacy_blocked']}"
                + (f" · **{output['aborted_by_cap']} 캡 중단**" if output["aborted_by_cap"] else "")
                + (f" · 스캐너 오류 {len(output['scanner_errors'])}" if output["scanner_errors"] else "")
                + " — 리뷰: `python -m nuri.agents.actors.maintenance_auditor list`"
            )
            # 카운트만 — 후보 title/detail 은 어떤 경로로도 Discord 에 싣지 않는다
            # (원장 격리의 요점; 잠금 테스트가 payload 를 검사한다).
            stage_ops(
                payload={"kind": "maintenance_audit_weekly", "summary": line},
                dedupe_key=None,
                actor_name=self.name,
            )
        except Exception as exc:
            logger.warning(f"[maintenance-auditor] #ops 표면화 실패 (본 작업은 완료): {exc}")


def main(argv: Optional[list[str]] = None) -> int:
    """CLI — scan / list [status] / review <id> <verdict> [note] / stats."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("scan")
    p_list = sub.add_parser("list")
    p_list.add_argument("status", nargs="?", default=None)
    p_review = sub.add_parser("review")
    p_review.add_argument("id", type=int)
    p_review.add_argument("verdict", choices=["approved", "rejected", "published"])
    p_review.add_argument("note", nargs="?", default=None)
    sub.add_parser("stats")
    args = parser.parse_args(argv)

    input_data: dict[str, Any] = {"action": args.action}
    if args.action == "list" and args.status:
        input_data["status"] = args.status
    if args.action == "review":
        input_data.update({"id": args.id, "verdict": args.verdict, "note": args.note})

    result = MaintenanceAuditor().run(input_data)
    print(json.dumps(result.output, ensure_ascii=False, indent=2, default=str))
    return 0 if result.outcome in (Outcome.PASS, Outcome.WARN) else 1


if __name__ == "__main__":
    raise SystemExit(main())
