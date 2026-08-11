# Production EOD Reconciliation Runbook

## Purpose

DATA-03B verifies canonical IDX closes against an independent provider before model,
dashboard, or notification artifacts are treated as production quality. This runbook
does not authorize model promotion or broker execution.

## Source Contract

- Primary: configured REST provider, currently EODHD, reported as `rest`.
- Reference: yfinance used only as `yfinance_reconciliation` while primary is REST.
- A yfinance primary fallback cannot reconcile against yfinance and remains unavailable.
- The API token exists only in `EODHD_API_TOKEN`; never put its value in config,
  source, command arguments, reports, screenshots, or logs.
- Secret presence alone is not readiness. Provider entitlement, daily limit, and
  remaining quota must cover the complete active universe before ticker requests begin.

## Preflight

After loading the token from an approved local or CI secret store, run:

```powershell
python -m src.cli check-eod-reconciliation-readiness
python -m src.cli check-eod-provider-account
```

The first command validates configuration without network access. The second contacts
the provider account endpoint and exits non-zero when the token is missing, the payload
is invalid, the daily entitlement is below one complete universe, or remaining quota is
insufficient. Output includes only account class and quota counters, never account
identity or credential values.

For GitHub Actions, set `EODHD_API_TOKEN` through the repository secret UI or
an approved interactive secret command. Do not pass the value on the command line.
Creating or changing a secret and dispatching a workflow are external actions requiring
explicit user approval.

## Verified Production Incident: 2026-08-11

- GitHub secret `EODHD_API_TOKEN` was present and Daily Pipeline run
  `31491250242` completed successfully.
- The run exported fresh market data through 2026-08-11 in commit `b2996b8`.
- The primary REST request returned HTTP 402 and ingestion used
  `yfinance_fallback`, so independent reconciliation remained unavailable.
- Provider account metadata reported `subscriptionType=free`,
  `dailyRateLimit=20`, and `apiRequests=20`.
- The active universe contains 45 tickers and requires at least 45 symbol calls for one
  complete run. The free account therefore cannot satisfy the source contract.

Do not treat this as a token-format bug, hide the 402, or lower reconciliation coverage.
A user must activate provider capacity sufficient for the actual scheduled workload or
approve a genuinely independent alternative source. Purchasing or changing a provider
plan is never automatic.

## Evidence Produced

Each completed reconciliation writes:

- `reports/price_reconciliation.json`: summary and qualification status;
- `reports/price_reconciliation_details.csv`: expected, matched, and mismatched rows;
- `data/raw/price_reconciliation/<market-date>/`: provider snapshots, comparison,
  and SHA-256 evidence;
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
3. After the ledger reports `qualified=true`, change
   `reconciliation_required=true` in a reviewed commit.
4. Prove unavailable and failed reconciliation both block `run-daily`.
5. Keep `EXECUTION_DISABLED`; DATA-03B does not promote Model V2 or enable orders.

## Failure Triage

- `provider_environment_ready=false`: configure the named GitHub secret.
- `provider_daily_limit_below_universe_requirement`: entitlement cannot cover one
  complete universe; activate sufficient capacity or an approved independent source.
- `provider_remaining_quota_insufficient`: wait for quota reset or reduce duplicate
  scheduled work without reducing universe coverage.
- HTTP 401: verify credential validity and secret mapping without printing the value.
- HTTP 402: verify plan entitlement/quota; do not misreport this as a missing token.
- `unexpected_primary_source`: REST failed and fallback became primary; inspect the
  preserved provider failure before using the fallback artifact.
- `unexpected_reference_source`: independent reference is missing or misconfigured.
- `coverage_below_threshold`: inspect missing ticker/date rows in the details CSV.
- `mismatch_above_threshold`: compare provider snapshots and corporate-action evidence.
- `market_calendar_unavailable`: repair or update the verified IDX calendar.
- `active_unresolved_price_anomaly`: resolve or quarantine using traceable evidence.
