---
name: nuri-review
description: Code review checklist. Use when asked to "review", "리뷰", "코드 검토", or when reviewing a PR diff.
---

# Code Review Checklist

## Architecture rules

- [ ] Cross-stage imports deferred into a function body (never module-level) and listed in `tests/core/test_cross_stage_imports.py` ALLOWED with a reason
- [ ] DB access via `nuri/core/db/` only — no direct `sqlite3` import
- [ ] Schema changes via `_MIGRATIONS` list in `nuri/core/db_migrations.py` — no direct ALTER TABLE
- [ ] Time via `kst_now()` / `today_kst()` — no `datetime.now()`
- [ ] Config in `config/*.yaml` — no hardcoded rules or thresholds

## Harness rules (STRATEGY.md §5)

- [ ] Function signatures verified before calling (no hallucinated APIs)
- [ ] Same approach failed twice? → must change approach, not retry
- [ ] Fix actually tested? → run tests, check coverage on target lines
- [ ] Scope limited to request? → no "while I'm here" improvements
- [ ] Numbers updated everywhere? → `grep -ri "changed_value"` across all docs

## Trading-specific (if BUY/SELL recommendation)

- [ ] Quantitative evidence provided (signal win rate, PF, regime stats)
- [ ] Price targets included (entry / stop-loss / target_1 / target_2 / trailing)
- [ ] 10 external sources cross-referenced
- [ ] SIEGE v2 gate (asset-class expansion) would pass — no error-grade failure

## Quality

- [ ] `make lint` clean
- [ ] Tests cover the changed code (not just passing)
- [ ] No dead code, unused imports, or commented-out blocks
- [ ] Korean comments, English variable/function names
