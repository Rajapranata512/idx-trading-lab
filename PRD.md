# PRD - IDX Trading Lab

Revision: 2026-08-12

Owner: Project repository
Status: Active, research/shadow, not final decision

This is the single product source of truth. Technical detail stays in linked
runbooks; volatile run output stays in structured reports.

## Agent Resume Block

Read this block after `AGENTS.md`. Do not scan the repository.

- Product: regime-aware, risk-first decision and execution platform for IDX equities.
- Policies: every T1/Swing, bullish/sideways/bearish, and long/short/hedge policy is
  evaluated and promoted independently.
- End state: an evidence-gated portfolio engine seeks positive after-cost expectancy
  across a complete market cycle and may submit controlled broker orders only after
  every model, regime, risk, execution, security, and reconciliation gate passes.
- Current state: `EXECUTION_DISABLED`; Model V2 is `SHADOW/BLOCKED`,
  rollout 0%, and no broker order is authorized.
- Evidence: Daily Pipeline run `31574193633` completed the first deferred batch
  and pushed production artifact commit `ebe3813` to `origin/main` and Vercel.
- EODHD free capacity cannot validate all 45 tickers on the same day. The approved
  interim design keeps Yahoo as daily primary and rotates a 15-ticker EODHD historical
  batch once per Jakarta date until delayed research coverage is complete.
- Deferred evidence can improve historical data auditing, but it is explicitly
  `final_execution_eligible=false`; same-day independent reconciliation remains unavailable.
- Primary blocker: same-day provider capacity and then statistical quality, not UI score quantity.
- Next Action: complete the remaining two deferred collection dates so the rotating
  batches advance from 15/45 to 45/45 tickers without duplicate quota consumption.
- Parallel research foundation: raw 5m/15m, timestamp-safe sentiment, and licensed
  IEP/IEV/order-book pre-open analysis are approved directions but remain disabled.
- Never bypass a gate, lower thresholds for signal quantity, fabricate evidence,
  push/deploy/send externally, or promote without required authority.

On reset, next read only Current State, Active Blockers, Next Action, and the
requirement being changed. Use `AGENTS.md` for routing and validation.

## 1. Product Vision

IDX Trading Lab turns Indonesian equity data into auditable, regime-aware portfolio
decisions, risk-controlled trade plans, measured outcomes, and eventually controlled
final execution across bullish, sideways, and bearish markets.
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

Long-term multi-regime objective:

1. Bullish: capture verified long momentum/relative-strength edge after costs.
2. Sideways: use separately validated selective long or mean-reversion policies;
   otherwise remain in cash through an explicit `NO_TRADE` decision.
3. Bearish: preserve capital through `RISK_OFF` by default; seek positive expectancy
   only through a separately modeled, legally/broker-supported short or hedge policy.
4. Full cycle: combine only promoted policies to pursue positive compounded return
   after fees, slippage, borrow/hedge costs, and drawdown limits.

This is an engineering and research objective, not a guarantee of profit in every
session or regime. Capital preservation and abstention remain successful decisions
when no policy has proven positive edge.

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
- features, V1 ranking, T1/Swing risk plans, point-in-time regime classification,
  and independently qualified bullish/sideways/bearish policies;
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
- short or hedge execution before separate data, model, borrow/fee, broker,
  compliance, risk, and activation contracts pass;
- derivatives, forex, crypto, or non-IDX markets in the current release;
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
- EOD reconciliation activation: `docs/EOD_RECONCILIATION_RUNBOOK.md`;
- V2 design: `docs/MODEL_V2_BLUEPRINT.md`.

## Current State

Last verified on 2026-08-12:

- PR #4 was merged as `0141801`. Successful production Daily Pipeline run
  `31574193633` then published the first deferred batch as current GitHub main
  `ebe3813`; Vercel reported that deployment complete.
- Production market data is current through 2026-08-12 with 0 stale sessions,
  52,931 rows, 56 represented tickers, no missing critical rows, and no duplicate rows.
  Daily primary source is explicitly `yfinance_primary`.
