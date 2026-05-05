# Live Reconciliation (Signal vs Broker Fill)

## Tujuan

Mengukur deviasi antara plan sistem dan eksekusi riil:

- coverage: berapa fill yang cocok dengan sinyal,
- biaya: slippage + fee riil vs estimasi,
- kualitas hasil live: win rate, expectancy (R), profit factor (R).

## Input

1. Snapshot sinyal otomatis:
   - `reports/snapshots/signals_<run_id>.json`
2. Fill broker (manual export):
   - `data/live/trade_fills.csv`
   - template: `data/live/trade_fills.sample.csv`

## Kolom CSV Fill (minimum)

- `executed_at`
- `ticker`
- `price`

Kolom yang direkomendasikan:

- `mode`, `side`, `qty`, `fee_idr`, `cost_pct`, `realized_r`, `pnl_idr`, `trade_id`, `run_id`

## Jalankan

```powershell
python -m src.cli reconcile-live
```

Atau:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/reconcile_live.ps1
```

Override manual:

```powershell
python -m src.cli reconcile-live --fills-path data/live/trade_fills.csv --lookback-days 30
```

## Output

- `reports/live_reconciliation.json`
- `reports/live_reconciliation.md`
- `reports/live_reconciliation_details.csv`
- `reports/live_reconciliation_unmatched_entries.csv`

## Status

- `ok`: match ditemukan.
- `no_signals`: snapshot sinyal belum ada.
- `no_fills`: belum ada fill pada window.
- `no_match`: ada sinyal + fill, tapi tidak ada pasangan valid.
