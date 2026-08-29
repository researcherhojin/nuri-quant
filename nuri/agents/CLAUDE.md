# nuri/agents/ — Actor Fleet + Discord Layer

## Scope

The autonomous operating layer: long-lived actors that observe the system, record verdicts to an audit ledger, and surface findings to Discord. Distinct from `nuri/trading/agents/` (the 10-agent *consensus* pipeline that scores tickers) — an actor here is an **operational unit with a run ledger**, not a signal contributor.

`actors/` holds **19 files: 16 registered actors + 3 unregistered infra helpers** (`brief_auditor`, `channel_dispatcher`, `outbox_watchdog` — deliberately outside the canonical roster).

## The actor contract (`base.py`)

`Actor(ABC)`. Subclass declares three class attributes and implements one method:

```python
name: str = ""          # DB key — must be in CANONICAL_ACTORS or DORMANT_ACTORS
version: str = "0.0.0"  # semver, recorded in every audit row
layer: Layer = Layer.B

def execute(self, input_data: dict[str, Any], ctx: RunContext) -> ActorResult: ...
```

**Callers invoke `run()`, never `execute()`.** `run()` is the lifecycle wrapper: `start_agent_run` → `execute` → `finish_agent_run` → `log_agent_audit`. Calling `execute()` directly produces an unaudited run — the ledger is the point of this layer.

| Layer | Meaning | Hard constraint |
|---|---|---|
| **A** | Enforcement — pure rule | **Zero LLM** (`_uses_llm=True` → `RuntimeError` at `__init__`) and **must return an `outcome`** (`None` → run marked failed + `ValueError`). Both enforced at runtime in `base.py`, not by convention. |
| **B** | Computation — statistical / deterministic | — |
| **C** | Interpretation — LLM essential | Async enrichment only; never in the decision path. |

`ActorResult(output, outcome=None, sample_n=None, input_summary=None, llm_narrative=None)`; `Outcome ∈ {PASS, BLOCK, WARN, ERROR}`.

**`WARN` 은 "작업은 됐지만 그대로 두면 안 되는 상태"다** — 실패가 아니라서 호출자가 계속 가도 되지만, 기록으로 남아야 한다. `CollectorOrchestrator` 가 rate limit 을 맞고 재시도로 살아난 런을 `PASS` 가 아니라 `WARN` 으로 돌리는 이유가 이것이다: 재시도가 성공을 만들어 주는 동안 IP ban 은 가까워지는데, `PASS` 로 적으면 그 카운트다운이 보이지 않는다.
**Test:** `tests/agents/test_collector_orchestrator.py::TestOrchestrateRetry::test_rate_limited_then_finished_is_warn_not_pass`

**`execute()` may raise** — `run()` records the failure (`status="failed"` + an `ERROR` audit row) and then **re-raises**. Failure isolation is the *caller's* responsibility: every `_run_*` wrapper in `nuri/scheduler.py` try/excepts, which is why one actor dying doesn't take the fleet down.