- Data quality is `warning/pass`: the historical GOTO 2023-05-31 outlier remains
  traceable to its verified event, unresolved active anomalies are 0, and the only
  current warning is `price_reconciliation_unavailable`.
- Same-day independent reconciliation is not operational. Reference source is empty,
  0 rows were compared, and no qualifying production reconciliation session exists.
- Provider account metadata reported `subscriptionType=free`,
  `dailyRateLimit=20`, and `apiRequests=20` on 2026-08-11. A same-day complete run
  needs at least 45 ticker calls, so the account cannot satisfy 95% universe coverage.
- The free-tier deferred collector is deployed: Yahoo is the daily 45-ticker source, EODHD is
  limited to one idempotent 15-ticker historical batch per Jakarta date, and a five-call
  reserve protects against quota variance.
- The reset-aware collector completed AADI through BUMI: 15/15 requests succeeded,
  no ticker failed, cache coverage is 15/45 (33.3333%), and SHA-256 evidence is
  `02e280d980a78341f4256fa66b76c1195c67d9db0f0260668bcd34d6436621b2`.
- Post-batch account metadata reports 15 calls used and five remaining on 2026-08-12.
  Generic preflight for another 15-ticker batch is quota-blocked, while collector state
  prevents the duplicate attempt before any account or ticker request.
- Deferred cache, state, coverage, mismatch, lag, and details are machine-readable.
  Even a passing deferred audit remains research-only and cannot satisfy the same-day
  production reconciliation or final-execution gate.
- Reset-aware quota validation: 20 focused tests and the full 185-test Python
  regression pass.
- `reconciliation_required` remains false until five consecutive real IDX
  sessions qualify; no qualifying reconciliation session exists yet.
- `FINAL_EXECUTION` remains the approved end-state, while the broker layer is
  unimplemented and the current runtime state is `EXECUTION_DISABLED`.
- The local pre-open auction foundation remains disabled and unpushed. It has no
  licensed provider feed, qualified model artifact, or real shadow-session evidence.

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
- `INTRA-01 Immutable 5m base`: licensed raw 5-minute OHLCV is append-only, timestamped
  in Asia/Jakarta, versioned, and backfilled for at least three years where available.
- `INTRA-02 Canonical 15m model bars`: 15-minute bars are deterministic session-aligned
  aggregates of 5-minute data; gaps, duplicates, partial bars, and corporate actions gate use.
- `INTRA-03 Effective samples`: evaluation splits by purged market date and reports
  independent ticker-session counts; snapshot row count cannot inflate sample claims.
- `PREOPEN-01 Licensed auction feed`: IEP, IEV, rule version, source, receive time, and
  five-level depth or order events require explicit storage/usage rights and immutable lineage.
- `PREOPEN-02 Fixed clock`: preliminary analysis is 08:55 WIB, the feature cutoff is
  08:57:40 WIB, matching/post-open data cannot enter prediction, and late data returns NO_TRADE.
- `SENT-01 Event provenance`: official disclosures and licensed news store publication/
  collection time, source tier, ticker mapping, event type, novelty, and confirmation state.
- `SENT-02 No leakage`: only information published before the decision cutoff may join
  a candidate; edits, duplicates, and collection latency remain auditable.
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
- `PREOPEN-03 Separate labels`: opening direction, after-cost 5/15-minute follow-through,
  and fake-gap reversal are separate point-in-time targets with MAE/MFE.
- `PREOPEN-04 Artifact gate`: a complete calibrated multi-target artifact, untouched
  holdout, ECE <= 10%, at least 120 OOS ticker-sessions, and five purged folds are minimum
  shadow inference requirements; they do not bypass final-decision promotion.
- `SENT-03 Ablation proof`: sentiment is retained only when technical+auction+sentiment
  improves untouched after-cost expectancy, calibration, false positives, and drawdown.
