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

## 3. Point-In-Time Universe Gate

Fungsi:

```text
maybe_auto_update_universe()
```

Tujuan:

- membaca membership LQ45/IDX30 dari `data/reference/universe_history.csv`,
- memilih snapshot yang aktif pada tanggal pipeline,
- memvalidasi tepat 45 anggota LQ45 dan 30 anggota IDX30,
- menulis snapshot aktif dan state update.

Konfigurasi produksi memakai `fail_on_error=true` dan `fail_on_stale=true`. Snapshot
hilang, kedaluwarsa, overlap, atau jumlah anggota salah harus memblokir pipeline; dilarang
melanjutkan dengan universe lama. Archive IDX resmi diimpor dengan
`python -m src.cli import-idx-universe-archive`.

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

1. Load snapshot universe aktif dari `data/reference/universe_lq45_idx30.csv`.
2. Ambil harga dari provider utama dan, bila tersedia, provider rekonsiliasi independen.
3. Filter ticker hanya yang ada di universe aktif.
4. Merge dan deduplicate canonical raw berdasarkan `ticker,date`.
5. Simpan raw auditable ke `data/raw/prices_daily.csv`.
6. Terapkan corporate action terkonfirmasi ke salinan adjusted.
7. Deteksi anomali, quarantine ticker aktif, dan rekonsiliasi close price.
8. Tulis adjusted prices serta laporan quality gate.

Output info mencakup jumlah row/ticker, source, rentang tanggal, missing ticker,
quarantined ticker, hasil corporate-action audit, dan hasil rekonsiliasi.

## 7. Compute Features

Fungsi:

```text
compute_features_step()
```

Input:

```text
data/processed/prices_daily_adjusted.csv
```

Raw prices tetap disimpan untuk audit. Fallback ke canonical raw hanya terjadi bila
`use_adjusted_for_features=false` atau file adjusted belum tersedia.

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
2. Buang ticker di luar snapshot universe aktif dan ticker yang sedang quarantine.
3. Jalankan `rank_all_modes()` dan buat kandidat T1/Swing.
4. Buat trade plan dengan `propose_trade_plan()`.
5. Terapkan minimum score live per mode dan event-risk filter.
6. Buang size di bawah lot, tambahkan liquidity cost estimate, dan jalankan profit-quality gate.
7. Batasi `top_n_combined`, global position cap, dan mode position cap.
8. Simpan jumlah row yang dibuang oleh universe/quality filter ke `signal_funnel.json`.

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

