# SOP Eksekusi Harian (Semi-Auto Stockbit)

## Waktu Operasional (WIB)

1. `16:25` - ingest data EOD.
2. `16:35` - compute features + scoring.
3. `16:40` - generate report + kirim Telegram.

## Checklist Sistem

1. Jalankan:
   `powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1`
2. (Opsional) Refresh event-risk feed manual:
   `powershell -ExecutionPolicy Bypass -File scripts/update_event_risk.ps1`
3. Cek keputusan otomatis:
   `powershell -ExecutionPolicy Bypass -File scripts/ops_daily_check.ps1`
4. Alternatif 1-command gate swing + top picks:
   `powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1`
5. Jika `NO_SIGNAL` dan ingin root-cause:
   `powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1 -SkipRun -DebugReasons`
4. Validasi status dari `reports/n8n_last_summary.json`.

## Decision Matrix

1. `status=SUCCESS` + `trade_ready=true`:
   eksekusi maksimal 1-3 saham teratas.
2. `BLOCKED_BY_GATE` atau `NO_SIGNAL`:
   no trade.
3. `STALE_DATA` atau `PARTIAL_DATA`:
   no trade.
4. `EVENT_RISK_UPDATE_ERROR`:
   no trade (safety mode, tunggu feed event-risk normal).
5. `FAILED` atau `SETUP_ERROR`:
   no trade, perbaiki sistem dulu.

## Recalibration Mingguan Volatilitas

1. Sistem sekarang auto-recalibrate mingguan saat `run-daily`.
2. Jika perlu manual force:
   `powershell -ExecutionPolicy Bypass -File scripts/recalibrate_volatility.ps1`

## Validasi Mingguan (Anti-Overfitting)

1. Jalankan:
   `python -m src.cli walk-forward`
2. Review file:
   `reports/walk_forward_metrics.json`
3. Jangan naik ukuran modal jika OOS gate belum stabil.

## Checklist Trader

1. Buka `reports/daily_signal.json` atau `reports/daily_report.html`.
2. Ambil maksimal 1-3 sinyal teratas.
3. Entry hanya saat harga dekat level `entry`.
4. Pasang Auto Order/Bracket (`stop`, `tp1`, `tp2`) saat entry.
5. Jangan override stop-loss kecuali rule invalidasi terpenuhi.

## Risk Defaults

- risk/trade: `0.75%`
- max positions: `3`
- daily loss stop: `2R`
- stop: `2 * ATR`
- target: `TP1 = 1R`, `TP2 = 2R`

## Live Score Guardrail

- `min_live_score_t1 = 95`
- `min_live_score_swing = 65`
- Hanya sinyal di atas threshold yang akan masuk `daily_signal.json`.
