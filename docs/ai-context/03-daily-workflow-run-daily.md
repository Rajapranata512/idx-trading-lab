# 03 - Daily Workflow Run Daily

Bagian ini menjelaskan workflow utama `python -m src.cli run-daily`.

Fungsi utama:

```text
src/cli.py::run_daily
```

## Ringkasan Alur

```text
load settings
-> create run logger
-> update universe
-> update event-risk
-> recalibrate volatility
-> ingest prices
-> compute features
-> score candidates
-> model_v2 shadow/promotion
-> render report
-> backtest and live gate
-> write final signal
-> write snapshot
-> reconcile live
-> write funnel
-> send telegram
-> weekly KPI and coaching
-> save run log
```

## 1. Load Settings

`load_settings()` membaca JSON config dan memvalidasi schema memakai class di `src/config.py`.

Default:

```text
config/settings.json
```

Command bisa memakai path lain:

```powershell
python -m src.cli --settings config/settings.beginner.json run-daily
```

## 2. Create Run ID dan Logger

Pipeline membuat run id dan `JsonRunLogger`.

Output log:

```text
reports/run_log_YYYYMMDD.json
```

Run log penting untuk debugging karena menyimpan event tahap demi tahap.

## 3. Auto Update Universe

Fungsi:

```text
maybe_auto_update_universe()
```

Tujuan:

- menyegarkan anggota LQ45/IDX30 dari source yang dikonfigurasi,
- menghormati interval `data.universe_auto_update.interval_days`,
- menyimpan state update.

Jika gagal dan `fail_on_error=false`, pipeline tetap lanjut memakai universe lama.

## 4. Auto Update Event Risk

Fungsi:

```text
maybe_auto_update_event_risk()
```

Tujuan:

- mengambil suspend, UMA, dan material event,
- menyusun blacklist aktif,
- menyimpan update state.

Output:

```text
reports/event_risk_update_state.json
```

Event-risk kemudian dipakai untuk membuang kandidat berisiko.

## 5. Auto Recalibrate Volatility

Fungsi:

```text
maybe_auto_recalibrate_volatility_targets()
```

Tujuan:

- membaca feature history,
- menghitung referensi ATR/realized volatility terbaru,
- memperbarui target jika perubahan cukup berarti.

Output:

```text
reports/volatility_recalibration_state.json
```

## 6. Ingest Daily Prices

Fungsi:

```text
ingest_daily()
```

Langkah:

1. Load universe dari `data/reference/universe_lq45_idx30.csv`.
2. Ambil harga dari provider.
3. Filter ticker hanya yang ada di universe.
4. Merge dengan existing canonical CSV.
5. Deduplicate berdasarkan `ticker,date`, keep latest `ingested_at`.
6. Simpan ke `data/raw/prices_daily.csv`.

Output info:

- jumlah row baru,
- jumlah ticker,
- source provider,
- min/max data date,
- missing ticker sample.

## 7. Compute Features

Fungsi:

```text
compute_features_step()
```

Input:

```text
data/raw/prices_daily.csv
```

Output:

```text
data/processed/features.parquet
```

Feature yang dihitung mencakup return, moving average, RSI, ATR, volatility, liquidity, trend, breakout, volume confirmation, dan market context.

## 8. Score Candidates

Fungsi:

```text
score_step()
```

Langkah:

1. Baca `data/processed/features.parquet`.
2. Jalankan `rank_all_modes()`.
3. Buat `top_t1` dan `top_swing`.
4. Buat trade plan dengan `propose_trade_plan()`.
5. Terapkan minimum score live per mode.
6. Terapkan event-risk filter.
7. Buang size di bawah lot.
8. Gabungkan kandidat.
9. Batasi `top_n_combined`.
10. Tambahkan liquidity cost estimate.
11. Terapkan global dan mode position cap.

Output awal:

```text
reports/top_t1.csv
reports/top_swing.csv
reports/daily_report.csv
reports/execution_plan.csv
reports/daily_signal.json
reports/signal_funnel.json
```

## 9. Model V2 Shadow dan Promotion

Jika `model_v2.enabled=true`, pipeline dapat:

- auto-train model,
- menjalankan shadow inference,
- menulis shadow signals,
- mengevaluasi promotion gate.

Model V2 tidak otomatis mengambil alih live signal. Rollout dikontrol oleh promotion policy.

Output:

```text
reports/model_v2_shadow_signals.csv
reports/model_v2_shadow_signals.json
reports/model_v2_ab_test.json
reports/model_v2_state.json
reports/model_v2_promotion_state.json
```

## 10. Render Report Awal

Fungsi:

```text
render_html_report()
write_signal_json()
```

Output:

```text
reports/daily_report.html
reports/daily_signal.json
```

Pada tahap ini report masih bisa berubah setelah live gate.

## 11. Backtest dan Live Gate

Fungsi:

```text
backtest_step()
```

Komponen gate:

- backtest metrics,
- walk-forward jika enabled,
- market regime,
- kill switch,
- model promotion gate jika required,
- mode activation policy.

Jika tidak ada mode yang lolos, final `daily_signal.json` dikosongkan.

Output:

```text
reports/backtest_metrics.json
```

## 12. Post-Gate Signal Filtering

Pipeline hanya mempertahankan sinyal dari mode yang lolos gate.

Jika Model V2 rollout live aktif:

- selection dapat mengikuti `apply_model_v2_rollout_selection()`,
- final execution bisa memilih slot V2 sesuai rollout percent.

Output final ditulis ulang:

```text
reports/daily_report.csv
reports/execution_plan.csv
reports/daily_signal.json
```

## 13. Write Signal Snapshot

Fungsi:

```text
write_signal_snapshot()
```

Output:

```text
reports/snapshots/signals_*.json
```

Snapshot ini penting untuk:

- live reconciliation,
- paper trading,
- evaluasi pasca-sinyal.

## 14. Live Reconciliation

Jika `reconciliation.enabled=true` dan `auto_reconcile_on_run_daily=true`, pipeline menjalankan:

```text
reconcile_live_step()
```

Input:

- signal snapshots,
- `data/live/trade_fills.csv`.

Output:

```text
reports/live_reconciliation.json
reports/live_reconciliation.md
reports/live_reconciliation_details.csv
reports/live_reconciliation_unmatched_entries.csv
```

## 15. Write Live Funnel

Output:

```text
reports/signal_funnel_live.json
```

File ini menjawab:

- berapa kandidat sebelum gate,
- berapa setelah gate,
- mode mana yang lolos,
- kenapa sinyal bisa hilang.

## 16. Telegram Notification

Jika tidak memakai `--skip-telegram`, pipeline mengirim ringkasan via Telegram.

Env yang dibutuhkan:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Jika env tidak ada, fungsi biasanya return false dan pipeline tetap selesai.

## 17. Weekly KPI dan Beginner Coaching

Jika `coaching.enabled=true`, pipeline menulis:

```text
reports/weekly_kpi.json
reports/weekly_kpi.md
reports/beginner_coaching.md
```

Coaching note membedakan:

- `SUCCESS`,
- `NO_SIGNAL`,
- `NO_TRADE`,
- blocked by gate.

## 18. Save Run Log

Run log selalu disimpan di `finally`.

Jika pipeline gagal, baca:

```text
reports/run_log_YYYYMMDD.json
```

## Urutan Debug Run Daily

Jika output tidak sesuai:

1. Baca run log terbaru.
2. Baca `reports/signal_funnel_live.json`.
3. Baca `reports/backtest_metrics.json`.
4. Baca `reports/event_risk_excluded.csv`.
5. Baca `reports/daily_signal.json`.