**The roster is closed and two-tier (#975).** `CANONICAL_ACTORS` (9) are actors with a real caller — scheduler, sleeve/rules, or the phase-2 manual chain; `DORMANT_ACTORS` (7) have implementations and tests but **no caller anywhere** — they register fine but are excluded from `missing()` so nothing advertises them as pending. Promoting a dormant actor to canonical requires the PR that adds its actual call path. `@REGISTRY.register` raises for names outside both tuples. Registration is idempotent for the same `module:qualname` so the `python -m` double-import (`__main__` reload) doesn't blow up. `CANONICAL_15` remains as a compatibility alias (= canonical + dormant).

## Invariants

- **Single-writer Discord.** Actors stage to the outbox — they never publish. Only `channel_dispatcher.py` (the writer) and `outbox_watchdog.py` (recursion break: if the dispatcher is dead, staging its own alarm would never be delivered) may touch `DiscordPublisher`. Everything else calls `nuri.agents.discord.outbox.stage_*` lazily inside the method. Breaking this breaks digest bucketing, the quiet-period gate, and dedupe at once.
- **No DB connections here.** Zero `sqlite3` in this directory. Reads go through `query()`; writes go through the named helpers (`log_decision`, `log_incident`, `register_hypothesis`, `stage_outbox`, …) — `query()` is read-only by contract.
- **Actors do not use `nuri/alerts/`.** That package is a separate scheduler-driven briefing path. The two never call each other; don't bridge them.
- **Mac mini is the sole writer; MBP is a read replica** (`nuri/agents/__init__.py`). An actor that writes must be safe to run in exactly one place.
- **Every actor module ships a `main(argv)` CLI** — `python -m nuri.agents.actors.<module> <action> ...`. Universal across all 19.
- Most actors dispatch on `input_data["action"]` against a class-level `VALID_ACTIONS` and return `ActorResult({"error": ...})` for an unknown action rather than raising.

## Scheduling

There is **no schedule declaration on the actor**. Cron lives entirely in `nuri/scheduler.py`'s module-level `SCHEDULES` list; jobs run **in-process** under APScheduler `BlockingScheduler` with `misfire_grace_time=300`.

Only 5 actors are reached from `SCHEDULES` today, and **two of them are registered actors**:

| Wrapper | Actor | Registered? |
|---|---|---|
| `_run_collector("alpha_tracking")` | `ForwardOutcomeTracker` | ✅ |
| `_run_maintenance_audit` (주간, #1308) | `MaintenanceAuditor` | ✅ |
| `_run_brief_audit` | `BriefAuditor` | — helper |
| `_run_channel_dispatcher` | `ChannelDispatcher` | — helper |
| `_run_outbox_watchdog` | `OutboxWatchdog` | — helper |

So **14 of the 16 registered actors have no cron** — they run from their `main()` CLI or another caller. **Do not assume an actor is running just because it exists and is registered.** Check `SCHEDULES` before claiming anything about live behaviour.

⚠️ **APScheduler weekday ≠ crontab weekday**, but `SCHEDULES` entries are written in **crontab** semantics (0=Sun) and `scheduler._make_trigger()` converts. Write `1-5` for Mon–Fri and `0` for Sunday, as you would in a crontab — do NOT pre-convert to `mon-fri`, and do NOT call `CronTrigger.from_crontab()` directly (it skips the conversion, which is how every non-`tz` job ran a day late until #929 — `stock_us_freshness` missed Tuesdays, leaving the §3.11 benchmark SPY stale each Mon/Tue).
**Test:** `tests/test_scheduler_weekday.py::TestEverySchedulesJobFiresOnIntendedDays::test_all_jobs_match_crontab_semantics` — asks the registered triggers which weekdays they actually fire on and compares against a hand-written crontab table.

## Adding an actor

1. `nuri/agents/actors/<snake>.py`; subclass `Actor`, set `name` / `version` / `layer`.
2. Add `name` to `CANONICAL_ACTORS` **in the same PR that wires its caller** (no caller yet → `DORMANT_ACTORS`), then decorate with `@REGISTRY.register`. (Order matters — registration validates against the tuples.)
3. Implement `execute()`. Layer A must always set `outcome`.
4. Add a module-level `main(argv)` CLI.
5. Export from `actors/__init__.py`.
6. To schedule: add a `_run_<x>()` wrapper in `scheduler.py` that try/excepts + logs `exc_info=True`, then append to `SCHEDULES`.
7. Discord output: `stage_*` only. Never import `DiscordPublisher`.

## Gotchas

- **Dedupe channel must match emit channel.** `brief_auditor.py` sets `_AUDIT_CHANNEL = "ops"` and uses it for *both* `stage_ops()` and `_dedupe_recent()`. If the two drift apart, the dedupe lookup queries the wrong channel, finds nothing, and re-emits the same incident every 6 hours.
- **Quiet period is `#brief`-only** (`QUIET_PERIOD_SECONDS = 60`). `#ops` / `#incidents` / `#rollout` bypass the gate — don't "fix" their apparent lack of throttling.
- **`outbox_watchdog` exists because silent failure is the default.** Scheduler wrappers swallow exceptions, so a dead dispatcher looks identical to an idle one. The watchdog measures outbox backlog (`>30 min` oldest pending, `>100` pending) and alerts `#ops` **directly via webhook**. Any new "quiet by design" component needs an equivalent liveness probe.
- **A detector must not die from the data it watches.** `_detect_alpha_report_stale` read `payload` two ways and both could kill it: `json_extract()` raises SQLite `OperationalError: malformed JSON` on one broken row (guard with `json_valid(payload) AND …`), and `json.loads` on non-object-but-valid JSON (`null` / `[]` / `"x"` / `5`) returns a non-dict whose `.get` raises `AttributeError` — which a narrow `except (JSONDecodeError, TypeError, KeyError)` does not catch. Either way the scan loop rebrands the corpse as a `db_lock` incident and **the fact being watched for disappears with the watcher**. Payload parsing supplies the *reason*; it must never decide *whether* to fire (#927, same family as #894). Same shape as `feedback_observability_must_not_gate`.
  **Test:** `tests/agents/test_sre_incident_agent.py::TestAlphaReportStaleDetector::test_broken_text_payload_does_not_kill_the_detector` (+ `::test_non_object_json_payload_still_alerts`) — dropping either the `json_valid` guard or the broad `except` fails them.
- **`forward_outcome_tracker` accepts only `SUPPORTED_WINDOWS = (7, 14, 30)`** — other horizons return an error result, not an exception.

## Tests

`tests/agents/` — no `conftest.py`; fixtures are duplicated per file (canonical form in `test_base.py`, `test_freshness_gatekeeper.py`):

1. `db_path(tmp_path)` → `init_db(path)`.
2. `patched_db(db_path)` → patch **`nuri.agents.base.log_agent_audit` / `start_agent_run` / `finish_agent_run`** with `side_effect` wrappers that `kwargs.setdefault("db_path", db_path)`.

**Patch the `nuri.agents.base` namespace, not `nuri.core.db`** — `base.py` imports those names directly, so patching the source module misses. Discord side effects: patch `nuri.agents.discord.outbox.stage_*` at its source module. See `tests/CLAUDE.md`.

## References

- `nuri/scheduler.py` — `SCHEDULES` wiring, heartbeat, launchd self-restart
- `nuri/agents/discord/outbox.py` — payload schema + single-writer invariant statement
- `docs/STRATEGY.md §3.11` — measurement mode (what these actors adjudicate)
- `nuri/trading/agents/CLAUDE.md` — the *other* agents (consensus pipeline), not this fleet
