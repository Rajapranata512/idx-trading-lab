# PRD - IDX Trading Lab

Revision: 2026-08-11

Owner: Project repository
Status: Active, research/shadow, not final decision

This is the single product source of truth. Technical detail stays in linked
runbooks; volatile run output stays in structured reports.

## Agent Resume Block

Read this block after `AGENTS.md`. Do not scan the repository.

- Product: risk-first decision-support and research platform for IDX equities.
- Modes: T1 and Swing are evaluated and promoted independently.
- End state: `FINAL_EXECUTION` may submit controlled broker orders after every
  model, risk, execution, security, and reconciliation gate passes.
- Current state: `EXECUTION_DISABLED`; Model V2 is `SHADOW/BLOCKED`,
  rollout 0%, and no broker order is authorized.
- Evidence: the production data/pipeline run is current as of 2026-08-10, but model
  edge and promotion evidence do not pass the final-decision contract.
- Production release: `origin/main` at `b37add5` includes Stage 1-3 and REL-01/REL-02;
  the public Vercel module, calendar, and dashboard wiring returned HTTP 200.
- Local quality remediation verifies the GOTO 2023-05-31 jump as an index-rebalance
  event without adjusting OHLCV; it is not yet committed, pushed, or deployed.
- Primary blocker: statistical quality and stability, not UI score quantity.
- Next Action: activate dependable independent EOD price reconciliation.
- Never bypass a gate, lower thresholds for signal quantity, fabricate evidence,
  push/deploy/send externally, or promote without required authority.

On reset, next read only Current State, Active Blockers, Next Action, and the
requirement being changed. Use `AGENTS.md` for routing and validation.

## 1. Product Vision

IDX Trading Lab turns Indonesian equity data into auditable candidate rankings,
risk-aware trade plans, measured outcomes, and eventually controlled final execution.
It should answer:

1. Is input data trustworthy for the latest completed IDX session?
2. Is there supported edge for this mode, regime, and candidate?
3. Should the system recommend, observe, or reject the trade?
4. What entry, stop, target, size, and invalidation rule control risk?
5. Did paper/live outcomes match model and execution assumptions?
6. When every gate passes, can an idempotent broker order be submitted, protected,
   acknowledged, reconciled, and stopped safely?

The endpoint is not "always predict stocks that rise." It is a system that abstains
when evidence is weak and demonstrates calibrated probability, positive
out-of-sample expectancy, controlled drawdown, and operational reliability.

## 2. Users And Value

Primary user:

- Indonesian retail trader/researcher using disciplined T1 and Swing screening;
- needs explainable plans and risk vetoes instead of raw stock tips;
- executes manually and reviews evidence before acting.

Portfolio audience:

- engineering/data/ML reviewers assessing architecture, reproducibility, testing,
  monitoring, product judgment, and truthful limitations.

Core value: consistent point-in-time research, fewer false positives, clear no-trade
outcomes, and traceability from data to score, model, gate, plan, and result.

## 3. Scope

In scope:

- point-in-time IDX30/LQ45 universe and EOD price quality;
- features, V1 ranking, T1/Swing risk plans, event/regime controls;
- realistic labels, backtests, walk-forward evaluation, and accuracy audits;
- calibrated Model V2 shadow recommendations and independent mode promotion;
- reconciliation, rollback, kill switch, reports, dashboard, and Telegram shadow;
- a future broker execution adapter with paper, canary, idempotency, bracket-order,
  acknowledgement, reconciliation, and emergency-stop controls;
- GitHub/Vercel operations and portfolio-quality documentation/tests.

Not authorized in the current release:

- any broker order while status is `EXECUTION_DISABLED`;
- autonomous real-capital execution before the Final Execution Contract passes and
  the user explicitly enables a named account, mode, and risk policy;
- guaranteed returns or personalized financial advice;
- derivatives, forex, crypto, or non-IDX markets;
- high-frequency execution;
- replacing risk gates with model confidence.

## 4. Product Principles

