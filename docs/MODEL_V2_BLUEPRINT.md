# Model V2 Blueprint (Profit-Oriented, Risk-First, Beginner-Friendly)

## 1. Tujuan

Bangun `model_v2` yang meningkatkan kualitas sinyal tanpa mengorbankan safety:

- Meningkatkan `ProfitFactor` dan `Expectancy` OOS.
- Menurunkan `Max Drawdown` dan overtrading.
- Menjaga error operasional tetap rendah (pipeline stabil, keputusan konsisten).
- Tetap ramah trader baru (aturan jelas, no-trade saat kondisi buruk).

Catatan: tidak ada model yang bisa menjamin profit maksimal.

## 1.1 Status Implementasi Saat Ini

Jalur final-decision sudah aktif secara fail-closed di pipeline harian:

- `src/model_v2/train.py`: kandidat logistic/LightGBM/XGBoost, calibration window,
  untouched holdout, threshold terkunci, dan lima purged walk-forward fold per mode.
- Model pohon hanya dituning/dipilih bila CV statis mengungguli logistic baseline dengan
  margin minimum; hal ini membatasi overfit dan waktu training.
- `src/model_v2/calibration.py`: pemilihan Platt/isotonic hanya pada calibration window.
- `src/model_v2/predict.py`: infer probabilitas shadow (`shadow_p_win`, `shadow_expected_r`).
- `src/model_v2/shadow.py`: output shadow + A/B test v1 vs v2.
- `src/model_v2/io.py`: simpan/load artifact + metadata + state.
- `src/analytics/model_v2_accuracy.py`: audit outcome, calibration, threshold, agreement,
  false positive, dan Bayesian ticker edge.
- Promotion T1 dan Swing terpisah, dengan rollout 0 -> 10 -> 30 -> 60 -> 100 dan rollback.
- Kandidat live awal wajib mendapat agreement V1+V2, EV positif, dan lolos meta-filter.

Status bukti terbaru dan blocker promosi dicatat hanya di `docs/AI_PROJECT_CONTEXT.md`
agar agent tidak memakai angka lama dari beberapa dokumen.

## 1.2 Kontrak Final Decision

Model V2 hanya berstatus `FINAL` saat seluruh syarat berikut lulus:

1. Mode yang dipromosikan memakai artefak model yang tersedia, valid, dan dapat dimuat.
2. Probabilitas dikalibrasi pada calibration window terpisah, lalu dievaluasi pada
   untouched holdout dengan `ECE <= 10%` dan `AUC >= 0.52`.
3. Walk-forward memiliki minimal 5 fold, minimal 120 trade OOS, `PF >= 1.25`,
   `expectancy >= 0.03R`, `MaxDD <= 12%`, dan minimal 60% fold profitable.
4. Accuracy audit terbaru berstatus `ok`, tidak memakai fallback, serta memenuhi
   batas trade, expectancy, profit factor, calibration error, dan freshness.
5. Kandidat membutuhkan agreement V1+V2, EV positif, serta Bayesian ticker edge yang sehat.
6. Minimal 20 sesi shadow nyata dan tiga evaluasi berturut-turut lulus.
7. Rekonsiliasi live memenuhi sample, expectancy, profit factor, dan entry-match gate.
8. Rollout mode tersebut telah naik bertahap hingga 100% tanpa rollback atau risk gate.

Status operasional:

- `BLOCKED`: artefak, kalibrasi, audit, atau data belum memenuhi kontrak. Tidak ada
  rekomendasi V2 live/final; output shadow tetap boleh dicatat dengan label yang jelas.
- `SHADOW`: sinyal model asli dicatat untuk audit, tetapi belum mengambil keputusan live.
- `CANARY`: hanya sebagian kecil kandidat yang dipilih V2 sesuai rollout.
- `FINAL`: rollout 100% dan semua gate tetap lulus. Risk engine dan kill-switch tetap
  berwenang membatalkan trade.

Fallback heuristik tidak boleh menghasilkan `p(win)`, expected R, rekomendasi Telegram,
atau kandidat final. Kehilangan atau kerusakan model harus selalu gagal tertutup
(`fail-closed`).

## 2. Prinsip Desain

1. `Risk-first`: model hanya boleh eksekusi jika lolos gate risiko.
2. `Data-first`: kualitas data lebih penting daripada frekuensi sinyal.
3. `Probabilistic`: output model berupa probabilitas/kepercayaan, bukan label kaku.
4. `Human-auditable`: setiap keputusan harus punya alasan yang terbaca.

## 3. Arsitektur Target

Pipeline saat ini:

`ingest -> features -> score -> risk -> gate -> report`

Pipeline v2:

`ingest -> features_v2 -> model_v2_infer -> calibration -> risk -> gate -> report`

Komponen baru:

- `src/model_v2/train.py` (training + walk-forward train loop).
- `src/model_v2/predict.py` (inference harian).
- `src/model_v2/calibration.py` (Platt/isotonic calibration tanpa leakage).
- `src/model_v2/io.py` (versioning model + metadata).
- `src/model_v2/promotion.py` (gate per mode, rollout, dan rollback).
- `src/model_v2/meta_filter.py` (Bayesian/shrinkage historical ticker edge).

## 4. Target Model

