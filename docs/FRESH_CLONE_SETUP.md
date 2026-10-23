# Fresh Clone Setup — End-to-End Verification

*Korean edition: [ko/FRESH_CLONE_SETUP.md](ko/FRESH_CLONE_SETUP.md)*

> Scope: disposable development setup. Do not run reset commands against the production adjudication ledger. The dated smoke logs below are historical evidence, not a fresh-clone run or a current service-health guarantee.

This is the procedure for a first install of Nuri-Quant, a reinstall, and onboarding a new contributor. It manually verifies the end-to-end scenario that PR CI does not check. It reflects #272 Phase 5 (2026-04-15).

> **When to run**: after a fresh clone, after resetting the environment, after a major dependency upgrade, and as a quarterly health check. Do not run it on every PR. The network work takes 20-30 minutes, and the results depend on the state of external APIs.

---

## 1. Prerequisites

| Item | Required version | Installation |
|------|----------|---------|
| Python | 3.12 | `brew install python@3.12` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| TA-Lib (C lib) | latest | `brew install ta-lib` |
| Node.js | 22+ | `brew install node@22` |
| Git | any | Probably already installed |

**Expected runtime (on an M2 Pro)**:

- `make setup`: 2-3 min (deps install + DB init)
- `make universe-sync-us`: 10-20 s (Wikipedia scrape)
- `make universe-sync-kr`: 10-30 s (FDR/KRX fetch; skipped when the network is unstable)
- `make collect-universe`: 15-20 min (yfinance in parallel for the US universe + pykrx sequentially for KR)
- `make validate-universe`: 3-5 s (includes the live fetch; the DB-only check is `make validate-universe-cache`)

**Total expected**: 20-30 min (depends on network + API state).

---

## 2. Fresh Clone Commands (Exact Order)

```bash
# 0. Clone + branch
git clone https://github.com/researcherhojin/nuri-quant.git
cd nuri-quant
git checkout main

# 1. Environment + DB initialization
cp config/portfolio.example.yaml config/portfolio.yaml  # make setup imports it (fails if missing; gitignored)
make setup                       # venv + deps + DB schema + portfolio import
cd frontend && npm ci && cd ..   # frontend deps

# 2. Universe sync (optional — can be skipped with the default universe.yaml)
make universe-sync-us            # dry-run: check the Wikipedia S&P 500 diff
make universe-sync-kr            # dry-run: KOSPI 200 diff (finance-datareader is a default dependency)
make universe-sync-apply         # apply to the actual universe.yaml (additions only)

# 3. Data collection
make collect-universe            # US + KR prices/fundamentals/wallstreet/estimates (~15 min)
# Optional: fetch 1y OHLCV for technical analysis (required after P1 A)
make collect-universe-1y         # backfill 1 year of price history (~10-15 min)

# 4. Validation
.venv/bin/python scripts/doc/validate_universe.py         # coverage gate: 5 DB checks + 1 per successful upstream fetch (up to 7)
.venv/bin/python scripts/doc/validate_universe.py --no-fetch  # for CI (skips the network)
make validate-portfolio                                   # check each portfolio.yaml ticker in the DB

# 5. Start the servers (visual check)
make start                       # API :8001 + Dashboard :3000
# Open http://localhost:3000 in a browser
```

---

## 3. Expected Success Signals

These are the outputs to check after each step completes. If a success signal does not appear, follow the triage in section 4.

| Step | Success signal | Failure signal |
|------|----------|----------|
| `make setup` | `=== Sync complete: -N +M ===` (the closing message of `scripts/ops/import_portfolio.py`) | ModuleNotFoundError / sqlite error |
| `make universe-sync-us` | `S&P 500: N종목 fetched` log line (N ≈ 500) + diff summary | Wikipedia 403 / HTTP error |
| `make universe-sync-kr` | `KOSPI 200: N종목 fetched` log line (N ≈ 200), or, if FDR is not installed or the KRX source fails, a `KR sync 건너뜀` warning + `KR KOSPI 200: ⏭️  건너뜀` | unexpected traceback |
| `make collect-universe` | `prices [universe]: 100%\|` tqdm completion + `수집 결과: ... 성공 / ... 실패` summary | silent hang > 5 min / 500 lines of ERROR |
| `make collect-universe-1y` | SPY rows in `prices` ≥ 200 (`SELECT COUNT(*) FROM prices WHERE ticker='SPY'`) | rows < 50 |
| `validate_universe.py` | every executed check PASS → exit 0 (7/7 when both upstream fetches succeed; `--no-fetch`: 5/5) | any FAIL check, or `exit 1` |

