# 00 - Token-Efficient Agent Reading Guide

This file is a router, not a request to understand the whole repository.

## Reset Protocol

1. Latest user request wins over old conversation context.
2. Read `docs/AI_PROJECT_CONTEXT.md` as the PRD and current recovery contract.
3. Run `git status --short --branch`; preserve all existing user changes.
4. Classify the task: analysis, operation, Model V2, daily pipeline, config/data,
   dashboard, testing, GitHub, or deployment.
5. Read only the route below, then stop when the edit surface and test are known.

Default reset budget: this file, the PRD, 1-2 source files, and 1-2 tests.

## Routes

| Task | Optional context | Source entry point |
|---|---|---|
| Project explanation | `01-project-overview.md` | none unless asked |
| Daily pipeline | `03-daily-workflow-run-daily.md` | relevant `src/cli.py` section |
| Config/data contract | `02-repository-map-and-config.md` | `src/config.py` plus affected module |
| V1 scoring/risk | `04-module-workflows.md` | relevant `src/strategy/` or `src/risk/` module |
| Model V2/final decision | `docs/MODEL_V2_BLUEPRINT.md` | relevant file in `src/model_v2/` plus nearest test |
| V2 label/live alignment | PRD Final Decision Contract | `src/model_v2/labeling.py`, `src/strategy/ranker.py`, or `src/paper_trading/auto_fill.py` |
| Accuracy audit | PRD section Final Decision Contract | `src/analytics/model_v2_accuracy.py` |
| Operations/no signal | `05-operations-and-debugging.md` | only the latest relevant report |
| Safe code change | `06-change-guide-and-tests.md` | changed module plus nearest test |
| Dashboard | none | `web/js/dashboard.js` and its report producer |

## Do Not Load At Startup

- `reports/` or `web/reports/` recursively
- raw price CSV or feature parquet data
- model binaries
- snapshots, historical run logs, temporary logs
- every test file or all of `src/`

Open one specific artifact only when a concrete failure or metric requires it.

## Stop Rule

Stop exploring and act when all are known:

- exact user deliverable,
- source module and downstream contract,
- nearest validation,
- whether the change can affect live signals, external notifications, or deployment.

If coding was requested, implement and verify. If analysis was requested, do not edit.

## Drift Prevention

- Do not add unrelated refactors, UI redesign, threshold weakening, or extra features.
- Do not claim Model V2 is final unless the current per-mode promotion state says so and
  every PRD gate is evidenced.
- Do not push, deploy, send Telegram, or mutate production state without an explicit request.
- Do not expose secrets. Do not revert dirty work that you did not create.
- After material contract changes, update `docs/AI_PROJECT_CONTEXT.md`; do not create a
  second competing PRD.