Priority order:

1. Positive, stable, out-of-sample expectancy after realistic costs.
2. Calibrated probabilities and false-positive control.
3. Data integrity, risk vetoes, rollback, and observability.
4. Reliable delivery and a truthful decision UI.
5. Idempotent, protected, reconciled execution only after decision qualification.
6. Signal quantity only after every quality gate passes.

No-trade is valid. A polished dashboard cannot compensate for stale input, leakage,
weak folds, uncalibrated probabilities, or missing live reconciliation.

## 5. System Boundary And Runtime

Core flow:

```text
point-in-time universe
-> ingest canonical unadjusted OHLCV
-> validate + corporate-action scan + independent reconciliation
-> fail-closed data quality
-> adjusted feature prices
-> V1 score and risk plan
-> V2 train/calibrate/infer in shadow
-> per-mode promotion and meta-filter
-> final gate, reports, dashboard, Telegram shadow
-> execution policy and immutable order intent
-> paper broker adapter and reconciliation
-> live canary/final broker adapter only after explicit activation
-> acknowledgement, bracket protection, reconciliation, and rollback evidence
```

Risk and kill switch remain downstream vetoes. Promotion intentionally uses the
previous version-matched audit; a new audit cannot promote its own run.

Authoritative paths:

- runtime config: `config/settings.json`;
- canonical prices: `data/raw/prices_daily.csv`;
- universe history: `data/reference/universe_history.csv`;
- orchestration: `src/cli.py`;
- Model V2: `src/model_v2/`;
- accuracy audit: `src/analytics/model_v2_accuracy.py`;
- public dashboard: `web/`;
- operations: `docs/STAGE_1_3_OPERATIONS.md`;
- V2 design: `docs/MODEL_V2_BLUEPRINT.md`.

## Current State

Last verified on 2026-08-11:

- GitHub/Vercel production main: `b37add5`; the latest production data artifacts were
  generated by the successful 2026-08-10 Daily Pipeline run.
- Live backtest generated: 2026-08-10T16:25:38.
- Live dashboard generated: 2026-08-10T16:26:19+00:00.
- Production data quality still reports `price_outliers`,
  `historical_unresolved_price_anomalies`, and `price_reconciliation_unavailable`
  until the local remediation is released and a new pipeline run completes.
- Local audit: one historical anomaly, GOTO 2023-05-31 (109 to 147, +34.8624%),
  is resolved by an exact-date, source-traceable MSCI index-rebalance annotation;
  unresolved anomalies 0 and quarantined tickers 0. Raw OHLCV remains unchanged.
- Independent reconciliation remains unavailable because the production primary
  source falls back to yfinance without `EODHD_API_TOKEN`; yfinance cannot be its
  own independent reference. This warning remains truthful and unresolved.
- Maximum production market-data date: 2026-08-10; stale days 0; missing tickers 0.
- REL-01/REL-02 remain deployed and Vercel/GitHub assets were synchronized when checked.
- `FINAL_EXECUTION` is the approved product end-state, but the broker execution
  layer is not implemented and current status is `EXECUTION_DISABLED`.
- Latest local regression: 153 Python and 7 Node tests passed; watchdog JavaScript
  syntax passed. The quality remediation is local only, not committed, pushed, or deployed.

Model research baseline from 2026-07-18:

- T1: 2,080 labeled rows, holdout AUC 0.5286, ECE 1.88%, five purged folds,
  41 eligible OOS trades, and no profitable fold.
- Swing 10-day: 748 labeled rows, holdout AUC 0.6206, ECE 17.39%, five folds,
  141 OOS trades, and only one profitable fold.
- Unfiltered candidate expectancy was negative after costs for both modes.
- Model V2 therefore remains `SHADOW/BLOCKED`; website score cannot override it.

Replace this baseline only with newer versioned, reproducible holdout and
walk-forward evidence.

## 6. Product Requirements

### Data And Reliability