Prioritas implementasi:

1. Baseline stabil: logistic regression.
2. Challenger: `LightGBM/XGBoost` hanya jika CV gain minimum 0.02 di atas baseline.
3. Opsional challenger: deep learning time-series setelah tabular baseline stabil.
4. LLM dipakai sebagai lapisan tambahan event/sentiment, bukan model utama entry.

Output minimum model:

- `p_win` (probabilitas sukses trade),
- `expected_r` (ekspektasi return dalam satuan R),
- `confidence` (quality score terkalibrasi 0-1).

## 5. Labeling dan Horizon

Gunakan label berbasis hasil trade dengan aturan entry/stop/TP yang sama dengan live:

- Mode `t1`: horizon 1 hari.
- Mode `swing`: horizon 5-10 hari.

Contoh label:

- `y_cls`: 1 jika mencapai TP sebelum stop dalam horizon.
- `y_reg`: realized return (R-multiple).

Ini memastikan training selaras dengan real execution.

## 6. Feature Set V2

Tambahkan/rapikan fitur:

- Trend-momentum: `ret_1d/5d/20d`, slope MA, distance to MA.
- Volatility: `atr_pct`, realized vol, volatility regime ratio.
- Liquidity: `avg_vol_20d`, turnover proxy, spread proxy (jika tersedia).
- Cross-sectional rank: rank score per hari di universe.
- Regime context: breadth, market return, median atr.
- Event-risk flags: suspend/UMA/material proximity.

Semua fitur harus lagged (anti look-ahead bias).

## 7. Training & Validation

Skema wajib:

1. Time-based split + walk-forward.
2. Purged window antar train-test bila perlu.
3. Pemilihan calibration method hanya pada calibration window.
4. Hyperparameter tuning di train fold saja dan tidak wajib bila tree baseline lemah.
5. Threshold dikunci pada calibration fold dan diuji pada test fold berikutnya.
6. Simpan metrik OOS per fold.

Promotion gate model_v2 (minimum):

- `OOS Trades >= 120`
- `OOS ProfitFactor >= 1.25`
- `Median OOS Expectancy > 0.03R`
- `OOS MaxDD <= 12%`
- Minimal 5 fold dan sekurangnya 60% fold profitable.

## 8. Integrasi ke Risk Engine

Gunakan `confidence` model untuk sizing dan filtering:

- Filter: trade hanya jika `confidence >= threshold_mode`.
- Sizing multiplier tambahan:
  - `conf_mult = clamp(confidence, conf_floor, conf_cap)`
  - `final_size = volatility_size * conf_mult`

Tetap aktif:

- regime filter,
- kill-switch,
- event-risk blacklist,
- max positions global + mode caps.

## 9. Beginner Mode (Wajib untuk Trader Baru)

Tambahkan profil konservatif:

- mode: swing-only,
- `risk_per_trade_pct` kecil (mis. 0.3-0.5),
- `max_positions` 1-2,
- confidence threshold lebih ketat,
- wajib no-trade saat `risk_off`.

Aturan edukasi:

1. 20-30 hari pertama paper/simulasi dulu.
2. Evaluasi jurnal harian sebelum naik ukuran.
3. Dilarang override stop-loss.

## 10. Operasional Anti-Error

Hardening:

- Input schema check sebelum infer.
- Blokir inferensi jika model file corrupt/missing; jangan membuat probabilitas fallback.
- Simpan `model_version` pada `daily_signal.json` dan summary.
- Tambahkan `reason_code` per sinyal:
  - `DROP_SCORE`
  - `DROP_CONFIDENCE`
  - `DROP_EVENT_RISK`
  - `DROP_SIZE`
  - `DROP_GATE`

## 11. KPI Dashboard

Pantau mingguan:

- WinRate, ProfitFactor, Expectancy, MaxDD.
- Hit ratio per mode.
- Avg hold period.
- Error rate pipeline (FAILED/SETUP_ERROR).
- No-trade rate (agar tidak overtrading).

Trigger risk reduction:

- PF rolling 4 minggu < 1.1 atau
- Expectancy rolling <= 0 atau
- Drawdown menembus limit.

## 12. Rollout Plan (30 Hari)

Minggu 1:

- Siapkan dataset train/infer + labeling v2.
- Build baseline model + calibration.

Minggu 2:

- Walk-forward full + threshold tuning.
- Bandingkan v1 vs v2 pada metrik OOS.

Minggu 3:

- Shadow mode (v2 jalan, belum dipakai eksekusi).
- Log reason-code dan selisih keputusan v1 vs v2.

Minggu 4:

- Canary T1 10% hanya jika seluruh gate lulus; Swing dapat tetap 0% secara independen.
- Jika KPI stabil, naikkan 30% -> 60% -> 100%; satu gate gagal memicu rollback ke 0%.

## 13. Definisi Sukses

Model v2 dianggap berhasil jika selama 8-12 minggu:

- error operasional tetap rendah,
- OOS expectancy konsisten positif,
- drawdown lebih rendah atau setara v1,
- trader baru bisa mengikuti SOP tanpa override discretionary.

## 14. Command Operasional yang Disarankan

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1 -DebugReasons
python -m src.cli walk-forward
```

Gunakan hasil command untuk audit sebelum menambah risk.
