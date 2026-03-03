# n8n Runbook (Robust)

For full local (non-cloud) installation flow, see:

- `docs/N8N_LOCAL_SETUP.md`

## 1) One-Time Local Setup

Close old terminal, open a new one, then validate env:

`powershell -ExecutionPolicy Bypass -File scripts/validate_env.ps1`

Expected: all 3 env vars detected.

## 2) Required Environment Variables

- `EODHD_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

For n8n host, these must exist in the environment seen by the n8n process/service.

## 3) Import Workflow

Import this file:

- `n8n/workflows/idx_trading_daily.json`

Workflow now uses:

- `Run Daily Retry` -> `scripts/run_daily_retry.ps1`
- Internal retry: 3 attempts (`60s`, `120s`, `240s`)
- Summary marker: `N8N_SUMMARY=...` parsed by code node
- `Execute Command` node is required; for n8n v2+, run n8n with `NODES_EXCLUDE=[]`.

## 4) Telegram Credential

1. Create `Telegram API` credential in n8n.
2. Paste your bot token.
3. Open node `Telegram Status`, choose that credential.
4. Ensure env `TELEGRAM_CHAT_ID` is set on the n8n host (workflow reads it via expression).
5. Save workflow.

## 5) Schedule

Default cron:

- `25 16 * * 1-5` (Mon-Fri, 16:25 WIB)
- `10 09 * * 1` (Mon, 09:10 WIB) for weekly universe refresh (`scripts/update_universe.ps1`)

## 6) Bootstrap and Daily Commands

One-time bootstrap:

`powershell -ExecutionPolicy Bypass -File scripts/backfill_2y.ps1`

Manual daily run:

`powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1`

Manual universe refresh:

`powershell -ExecutionPolicy Bypass -File scripts/update_universe.ps1`

Manual event-risk refresh:

`powershell -ExecutionPolicy Bypass -File scripts/update_event_risk.ps1`

Manual volatility recalibration:

`powershell -ExecutionPolicy Bypass -File scripts/recalibrate_volatility.ps1`

Quick trade decision:

`powershell -ExecutionPolicy Bypass -File scripts/ops_daily_check.ps1`

One-command swing gate + top picks:

`powershell -ExecutionPolicy Bypass -File scripts/trade_gate_swing.ps1`

Walk-forward validation (manual audit):

`python -m src.cli walk-forward`

## 7) Status Semantics

Telegram status can be:

- `SUCCESS`: pipeline OK and signals available.
- `NO_SIGNAL`: run OK but no executable signal.
- `BLOCKED_BY_GATE`: run OK but backtest gate blocks live signal.
- `STALE_DATA`: latest market data too old.
- `PARTIAL_DATA`: too many tickers missing from ingest.
- `EVENT_RISK_UPDATE_ERROR`: event-risk auto-update failed (conservative no-trade).
- `FAILED`: run failed after retries.
- `SETUP_ERROR`: env/setup invalid.

Additional summary fields:

- `trade_ready`: true/false readiness flag for execution.
- `action`: `EXECUTE_MAX_3` or `NO_TRADE`.
- `action_reason`: short reason for action.
- `volatility_recalibration_status`: status of weekly volatility reference recalibration.

Backtest report fields:

- `gate_pass_insample`: gate from full-sample filtered backtest.
- `gate_pass_oos`: gate from walk-forward out-of-sample summary.
- `gate_pass`: final gate (combined when walk-forward gate enabled).

## 8) Profit and Risk Guardrails

- Do not force order execution when status is `BLOCKED_BY_GATE`.
- Trade only when gate passes and signal count > 0.
- Keep max positions and risk budget from `config/settings.json`.
- Live score filter defaults in `config/settings.json`:
  - `pipeline.min_live_score_t1 = 95`
  - `pipeline.min_live_score_swing = 65`