- `DATA-01 Point-in-time universe`: every live date uses the official active
  IDX30/LQ45 period. Missing, expired, overlapping, or invalid membership blocks the run.
- `DATA-02 Auditable prices`: canonical raw OHLCV stays unadjusted; feature prices
  apply only confirmed corporate actions with traceable sources.
- `DATA-03 Price quality`: schema, missingness, duplicates, outliers, active
  unexplained jumps, and independent close reconciliation are machine-readable.
- `DATA-04 Fail closed`: active unexplained anomalies quarantine affected tickers
  and block production according to configuration.
- `REL-01 Market-session freshness`: dashboard freshness uses
  `data_quality_report.stats.max_data_date` against the latest expected completed
  IDX session in Asia/Jakarta, not 24-hour calendar age.
- `REL-02 Timezone contract`: new timestamps are ISO-8601 with `+00:00` or
  explicit Jakarta timezone; browser parsing must not infer timezone.
- `REL-03 Delivery`: pre-open Telegram has primary, retry, idempotency, stale
  report rejection, failure alert, and independent watchdog.
- `REL-04 Observability`: every run exposes stage status, input date, model
  version, gate reason, final action, and external delivery result.
- `REL-05 Retention`: reports/snapshots are pruned only by a documented retention
  policy that preserves KPI and reconciliation lookback.

### Signals, Model, And Risk

- `SIG-01 Candidate contract`: historical and live candidates use the same
  point-in-time score floor, top-N rule, active universe, event gate, and mode.
- `SIG-02 Realistic outcomes`: labels record TP/SL first touch, MAE/MFE,
  fee/slippage-adjusted R, and mode-specific horizon.
- `SIG-03 Abstention`: empty output caused by quality/risk gates is a valid
  no-trade result and is distinguishable from pipeline failure.
- `V2-01 Real artifacts`: a loadable model and versioned metadata are mandatory;
  fallback probability cannot produce recommendation or final state.
- `V2-02 Calibration`: calibration fits on a separate window and is evaluated
  on untouched holdout data.
- `V2-03 Walk-forward`: threshold and edge must be stable across purged folds,
  not selected from one attractive small sample.
- `V2-04 Agreement filter`: initial eligible candidates require V1/V2 agreement,
  positive EV, passing calibration, and a Bayesian ticker-edge filter.
- `V2-05 Independent modes`: T1 and Swing have separate artifacts, thresholds,
  audits, shadow sessions, rollout, and rollback.
- `RISK-01 Veto`: regime, liquidity, event risk, size, data quality, kill switch,
  and drawdown can reject any signal.
- `RISK-02 No guarantee`: the UI and Telegram never describe probability or
  historical performance as guaranteed profit.

### Dashboard And Operations

- `UI-01 Truthful status`: distinguish market-data date, pipeline generation,
  model state, recommendation, and final trade eligibility.
- `UI-02 Explain blocked`: show concise gate reasons without implying system error.
- `UI-03 Accuracy audit`: expose expectancy, PF, threshold evidence,
  calibration, sample count, false-positive segments, model version, and freshness.
- `UI-04 Responsive portfolio UI`: desktop/mobile layout is readable,
  accessible, stable, and free of overlapping controls.
- `OPS-01 Reproducibility`: a clean environment can install, validate config,
  run focused tests, and export the static site using documented commands.
- `OPS-02 CI/deploy integrity`: GitHub Actions commits intended artifacts;
  Vercel serves the exact main revision and deploy health is verifiable.
- `OPS-03 Secret safety`: secrets live only in environment/secret stores and
  public logs/artifacts contain no credentials.
- `PORT-01 Case study`: portfolio presentation explains problem, architecture,
  decisions, metrics, limitations, tests, and screenshots without overstating returns.

### Final Execution Requirements

- `EXEC-01 Immutable intent`: every order has a unique idempotency key, model/data
  version, mode, ticker, side, type, quantity, entry, stop, targets, validity, and reason.
- `EXEC-02 Account allowlist`: environment, broker, account ID/type, currency,
  mode, symbols, and maximum risk policy must match an explicit deployment allowlist.
