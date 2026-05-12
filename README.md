# IDX Trading Lab

> 🚀 **Live Premium Dashboard:** [https://idx-trading-lab.vercel.app](https://idx-trading-lab.vercel.app)

An Institutional-Grade automated daily trading research pipeline for Indonesian stocks (IDX). It fetches data, computes technical/statistical features, scores candidates using Machine Learning V2 (LightGBM/XGBoost), applies Risk-On/Risk-Off regime filters, calculates Kelly Criterion position sizing, and outputs executable daily plans via a sleek Glassmorphism web dashboard.

Features:
- **ML V2 Scoring Engine**: Advanced probability scoring and Shadow/A-B testing.
- **Dynamic Guardrails**: Macro Regime Thresholds and Sector Diversification Limits (Max 35%).
- **Closed-Loop Feedback**: Live reconciliation and performance expectancy tracking.
- **Automated Pipeline**: 100% Serverless execution via GitHub Actions.
- **Premium UI**: React + Tailwind + GSAP dashboard hosted on Vercel.

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
- optional conservative profile: `config/settings.beginner.json`

Current default profile is tuned for defensive live operation:

- swing-priority (`min_live_score_t1=999`, `min_live_score_swing=70`)
- tighter risk (`risk_per_trade_pct=0.5`, `daily_loss_stop_r=1.5`)
- stress-tested costs (`buy_fee_pct=0.2`, `sell_fee_pct=0.3`, `slippage_pct=0.15`)
- gradual regime filter (`min_breadth_ma50_pct=35`, `min_breadth_ma20_pct=30`)

Schema is validated by pydantic (`src/config.py`).

Default setup now uses:

- primary REST provider: EODHD (`base_url_template`)
- token from env placeholder: `${EODHD_API_TOKEN}`
- automatic fallback chain: `REST -> yfinance -> CSV`

Risk sizing now supports:

- ATR + realized volatility blend (`risk.volatility_realized_weight`)
- dynamic market-vol regime cap (`calm/normal/high/stress`)
- configurable regime caps for position-size multiplier
- mode-level execution caps and priority (`risk.max_positions_t1`, `risk.max_positions_swing`, `risk.execution_mode_priority`)

## Data contract

Canonical price columns:

- `date,ticker,open,high,low,close,volume,source,ingested_at`

Universe file:

- `data/reference/universe_lq45_idx30.csv`
- optional event-risk blocklist: `data/reference/event_risk_blacklist.csv` (local live file, git-ignored)
- tracked baseline snapshot: `data/reference/event_risk_blacklist.sample.csv`
- optional auto-update feeds for event-risk: `pipeline.event_risk.auto_update`

## CLI

```bash
python -m src.cli update-universe --force
python -m src.cli update-event-risk --force
python -m src.cli recalibrate-volatility --force
python -m src.cli ingest-daily
python -m src.cli ingest-intraday --timeframe 5m --lookback-minutes 240
python -m src.cli backfill-history --years 2
python -m src.cli compute-features
python -m src.cli score
python -m src.cli backtest
python -m src.cli run-intraday
python -m src.cli run-intraday-daemon
python -m src.cli reconcile-live --fills-path data/live/trade_fills.sample.csv
python -m src.cli weekly-kpi
python -m src.cli send-telegram
python -m src.cli run-daily
python -m src.cli serve-web --host 127.0.0.1 --port 8080 --open-browser
```

PowerShell automation:

```bash
powershell -ExecutionPolicy Bypass -File scripts/validate_env.ps1
powershell -ExecutionPolicy Bypass -File scripts/backfill_2y.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1 -SettingsPath config/settings.beginner.json
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1 -DebugReasons
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_beginner.ps1
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_beginner.ps1 -DebugReasons
```

Local n8n setup guide:

- `docs/N8N_LOCAL_SETUP.md`

Model v2 integration blueprint:

- `docs/MODEL_V2_BLUEPRINT.md`
- `docs/TRADER_BEGINNER_PLAYBOOK.md`

Backward compatibility:

```bash
python -m src.run_daily run-daily
```

## Web Dashboard

The project now includes an interactive web app layer built on top of the same production pipeline engine.

Run it locally:

```bash
python -m src.cli serve-web --host 127.0.0.1 --port 8080 --open-browser
```

Or directly:

```bash
python -m src.web.server --host 127.0.0.1 --port 8080 --open-browser
```

Main capabilities:

- monitor live signals, execution plan, event-risk exclusions, and recent run logs
- interactive signal explorer (mode filter, min score, ticker search, sortable table)
- auto-refresh dashboard in the browser for near-real-time updates
- view guardrail status (model gate, regime status, kill-switch state)

Current web posture:

- `/` serves the public premium dashboard
- legacy console is no longer publicly exposed
- operational access is routed through `/ops-login.html`
- protected report view is available through `/ops-report.html`
- `src.cli` and `src.web.server` auto-load `.env` from the working directory on startup
- protected operational routes can be gated with:
  - `IDX_WEB_USERNAME`
  - `IDX_WEB_PASSWORD`
- optional ops-login guardrails are available through:
  - `IDX_WEB_OPS_LOGIN_ALLOWLIST`
  - `IDX_WEB_OPS_LOGIN_RATE_LIMIT_MAX_REQUESTS`
  - `IDX_WEB_OPS_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- optional failed-login lockout is available through:
  - `IDX_WEB_AUTH_LOCKOUT_MAX_FAILURES`
  - `IDX_WEB_AUTH_LOCKOUT_SECONDS`
- `run-daily` remains localhost-only even when auth is enabled

Quick Docker start:

```bash
docker compose up -d --build
```

With bundled Nginx proxy profile:

```bash
docker compose --profile proxy up -d --build
```

Production-ready Docker/TLS flow:

```bash
cp .env.example .env
# edit IDX_PUBLIC_DOMAIN, LETSENCRYPT_EMAIL, IDX_WEB_USERNAME, IDX_WEB_PASSWORD
docker compose -f docker-compose.prod.yml up -d idx-web nginx
docker compose -f docker-compose.prod.yml --profile certbot-init run --rm certbot-init
# switch IDX_NGINX_TEMPLATE in .env to ./deploy/nginx.prod.conf.template
docker compose -f docker-compose.prod.yml up -d nginx
docker compose -f docker-compose.prod.yml --profile tls up -d certbot-renew
```

Production deploy artifacts:

- `docker-compose.prod.yml`
- `docker-compose.prod.override.yml`
- `deploy/nginx.bootstrap.conf.template`
- `deploy/nginx.prod.conf.template`
- `deploy/init-letsencrypt.sh.example`
- `deploy/fail2ban/`
- `docs/DEPLOY_HEALTHCHECK_CHECKLIST.md`
- `docs/PUBLIC_CUTOVER_PLAN.md`

## Oracle Always Free (24/7) Quick Deploy

After SSH into your Oracle Ubuntu VM, run:

```bash
sudo apt-get update -y
sudo apt-get install -y git
git clone <YOUR_REPO_URL>
cd idx-trading-lab
bash deploy/oracle/bootstrap_oracle.sh <YOUR_REPO_URL> <YOUR_DOMAIN_OR__>
```

Examples:

```bash
bash deploy/oracle/bootstrap_oracle.sh https://github.com/username/idx-trading-lab.git _
bash deploy/oracle/bootstrap_oracle.sh https://github.com/username/idx-trading-lab.git trading.example.com
```

What it sets up automatically:

- Python env + dependencies
- `idx-web` systemd service (web dashboard)
- `idx-daemon` systemd service (intraday scheduler)
- Nginx reverse proxy on port `80`

Update after each `git push`:

```bash
bash deploy/oracle/update_oracle.sh /opt/idx-trading-lab
```

## Intraday Mode (Polling + Optional WebSocket)

The project now supports intraday pipeline with resilient ingestion:

- provider chain: `WebSocket (optional) -> REST polling -> yfinance polling -> CSV fallback`
- canonical intraday storage at `data/raw/prices_intraday.csv`
- intraday scoring output:
  - `reports/intraday_top.csv`
  - `reports/intraday_execution_plan.csv`
  - `reports/intraday_signal.json`
  - `reports/intraday_signal_funnel.json`
- daemon state and reconnect diagnostics:
  - `reports/intraday_daemon_state.json`
  - `reports/intraday_status.json`

Run one intraday cycle:

```bash
python -m src.cli run-intraday
```

Run continuous daemon (with reconnect/backoff):

```bash
python -m src.cli run-intraday-daemon
```

Bounded daemon run for testing:

```bash
python -m src.cli run-intraday-daemon --max-loops 3
```

## Shadow Model + Live Reconciliation

Merged enhancement modules now include:

- shadow scoring model (`src/model_v2`) with A/B output vs current scorer
- signal snapshot writer per run (`reports/snapshots/signals_<run_id>.json`)
- live fills reconciliation report (`reconcile-live`)
- weekly KPI and beginner coaching notes

Run manually:

```bash
python -m src.cli reconcile-live --fills-path data/live/trade_fills.sample.csv --lookback-days 45
python -m src.cli weekly-kpi
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
- `reports/model_v2_shadow_signals.csv`
- `reports/model_v2_shadow_signals.json`
- `reports/model_v2_ab_test.json`
- `reports/live_reconciliation.json`
- `reports/live_reconciliation.md`
- `reports/live_reconciliation_details.csv`
- `reports/weekly_kpi.json`
- `reports/weekly_kpi.md`
- `reports/beginner_coaching.md`
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
