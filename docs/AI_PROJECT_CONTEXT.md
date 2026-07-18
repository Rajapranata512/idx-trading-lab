# PRD and AI Recovery Contract - IDX Trading Lab

Revision: 2026-07-18
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

Execution-aligned validation on 2026-07-18 used point-in-time V1 scores, the same score
floor/top-N candidate set as live, next-session-open entry, conservative first-touch
stop/TP outcomes, and fee/slippage-adjusted returns:

- T1: 2,080 labeled rows, holdout AUC 0.5286, ECE 1.88%, five purged walk-forward
  folds, and 41 OOS trades. No fold was profitable, so both stability and minimum-trade
  gates fail despite acceptable calibration.
- Swing (10-day horizon): 748 labeled rows, holdout AUC 0.6206, ECE 17.39%, five folds,
  and 141 OOS trades. Only one fold was profitable and median PF/expectancy were zero;
  calibration and stability gates fail. A tested 5-day horizon was worse and was rejected.
- The unfiltered candidate pools were negative after costs in the diagnostic sample:
  T1 expectancy -0.1231R/PF 0.4369 and Swing -0.1229R/PF 0.7509. No single feature
  quartile produced stable positive edge in both discovery and later holdout periods.
- Therefore the honest product state remains `SHADOW/BLOCKED`, rollout 0%, not `FINAL`.

These are validation findings, not a promise of future returns. Runtime status must always
be read from current model metadata, accuracy audit, promotion state, and reconciliation.

## Final Decision Contract

Promotion is independent for `t1` and `swing`. A mode may move through
`SHADOW -> CANARY 10% -> 30% -> 60% -> FINAL 100%` only when all checks pass:

1. Labels use point-in-time scores, the live score-floor/top-N candidate contract,
   next-session-open entry, first-touch stop/TP, and configured costs. Entries opening
   outside the planned stop/TP range are rejected from both training and paper execution.
2. A real, loadable model artifact exists; heuristic probability fallback is forbidden.
3. Calibration uses a window separate from model fitting and is evaluated on untouched
   holdout data: `calibrated=true`, `evaluated_on_holdout=true`, ECE <= 10%, AUC >= 0.52.
4. At least five purged walk-forward folds exist, with at least 120 OOS trades, median
   PF >= 1.25, median expectancy > 0.03R, MaxDD <= 12%, and >= 60% profitable folds.
5. The accuracy audit is fresh, uses the exact model version, uses model output only,
   and passes trade count, PF, expectancy, and calibration gates.
6. A live candidate needs V1 and V2 agreement, positive EV, and a passing Bayesian
   ticker-edge filter. Sparse ticker history must shrink to the mode prior, not blacklist.
7. Shadow evidence covers at least 20 real market sessions and passes three consecutive
   evaluations. Do not fabricate or backfill session dates.
8. Canary stages require passing live reconciliation. One failed safety gate rolls the
   affected mode back to 0%; risk engine and kill switch always retain veto authority.

## Non-Negotiable Invariants

- Never lower thresholds merely to produce more signals.
- Never select, calibrate, or tune on the final test window.
- Never calculate a historical cross-sectional score with rows from future dates.
- Never replace first-touch labels with future-return ranks to improve class balance.
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
| V2 labels/execution alignment | `src/model_v2/labeling.py`, `src/strategy/ranker.py`, `src/paper_trading/auto_fill.py` | `tests/test_model_v2_label_alignment.py`, `tests/test_paper_trading.py` |
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

1. Redesign the upstream candidate edge before adding model complexity. Evaluate new
   point-in-time market/sector-relative, liquidity, regime, and entry-gap features using
   discovery data, then accept them only when a later untouched period confirms the gain.
2. Improve T1 until at least 120 eligible OOS trades and three of five profitable folds
   exist, then meet the full median PF/expectancy/drawdown contract.
3. Keep Swing on the 10-day horizon and at rollout 0%. Retrain/resegment it until ECE,
   profitable-fold stability, and median expectancy pass; do not adopt the rejected 5-day test.
4. Generate a version-matched accuracy audit with at least 120 eligible OOS outcomes per mode.
5. Collect 20-30 real shadow market sessions, then three consecutive passing evaluations.
6. Promote T1 independently to 10% canary only after every gate passes; keep Swing at 0%.

## Validation And Handoff

Minimum Model V2 validation:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_model_v2_label_alignment.py tests/test_model_v2_promotion.py tests/test_model_v2_final_guardrails.py tests/test_model_v2_final_stage.py tests/test_model_v2_accuracy.py tests/test_model_v2_upgrade.py tests/test_paper_trading.py tests/test_strategy.py
node --check web/js/dashboard.js
git diff --check
```

Last full regression verification: `128 passed` on 2026-07-18.

Before ending a coding task, state: changed files, tests run, measured blockers, and whether
anything was committed, pushed, or deployed. Update this PRD only when product contracts,
runtime order, current evidence, or the recovery route materially changes.
