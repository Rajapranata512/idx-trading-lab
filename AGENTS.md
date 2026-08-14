# AGENTS.md - IDX Trading Lab Operating Contract

This is the mandatory operating contract for every AI agent in this repository.
It preserves context, prevents repetitive exploration, protects trading safety,
and moves the project toward a credible portfolio release.

## 1. Authority And Source Of Truth

Use this order when information conflicts:

1. The user's latest request.
2. This `AGENTS.md`.
3. `PRD.md`, especially its resume, state, blockers, and next-action sections.
4. Executable tests, runtime configuration, and current source code.
5. Focused technical documents in `docs/`.
6. Generated reports and historical notes.

`PRD.md` is the only product source of truth. Do not create another PRD,
roadmap, recovery contract, or progress diary. Reports describe a run; they do not
redefine product policy.

## 2. Reset And Startup Protocol

After a new session, token reset, or context compaction:

1. Read the user's latest request.
2. Read this file.
3. Read only `Agent Resume Block`, `Current State`,
   `Active Blockers`, and `Next Action` in `PRD.md`.
4. Run:

   ```powershell
   git status --short --branch
   git log -5 --oneline --decorate
   ```

5. Preserve existing changes. If the main worktree is dirty, use an isolated
   worktree or task branch without resetting user work.
6. Classify the task, follow one route below, and stop reading when the affected
   contract, source file, and nearest test are known.
7. Unless the latest request pauses or redirects work, begin the PRD Next Action
   immediately. Do not spend a turn asking whether to continue.

Default recovery budget: this file, four short PRD sections, one optional context
document, one or two source files, one or two nearest tests, and one specific report
only when evidence is required. Do not scan the full repository.

## 3. Files Never Loaded At Startup

Do not recursively read:

- `reports/`, `web/reports/`, `data/raw/`, or `data/processed/`;
- historical run logs, snapshots, parquet files, model binaries, or generated CSV;
- all of `src/`, `tests/`, or Git history;
- temporary logs, screenshots, caches, and local tool state.

Open one artifact only when it answers a concrete question. Query required fields
instead of printing an entire structured file.

## 4. Task Router

| Task | Context | Source entry point | Minimum validation |
|---|---|---|---|
| Direction/status | `PRD.md` only | none unless disputed | verify cited artifact fields |
| Daily pipeline | `docs/ai-context/03-daily-workflow-run-daily.md` | relevant `src/cli.py` function | nearest CLI/integration test |
| Config/data | `docs/ai-context/02-repository-map-and-config.md` | `src/config.py` plus affected module | config and nearest test |
| Intraday 5m/15m | PRD INTRA requirements | `src/intraday/` | `tests/test_intraday_pipeline.py` plus affected tests |
| Pre-open auction | `docs/PREOPEN_AUCTION_BLUEPRINT.md` | `src/preopen/` | `tests/test_preopen_auction.py`; never send live in tests |
| Sentiment/events | PRD SENT requirements | timestamped licensed source adapter when introduced | no-leakage, dedupe, and ablation tests |
| Model V2 | `docs/MODEL_V2_BLUEPRINT.md` | affected `src/model_v2/` module | affected V2 tests |
| Accuracy/meta-filter | PRD evidence contract | `src/analytics/model_v2_accuracy.py`, `src/model_v2/meta_filter.py` | accuracy/final-stage tests |
| Promotion/rollback | PRD state machine | `src/model_v2/promotion.py` | promotion/guardrail tests |
| Universe/price quality | `docs/STAGE_1_3_OPERATIONS.md` | `src/universe/`, `src/ingest/quality.py` | universe/quality tests |
| EOD reconciliation | `docs/EOD_RECONCILIATION_RUNBOOK.md` | `src/ingest/reconciliation_*`, `src/ingest/quality.py`, REST provider | `tests/test_eod_reconciliation_evidence.py` plus affected ingest tests |
| No signal/blocked | `docs/ai-context/05-operations-and-debugging.md` | latest funnel, quality, and gate report | focused reproduction |
| Dashboard | relevant PRD requirement | `web/js/dashboard.js` plus producer | JS/static-dashboard tests |
| Daily Telegram | `docs/STAGE_1_3_OPERATIONS.md` | workflow, guard, sender | delivery tests; do not send live |
| Final execution | PRD Final Execution Contract | order intent, state store, broker adapter when introduced | paper contract/failure tests; never live by default |
| GitHub/Vercel | failing run or deployed artifact | workflow, `web/`, export/Vercel config | local failed step or exact artifact comparison |
| Documentation | this file and target doc | linked files only | links and `git diff --check` |

If still unclear, open only the one task-specific document named in the table.
Do not read every context document.

## 5. Anti-Repetition Rules

Before doing work, check:

1. Is the result already recorded in PRD Current State or the latest commit?
2. Does `git status` show an existing implementation?
3. Does `git grep` locate an existing helper, test, or contract?
4. Can one current structured report answer the evidence question?