**5/5 PASS thresholds** (measured 2026-04-15):

- prices ≥ 95% (measured 99%)
- fundamentals ≥ 80% (measured 99%)
- analyst_ratings ≥ 70% (measured 97%)
- insider_trades ≥ 50% (measured 97%)
- superinvestors ≥ 80% (measured 97%)

---

## 4. Failure Triage

| Symptom | Possible cause | Fix |
|------|----------|------|
| `FileNotFoundError: config/universe.yaml 가 없습니다` | the tracked file was deleted (`make setup` does not create it) | `git checkout main -- config/universe.yaml` |
| `YAML 파싱 실패` | manual editing error | `git checkout main -- config/universe.yaml` |
| Wikipedia 403 / timeout | User-Agent blocked | Retry after 10 minutes. If it keeps failing, run KR only (`.venv/bin/python -m nuri.collectors.universe_sync --market kr`) |
| pykrx stall / hang after 60 tickers | KR rate-limit | Normal behavior. Sequential fetching + a 0.1s sleep are already applied, so wait 15-30 minutes |
| many yfinance 404s | ticker delisting (normal) | Failures of up to 5-10% are acceptable. The summary shows them |
| a FAIL check in `validate_universe.py` | coverage below the threshold for a specific table | Rerun the corresponding collector (`make wallstreet`, etc.) |
| Dashboard 500 error | API server not running | Start `make api` on its own + check the logs |
| OOM during `make collect-universe-1y` | too many parallel workers | The default is 10 threads. Adjust `max_workers=10` in `nuri/collectors/stock.py` |

**Debugging**: Check the latest report in `data/reports/YYYY-MM-DD/`. `scripts/doc/validate_universe.py` prints a detailed table (supported flags: `--no-fetch`, `--format {table,json}`; the default is table).

---

## 5. Cleanup / Reset (Preparing a Rerun)

```bash
# Level 1: reset only the DB (fast)
rm data/portfolio.db
make setup                       # schema + portfolio re-import

# Level 2: include build artifacts
make clean-all                   # __pycache__ + build + token cache

# Level 3: full reset (deps must be reinstalled)
make clean-deep                  # clean-all + delete frontend node_modules/.next + .venv; asks for interactive confirmation
# Afterwards: make setup && cd frontend && npm ci
```

**Caution**: `config/portfolio.yaml` holds the user's real data and is gitignored. Back it up before deleting anything.

---

## Note — Phase 5 QA Scope

This document is for a manual smoke test. The negative tests included in PR CI are:

- `tests/collectors/test_universe_sync.py::TestPhase5NegativeGuardrails` — missing/malformed/empty `universe.yaml` graceful error
- `tests/integration/test_universe_sync_real.py` — real network integration (marker `integration`; runs only through `make test-integration`)

**Out of scope** (candidates for separate PRs):

- Tests for API-key-based collectors (every current path is keyless)
- An automated quarterly live smoke CI job
- Dependency drift detection

---

## 2026-04-29 re-smoke execution log