- `SENT-04 Meta-filter only`: rumor, social text, or LLM output can raise event risk or
  confidence context but can never directly authorize an order.
- `V2-01 Real artifacts`: a loadable model and versioned metadata are mandatory;
  fallback probability cannot produce recommendation or final state.
- `V2-02 Calibration`: calibration fits on a separate window and is evaluated
  on untouched holdout data.
- `V2-03 Walk-forward`: threshold and edge must be stable across purged folds,
  not selected from one attractive small sample.
- `V2-04 Agreement filter`: initial eligible candidates require V1/V2 agreement,
  positive EV, passing calibration, and a Bayesian ticker-edge filter.
- `V2-05 Independent policies`: each mode, regime, and side has separate eligible
  samples, thresholds, audits, shadow sessions, rollout, and rollback.
- `REGIME-01 Point-in-time regime`: bullish, sideways, and bearish labels use only
  information available at decision time and are versioned with every outcome.
- `REGIME-02 Specialized policy`: no universal threshold may claim all-regime edge;
  the router selects only a policy promoted for the current regime or returns no-trade.
- `REGIME-03 Bearish separation`: short/hedge labels include borrow availability,
  borrow/hedge costs, asymmetric risk, and broker constraints and cannot inherit
  approval from a long-only model.
- `REGIME-04 Portfolio orchestration`: the final portfolio combines promoted cells
  under shared exposure, correlation, drawdown, and capital-preservation limits.
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

A `{mode, regime, side}` policy may become final only when all conditions pass on
the exact model, regime classifier, label, feature, and cost-model versions:

1. Point-in-time labels match live candidate and execution assumptions.
2. A real loadable artifact exists; no fallback output is eligible.
3. Calibration is separate from fitting and evaluated on untouched holdout:
   `calibrated=true`, `evaluated_on_holdout=true`, ECE <= 10%, AUC >= 0.52.
4. At least five purged walk-forward folds and at least 120 eligible OOS trades exist
   for the exact policy cell being promoted.
5. Walk-forward median PF >= 1.25, median expectancy > 0.03R, MaxDD <= 12%, and
   at least 60% of folds are profitable.
6. The fresh accuracy audit uses model-only output and matches artifact version,
   label contract, mode, costs, threshold, and candidate policy.
7. Eligible candidates pass V1/V2 agreement, positive EV, calibration, liquidity,
   point-in-time regime routing, event risk, and Bayesian ticker-edge checks.
8. At least 20 real market shadow sessions exist and three consecutive promotion
   evaluations pass. Sessions cannot be fabricated or backfilled.
9. Canary stages maintain PF, expectancy, ECE, drawdown, data quality, and live
   reconciliation; a failed safety gate rolls the mode back to 0%.
10. Risk engine, kill switch, and manual approval remain authoritative at 100%
    model rollout; broker submission remains disabled until section 8 passes.

Promotion state machine, per `{mode, regime, side}` policy:

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

1. The selected mode, regime, and side policy is `FINAL 100%` and all section 7
   evidence is fresh.
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

Model quality, per `{mode, regime, side}` policy:

- expectancy R and profit factor after all applicable costs;
- precision at top 3/top 5 and false-positive rate;
- calibrated ECE/Brier score and reliability bins;
- OOS trade count, profitable-fold ratio, and threshold stability;
- MaxDD, MAE/MFE, average win/loss R, and signal decay.

Full-cycle portfolio quality:

- positive compounded return after costs across untouched multi-regime evaluation;
- contribution, exposure, turnover, and drawdown segmented by market regime;
- bearish downside protection and short/hedge performance reported separately;
- no-trade frequency and avoided-loss evidence, without counting abstention as profit;
- policy correlation and portfolio-level drawdown under shared risk limits.

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
4. No bullish/sideways/bearish policy matrix has sufficient independent OOS evidence;
   the bearish short/hedge track is not implemented or authorized.
5. Pre-open Vercel secrets, watchdog dispatch, and duplicate-free external delivery
   still require a complete production health check.