- `EXEC-03 Atomic pre-trade gate`: immediately before submission, recheck data
  freshness, final model state, market session, price gap, liquidity, exposure, daily
  loss, drawdown, event risk, kill switch, and available buying power.
- `EXEC-04 Idempotent order state`: retries cannot duplicate an order; every
  intent moves through persisted requested, submitted, acknowledged, rejected,
  cancelled, filled, protected, and reconciled states.
- `EXEC-05 Protection`: a filled position must receive acknowledged stop and
  target protection within a configured timeout or trigger cancel/flatten escalation.
- `EXEC-06 Reconciliation`: broker orders, fills, positions, fees, slippage,
  rejects, and protection state reconcile to internal intent and risk records.
- `EXEC-07 Emergency control`: local and remote kill switches can prevent new
  orders and cancel/flatten according to an explicitly tested incident policy.
- `EXEC-08 Fail closed`: timeout, ambiguous broker response, stale quote,
  partial fill, rejected protection, restart, or connectivity loss cannot silently
  become success.
- `EXEC-09 Security`: credentials stay in secret storage with least privilege;
  logs redact credentials and sensitive account data.
- `EXEC-10 Explicit activation`: live execution requires a named account,
  selected mode, risk policy, expiry, and explicit user activation. Default is disabled.

## 7. Final Decision Contract

A mode may become final only when all conditions pass on the exact model version:

1. Point-in-time labels match live candidate and execution assumptions.
2. A real loadable artifact exists; no fallback output is eligible.
3. Calibration is separate from fitting and evaluated on untouched holdout:
   `calibrated=true`, `evaluated_on_holdout=true`, ECE <= 10%, AUC >= 0.52.
4. At least five purged walk-forward folds and at least 120 eligible OOS trades exist.
5. Walk-forward median PF >= 1.25, median expectancy > 0.03R, MaxDD <= 12%, and
   at least 60% of folds are profitable.
6. The fresh accuracy audit uses model-only output and matches artifact version,
   label contract, mode, costs, threshold, and candidate policy.
7. Eligible candidates pass V1/V2 agreement, positive EV, calibration, liquidity,
   regime/event risk, and Bayesian ticker-edge checks.
8. At least 20 real market shadow sessions exist and three consecutive promotion
   evaluations pass. Sessions cannot be fabricated or backfilled.
9. Canary stages maintain PF, expectancy, ECE, drawdown, data quality, and live
   reconciliation; a failed safety gate rolls the mode back to 0%.
10. Risk engine, kill switch, and manual approval remain authoritative at 100%
    model rollout; broker submission remains disabled until section 8 passes.

Promotion state machine, per mode:

```text
SHADOW 0%
-> CANARY 10%
-> CANARY 30%
-> CANARY 60%
-> FINAL 100%
```

Every transition requires fresh evidence. There is no manual "force final" path.

## 8. Final Execution Contract

`FINAL_DECISION` authorizes a model decision; it does not submit an order.
`FINAL_EXECUTION` is a separate system-level state and requires all of these:

1. The selected mode is `FINAL 100%` and all section 7 evidence is fresh.
2. DATA, REL, RISK, and EXEC requirements pass at submission time.
3. The broker adapter is contract-tested for success, reject, timeout, duplicate
   retry, disconnect, partial fill, market close, and protection failure.
4. Paper execution covers at least 30 completed market sessions and 100 accepted
   order intents with zero duplicates and zero silently unprotected positions.
5. At least 99.5% of paper intents reconcile automatically; every remaining mismatch
   is resolved before the next session and no critical incident is open.
6. Kill switch, restart recovery, stale-data rejection, and cancel/flatten procedures
   pass a recorded drill.
7. Live canary uses the minimum configured risk and an explicit ticker/mode allowlist
   for at least 20 executed orders across 20 market sessions.
