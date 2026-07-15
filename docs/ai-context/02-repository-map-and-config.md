# 02 - Repository Map And Config

## Struktur Direktori

```text
src/
  cli.py                    Entry point utama pipeline dan command CLI.
  run_daily.py              Wrapper kompatibilitas lama ke src.cli.run_daily.
  config.py                 Schema settings berbasis pydantic.
  ingest/                   Load dan validasi data harga.
  features/                 Feature engineering dari OHLCV.
  strategy/                 Scoring t1, swing, intraday.
  risk/                     Position sizing, event-risk, volatility recalibration.
  backtest/                 Backtest, metrics, walk-forward gate.
  model_v2/                 Training, inference, shadow, calibration, promotion.
  report/                   HTML/JSON report, weekly KPI, reconciliation, coaching.
  web/                      Service dan HTTP server dashboard.
  intraday/                 Pipeline intraday.
  paper_trading/            Simulasi paper fills dari snapshot sinyal.
  analytics/                Audit tambahan seperti swing audit.
  runtime/                  Mode/regime policy.
  notify/                   Telegram.
  utils/                    IO, env loader, json logger.
```

```text
config/
  settings.json             Runtime config utama.
  settings.example.json     Template config aman.
  settings.beginner.json    Profil konservatif.

data/
  raw/                      Data harga canonical dan intraday.
  reference/                Universe dan event-risk blacklist.
  live/                     CSV fills broker manual.

reports/
  *.csv, *.json, *.html     Output pipeline live.
  snapshots/                Snapshot sinyal historis.

web/
  *.html, *.css, *.js       Frontend dashboard statis.

docs/
  *.md                      Dokumentasi operasional dan blueprint.
```

## Entry Point

CLI utama:

```powershell
python -m src.cli <command>
```

Command penting:

```powershell
python -m src.cli ingest-daily
python -m src.cli backfill-history --years 2
python -m src.cli compute-features
python -m src.cli score
python -m src.cli backtest
python -m src.cli walk-forward
python -m src.cli model-v2-promotion
python -m src.cli reconcile-live
python -m src.cli send-telegram
python -m src.cli run-daily
```

Wrapper lama:

```powershell
python -m src.run_daily --settings config/settings.json
```

Web server:

```powershell
python -m src.web.server --host 127.0.0.1 --port 8080
```

Catatan: `src.cli.py` saat dokumen ini dibuat tidak punya subcommand `serve-web`. Jangan memakai `python -m src.cli serve-web` kecuali parser sudah ditambah.

## Runtime Config

Config dibaca dari:

```text
config/settings.json
```

Schema ada di:

```text
src/config.py
```

Root settings:

- `data`
- `pipeline`
- `risk`
- `backtest`
- `validation`
- `regime`
- `guardrail`
- `model_v2`
- `coaching`
- `reconciliation`
- `notifications`

## Provider Data

Default flow:

```text
REST -> yfinance -> CSV
```

REST provider memakai:

- `settings.data.provider.rest.base_url_template`
- `settings.data.provider.rest.query_params`
- `settings.data.provider.rest.column_mapping`

Token EODHD dibaca dari env placeholder:

```text
${EODHD_API_TOKEN}
```

## Environment Variables

Jangan tulis secret ke repo. Gunakan env:

```text
EODHD_API_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
IDX_WEB_USERNAME
IDX_WEB_PASSWORD
IDX_WEB_OPS_LOGIN_ALLOWLIST
```

## Kontrak Data Harian

Canonical daily price columns:

```text
date,ticker,open,high,low,close,volume,source,ingested_at
```

File default:

```text
data/raw/prices_daily.csv
```

Fallback sample:

```text
data/raw/prices_daily.sample.csv
```

## Kontrak Data Intraday

Kolom umum:

```text
timestamp,ticker,open,high,low,close,volume,timeframe,source,ingested_at
```

File default:

```text
data/raw/prices_intraday.csv
```

## Universe

File:

```text
data/reference/universe_lq45_idx30.csv
```

Minimal kolom:

```text
ticker
```

Universe bisa auto-update jika `data.universe_auto_update.enabled=true`.

## Event Risk

Live file lokal:

```text
data/reference/event_risk_blacklist.csv
```

Sample tracked:

```text
data/reference/event_risk_blacklist.sample.csv
```

Status aktif default:

- `SUSPEND`
- `UMA`
- `MATERIAL`
- `SPECIAL_MONITORING`

## Live Fills

File fills broker:

```text
data/live/trade_fills.csv
```

Template:

```text
data/live/trade_fills.sample.csv
```

Dipakai oleh live reconciliation.