Reuse existing modules and tests. Do not repeat repository-wide assessments, rerun
full suites for narrow edits, regenerate reports merely to inspect known fields, or
append activity diaries. Do not ask whether to continue when the next internally
safe step is already inside the user's explicit objective.

## 6. Continuous Autonomous Execution Loop

Continuation is the default. Within an active session and the user's objective:

1. Select the highest-priority unblocked item from PRD Next Action.
2. Confirm its requirement ID, safety boundary, affected files, and test.
3. Implement the smallest complete change.
4. Run focused validation, then broaden it according to blast radius.
5. Inspect the diff for unrelated changes, secrets, and generated churn.
6. Update only material PRD state as described in section 11.
7. Set exactly one recommended next action.
8. If that action is unblocked, in scope, and allowed by section 7, start it in the
   same session instead of ending with a recommendation.
9. Repeat the loop while each iteration produces a measurable code, test, data-quality,
   reliability, documentation, or deployment improvement.

A completed milestone is not a handoff boundary while a safe PRD Next Action remains.
Do not ask the user to continue, do not merely restate the recommendation, and do not
repeat repository orientation between iterations. Treat the recommendation as the next
work item and route back to step 1.

The maximum autonomous point is reached only when all currently unblocked roadmap work
is complete and every remaining item meets at least one terminal boundary:

- it requires a missing credential, licensed dataset, external account change, elapsed
  real-market evidence, or a product/risk decision that cannot be inferred safely;
- it requires an external side effect outside the standing authorization in section 7;
- it would weaken a data, model, risk, security, reconciliation, or execution gate;
- the same evidence-backed remediation has failed and no new diagnostic path remains;
- acceptance criteria are satisfied and PRD has no further material unblocked action;
- the user explicitly asks to pause, stop, discuss, or report status only.

At a terminal boundary, record the exact blocker, preserve one resumable Next Action,
and report the highest completed point. Continuous execution means persistence within
available active sessions plus deterministic recovery from AGENTS/PRD; never claim
background or asynchronous work after a response ends.

## 7. External Side-Effect Boundary

Approval may be one-time, task-scoped, or standing. Do not repeatedly request approval
for an unchanged scope already granted by the user and recorded here or in PRD.

The repository owner's continuous-execution directive is standing authorization for:

- local implementation, tests, documentation, and conservative cleanup;
- creating task branches and commits, pushing them, opening PRs, and merging only after
  applicable local validation and required repository checks pass;
- ordinary configured CI, data-refresh jobs, and passive Vercel deployments triggered
  by those approved repository updates;
- read-only GitHub, workflow, provider-status, and public-deployment verification.

This standing authorization never includes:

- force-pushing, rewriting shared history, or changing branch protection;
- manually dispatching a production workflow, changing Vercel production settings, or
  sending Telegram messages;
- changing secrets, credentials, admin accounts, billing, or external services;
- enabling shadow-to-canary, live, or final model rollout;
- activating a broker account, submitting an order, or changing
  `EXECUTION_DISABLED`;
- deleting non-reproducible data, model artifacts, audit evidence, or user files.

The latest user request can narrow or revoke standing authorization at any time. A
successful local test is not a deployment, and passive deployment is not execution
authorization.

## 8. Trading And Model Safety Invariants

These rules cannot be weakened to improve presentation or signal count:

- The project is decision support, not a guaranteed-profit system.
- Data quality, risk engine, kill switch, rollback, and manual review retain veto power.
- A high score is not a calibrated probability or final recommendation.
- T1 and Swing train, evaluate, promote, and roll back independently.
- No heuristic or fallback probability may be labeled as Model V2 output.
- Training, calibration, threshold selection, and final test windows stay separate.
- Labels use point-in-time candidates, next-session-open entry, first-touch stop/TP,
  and configured fee/slippage.
- Thresholds are never lowered merely to produce more signals.
- Holdout and walk-forward evidence must be out-of-sample and reproducible.
- Sparse ticker evidence shrinks toward a mode prior instead of eager blacklisting.
- Promotion evidence must match the exact model artifact version.
- Raw 5-minute bars are immutable inputs; 15-minute model bars are deterministic,
  session-aligned aggregates with gap and duplicate checks.
- EOD reconciliation evidence is idempotent by market date; do not enable required
  enforcement until five consecutive real IDX sessions qualify.
- Secret presence is not provider readiness. Before EOD ticker fan-out, the account
  entitlement and remaining quota must cover the planned request batch.
- Free-tier deferred reconciliation may rotate a bounded ticker batch and accumulate
  historical evidence, but it is never same-day evidence or final-execution eligibility.
  Same-day production reconciliation still requires at least 95% active-universe coverage.
- Pre-open features use only licensed snapshots at or before the fixed cutoff; IEP
  opening direction and post-open follow-through are separate labels.
- Order-book withdrawal proxies are not called cancellations without event-level proof.
- Sentiment joins use publication time available before cutoff, source tier, dedupe,
  and latency; rumor or an LLM output can never directly authorize an order.
