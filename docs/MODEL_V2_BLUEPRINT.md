# Model V2 Blueprint (Profit-Oriented, Risk-First, Beginner-Friendly)

## 1. Tujuan

Bangun `model_v2` yang meningkatkan kualitas sinyal tanpa mengorbankan safety:

- Meningkatkan `ProfitFactor` dan `Expectancy` OOS.
- Menurunkan `Max Drawdown` dan overtrading.
- Menjaga error operasional tetap rendah (pipeline stabil, keputusan konsisten).
- Tetap ramah trader baru (aturan jelas, no-trade saat kondisi buruk).

Catatan: tidak ada model yang bisa menjamin profit maksimal.

## 1.1 Status Implementasi Saat Ini

Scaffolding fase awal sudah aktif di pipeline harian:

- `src/model_v2/train.py`: auto-train baseline logistic (interval mingguan, per mode).
- `src/model_v2/predict.py`: infer probabilitas shadow (`shadow_p_win`, `shadow_expected_r`).
- `src/model_v2/shadow.py`: output shadow + A/B test v1 vs v2.
- `src/model_v2/io.py`: simpan/load artifact + metadata + state.
- `run-daily` tetap memakai gate risiko live yang sama; model_v2 belum override eksekusi.

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
- `src/model_v2/calibration.py` (opsional/fase lanjutan untuk probability calibration).
- `src/model_v2/io.py` (versioning model + metadata).

## 4. Target Model

Prioritas implementasi:

1. Baseline: `LightGBM/XGBoost` (tabular, stabil untuk data saat ini).
2. Opsional challenger: deep learning time-series (LSTM/Transformer) setelah baseline stabil.
3. LLM dipakai sebagai lapisan tambahan event/sentiment, bukan model utama entry.

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
3. Hyperparameter tuning di train fold saja.
4. Simpan metrik OOS per fold.

Promotion gate model_v2 (minimum):

- `OOS Trades >= 120`
- `OOS ProfitFactor >= 1.25`
- `OOS Expectancy > 0`
- `OOS MaxDD <= 12%`
- Stabil antar fold (tidak hanya 1 fold bagus).

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
- Fallback ke model sebelumnya jika model file corrupt/missing.
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

- Partial rollout: 30-50% risk budget ke v2 (paper/live terbatas).
- Jika KPI stabil, naikkan bertahap; jika tidak, rollback otomatis ke v1.

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
