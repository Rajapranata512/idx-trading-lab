# 01 - Project Overview

## Gambaran Umum

IDX Trading Lab adalah sistem riset dan operasional trading berbasis data untuk saham Indonesia, terutama universe LQ45 dan IDX30.

Sistem ini bukan bot eksekusi broker. Sistem tidak mengirim order langsung ke broker. Perannya adalah:

- mengambil dan memvalidasi data harga,
- menghitung fitur teknikal dan market context,
- memilih kandidat saham,
- menerapkan risk gate,
- membuat rencana entry, stop, target, dan size,
- menghasilkan laporan dan dashboard,
- membantu evaluasi performa lewat backtest, walk-forward, paper trading, dan live reconciliation.

Alur konseptual:

```text
ingest -> validate -> features -> score -> risk -> backtest/gate -> report -> notify -> monitor -> reconcile
```

## Tujuan Proyek

Proyek ini dibangun untuk:

- mengurangi keputusan trading yang emosional,
- membuat proses seleksi saham lebih konsisten,
- membatasi risiko saat market buruk,
- membedakan no-trade sehat dari error sistem,
- menyediakan audit trail dari sinyal sampai hasil real,
- menguji Model V2 tanpa langsung membahayakan live flow.

## Prinsip Desain

Risk-first:

- Sinyal bagus tetap bisa diblokir.
- No-trade adalah hasil valid jika risk gate tidak mendukung.

Validation-first:

- Backtest, walk-forward, regime filter, dan kill switch dipakai sebagai guardrail.

Manual execution:

- Trader tetap memasukkan order secara manual.
- Sistem memberi rencana, bukan mengeksekusi order broker.

Observable:

- Output JSON/CSV/HTML/log dibuat agar status pipeline bisa diaudit.

Model V2 hati-hati:

- Model V2 berjalan sebagai shadow layer.
- Promotion gate mengontrol rollout.
- Risk engine tetap menjadi pengaman utama.

## Mode Strategi

Mode `t1`:

- Horizon sangat pendek.
- Saat ini cenderung lebih konservatif.
- Threshold live bisa sangat tinggi.

Mode `swing`:

- Horizon beberapa hari sampai 1-4 minggu.
- Fokus utama operasional saat ini.
- Menggabungkan trend, momentum relatif, breakout proximity, volume confirmation, volatility discipline, dan market support.

Mode `intraday`:

- Pipeline terpisah.
- Menggunakan data intraday dan output sendiri.

## Output Utama

Output harian:

- `reports/top_t1.csv`
- `reports/top_swing.csv`
- `reports/daily_report.csv`
- `reports/execution_plan.csv`
- `reports/daily_report.html`
- `reports/daily_signal.json`
- `reports/signal_funnel.json`
- `reports/signal_funnel_live.json`

Output validasi:

- `reports/backtest_metrics.json`
- `reports/walk_forward_metrics.json`
- `reports/signal_accuracy_audit.json`
- `reports/signal_accuracy_by_ticker.csv`
- `reports/signal_accuracy_by_regime.csv`
- `reports/signal_accuracy_by_score_bucket.csv`
- `reports/run_log_YYYYMMDD.json`

Output Model V2:

- `reports/model_v2_shadow_signals.csv`
- `reports/model_v2_shadow_signals.json`
- `reports/model_v2_ab_test.json`
- `reports/model_v2_state.json`
- `reports/model_v2_promotion_state.json`

Output monitoring:

- `reports/weekly_kpi.json`
- `reports/weekly_kpi.md`
- `reports/beginner_coaching.md`
- `reports/live_reconciliation.json`
- `reports/live_reconciliation.md`

## Cara Membaca Hasil

Jika `daily_signal.json` berisi sinyal:

- Masih perlu cek apakah status trade-ready.
- Gunakan `execution_plan.csv` untuk rencana eksekusi.
- Eksekusi maksimal sesuai risk cap.

Jika `daily_signal.json` kosong:

- Bisa berarti score kurang.
- Bisa berarti event-risk memblokir kandidat.
- Bisa berarti size tidak cukup satu lot.
- Bisa berarti live gate, regime, kill switch, atau promotion gate memblokir mode.
- Mulai debug dari `signal_funnel_live.json`.