8. Canary has no duplicate order, unresolved position mismatch, risk-limit breach,
   missing protection, or critical execution incident; observed slippage remains
   inside the configured stress budget.
9. Security, account identity, secret storage, alerting, audit retention, and operator
   runbook are reviewed before each rollout increase.
10. The user explicitly activates the named live account and may revoke activation
    at any time. Expired activation returns to `EXECUTION_DISABLED`.

Execution state machine:

```text
EXECUTION_DISABLED
-> PAPER_EXECUTION
-> LIVE_CANARY
-> FINAL_EXECUTION
```

Any stale model/data evidence, gate failure, ambiguity, reconciliation mismatch,
kill-switch event, or activation expiry blocks new orders and rolls execution back
to the safest valid state. There is no direct path from SHADOW to broker execution.

## 9. Success Metrics

Model quality, per mode:

- expectancy R and profit factor after costs;
- precision at top 3/top 5 and false-positive rate;
- calibrated ECE/Brier score and reliability bins;
- OOS trade count, profitable-fold ratio, and threshold stability;
- MaxDD, MAE/MFE, average win/loss R, and signal decay.

Operational quality:

- completed-session data freshness;
- missing ticker and unresolved anomaly count;
- pipeline success and retry recovery rate;
- Telegram on-time delivery without duplicates;
- GitHub/Vercel revision parity;
- reconciliation coverage and mismatch rate.

Execution quality:

- duplicate-order and unprotected-position count;
- order acknowledgement/protection latency and rejection rate;
- intent-to-broker reconciliation coverage;
- expected versus realized fees/slippage;
- partial-fill, disconnect, rollback, and critical-incident rate;
- kill-switch drill and restart-recovery success.

Portfolio quality:

- CI green on supported environment;
- setup and architecture reproducible from documentation;
- dashboard accurately separates data/model/risk states;
- no secrets, broken routes, stale claims, or misleading profitability language.

## Active Blockers

1. T1 has too few eligible OOS trades and no profitable fold in the recorded baseline.
2. Swing holdout calibration and fold stability fail the contract.
3. Candidate pools do not yet demonstrate stable positive edge after costs.
4. Pre-open Vercel secrets, watchdog dispatch, and duplicate-free external delivery
   still require a complete production health check.
5. Universe history has only two official periods, insufficient for long historical
   survivorship-bias-safe claims.
6. Independent price reconciliation is unavailable because production lacks an
   active independent EOD source; `EODHD_API_TOKEN` is not configured and the
   yfinance fallback cannot reconcile against itself.
7. Real shadow sessions, consecutive passes, and live reconciliation are insufficient
   for canary promotion.
8. No production broker adapter, immutable order-intent store, or broker execution
   state machine exists yet.
9. Paper execution, failure-injection, kill-switch drill, and live-canary evidence
   required by section 8 have not been collected.
10. Live account activation is intentionally absent; current execution status is
    `EXECUTION_DISABLED`.

These blockers are work items, not reasons to weaken thresholds or relabel the product.

## 10. Roadmap

### Phase 0 - Governance And Recovery

Status: complete and deployed.

- Root `AGENTS.md` controls token-efficient agent behavior.
- Root `PRD.md` is the only product state and direction source.
- Duplicate recovery PRD and tracked temporary logs are removed.
- Future agents update material status and one next action automatically.

### Phase 1 - Production Data And Delivery Foundation

Status: deployed; production pipeline green, external delivery health check pending.

- Point-in-time universe with official current period.
- Corporate-action-aware adjusted feature prices and raw auditability.
- Active anomaly quarantine and independent price reconciliation.
- Idempotent pre-open delivery, retry, alert, and Vercel watchdog.

Exit: branch merged, production workflow green, required Vercel secrets configured,
and live health checks verified without sending duplicates.

### Phase 2 - Truthful Freshness And Observability

Status: complete, deployed, and public assets verified.

