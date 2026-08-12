# Production EOD Reconciliation Runbook

## Purpose

DATA-03 verifies canonical IDX closes against an independent source before data is
eligible for final-decision or execution gates. This runbook defines two distinct modes:

- same-day production reconciliation, which can qualify production evidence;
- free-tier deferred reconciliation, which is delayed research evidence only.

Neither mode authorizes Model V2 promotion or broker execution by itself.

## Source Contracts

### Same-Day Production

- Primary: configured paid/licensed REST provider, reported as `rest`.
- Reference: yfinance, reported as `yfinance_reconciliation`.
- At least 95% of the active 45-ticker universe must reconcile for the session.
- Five consecutive completed IDX sessions must pass before required enforcement.
- This remains unavailable while EODHD free capacity is limited to 20 calls/day.

### Free-Tier Deferred

- Daily primary: Yahoo for all 45 active tickers, reported as `yfinance_primary`.
- Delayed reference: EODHD free-tier historical batches, reported as
  `eodhd_deferred`.
- One Jakarta calendar date may collect at most 15 tickers; five calls remain reserved.
- Each request retrieves a bounded historical window, so three distinct daily batches
  can create complete historical session coverage for all 45 tickers.
- Retries on the same Jakarta date perform zero provider-account and ticker requests.
- A deferred pass is always `same_day_reconciliation=false` and
  `final_execution_eligible=false`.

The API token exists only in `EODHD_API_TOKEN`. Never store or print the value
in config, source, reports, screenshots, command arguments, or logs.

## Commands

Validate configuration without network access:

```powershell
python -m src.cli check-eod-reconciliation-readiness
```

Check whether the current account can cover today's planned batch:

```powershell
python -m src.cli check-eod-provider-account
```

Collect one idempotent free-tier batch and refresh delayed audit evidence:

```powershell
python -m src.cli collect-deferred-eod-reconciliation
```

The collector exits normally when evidence is still collecting or quota is unavailable;
its structured `status` and `account.reason_codes` carry the truth.
The production workflow preserves those artifacts for inspection.

EODHD resets daily limits at midnight GMT/UTC, but its User API keeps reporting the
previous active day's `apiRequests` until the first data request after reset. Preflight
therefore applies these rules:

- when `apiRequestsDate` is before the current UTC date, effective used calls are zero;
- `reported_used_calls` preserves the provider value and `quota_reset_applied=true`
  records the adjustment;
- a same-date counter is enforced as reported;
- a missing, invalid, or future usage date blocks collection.

## Deferred Artifacts

- `data/raw/deferred_eodhd_reference.csv`: canonical deduplicated EODHD cache;
- `reports/deferred_eod_reconciliation_state.json`: batch rotation and
  same-day idempotency state;
- `reports/deferred_eod_reconciliation.json`: quota, coverage, lag, source,
  mismatch, and eligibility status;
- `reports/deferred_eod_reconciliation_details.csv`: ticker/session comparison.

The report includes a SHA-256 digest of the cache. Cache retention is bounded by
configuration and raw rows are never rewritten to match Yahoo.

## Deferred Qualification

Deferred research evidence passes only when:

1. all selected provider rows validate as canonical OHLCV;
2. at least five historical sessions have at least 95% active-universe coverage;
3. close differences above 1% affect at most 5% of compared rows;
4. cache and detail evidence persist;
5. the report remains marked delayed and ineligible for final execution.

A pass helps detect data errors and supports research dataset quality. It does not count
toward the five consecutive same-day production sessions.

## Same-Day Qualification

A production session qualifies only when:

1. `primary_source=rest`;
2. `reference_source=yfinance_reconciliation`;
3. reconciliation status is `pass`;
4. coverage is at least 95%;
5. mismatch ratio is at most 5%;
6. no active unresolved price anomaly exists;
7. the date is a valid IDX session in the verified calendar.

Only this track may eventually support `reconciliation_required=true`, after
five consecutive real sessions and a reviewed change.

## Failure Triage

- `provider_account_token_missing`: configure the named secret without printing it.
- `provider_daily_limit_below_universe_requirement`: the plan cannot cover the
  planned request scope.
- `provider_remaining_quota_insufficient`: do not fetch; wait for the next reset.
- `provider_account_usage_date_invalid`: do not infer a reset; inspect provider payload.
- `provider_account_usage_date_in_future`: stop and inspect clock/provider metadata.
- HTTP 401: verify credential validity and secret mapping.
- HTTP 402: verify entitlement; do not misreport it as a missing token.
- HTTP 429: stop the batch and preserve partial state; do not retry repeatedly.
- `collecting`: fewer than 45 cached tickers or fewer than five complete sessions.
- `failed`: inspect detail rows and corporate-action evidence; never suppress mismatch.
- Same-day warning `price_reconciliation_unavailable` is expected in deferred mode
  and must remain visible.

## Upgrade Path

When a user activates sufficient same-day licensed capacity:

1. disable `deferred_eod_reconciliation.use_yfinance_as_daily_primary`;
2. confirm full-universe provider quota;
3. restore REST primary plus independent Yahoo reference;
4. collect five consecutive same-day sessions;
5. enable required enforcement only in a reviewed commit;
6. keep `EXECUTION_DISABLED` until all model, risk, broker, and canary gates pass.
