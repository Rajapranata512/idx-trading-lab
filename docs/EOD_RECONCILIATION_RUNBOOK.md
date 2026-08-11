# Production EOD Reconciliation Runbook

## Purpose

DATA-03B verifies canonical IDX closes against an independent provider before model,
dashboard, or notification artifacts are treated as production quality. This runbook
does not authorize model promotion or broker execution.

## Source Contract

- Primary: configured REST provider, currently EODHD, reported as `rest`.
- Reference: yfinance used only as `yfinance_reconciliation` while primary is REST.
- A yfinance primary fallback cannot reconcile against yfinance and remains unavailable.
- The API token exists only in `EODHD_API_TOKEN`; never put its value in config, source,
  command arguments, reports, screenshots, or logs.

## Preflight

Run without network access:

```powershell
$env:EODHD_API_TOKEN = Read-Host "EODHD API token"
python -m src.cli check-eod-reconciliation-readiness
```

The output may list required or missing environment variable names, but never values.
A missing token exits non-zero before an HTTP request, preventing the old HTTP 401 path.

For GitHub Actions, set `EODHD_API_TOKEN` through the repository secret UI or an
approved interactive secret command. Do not pass the value on the command line. Triggering
or editing a GitHub secret is an external action and requires explicit user approval.

## Evidence Produced

Each completed reconciliation writes:

- `reports/price_reconciliation.json`: summary and qualification status;
- `reports/price_reconciliation_details.csv`: expected, matched, and mismatched rows;
- `data/raw/price_reconciliation/<market-date>/`: provider snapshots, comparison, and
  SHA-256 evidence;
- `reports/price_reconciliation_evidence.json`: idempotent per-market-date ledger.

Retries replace the same market-date ledger entry instead of inflating session count.
The ledger uses `web/idx_market_calendar.json`; missing or expired calendar evidence
blocks qualification.

## Qualification Gate

A session qualifies only when all are true:

1. `primary_source=rest`;
2. `reference_source=yfinance_reconciliation`;
3. reconciliation status is `pass`;
4. coverage is at least 95%;
5. mismatch ratio is at most 5%;
6. no active unresolved price anomaly exists;
7. the date is a valid IDX session in the configured calendar.

Five consecutive expected IDX sessions must qualify. A missing session, failed session,
provider substitution, calendar problem, low coverage, mismatch, or unresolved anomaly
resets the consecutive window.

## Enforcement Sequence

1. Keep `reconciliation_required=false` while collecting the first five real sessions.
2. Investigate every mismatch and preserve provider evidence; never suppress a row to
   make the gate pass.
3. After the ledger reports `qualified=true`, change `reconciliation_required=true` in a
   reviewed commit.
4. Prove unavailable and failed reconciliation both block `run-daily`.
5. Keep `EXECUTION_DISABLED`; DATA-03B does not promote Model V2 or enable orders.

## Failure Triage

- `provider_environment_ready=false`: configure the named GitHub secret.
- `unexpected_primary_source`: REST failed and fallback became primary; fix REST first.
- `unexpected_reference_source`: independent reference is missing or misconfigured.
- `coverage_below_threshold`: inspect missing ticker/date rows in the details CSV.
- `mismatch_above_threshold`: compare provider snapshots and corporate-action evidence.
- `market_calendar_unavailable`: repair or update the verified IDX calendar.
- `active_unresolved_price_anomaly`: resolve or quarantine using traceable evidence.