# 04 - Module Workflows

Bagian ini merangkum workflow per modul. Pakai bagian ini saat tugas menyentuh satu area kode.

## Ingestion

File utama:

- `src/ingest/load_prices.py`
- `src/ingest/validator.py`
- `src/ingest/providers/rest_provider.py`
- `src/ingest/providers/yfinance_provider.py`
- `src/ingest/providers/csv_provider.py`

Workflow:

1. Pilih provider dari settings.
2. Resolve env placeholder seperti `${EODHD_API_TOKEN}`.
3. Ambil harga per ticker.
4. Mapping kolom provider ke canonical schema.
5. Validasi OHLCV.
6. Fallback ke yfinance atau CSV jika provider utama gagal.

Hal yang harus dijaga:

- Kolom canonical tidak berubah.
- Duplicate `ticker,date` harus ditangani.
- OHLC anomaly harus tetap dianggap invalid.

Test terkait:

- `tests/test_ingest_validation.py`
- `tests/test_rest_provider.py`

## Feature Engineering

File utama:

- `src/features/compute_features.py`

Input:

```text
date,ticker,open,high,low,close,volume
```

Feature penting:

- `ret_1d`, `ret_5d`, `ret_20d`
- `ma_20`, `ma_50`, `ma_200`
- `vol_20d`, `vol_60d`, `vol_ratio`
- `avg_vol_20d`, `turnover`, `turnover_20d`
- `rsi_14`, `atr_14`, `atr_pct`
- `ma_slope_20`, `ma_slope_50`
- `dist_ma_20`, `dist_ma_50`
- `volume_ratio_20d`, `turnover_ratio_20d`
- `obv_slope`, `mfi_14`
- `dist_high_20`, `dist_low_20`, `ma_gap_20_50`, `ma_stack_bullish`
- market context: breadth, market return, market median ATR, relative return.

Hal yang harus dijaga:

- Tidak boleh ada future leakage.
- Rolling feature harus memakai data saat ini dan masa lalu.
- Cross-sectional ranks dihitung per tanggal.

Test terkait:

- `tests/test_features.py`

## Strategy Scoring

File utama:

- `src/strategy/ranker.py`
- `src/strategy/t1_model.py`
- `src/strategy/swing_model.py`
- `src/strategy/intraday_model.py`

Mode:

- `t1`: horizon sangat pendek.
- `swing`: horizon beberapa hari sampai 1-4 minggu.
- `intraday`: pipeline terpisah.

Swing scoring:

1. Ambil bar terbaru per ticker.
2. Filter liquidity minimum.
3. Hard filter close > MA50.
4. Hard filter ret_20d positif.
5. Hitung score dari momentum, relative momentum, trend stack, breakout, volume, volatility quality, market support.
6. Sort score descending.

Historical scoring:

- `score_history_modes()` membuat row per `ticker,date,mode`.
- Dipakai backtest dan gate.

Hal yang harus dijaga:

- Score tetap 0-100.
- Ranking descending.
- Mode string konsisten: `t1`, `swing`, `intraday`.

Test terkait:

- `tests/test_strategy.py`

## Risk Engine

File utama:

- `src/risk/manager.py`
- `src/risk/position_sizing.py`
- `src/risk/event_risk_updater.py`
- `src/risk/volatility_recalibration.py`
- `src/risk/kelly_sizing.py`
- `src/risk/sector_diversification.py`

Trade plan:

1. Entry default = close.
2. Stop = entry - ATR multiple.
3. Risk per share = entry - stop.
4. Risk budget = account size * risk per trade.
5. Volatility multiplier diterapkan.
6. Size dibulatkan ke lot.
7. Exposure cap diterapkan.
8. TP1 dan TP2 dihitung dari R multiple.

Volatility targeting:

- `market`
- `per_asset`
- `hybrid`

Market volatility regime:

- `calm`
- `normal`
- `high`
- `stress`

Position limit:

- global `max_positions`,
- per-mode cap,
- mode priority.

Hal yang harus dijaga:

- Jangan melemahkan guardrail tanpa instruksi.
- Size harus lot-aware.
- Risk budget dan exposure cap harus tetap dihormati.

Test terkait:

- `tests/test_risk.py`
- `tests/test_event_risk_update.py`
- `tests/test_volatility_recalibration.py`

## Backtest, Walk-Forward, Guardrail

File utama:

- `src/backtest/engine.py`
- `src/backtest/metrics.py`
- `src/backtest/walkforward.py`
- gate logic di `src/cli.py`

Metrics:

- win rate,
- profit factor,
- expectancy,
- CAGR,
- max drawdown,
- trade count.

