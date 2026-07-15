# 05 - Operations And Debugging

Bagian ini dipakai untuk menjalankan, memeriksa, dan mencari penyebab error/no-signal.

## SOP Harian

Waktu ideal WIB:

1. 16:25 ingest data EOD.
2. 16:35 compute features dan scoring.
3. 16:40 generate report dan kirim Telegram.

Command utama:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1
```

Refresh event-risk manual:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/update_event_risk.ps1
```

Daily ops check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ops_daily_check.ps1
```

Swing gate cepat:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1
```

Swing root-cause:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1 -SkipRun -DebugReasons
```

Mode pemula:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_beginner.ps1 -DebugReasons
```

## Decision Matrix

`SUCCESS` dan `trade_ready=true`:

- boleh review sinyal,
- eksekusi maksimal 1-3 saham sesuai cap,
- pasang stop dan target.

`BLOCKED_BY_GATE`:

- no trade,
- cek backtest, regime, kill switch, promotion gate.

`NO_SIGNAL`:

- no trade,
- cek funnel untuk tahu kandidat hilang di tahap mana.

`STALE_DATA` atau `PARTIAL_DATA`:

- no trade,
- perbaiki data/provider.

`EVENT_RISK_UPDATE_ERROR`:

- no trade dalam safety mode,
- cek source event-risk.

`FAILED` atau `SETUP_ERROR`:

- no trade,
- perbaiki sistem dulu.

## Output Yang Dicek Setelah Run

Ringkasan sinyal:

```text
reports/daily_signal.json
reports/execution_plan.csv
reports/daily_report.html
```

Penyebab filtering:

```text
reports/signal_funnel.json
reports/signal_funnel_live.json
reports/event_risk_excluded.csv
```

Gate dan performa:

```text
reports/backtest_metrics.json
reports/walk_forward_metrics.json
```

Operasional:

```text
reports/run_log_YYYYMMDD.json
reports/weekly_kpi.json
reports/beginner_coaching.md
```

## Debug NO_SIGNAL

Urutan baca:

1. `reports/signal_funnel_live.json`
2. `reports/signal_funnel.json`
3. `reports/backtest_metrics.json`
4. `reports/event_risk_excluded.csv`
5. `reports/daily_signal.json`
6. run log terbaru

Kemungkinan penyebab:

- kandidat rank ada, tetapi score di bawah `min_live_score_t1` atau `min_live_score_swing`,
- event-risk memblokir ticker,
- size kurang dari lot,
- tidak lolos `max_positions` atau mode cap,
- backtest gate gagal,
- walk-forward gate gagal,
- market regime risk-off,
- kill switch aktif,
- Model V2 promotion gate memblokir,
- data stale atau partial.

Cara baca funnel:

- `rank_candidates`: kandidat awal dari strategy ranker.
- `after_score_filter`: sisa setelah minimum live score.
- `after_event_risk`: sisa setelah blacklist event.
- `dropped_by_size_filter`: kandidat yang size-nya tidak cukup lot.
- `execution_plan_count`: kandidat yang masuk rencana eksekusi.
- `post_gate.signal_count`: final signal setelah live gate.

## Debug Data Provider

Baca:

1. `config/settings.json`
2. `src/ingest/load_prices.py`
3. `src/ingest/providers/rest_provider.py`
4. run log terbaru

Cek:

- `EODHD_API_TOKEN` tersedia,
- `base_url_template` benar,
- query params benar,
- column mapping benar,
- yfinance fallback enabled,
- fallback CSV ada,
- ticker suffix sesuai.

Command manual:

```powershell
python -m src.cli ingest-daily
```

Jika provider gagal tapi fallback jalan, source di output akan menunjukkan fallback.

## Debug Dashboard

Jalankan server:

```powershell
python -m src.web.server --host 127.0.0.1 --port 8080
```

Health:

```text
http://127.0.0.1:8080/api/health
```

Dashboard data:

```text
http://127.0.0.1:8080/api/dashboard
```

Baca file ini jika dashboard kosong:

1. `src/web/server.py`
2. `src/web/service.py`
3. `web/premium-dashboard.js`
4. `reports/daily_signal.json`
5. `reports/backtest_metrics.json`

Operational auth:

- Jika `IDX_WEB_USERNAME` dan `IDX_WEB_PASSWORD` di-set, route operational butuh Basic Auth.
- `POST /api/run-daily` hanya boleh dari localhost.

## Debug Model V2

Baca:

1. `reports/model_v2_state.json`
2. `reports/model_v2_shadow_signals.json`
3. `reports/model_v2_ab_test.json`
4. `reports/model_v2_promotion_state.json`
5. `reports/live_reconciliation.json`

Penyebab umum promotion tidak naik:

- live sample kurang,
- expectancy R belum memenuhi minimum,
- profit factor R rendah,
- entry match rate rendah,
- consecutive passes belum cukup,
- rollback condition terpenuhi.

## Debug Live Reconciliation

Baca:

1. `data/live/trade_fills.csv`
2. `reports/snapshots/signals_*.json` yang relevan
3. `reports/live_reconciliation.json`
4. `reports/live_reconciliation_details.csv`
5. `reports/live_reconciliation_unmatched_entries.csv`

Command:

```powershell
python -m src.cli reconcile-live
```

Dengan fills path custom:

```powershell
python -m src.cli reconcile-live --fills-path data/live/trade_fills.csv
```

## Validasi Mingguan

Walk-forward:

```powershell
python -m src.cli walk-forward
```

Review:

```text
reports/walk_forward_metrics.json
```

Recalibration volatility manual:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/recalibrate_volatility.ps1
```

## Checklist Trader

1. Buka `reports/daily_signal.json` atau `reports/daily_report.html`.
2. Ambil maksimal sinyal sesuai cap.
3. Entry hanya saat harga dekat level `entry`.
4. Pasang bracket/auto order: `stop`, `tp1`, `tp2`.
5. Jangan override stop-loss kecuali rule invalidasi terpenuhi.
6. Jika status no-trade, jangan memaksa trade manual dari kandidat yang diblokir.

