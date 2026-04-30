#!/usr/bin/env bash
# scripts/health_check.sh — service-grade infra health (#529 Phase 1).
#
# Codex Round 5 mandatory #1: single-writer prod invariant 검증.
# Mac mini = sole writer (production), MBP = read-only replica.
#
# 검증 항목:
#   1. DB schema version >= 29 (Phase 1+2 migrations 적용)
#   2. agent_audit_ledger / feature_flags / agent_run_ledger / agent_messages 테이블 존재
#   3. orphan run 탐지 (started + finished_at NULL + 1h 경과) → SRE alert
#   4. 머신 식별 (Mac mini vs MBP) + writer 권한 추정
#
# Exit codes: 0 OK / 1 WARN / 2 FAIL.
set -euo pipefail

cd "$(dirname "$0")/.."

DB="${NURI_DB_PATH:-data/portfolio.db}"
HOSTNAME=$(hostname -s 2>/dev/null || hostname)
EXIT_CODE=0

echo "═══════════════════════════════════════════════════"
echo " nuri-quant service-grade health check (#529)"
echo "═══════════════════════════════════════════════════"
echo " host:    $HOSTNAME"
echo " db:      $DB"
echo " time:    $(date -Iseconds)"
echo "──────────────────────────────────────────────────"

if [ ! -f "$DB" ]; then
    echo " ❌ DB missing: $DB"
    exit 2
fi

# 1) Schema version
SCHEMA_VERSION=$(.venv/bin/python -c "from nuri.core.db import get_schema_version; print(get_schema_version())" 2>/dev/null || echo "0")
if [ "$SCHEMA_VERSION" -ge 32 ]; then
    echo " ✅ schema version: $SCHEMA_VERSION (>=32)"
else
    echo " ❌ schema version: $SCHEMA_VERSION (need >=32 for #529 Phase 1+2)"
    EXIT_CODE=2
fi

# 2) Required Phase 1+2 tables
for table in agent_audit_ledger feature_flags agent_run_ledger agent_messages walkforward_runs regime_posteriors hypotheses causal_audits; do
    EXISTS=$(.venv/bin/python -c "from nuri.core.db import query; r=query(\"SELECT 1 FROM sqlite_master WHERE type='table' AND name='$table'\"); print(len(r))" 2>/dev/null || echo "0")
    if [ "$EXISTS" = "1" ]; then
        echo " ✅ table exists: $table"
    else
        echo " ❌ table missing: $table"
        EXIT_CODE=2
    fi
done

# 3) Orphan run detection (started but not finished, >1h)
ORPHANS=$(.venv/bin/python -c "
from nuri.core.db import query
r = query(\"SELECT COUNT(*) AS c FROM agent_run_ledger WHERE status='started' AND finished_at IS NULL AND datetime(started_at) < datetime('now', '-1 hour')\")
print(r[0]['c'])
" 2>/dev/null || echo "0")
if [ "$ORPHANS" = "0" ]; then
    echo " ✅ orphan runs: 0"
else
    echo " ⚠️  orphan runs: $ORPHANS (started >1h ago, no finished_at — SRE alert 후보)"
    [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1
fi

# 4) Single-writer machine inference (case-insensitive via lowercase compare)
HOSTNAME_LC=$(echo "$HOSTNAME" | tr '[:upper:]' '[:lower:]')
case "$HOSTNAME_LC" in
    *macmini*)
        echo " ✅ machine role: PRIMARY (Mac mini single writer)"
        ;;
    *macbook*|*mbp*)
        echo " ⚠️  machine role: REPLICA (MBP — write 시도 금지)"
        [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1
        ;;
    *)
        echo " ⚠️  machine role: UNKNOWN ($HOSTNAME) — manual classification 필요"
        [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1
        ;;
esac

# 5) Active feature flags
ACTIVE_FLAGS=$(.venv/bin/python -c "
from nuri.core.db import query
r = query(\"SELECT flag_name, canary_scope FROM feature_flags WHERE enabled=1 AND disabled_at IS NULL\")
if not r:
    print('  (none)')
else:
    for row in r:
        print(f\"  - {row['flag_name']} ({row['canary_scope'] or '?'})\")
" 2>/dev/null || echo "  (query failed)")
echo " 🚩 active feature flags:"
echo "$ACTIVE_FLAGS"

echo "──────────────────────────────────────────────────"
case "$EXIT_CODE" in
    0) echo " ✅ HEALTH OK" ;;
    1) echo " ⚠️  HEALTH WARN" ;;
    *) echo " ❌ HEALTH FAIL" ;;
esac
echo "═══════════════════════════════════════════════════"

exit "$EXIT_CODE"
