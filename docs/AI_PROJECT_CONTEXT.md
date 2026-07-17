# PRD and AI Recovery Contract - IDX Trading Lab

Revision: 2026-07-17
Owner document: this file is the first source of truth after an AI context reset.

## Resume In 60 Seconds

Do not scan the repository. Read, in order:

1. The user's latest request.
2. This file.
3. `git status --short --branch` to protect existing work.
4. `docs/ai-context/00-agent-reading-guide.md` only if a file route is still unclear.
5. The one source module and nearest test for the requested task.

Stop reading once the requested output, affected contract, and validation command are known.
Historical reports, raw data, model binaries, snapshots, and logs are not startup context.

## Product Mission

IDX Trading Lab is a risk-first decision-support system for Indonesian stocks. It ranks
T1 and Swing candidates, measures realistic outcomes after fee/slippage, and can reject
trades when evidence is weak. It is not a broker execution bot and cannot guarantee profit.

Product priorities, in order:

1. Positive and stable out-of-sample expectancy.
2. Calibrated probabilities and low false positives.
3. Risk gates, rollback, data quality, and operational observability.
4. Clear reports, dashboard, and Telegram shadow monitoring.
5. Signal quantity only after quality gates pass.

## Authoritative Current Status

The final-decision mechanism is implemented, but Model V2 is not yet statistically ready
to be declared final. Never infer `FINAL` from a high score or from successful training.

An isolated full-data validation on 2026-07-17 completed both modes in about 89 seconds:

- T1: calibrated on a separate holdout, ECE 7.74%, holdout AUC 0.5604, five purged
  walk-forward folds, and 281 OOS trades. Promotion remains blocked because median PF is
  0.8259, median expectancy is -0.0180R, and only 20% of folds are profitable.
- Swing: calibrated on a separate holdout, ECE 7.67%, holdout AUC 0.3900, five folds,
  and zero OOS trades at the locked threshold. Swing remains disabled from rollout.
- Therefore the honest product state is `SHADOW/BLOCKED`, rollout 0%, not `FINAL`.

These are validation findings, not a promise of future returns. Runtime status must always
be read from current model metadata, accuracy audit, promotion state, and reconciliation.

## Final Decision Contract

Promotion is independent for `t1` and `swing`. A mode may move through
`SHADOW -> CANARY 10% -> 30% -> 60% -> FINAL 100%` only when all checks pass:

1. A real, loadable model artifact exists; heuristic probability fallback is forbidden.
2. Calibration uses a window separate from model fitting and is evaluated on untouched
   holdout data: `calibrated=true`, `evaluated_on_holdout=true`, ECE <= 10%, AUC >= 0.52.
3. At least five purged walk-forward folds exist, with at least 120 OOS trades, median
   PF >= 1.25, median expectancy > 0.03R, MaxDD <= 12%, and >= 60% profitable folds.
4. The accuracy audit is fresh, uses the exact model version, uses model output only,
   and passes trade count, PF, expectancy, and calibration gates.
5. A live candidate needs V1 and V2 agreement, positive EV, and a passing Bayesian
   ticker-edge filter. Sparse ticker history must shrink to the mode prior, not blacklist.
6. Shadow evidence covers at least 20 real market sessions and passes three consecutive
   evaluations. Do not fabricate or backfill session dates.
7. Canary stages require passing live reconciliation. One failed safety gate rolls the
   affected mode back to 0%; risk engine and kill switch always retain veto authority.

## Non-Negotiable Invariants

- Never lower thresholds merely to produce more signals.
- Never select, calibrate, or tune on the final test window.
- Never combine T1 and Swing promotion state or let one mode unblock the other.
- Never publish fallback `p(win)`, expected R, V2 recommendation, or final candidate.
- Never force rollout, rewrite audit results, or simulate live passes to make a gate green.
- Never treat backtest, shadow output, website score, or Telegram output as a trade order.
- Never expose secrets or commit `.env`, tokens, passwords, private chat IDs, or credentials.
- Never push, deploy, send Telegram, or change production state unless explicitly requested.
- Work with existing dirty files; do not reset or revert user changes.

## Runtime Order That Matters

`run-daily` uses this relevant sequence:

```text
ingest -> data quality -> features -> V1 score
-> V2 train/infer shadow
-> promotion evaluates the previous matching accuracy audit
-> current accuracy audit is generated
-> per-mode rollout selection
-> reports/dashboard/notification/reconciliation
```

The one-run audit delay after a new model version is intentional. Promotion must not use an
audit produced by a different artifact version.

## Minimal Source Map

| Task | Read source | Read test |
|---|---|---|
| V2 train/calibration/WF | `src/model_v2/train.py`, `src/model_v2/calibration.py` | `tests/test_model_v2_final_stage.py`, `tests/test_model_v2_upgrade.py` |
| Promotion/rollback | `src/model_v2/promotion.py` | `tests/test_model_v2_promotion.py`, `tests/test_model_v2_final_guardrails.py` |
| Accuracy/meta-filter | `src/analytics/model_v2_accuracy.py`, `src/model_v2/meta_filter.py` | `tests/test_model_v2_accuracy.py`, `tests/test_model_v2_final_stage.py` |
| Daily wiring | relevant section of `src/cli.py` | nearest CLI/pipeline test |
| Dashboard | `web/js/dashboard.js` | `node --check web/js/dashboard.js` |
| Config | `src/config.py`, one active preset | config validation plus affected tests |

Read `docs/MODEL_V2_BLUEPRINT.md` only for Model V2 product design. Read other files in
`docs/ai-context/` only when the table above is insufficient.

## Work Still Required Before Final

This is model-quality work, not a reason to bypass gates:

1. Improve T1 labels/features/regime segmentation until performance is positive and stable
   across at least three of five folds, then meet the full 60%/PF/expectancy contract.
2. Redesign or retrain Swing; its current holdout AUC and zero-trade result prohibit rollout.
3. Generate a version-matched accuracy audit with at least 120 eligible OOS outcomes per mode.
4. Collect 20-30 real shadow market sessions, then three consecutive passing evaluations.
5. Promote T1 independently to 10% canary only after gates pass; keep Swing at 0%.
6. Preserve PF, expectancy, ECE, drawdown, and reconciliation at every rollout stage.

## Validation And Handoff

Minimum Model V2 validation:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_model_v2_promotion.py tests/test_model_v2_final_guardrails.py tests/test_model_v2_final_stage.py tests/test_model_v2_accuracy.py tests/test_model_v2_upgrade.py
node --check web/js/dashboard.js
git diff --check
```

Before ending a coding task, state: changed files, tests run, measured blockers, and whether
anything was committed, pushed, or deployed. Update this PRD only when product contracts,
runtime order, current evidence, or the recovery route materially changes.