- Freshness uses the expected completed IDX session and official 2026 holiday calendar.
- Market-data date and timezone-aware pipeline generation time are separate.
- Weekend, holiday, cutoff, missing metadata, invalid date, and missed-session tests pass.
- One missed session warns; two or more missed sessions and invalid evidence block use.
- Price-quality warnings render separately and do not change the freshness calculation.

Exit: satisfied for release `e67d859`; renew the market calendar before its 2026 expiry.

### Phase 3 - Research Data Depth

Status: in progress locally; not committed, pushed, or deployed.

- Import older official universe periods.
- Establish dependable independent EOD reconciliation.
- Verified non-corporate event annotations resolve exact-date historical outliers
  without modifying raw or adjusted OHLCV; GOTO 2023-05-31 is the first entry.
- Resolve/annotate corporate actions and recurrent price outliers.
- Version immutable research datasets and feature contracts.

Exit: reproducible point-in-time research window with documented coverage and no
unresolved active quality blocker.

### Phase 4 - Candidate Edge Redesign

Status: pending; T1 first, Swing remains 0%.

- Add market/sector-relative, liquidity, regime, and entry-gap features.
- Evaluate discovery data, then confirm on a later untouched period.
- Reject complexity that does not improve stable after-cost expectancy.
- Increase eligible OOS samples without lowering quality thresholds.

Exit: candidate edge passes minimum folds/trades and final numeric contract.

### Phase 5 - Model V2 Qualification

Status: pending.

- Fit and version separate T1/Swing models.
- Calibrate on dedicated windows and test on untouched holdout.
- Lock thresholds before final evaluation.
- Produce version-matched accuracy, false-positive, and calibration audits.

Exit: all section 7 gates pass for one mode. T1 may progress while Swing stays blocked.

### Phase 6 - Shadow, Canary, And Rollback

Status: pending.

- Collect at least 20 real market sessions and three consecutive passing evaluations.
- Promote independently through 10%, 30%, 60%, and 100%.
- Require reconciliation and automatic rollback at each stage.

Exit: one mode reaches 100% without violating any safety or evidence contract.

### Phase 7 - Final Execution Safety Layer

Status: approved end-state, not implemented, `EXECUTION_DISABLED`.

- Define immutable order intent and persisted idempotent execution states.
- Implement a broker-neutral interface and paper adapter before any live adapter.
- Contract-test rejects, timeouts, retries, disconnects, partial fills, and protection.
- Complete paper evidence, failure drills, account allowlisting, and live canary.
- Promote execution independently from model promotion under section 8.

Exit: `FINAL_EXECUTION` submits only authorized intents, every position is
protected/reconciled, rollback works, and no unresolved critical incident remains.

### Phase 8 - Portfolio Release

Status: pending, but a research portfolio release may precede final trading promotion.

- Publish architecture, data lineage, test strategy, screenshots, and measured case study.
- Provide one-command local demo or stable public read-only dashboard.
- Explain blocked/no-trade behavior and limitations honestly.
- Verify responsive UI, accessibility, CI, secret scan, deploy health, and links.

Exit: a reviewer can reproduce the demo and understand value, evidence, limitations,
and engineering quality without assuming guaranteed returns.

## Next Action

`DATA-03B Production independent EOD reconciliation activation` is the single next action.

Acceptance criteria:

1. Configure `EODHD_API_TOKEN` as a GitHub Actions secret through an approved external
   action; never store or print the value in repository files or logs.
2. Release the verified-event remediation with explicit push/deploy approval, then run
   Daily Pipeline and confirm `primary_source=rest`, `reference_source=yfinance_reconciliation`.
3. Record at least five consecutive completed market sessions with reconciliation
   coverage at least 95%, mismatch ratio at most 5%, and no unresolved active anomaly.
4. Investigate any mismatch rather than suppressing it; preserve raw provider evidence.
5. After the evidence window passes, set `reconciliation_required=true` and prove that
   unavailable/failed reconciliation blocks production while execution stays disabled.
6. Update this PRD with measured evidence and one successor action; do not promote Model
   V2 or enable broker execution as part of this data-quality task.