Live gate mengecek:

- backtest pass,
- walk-forward pass jika enabled,
- regime OK,
- kill switch tidak aktif,
- model promotion gate jika required.

Test terkait:

- `tests/test_backtest.py`
- `tests/test_integration_cli.py`
- `tests/test_roadmap_ops.py`

## Signal Accuracy dan Profit Quality

File utama:

- `src/analytics/signal_accuracy.py`
- `src/risk/profit_quality.py`
- wiring command di `src/cli.py`
- settings di `src/config.py`

Output utama:

- `reports/signal_accuracy_audit.json`
- `reports/signal_accuracy_by_ticker.csv`
- `reports/signal_accuracy_by_regime.csv`
- `reports/signal_accuracy_by_score_bucket.csv`
- `reports/profit_quality_gate.json`
- `reports/ticker_edge_profile.csv`

Konsep:

- Signal accuracy audit mengukur outcome sinyal dari OHLC masa depan dengan TP1/TP2/SL, fee, slippage, MAE/MFE, score bucket, regime, liquidity, dan signal decay.
- Profit quality gate memberi filter tambahan untuk kandidat live berdasarkan expected R, edge per ticker, dan probability model.
- Fokus modul ini adalah mengurangi false positive, bukan memperbanyak sinyal.

Hal yang harus dijaga:

- Jangan memakai future close saja sebagai label kualitas jika TP/SL path tersedia.
- Jangan menurunkan threshold tanpa melihat expectancy R, profit factor, dan false positive.
- Jangan menjadikan calibration score sebagai probability final jika calibration report buruk.
- Jika mengubah output report, cek reader dashboard/report/downstream.

Test terkait:

- `tests/test_signal_accuracy.py`
- `tests/test_profit_quality.py`

## Model V2

File utama:

- `src/model_v2/train.py`
- `src/model_v2/predict.py`
- `src/model_v2/shadow.py`
- `src/model_v2/promotion.py`
- `src/model_v2/calibration.py`
- `src/model_v2/labeling.py`
- `src/model_v2/closed_loop.py`
- `src/model_v2/regime_thresholds.py`
- `src/model_v2/io.py`

Konsep:

- Model V2 adalah ML layer tambahan.
- Default shadow mode.
- Output dipakai untuk evaluasi dan rollout bertahap.
- Risk engine tetap wajib.

Promotion:

- butuh jumlah sample minimum,
- expectancy R minimum,
- profit factor R minimum,
- entry match rate minimum,
- rollback jika live metrics buruk.

Test terkait:

- `tests/test_model_v2_upgrade.py`
- `tests/test_model_v2_promotion.py`

## Reporting dan Dashboard

File utama:

- `src/report/render_report.py`
- `src/report/weekly_kpi.py`
- `src/report/beginner_coach.py`
- `src/report/live_reconciliation.py`
- `src/web/service.py`
- `src/web/server.py`
- `web/premium-dashboard.html`
- `web/premium-dashboard.css`
- `web/premium-dashboard.js`

Dashboard API:

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/signals`
- `GET /api/ticker-detail`
- `GET /api/close-analysis`
- `GET /api/close-prices`
- `GET /api/report-html`
- `POST /api/run-daily`
- `GET /api/jobs`

Hal yang harus dijaga:

- JSON contract di `src/web/service.py`.
- Operational routes harus tetap terlindungi.
- `POST /api/run-daily` hanya localhost.

Test terkait:

- `tests/test_web_service.py`
- `tests/test_web_server.py`

## Paper Trading dan Live Reconciliation

File utama:

- `src/paper_trading/auto_fill.py`
- `src/report/live_reconciliation.py`
- `src/model_v2/closed_loop.py`

Workflow:

1. Baca snapshot sinyal.
2. Baca price history atau fills broker.
3. Match entry ke sinyal.
4. Hitung slippage, match rate, expectancy R, profit factor.
5. Tulis summary dan details.

Test terkait:

- `tests/test_paper_trading.py`
- `tests/test_live_reconciliation.py`
- `tests/test_paper_analytics.py`

## Intraday

File utama:

- `src/intraday/pipeline.py`
- `src/intraday/daemon.py`
- `src/strategy/intraday_model.py`
- `src/ingest/providers/websocket_provider.py`

Output:

- `reports/intraday_signal.json`
- `reports/intraday_execution_plan.csv`
- `reports/intraday_status.json`
- `reports/intraday_daemon_state.json`

Catatan:

- Intraday adalah jalur tambahan.
- Jangan campur behavior EOD harian kecuali tugasnya memang integrasi.