6. Universe history has only two official periods, insufficient for long historical
   survivorship-bias-safe claims.
7. Same-day independent price reconciliation is unavailable. Free EODHD capacity cannot
   cover all 45 tickers; the deferred 15-ticker/day collector can create delayed
   research evidence only and no qualifying production session exists.
8. No licensed retained 5-minute/pre-open IEP/IEV/order-event feed or compatible
   historical backfill is configured; the pre-open module therefore remains disabled.
9. No qualified pre-open artifact, timestamp-safe sentiment dataset, or real auction
   shadow-session evidence exists; no current ticker may be called an auction recommendation.
10. Real shadow sessions, consecutive passes, and live reconciliation are insufficient
    for canary promotion.
11. No production broker adapter, immutable order-intent store, or broker execution
    state machine exists yet.
12. Paper execution, failure-injection, kill-switch drill, and live-canary evidence
    required by section 8 have not been collected.
13. Live account activation is intentionally absent; current execution status is
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

Status: production data is fresh; independent reconciliation is blocked by provider capacity.

- Import older official universe periods.
- Establish dependable independent EOD reconciliation.
- Verified non-corporate event annotations resolve exact-date historical outliers
  without modifying raw or adjusted OHLCV; GOTO 2023-05-31 is the first entry.
- Resolve/annotate corporate actions and recurrent price outliers.
- Version immutable research datasets and feature contracts.
- Backfill licensed raw 5-minute bars, derive canonical 15-minute bars, and record
  effective ticker-session samples without treating correlated snapshots as independent.
- Acquire licensed historical/forward IEP, IEV, order-book/event data and timestamp-safe
  official disclosure/news events under explicit retention terms.

Exit: reproducible point-in-time research window with documented coverage and no
unresolved active quality blocker.

### Phase 4 - Candidate Edge Redesign

Status: pending; T1 first, Swing remains 0%.

- Add market/sector-relative, liquidity, point-in-time regime, and entry-gap features.
- Qualify a separate pre-open auction policy for opening, follow-through, and fake-gap
  outcomes; its alert is shadow observation until its own promotion evidence passes.
- Compare technical baseline, plus IEP/IEV, plus order book, and plus sentiment through
  a versioned ablation before accepting additional complexity.
- Define independent bullish-long, sideways-selective, and bearish-risk-off policy
  cells; research short/hedge only as a separately authorized track.
- Evaluate discovery data, then confirm on a later untouched period.
- Reject complexity that does not improve stable after-cost expectancy.
- Increase eligible OOS samples without lowering quality thresholds.

Exit: candidate edge passes minimum folds/trades and final numeric contract.

### Phase 5 - Model V2 Qualification

Status: pending.

- Fit and version separate T1/Swing models by eligible regime and side.
- Keep any bearish short/hedge model isolated from long-policy promotion evidence.
- Calibrate on dedicated windows and test on untouched holdout.
- Lock thresholds before final evaluation.
- Produce version-matched accuracy, false-positive, and calibration audits.

Exit: all section 7 gates pass for one mode. T1 may progress while Swing stays blocked.

### Phase 6 - Shadow, Canary, And Rollback

Status: pending.

- Collect at least 20 real market sessions and three consecutive passing evaluations.
- Promote each `{mode, regime, side}` policy independently through 10%, 30%, 60%,
  and 100%; an unqualified cell remains `NO_TRADE`.
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

`DATA-03C Free-tier deferred EOD evidence rollout` is the single next action.

The collector is deployed and the first successful production batch is verified.
Production must complete two more distinct-date batches and then evaluate delayed audit
behavior before this interim path is considered operational.

Acceptance criteria:

1. **Verified 2026-08-12:** daily ingestion uses `yfinance_primary` and does not attempt
   a full-universe EODHD fan-out while deferred mode is enabled.
2. **Partially verified:** production used exactly 15 calls and retained the five-call
   reserve. Another generic batch is quota-blocked; collector no-account-call idempotency
   is covered by automated tests and awaits the next scheduled production retry.