Likely files: GitHub Actions secret/config, `config/settings.json`, reconciliation reports,
nearest price-quality/integration tests, and this PRD.

## 11. Portfolio Release Checklist

A public portfolio release is ready when:

- [ ] README starts with problem, architecture, demo, evidence, setup, and limitations.
- [ ] Public dashboard is current, responsive, accessible, and truthful.
- [ ] CI runs focused Python/Node tests and blocks broken builds.
- [ ] Sample/demo data is reproducible and contains no secrets/private identifiers.
- [ ] Data lineage and point-in-time universe behavior are documented.
- [ ] Model card states training/calibration/test windows and per-mode metrics.
- [ ] Accuracy audit shows sample sizes and uncertainty, not only headline win rate.
- [ ] Risk, kill switch, rollback, and no-trade paths are demonstrated.
- [ ] GitHub and Vercel revisions can be reconciled.
- [ ] Case study names failures, decisions, tradeoffs, and next experiments.
- [ ] No claim implies guaranteed returns or autonomous live execution.
- [ ] License and public-repository security checklist are resolved.

Model V2 does not need to be FINAL for an honest research portfolio release. If it is
still shadow, the portfolio must present shadow status as a product-safety strength.

## 12. Validation And Evidence

Minimum production-foundation regression:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_preopen_delivery.py tests/test_stage123_configuration.py tests/test_universe_snapshot.py tests/test_universe_update.py tests/test_price_quality.py tests/test_ingest_validation.py tests/test_integration_cli.py
node --test tests_js/preopen_watchdog.test.js tests_js/preopen_watchdog_handler.test.js
node --check web/api/preopen-watchdog.js
git diff --check
```

Minimum Model V2 regression:

```powershell
python -B -m pytest -p no:cacheprovider tests/test_model_v2_label_alignment.py tests/test_model_v2_promotion.py tests/test_model_v2_final_guardrails.py tests/test_model_v2_final_stage.py tests/test_model_v2_accuracy.py tests/test_model_v2_upgrade.py tests/test_paper_trading.py tests/test_strategy.py
```

Evidence hierarchy:

1. current reproducible test/holdout output;
2. versioned machine-readable reports;
3. current source/config;
4. dashboard screenshot;
5. historical narrative.

Screenshots alone cannot promote a model or prove data freshness.

## 13. PRD Maintenance Contract

Agents update this document automatically only when product facts change:

- replace Current State rather than appending duplicate status;
- mark roadmap exit evidence, not activity;
- keep one Next Action;
- add one compact Decision Log entry per material decision;
- state local, committed, pushed, and deployed status separately;
- never insert secrets, noisy command logs, or unverified claims.

Stable implementation details belong in runbooks. Runtime metrics belong in reports.
This PRD stays compact enough for reset recovery.

## 14. Decision Log

- 2026-08-11: separated source-traceable non-corporate price events from corporate
  actions. A verified event can resolve only an exact ticker/date anomaly and cannot
  adjust OHLCV. Local audit resolves GOTO 2023-05-31; reconciliation remains blocked
  on an independent source. Changes are not yet committed, pushed, or deployed.
- 2026-08-10: Stage 1-3 and REL-01/REL-02 were pushed to `main`; Daily Pipeline
  run 31408655821 passed, produced `e67d859`, and public Vercel asset checks returned
  HTTP 200. Execution remains `EXECUTION_DISABLED`.
- 2026-08-10: established root `AGENTS.md` and `PRD.md` as the only
  agent/product control plane; the old duplicate recovery PRD is retired.
- 2026-08-10: final decision remains per-mode and evidence-gated; portfolio release
  may honestly present a shadow research system before final promotion.
- 2026-08-10: dashboard freshness must use expected completed IDX sessions and
  market-data date, not backtest calendar age.
- 2026-08-10: approved `FINAL_EXECUTION` as the long-term product end-state,
  separated from model `FINAL_DECISION`; live orders remain disabled until
  section 8 and explicit account activation pass.
