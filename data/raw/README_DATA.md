Place raw daily data here.

Minimal input columns for provider/CSV source:

- `date,ticker,open,high,low,close,volume`

Canonical output written by ingest step:

- `date,ticker,open,high,low,close,volume,source,ingested_at`

For public repository hygiene, `data/raw/prices_daily.csv` is ignored by git.
Use `data/raw/prices_daily.sample.csv` as committed example.

Example source row:

`2026-01-02,BBCA,10000,10100,9900,10050,123456789`
