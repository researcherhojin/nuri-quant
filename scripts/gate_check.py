"""Gate 검증 스크립트 — Makefile에서 단계 실행 전 호출.

사용법:
    python scripts/gate_check.py validate   # validate 단계 게이트 확인
    python scripts/gate_check.py recommend  # recommend 단계 게이트 확인

종료 코드:
    0 = READY (실행 진행)
    1 = BLOCKED (실행 차단)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from nuri.engine.gate import check_gate, print_gate


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/gate_check.py <phase>")
        print("  phase: collect, validate, regime, recommend")
        sys.exit(1)

    phase = sys.argv[1]
    result = check_gate(phase)
    print_gate(result)

    if not result.ready:
        failed = [c for c in result.conditions if not c.passed]
        print(f"❌ GATE BLOCKED: {phase} 단계 실행 불가")
        print(f"   미충족 조건 {len(failed)}개:")
        for c in failed:
            print(f"   - {c.description}")
            print(f"     해결: {c.detail}")
        sys.exit(1)
    else:
        print(f"✅ GATE READY: {phase} 단계 실행 가능")
        sys.exit(0)


if __name__ == "__main__":
    main()