- GitHub Actions and Vercel Hobby cron are not used for minute-critical pre-open timing;
  use an idempotent persistent scheduler and synchronized Asia/Jakarta clock.
- Backtest, shadow, dashboard, and Telegram output are not trade orders.
- `FINAL_DECISION` is only a prerequisite; only an explicitly activated
  `FINAL_EXECUTION` state may submit a real broker order.
- Execution defaults to `EXECUTION_DISABLED`. A model rollout, code deploy,
  environment variable, or agent instruction cannot implicitly enable it.
- Live execution cannot precede paper adapter evidence, idempotency, protection,
  failure drills, reconciliation, account allowlisting, and user activation.
- Never fabricate sessions, rewrite reports, or bypass a gate to make status green.

The numeric promotion contract lives in `PRD.md`; never silently change it.

## 9. Engineering And Git Discipline

- Read before editing and follow existing project patterns.
- Use structured parsers for JSON, CSV, YAML, and configuration.
- Keep edits scoped and tests proportional to financial/operational risk.
- Work with dirty files; never revert changes you did not create.
- Never use `git reset --hard`, destructive checkout, recursive deletion, or
  unreviewed mass formatting.
- Never commit secrets, private data, local memory, caches, screenshots, or logs.
- Commit generated reports only when the production workflow requires them.
- Before commit or handoff, inspect `git status` and run `git diff --check`.

Use patch-based manual edits. If the patch tool is unavailable, verify the absolute
target is inside the isolated worktree before using a structured writer.

## 10. Validation Matrix

Start with the smallest sufficient command.

Documentation:

```powershell
git grep -n old-or-removed-path
git diff --check
```

Python:

```powershell
python -B -m pytest -p no:cacheprovider path/to/nearest_test.py
```

Dashboard/API JavaScript:

```powershell
node --check web/js/dashboard.js
node --test tests_js/<affected-test>.test.js
```

Production foundation:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_preopen_delivery.py tests/test_stage123_configuration.py tests/test_universe_snapshot.py tests/test_universe_update.py tests/test_price_quality.py tests/test_ingest_validation.py tests/test_integration_cli.py
node --test tests_js/preopen_watchdog.test.js tests_js/preopen_watchdog_handler.test.js
```

EOD reconciliation:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_deferred_eod_reconciliation.py tests/test_eod_reconciliation_evidence.py tests/test_price_quality.py tests/test_rest_provider.py tests/test_ingest_validation.py tests/test_stage123_configuration.py tests/test_roadmap_ops.py
```
Pre-open auction:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_preopen_auction.py tests/test_operational.py tests/test_preopen_delivery.py tests/test_stage123_configuration.py
```

Model V2 final-decision surface:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_model_v2_label_alignment.py tests/test_model_v2_promotion.py tests/test_model_v2_final_guardrails.py tests/test_model_v2_final_stage.py tests/test_model_v2_accuracy.py tests/test_model_v2_upgrade.py tests/test_paper_trading.py tests/test_strategy.py
```

Do not run `run-daily` only as a test. It mutates data/reports and may use
network or notification integrations.

## 11. Automatic PRD Maintenance

At the end of every material task, update `PRD.md` without waiting for another
request, but only when facts changed.

Allowed updates:

- Current State and verified commit/date;
- completed requirement or milestone;
- measured evidence and remaining blocker;
- one material decision;
- exactly one Next Action;
- validation and local/committed/pushed/deployed state.

Do not add formatting churn, generated timestamps, assumptions, repetitive command
logs, or scores copied from screenshots. Replace stale state instead of appending a
second version. Add at most one Decision Log entry per material decision.

After updating PRD, return to section 6 and execute its Next Action unless a terminal
boundary applies. PRD maintenance is a checkpoint, not a reason to stop.

## 12. Cleanup Policy

A file may be deleted automatically only when all are true:

1. `git grep` finds no runtime, test, workflow, or documentation dependency;
2. it is temporary, cached, duplicated, or fully reproducible;
3. it is not market history, model/reconciliation evidence, or a user file;
4. deletion preserves auditability and deployment;
5. affected validation still passes.

Ignore temporary `tmp_*`, `*.log`, caches, local worktrees, and local tool
state. Historical reports and snapshots need an explicit retention policy. A large
file is not automatically unnecessary.

## 13. Definition Of Done And Handoff

A material milestone is complete only when:

- requested behavior or analysis is delivered;
- focused validation passes, or the exact blocker is recorded;
- no unrelated user changes were reverted;
- PRD material state and Next Action are current;
- Git and external-side-effect state are stated honestly.

Do not send a final handoff after an intermediate milestone while another safe,
unblocked PRD action can be executed in the active session. A final handoff is for a
terminal boundary, an achieved end state, or an explicit user pause/status request.
It states: what changed, tests/evidence, remaining blocker, whether work was
committed/pushed/deployed, and one resumable next action.

Never say production, final decision, deployed, or accurate without current evidence.
