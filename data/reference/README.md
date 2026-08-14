# Reference Data

## Point-In-Time IDX Universe

`universe_history.csv` is the authoritative membership history. Every row records a
ticker, index, effective period, and official source document. The pipeline selects the
active period and writes `universe_lq45_idx30.csv` for live ingestion and scoring.

Production validates exactly 45 LQ45 and 30 IDX30 members and blocks when the history is
missing, stale, overlapping, or malformed. Import an official IDX announcement ZIP with:

```powershell
python -m src.cli import-idx-universe-archive `
  --archive C:\path\official-idx-announcement.zip `
  --source-document "https://www.idx.co.id/..."
python -m src.cli update-universe --force
```

The active official snapshot is effective from `2026-08-03` through `2026-10-30`.
History also contains the period from `2026-05-04` through `2026-07-31`. Import the next
official announcement before the active period expires; older periods are still required
for survivorship-bias-safe long-horizon backtests.

## Corporate Actions

`corporate_actions.csv` has this contract:

```text
ticker,effective_date,action_type,ratio,status,source
```

Only confirmed `stock_split` and `reverse_split` rows adjust historical OHLCV. `ratio`
means new shares divided by old shares. Keep the source traceable; never mark an event
confirmed from an unexplained price jump alone.

## Price Reconciliation Incidents

`price_reconciliation_incidents.csv` preserves source values and root-cause disposition
for historical reconciliation differences. It is evidence, not a correction feed:

- never edit a raw provider value to force agreement;
- record the original primary/reference values and immutable evidence paths;
- mark an incident resolved only after the ingestion fix and a rerun prove the result;
- keep same-day and final-execution eligibility independent from incident status.

## Event Risk

`event_risk_blacklist.csv` blocks risky tickers from live signals. The frequently refreshed
live file is ignored by git; `event_risk_blacklist.sample.csv` is the tracked baseline.
Statuses are controlled by `pipeline.event_risk.active_statuses`. Refresh manually with:

```powershell
python -m src.cli update-event-risk --force
```
