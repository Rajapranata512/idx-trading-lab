# 06 - Change Guide And Tests

Bagian ini dipakai saat agent AI akan mengubah kode.

## Aturan Umum

Jangan ubah schema output tanpa update semua pembaca downstream.

Jangan melemahkan risk gate tanpa instruksi eksplisit.

Jangan menulis secret ke repo.

Jangan menghapus data/report historis tanpa instruksi jelas.

Jangan membaca semua file besar hanya untuk memahami proyek.

Jangan mengubah banyak area sekaligus jika tugasnya sempit.

## Jika Menambah Config

Langkah:

1. Tambah field di `src/config.py`.
2. Tambah default di `config/settings.example.json`.
3. Pertimbangkan update `config/settings.json`.
4. Pertimbangkan update `config/settings.beginner.json`.
5. Tambah atau update test load settings.
6. Dokumentasikan jika mempengaruhi workflow.

Risiko:

- config lama bisa gagal load,
- script ops bisa memakai default yang tidak diharapkan,
- dashboard bisa membaca output yang belum ada.

## Jika Mengubah Ingestion

Jaga:

- canonical daily schema,
- fallback behavior,
- error message provider chain,
- env placeholder resolution.

Test:

```powershell
pytest tests/test_ingest_validation.py
pytest tests/test_rest_provider.py
```

## Jika Menambah Feature

Jaga:

- tidak ada future leakage,
- rolling window konsisten,
- feature cross-sectional dihitung per tanggal,
- nilai NaN awal rolling tetap wajar.

Test:

```powershell
pytest tests/test_features.py
```

Jika fitur dipakai Model V2, update feature frame di `src/model_v2/`.

## Jika Mengubah Scoring

Jaga:

- score tetap 0-100,
- ranking descending,
- mode string konsisten,
- historical scoring sejalan dengan live scoring jika perlu.

Test:

```powershell
pytest tests/test_strategy.py
pytest tests/test_backtest.py
```

Periksa dampak ke:

- `reports/signal_funnel.json`,
- `reports/backtest_metrics.json`,
- no-signal rate.

## Jika Mengubah Risk

Jaga:

- lot rounding,
- exposure cap,
- volatility targeting,
- global/mode position cap,
- event-risk filter,
- kill switch.

Test:

```powershell
pytest tests/test_risk.py
pytest tests/test_event_risk_update.py
pytest tests/test_volatility_recalibration.py
```

## Jika Mengubah Backtest/Gate

Jaga:

- metrics tetap stabil,
- gate reason terbaca,
- no-trade tetap bisa dijelaskan,
- walk-forward tidak bocor masa depan.

Test:

```powershell
pytest tests/test_backtest.py
pytest tests/test_integration_cli.py
pytest tests/test_roadmap_ops.py
```

## Jika Mengubah Model V2

Jaga:

- time split,
- leakage prevention,
- shadow mode behavior,
- promotion gate,
- rollback behavior.

Test:

```powershell
pytest tests/test_model_v2_upgrade.py
pytest tests/test_model_v2_promotion.py
```

## Jika Mengubah Dashboard

Jaga:

- API contract,
- auth behavior,
- localhost restriction untuk run-daily,
- frontend tetap membaca field lama.

Test:

```powershell
pytest tests/test_web_service.py
pytest tests/test_web_server.py
```

## Jika Mengubah Reconciliation

Jaga:

- fills schema tetap fleksibel,
- matching signal ke fill tidak terlalu agresif,
- unmatched entries tetap ditulis,
- KPI tetap jelas.

Test:

```powershell
pytest tests/test_live_reconciliation.py
pytest tests/test_paper_trading.py
pytest tests/test_paper_analytics.py
```

## Test Map Lengkap

```text
tests/test_ingest_validation.py        Ingestion dan canonical validation.
tests/test_rest_provider.py            REST provider dan env resolution.
tests/test_features.py                 Feature engineering.
tests/test_strategy.py                 Ranking/scoring.
tests/test_risk.py                     Position sizing dan risk limit.
tests/test_backtest.py                 Backtest metrics/live gate.
tests/test_integration_cli.py          End-to-end CLI pipeline.
tests/test_event_risk_update.py        Event-risk updater.
tests/test_universe_update.py          Universe updater.
tests/test_volatility_recalibration.py Vol target recalibration.
tests/test_model_v2_upgrade.py         Model V2 training/labeling/calibration.
tests/test_model_v2_promotion.py       Model V2 rollout/promotion.
tests/test_live_reconciliation.py      Broker fill reconciliation.
tests/test_paper_trading.py            Paper fills.
tests/test_paper_analytics.py          Swing audit/paper analytics.
tests/test_intraday_pipeline.py        Intraday pipeline.
tests/test_web_service.py              Dashboard service JSON contract.
tests/test_web_server.py               HTTP routes/auth/jobs.
tests/test_operational.py              Telegram/signal JSON basics.
tests/test_roadmap_ops.py              Data quality/ops checks.
```

## Dependency

Python:

- Python 3.11 direkomendasikan.

Install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dependency utama:

- pandas
- numpy
- matplotlib
- scikit-learn
- ta
- pyarrow
- jinja2
- pydantic
- rich
- pytest
- yfinance
- websocket-client
- lightgbm
- xgboost

## Validasi Minimum Sebelum Selesai

Untuk perubahan dokumen saja:

- cek file terbaca,
- cek link/path masuk akal.

Untuk perubahan kode kecil:

- jalankan test terdekat.

Untuk perubahan pipeline:

- jalankan test integrasi terkait,
- jika memungkinkan jalankan `python -m src.cli run-daily --skip-telegram` dengan data sample atau config aman.

Untuk perubahan dashboard:

- jalankan test web service/server,
- cek `/api/health` dan `/api/dashboard` jika server dijalankan.

## Dokumen Pendukung

Baca sesuai kebutuhan:

- `README.md`
- `docs/PENJELASAN_PROYEK_LENGKAP.md`
- `docs/SOP_DAILY.md`
- `docs/TRADER_BEGINNER_PLAYBOOK.md`
- `docs/MODEL_V2_BLUEPRINT.md`
- `docs/LIVE_RECONCILIATION.md`
- `docs/N8N_LOCAL_SETUP.md`
- `docs/N8N_RUNBOOK.md`
- `docs/PUBLIC_REPO_CHECKLIST.md`
- `docs/DEPLOY_HEALTHCHECK_CHECKLIST.md`

## Mental Model Untuk Coding

Perubahan kecil di scoring/risk bisa mengubah sinyal live. Karena itu, setiap perubahan yang mempengaruhi kandidat, gate, size, atau report harus dilihat sebagai perubahan behavior trading, bukan sekadar perubahan teknis.

Sistem ini sengaja defensif. Hasil kosong sering lebih aman daripada sinyal yang dipaksakan.