Purpose: verify that there is no coverage regression after the 17 PRs (#479-#502) merged in the two weeks since the 2026-04-15 (Phase 5 ship) baseline. A fresh clone was not performed. The Mac mini runs the same environment every day as a 24/7 scheduler, so that was treated as equivalent to a fresh-clone verification (running smoke). This run only spot-checked the collector state, the negative tests and the validators in the working repo.

### Negative tests (3 cases — `tests/collectors/test_universe_sync.py::TestPhase5NegativeGuardrails`)

```
test_missing_universe_yaml_raises_actionable_error      PASSED
test_malformed_universe_yaml_raises_actionable_error    PASSED
test_empty_universe_yaml_raises_actionable_error        PASSED
============================== 3 passed in 0.15s ===============================
```

The run confirmed that the recovery commands (`make setup` / `git checkout main -- config/universe.yaml`) appear in the actionable error messages and that the diagnostic messages are in Korean. 3/3 passed.

### `make validate-universe-cache` (DB-only, no fetch)

```
2026-04-29 23:27:57 KST
─────────────────────────────────────────────────────
  data.prices                  99%   ≥95%   ✅ PASS
  data.fundamentals            99%   ≥80%   ✅ PASS
  data.analyst_ratings         97%   ≥70%   ✅ PASS
  data.insider_trades          97%   ≥50%   ✅ PASS
  data.superinvestors          97%   ≥80%   ✅ PASS
  Result: 5/5 PASS → exit 0
─────────────────────────────────────────────────────
real 0.31s
```

All 5 coverage thresholds passed, with no regression against the baseline (2026-04-15).

### `make validate-universe` (with network fetch)

```
2026-04-29 23:28:01 KST
─────────────────────────────────────────────────────
  universe.us_sp500           100%   ≥95%   ✅ PASS
  universe.kr_kospi200         99%   ≥95%   ✅ PASS
  data.prices                  99%   ≥95%   ✅ PASS
  data.fundamentals            99%   ≥80%   ✅ PASS
  data.analyst_ratings         97%   ≥70%   ✅ PASS
  data.insider_trades          97%   ≥50%   ✅ PASS
  data.superinvestors          97%   ≥80%   ✅ PASS
  Result: 7/7 PASS → exit 0
─────────────────────────────────────────────────────
real 1.49s
```

All 7 checks, including the fetch, passed. The Wikipedia and FDR live APIs worked normally.

### `make universe-sync-us` (dry-run)

```
US S&P 500 (current coverage: 100.0%)
  + 추가될 종목 (0):
  - 제거될 종목 (40): ANSS, ARKK, ARM, DKNG, DUOL, HES, HIMS, IONQ, IPG, IWM ... 외 30개
  ⚠️  manual ETF 보호: removed 40건 무시 (--allow-removal 로 명시적 허용)
```

All 40 removal candidates are manual ETFs or universe entries outside the S&P 500 (including holdings and watchlist entries such as ARK). The protection policy is active, so applying the sync loses no manual ETFs.

### `make universe-sync-kr` (dry-run)

```
KR KOSPI 200 (current coverage: 99.0%)
  + 추가될 종목 (2): 077970.KS, 229640.KS
  - 제거될 종목 (5): 000080.KS, 003540.KS, 010620.KS, 067160.KS, 073240.KS
  ⚠️  manual ETF 보호: removed 5건 무시
  ℹ️  dry-run — 실제 변경 없음 (총 7건)
```

2 adds (new KOSPI 200 constituents) and 5 removes (dropped from the index). The KR universe drift is within the normal range.

### Mac mini scheduler heartbeat (running smoke proxy)

```
$ ls -la data/logs/scheduler.log
.rw-r--r--@ 40k user 29 Apr 23:11

$ tail -3 data/logs/scheduler.log
2026-04-29 23:10:59 ark WARNING ARK CSV 다운로드 실패: 404 Client Error
2026-04-29 23:10:59 ark WARNING 모든 ARK 소스 실패 (CSV + yfinance)
2026-04-29 23:11:02 db_maintenance WARNING 테이블 strategy_memory 조회 실패 (미존재 가능)
```

The ARK CSV 404 recurs (the ark-funds.com endpoint changes often, and the yfinance fallback works). The `strategy_memory` warning was not a missing table: the retention policy named a column that does not exist, so the weekly job never pruned it. #1786 removed the policy, because `strategy_memory` is append-only. There were no critical failures, and log volume is normal after RotatingFileHandler (PR #498) and yfinance WARNING (PR #501) were applied.

### Verdict

- **Negative path**: 3/3 PASS. The actionable-error contract holds.
- **Coverage**: 7/7 PASS (network) / 5/5 PASS (cache). No regression against the 2026-04-15 baseline.
- **Live scheduler**: The Mac mini 24/7 receiver is stable. Logs are normal, with no critical failures.
- **Drift**: The dry-run confirmed us_sp500 40 removals and kr_kospi200 2 add / 5 remove. At the time, the manual ETF protection was expected to take effect at the next weekly cron.

**Phase 5 QA close**: TODO Tier 2 P1 #1 is satisfied. The next check is quarterly or when dependencies change.
