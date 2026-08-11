# Pre-Open Auction Blueprint

This runbook defines the research-only IEP/IEV and order-book track. It does not
change Model V2 promotion or authorize an order.

## Objective

Estimate three separate outcomes for eligible IDX stocks:

1. opening direction versus previous close;
2. after-cost follow-through from the opening price over 5 and 15 minutes;
3. probability that an indicated gap reverses after the open.

IEP predicts a possible auction-clearing price, not a guaranteed post-open trend.
A missing or weak edge is `NO_TRADE`.

## Exchange Clock

The rule version must be stored with every snapshot. Under the current IDX schedule:

- input: 08:45:00-08:57:59 WIB;
- non-cancellation restrictions begin at 08:56:00 WIB;
- matching: 08:58:00-08:59:59 WIB;
- Session I opens at 09:00:00 WIB.

Authoritative reference:
https://www.idx.id/en/products-services/trading-hours-and-mechanism/

Runtime phases:

- 08:55:00: preliminary shadow watchlist;
- 08:57:40: fixed final model cutoff and Telegram target;
- 09:00 onward: outcome observation only, never retroactive feature input.

GitHub Actions and Vercel Hobby cron are not precision schedulers. Use the local or
persistent-host daemon with a synchronized Asia/Jakarta clock. The daemon is
idempotent per session date and phase.

## Licensed Data Contract

Do not scrape a broker UI or reverse engineer a private endpoint. Confirm provider
license, redistribution limits, and historical retention before enabling collection.
IDX data products are described at:
https://www.idx.id/en/products/idx-data-services/

Canonical snapshot fields:

- `timestamp`, `received_at`, `ticker`, `source`, `rule_version`;
- `previous_close`, `iep`, `iev`, optional `avg_daily_volume_20d`;
- `bid_price_1..5`, `bid_volume_1..5`;
- `ask_price_1..5`, `ask_volume_1..5`.

Store event-level data when licensed. Otherwise collect 1-5 second immutable snapshots.
Five-minute OHLCV bars cannot reconstruct cancellations or IEP/IEV evolution.

## Feature Contract

The current foundation computes:

- IEP gap, path slope, volatility, sign flips, peak reversal, and trough rebound;
- IEV growth, peak retention, and IEV/ADV;
- late-window IEP change and IEV retention after 08:56;
- L1/L5 and distance-weighted depth imbalance;
- spread, microprice versus IEP, and imbalance stability;
- bid/ask depth withdrawal proxies.

A withdrawal proxy is not labeled as a cancellation unless event-level order data
proves the event type.

## Label Contract

Labels use only snapshots at or before 08:57:40 and observed bars after 09:00:

- `y_open_up`;
- `y_follow_up_5m`, `y_follow_up_15m` after round-trip costs;
- `y_follow_down_15m` for risk research, not short authorization;
- `y_fake_gap_up_15m`, `y_fake_gap_down_15m`;
- open gap, gross/net return, MAE, and MFE.

Fit, calibration, threshold selection, and final test dates stay separate. Split by
session date with purging; ticker snapshots from the same date must never appear on
both sides of a split.

## Model Artifact Contract

`models/preopen_auction/preopen_auction.joblib` contains classifiers for opening,
follow-through, and fake-gap targets plus a 15-minute return regressor.
`preopen_auction.meta.json` records feature, label, rule, cutoff, threshold, calibration,
holdout, OOS sample, and walk-forward versions.

Inference is blocked unless:

- the artifact and metadata are loadable and complete;
- calibration and untouched holdout evaluation are true;
- ECE is at most 10%;
- at least 120 OOS ticker-session samples and five folds exist;
- the exact 08:57:40 cutoff and feature contract match;
- snapshots are licensed, complete, and no more than 20 seconds old.

These are minimum inference gates, not automatic final-decision approval. PRD promotion,
shadow-session, risk, and execution contracts remain authoritative.

## Runtime Commands

Dry-run one snapshot file:

```powershell
python -m src.cli run-preopen-auction --as-of 2026-08-11T08:57:40+07:00
```

Run the local scheduler without sending Telegram:

```powershell
python -m src.cli run-preopen-daemon
```

External Telegram delivery requires the explicit `--send-telegram` flag and configured
secrets. Keep `preopen_auction.enabled=false` until provider and retention approval are
recorded. `shadow_only` must remain true throughout research and qualification.

## Sentiment Join

Official disclosures and licensed news may join by ticker and publication timestamp
only when published before the model cutoff. Store source tier, event type, confidence,
novelty, official confirmation, and collection latency. Social rumor is a separate
high-risk source tier and never directly triggers an order.

Prove incremental value with an ablation:

1. technical and regime baseline;
2. baseline plus IEP/IEV;
3. plus order book;
4. plus timestamp-safe sentiment.

Keep the more complex model only when untouched OOS expectancy, calibration,
false-positive rate, and drawdown improve after costs.