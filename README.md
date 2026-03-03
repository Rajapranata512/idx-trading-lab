# idx-trading-lab

Production-oriented EOD research pipeline for Indonesian stocks (IDX):

- ingest -> validate -> features -> score -> risk -> report -> notify
- dual signal model: `T+1` and `Swing 1-4 weeks`
- semi-auto execution workflow (manual order entry in Stockbit with Auto Order/Bracket)

## What this project does

This project does **not** execute broker orders directly.

It generates:

- top candidates by mode (`top_t1`, `top_swing`)
- suggested entry / stop / TP1 / TP2 / position size
- HTML / CSV / JSON reports
- optional Telegram summary

## Runtime config

Primary runtime config:

- `config/settings.json`

Schema is validated by pydantic (`src/config.py`).

Default setup now uses:

- primary REST provider: EODHD (`base_url_template`)
- token from env placeholder: `${EODHD_API_TOKEN}`
- automatic fallback chain: `REST -> yfinance -> CSV`

Risk sizing now supports:

- ATR + realized volatility blend (`risk.volatility_realized_weight`)
- dynamic market-vol regime cap (`calm/normal/high/stress`)
- configurable regime caps for position-size multiplier

## Data contract

Canonical price columns:

- `date,ticker,open,high,low,close,volume,source,ingested_at`

Universe file:

- `data/reference/universe_lq45_idx30.csv`
- optional event-risk blocklist: `data/reference/event_risk_blacklist.csv`
- optional auto-update feeds for event-risk: `pipeline.event_risk.auto_update`

## CLI

```bash
python -m src.cli update-universe --force
python -m src.cli update-event-risk --force
python -m src.cli recalibrate-volatility --force
python -m src.cli ingest-daily
python -m src.cli backfill-history --years 2
python -m src.cli compute-features
python -m src.cli score
python -m src.cli backtest
python -m src.cli send-telegram
python -m src.cli run-daily
```

PowerShell automation:

```bash
powershell -ExecutionPolicy Bypass -File scripts/validate_env.ps1
powershell -ExecutionPolicy Bypass -File scripts/backfill_2y.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1 -DebugReasons
```

Local n8n setup guide:

- `docs/N8N_LOCAL_SETUP.md`

Backward compatibility:

```bash
python -m src.run_daily run-daily
```

## Output files

- `data/raw/prices_daily.csv`
- `data/processed/features.parquet`
- `reports/top_t1.csv`
- `reports/top_swing.csv`
- `reports/daily_report.csv`
- `reports/execution_plan.csv`
- `reports/daily_report.html`
- `reports/daily_signal.json`
- `reports/backtest_metrics.json`
- `reports/event_risk_active.csv`
- `reports/event_risk_excluded.csv`
- `reports/universe_update_state.json`
- `reports/run_log_YYYYMMDD.json`

## Daily operational flow

1. Run `python -m src.cli run-daily` (auto includes weekly universe refresh attempt and event-risk auto-refresh if enabled).
2. Optional manual refresh: `python -m src.cli update-event-risk --force`.
3. Review `reports/daily_report.html`.
4. Select max 1-3 signals.
5. Place manual order in Stockbit and set Auto Order/Bracket.
6. Do not override stop unless invalidation rule is met.

For first setup, run one-time historical bootstrap first:

1. Set `EODHD_API_TOKEN` (optional if you rely on yfinance fallback).
2. Run `python -m src.cli backfill-history --years 2`.
3. Then run `python -m src.cli run-daily`.

## Notes

- This is research infrastructure, not financial advice.
- No strategy can guarantee profit.

## Public Repo Safety

- Keep secrets in environment variables only (`.env` is ignored, `.env.example` is safe template).
- `n8n/workflows/idx_trading_daily.json` uses `{{$env.TELEGRAM_CHAT_ID}}` and does not store local credential IDs.
- Raw local market dump `data/raw/prices_daily.csv` is intentionally ignored for public publishing.
- If a secret was ever committed, rotate it immediately (EODHD and Telegram token/chat access).