3. **In progress, 1/3 dates:** the first batch persisted 15/45 canonical tickers with
   no failures and SHA-256 cache evidence. Two successful distinct-date batches remain.
4. At least five historical sessions reach 95% ticker coverage, mismatch ratio at most
   5%, and no active unresolved anomaly; every mismatch is investigated.
5. Reports expose source, batch, cache coverage, lag, mismatch, and
   `final_execution_eligible=false`. Deferred pass never sets
   `reconciliation_required=true` or promotes Model V2.
6. Same-day independent reconciliation remains the later DATA-03B requirement before
   final decision/execution; paid capacity or an approved licensed CSV/provider is still needed.
7. After three successful dates, update this PRD with measured coverage/mismatch evidence
   and exactly one successor action.

Likely files: deferred reconciliation reports/cache/state, Daily Pipeline output,
nearest data-quality tests, and this PRD.

## 11. Portfolio Release Checklist

A public portfolio release is ready when:

- [ ] README starts with problem, architecture, demo, evidence, setup, and limitations.
- [ ] Public dashboard is current, responsive, accessible, and truthful.
- [ ] CI runs focused Python/Node tests and blocks broken builds.
- [ ] Sample/demo data is reproducible and contains no secrets/private identifiers.
- [ ] Data lineage and point-in-time universe behavior are documented.
- [ ] Model card states training/calibration/test windows and per-mode metrics.
- [ ] Accuracy audit shows sample sizes and uncertainty, not only headline win rate.
- [ ] Bullish, sideways, and bearish results are segmented; unsupported regimes are
  visibly no-trade and no result implies guaranteed all-weather profit.
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

- 2026-08-12: merged and deployed free-tier deferred reconciliation. Production run
  `31574193633` passed and published commit `ebe3813` after PR #4 corrected EODHD's
  stale previous-day counter behavior. Batch 1/3 succeeded for 15/45 tickers with no
  failures, retained five calls, and remained research/final-execution ineligible.
  The next action is the two remaining distinct-date batches.
- 2026-08-12: approved an interim free-tier deferred reconciliation track. Yahoo remains
  the complete daily source; EODHD rotates 15 historical tickers once per Jakarta date,
  with idempotent retries, retained cache, and explicit delayed/research-only status.
  It cannot satisfy same-day final-decision or execution gates.
- 2026-08-11: activated the approved GitHub EOD token secret and verified successful
  production run 31491250242/commit `b2996b8`. Fresh data exported, but EODHD
  returned HTTP 402 because its free 20-call quota cannot cover 45 tickers; yfinance
  fallback left reconciliation unavailable. A local fail-closed quota probe now prevents
  wasteful ticker fan-out. Provider-plan choice remains user-controlled and execution
  stays disabled.
- 2026-08-11: approved raw 5-minute storage with canonical 15-minute modeling,
  timestamp-safe official/licensed sentiment, and a separate IEP/IEV/order-book
  pre-open shadow track. Alerts target 08:55 and 08:57:40 WIB; opening direction,
  follow-through, and fake gaps are separate labels, and no feed/model means NO_TRADE.

- 2026-08-11: set the long-term goal to an evidence-gated multi-regime portfolio
  engine. Bullish long, sideways selective/no-trade, and bearish risk-off or separately
  qualified short/hedge policies must prove after-cost edge independently; profit is
  an objective, never a guarantee, and unsupported cells remain no-trade.
- 2026-08-11: pushed verified price-event remediation as `e79891b`. Daily Pipeline
  run 31413187445 and one rerun failed before export because `EODHD_API_TOKEN` was
  empty and yfinance returned 45 invalid rows; no validator or production gate was weakened.
- 2026-08-11: separated source-traceable non-corporate price events from corporate
  actions. A verified event can resolve only an exact ticker/date anomaly and cannot
  adjust OHLCV. Local audit resolves GOTO 2023-05-31; production artifact export
  remains blocked on an operational independent EOD source.
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
