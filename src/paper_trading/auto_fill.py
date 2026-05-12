from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.utils import atomic_write_json, atomic_write_text

REQUIRED_FILL_COLUMNS = [
    "executed_at",
    "ticker",
    "mode",
    "side",
    "qty",
    "price",
    "fee_idr",
    "realized_r",
    "pnl_idr",
    "trade_id",
    "run_id",
]

MODE_HORIZON_DAYS = {
    "t1": 1,
    "swing": 10,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, "", "NaT"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _profit_factor(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    series = pd.to_numeric(values, errors="coerce").dropna()
    if series.empty:
        return 0.0
    gross_profit = float(series[series > 0].sum())
    gross_loss = float(-series[series < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _load_signal_rows(snapshot_dir: str | Path, lookback_days: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    base = Path(snapshot_dir)
    if not base.exists():
        return [], {
            "snapshot_files_total": 0,
            "snapshot_files_in_window": 0,
            "signals_total": 0,
            "valid_signals": 0,
        }

    cutoff = datetime.utcnow() - timedelta(days=max(1, int(lookback_days)))
    rows: list[dict[str, Any]] = []
    snapshot_files_total = 0
    snapshot_files_in_window = 0
    signals_total = 0
    for path in sorted(base.glob("signals_*.json")):
        snapshot_files_total += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        generated_at = _parse_dt(payload.get("generated_at"))
        if generated_at is None or generated_at < cutoff:
            continue
        snapshot_files_in_window += 1
        run_id = str(payload.get("run_id", "")).strip()
        signals = payload.get("signals", [])
        if not run_id or not isinstance(signals, list):
            continue
        signals_total += len(signals)
        for index, raw in enumerate(signals):
            if not isinstance(raw, dict):
                continue
            ticker = str(raw.get("ticker", "")).strip().upper()
            mode = str(raw.get("mode", "")).strip().lower()
            qty = int(round(_safe_float(raw.get("size"), 0.0)))
            if not ticker or mode not in MODE_HORIZON_DAYS or qty <= 0:
                continue
            rows.append(
                {
                    "signal_id": f"{run_id}:{ticker}:{mode}:{index}",
                    "run_id": run_id,
                    "signal_time": generated_at,
                    "ticker": ticker,
                    "mode": mode,
                    "qty": qty,
                    "entry_plan": _safe_float(raw.get("entry"), 0.0),
                    "stop_plan": _safe_float(raw.get("stop"), 0.0),
                    "tp1_plan": _safe_float(raw.get("tp1"), 0.0),
                    "tp2_plan": _safe_float(raw.get("tp2"), 0.0),
                    "score": _safe_float(raw.get("score"), 0.0),
                    "est_roundtrip_cost_pct": _safe_float(raw.get("est_roundtrip_cost_pct"), 0.0),
                }
            )
    rows.sort(key=lambda row: (row["signal_time"], row["ticker"], row["mode"]))
    return rows, {
        "snapshot_files_total": int(snapshot_files_total),
        "snapshot_files_in_window": int(snapshot_files_in_window),
        "signals_total": int(signals_total),
        "valid_signals": int(len(rows)),
    }


def _load_prices(prices_path: str | Path) -> pd.DataFrame:
    path = Path(prices_path)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame()
    required = {"date", "ticker", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "ticker", "open", "high", "low", "close"]).copy()
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


def _load_existing_fills(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        return pd.DataFrame(columns=REQUIRED_FILL_COLUMNS)
    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=df.columns.tolist() or REQUIRED_FILL_COLUMNS)
    for col in REQUIRED_FILL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


def _entry_execution_time(date_value: pd.Timestamp) -> str:
    base = pd.Timestamp(date_value).normalize() + pd.Timedelta(hours=9, minutes=15)
    return base.isoformat()


def _simulate_fill(
    signal: dict[str, Any],
    ticker_prices: pd.DataFrame,
    settings: Settings,
) -> tuple[str, dict[str, Any] | None]:
    signal_time = _parse_dt(signal.get("signal_time"))
    if signal_time is None:
        return "invalid_signal_time", None

    future = ticker_prices[ticker_prices["date"] > pd.Timestamp(signal_time.date())].copy()
    if future.empty:
        return "waiting_entry_bar", None

    entry_bar = future.iloc[0]
    horizon_days = MODE_HORIZON_DAYS.get(str(signal.get("mode", "")).strip().lower(), 0)
    if horizon_days <= 0:
        return "invalid_mode", None

    entry_index = int(future.index[0])
    window = ticker_prices.loc[entry_index : entry_index + horizon_days - 1].copy()
    if len(window) < horizon_days:
        return "waiting_exit_horizon", None

    paper_cfg = settings.paper_trading
    buy_fee_pct = max(0.0, float(paper_cfg.buy_fee_pct))
    sell_fee_pct = max(0.0, float(paper_cfg.sell_fee_pct))
    slippage_pct = max(0.0, float(paper_cfg.slippage_pct))
    qty = int(signal["qty"])

    entry_plan = _safe_float(signal.get("entry_plan"), 0.0)
    stop_plan = _safe_float(signal.get("stop_plan"), 0.0)
    tp2_plan = _safe_float(signal.get("tp2_plan"), 0.0)

    entry_raw = _safe_float(entry_bar.get("open"), 0.0) or entry_plan
    if entry_raw <= 0:
        return "invalid_entry_price", None

    entry_exec = entry_raw * (1.0 + (slippage_pct / 100.0))
    stop_exec = stop_plan * (1.0 - (slippage_pct / 100.0)) if stop_plan > 0 else 0.0
    tp2_exec = tp2_plan * (1.0 - (slippage_pct / 100.0)) if tp2_plan > 0 else 0.0

    exit_price = 0.0
    exit_reason = ""
    exit_bar = window.iloc[-1]
    for _, bar in window.iterrows():
        bar_low = _safe_float(bar.get("low"), 0.0)
        bar_high = _safe_float(bar.get("high"), 0.0)
        if stop_plan > 0 and bar_low <= stop_plan:
            exit_price = stop_exec
            exit_reason = "stop_loss"
            exit_bar = bar
            break
        if tp2_plan > 0 and bar_high >= tp2_plan:
            exit_price = tp2_exec
            exit_reason = "tp2_hit"
            exit_bar = bar
            break

    if exit_price <= 0:
        exit_price = _safe_float(exit_bar.get("close"), 0.0) * (1.0 - (slippage_pct / 100.0))
        exit_reason = "time_exit"

    entry_notional = entry_exec * qty
    exit_notional = exit_price * qty
    buy_fee_idr = entry_notional * (buy_fee_pct / 100.0)
    sell_fee_idr = exit_notional * (sell_fee_pct / 100.0)
    total_fee_idr = buy_fee_idr + sell_fee_idr
    net_pnl = (exit_notional - entry_notional) - total_fee_idr

    risk_per_share = max(entry_exec - stop_plan, entry_exec * 0.005, 1e-9)
    realized_r = net_pnl / max(risk_per_share * qty, 1e-9)
    cost_pct = buy_fee_pct + sell_fee_pct + (2.0 * slippage_pct)
    trade_id = f"PAPER:{signal['run_id']}:{signal['ticker']}:{signal['mode']}"

    payload = {
        "executed_at": _entry_execution_time(entry_bar["date"]),
        "ticker": signal["ticker"],
        "mode": signal["mode"],
        "side": "BUY",
        "qty": qty,
        "price": round(entry_exec, 4),
        "fee_idr": round(total_fee_idr, 2),
        "cost_pct": round(cost_pct, 4),
        "realized_r": round(realized_r, 6),
        "pnl_idr": round(net_pnl, 2),
        "trade_id": trade_id,
        "run_id": signal["run_id"],
        "signal_generated_at": signal_time.isoformat(),
        "entry_price_plan": round(entry_plan, 4),
        "stop_price_plan": round(stop_plan, 4),
        "tp1_price_plan": round(_safe_float(signal.get("tp1_plan"), 0.0), 4),
        "tp2_price_plan": round(tp2_plan, 4),
        "exit_price_exec": round(exit_price, 4),
        "exit_reason": exit_reason,
        "exit_at": pd.Timestamp(exit_bar["date"]).isoformat(),
        "horizon_days": horizon_days,
        "paper_fill": True,
        "paper_fill_status": "closed",
        "score": round(_safe_float(signal.get("score"), 0.0), 4),
        "est_roundtrip_cost_pct": round(_safe_float(signal.get("est_roundtrip_cost_pct"), 0.0), 4),
    }
    return "generated", payload


def _write_fills_csv(path: str | Path, df: pd.DataFrame) -> str:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_text = df.to_csv(index=False)
    atomic_write_text(out_path, csv_text, encoding="utf-8")
    return str(out_path)


def _persist_payload(state_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(state_path, payload)
    summary_path = state_path.parent / "paper_fills_summary.json"
    atomic_write_json(summary_path, payload)
    payload["summary_path"] = str(summary_path)
    return payload


def maybe_generate_paper_fills(
    settings: Settings,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    cfg = settings.paper_trading
    state_path = Path(cfg.state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "enabled": bool(cfg.enabled),
        "auto_fill_enabled": bool(cfg.auto_fill_enabled),
        "mode": str(cfg.mode).strip().lower(),
        "fills_csv_path": settings.reconciliation.fills_csv_path,
        "snapshot_dir": settings.reconciliation.signal_snapshot_dir,
        "state_path": str(state_path),
        "generated_count": 0,
        "skipped_existing": 0,
        "pending_count": 0,
        "skipped_invalid": 0,
        "snapshot_files_total": 0,
        "snapshot_files_in_window": 0,
        "signals_total": 0,
        "valid_signals": 0,
        "trade_count_total": 0,
        "win_rate_pct": 0.0,
        "expectancy_r": 0.0,
        "profit_factor_r": 0.0,
        "recent_generated": [],
    }

    if not cfg.enabled or not cfg.auto_fill_enabled or str(cfg.mode).strip().lower() != "paper":
        payload["status"] = "disabled"
        payload["message"] = "Paper auto-fill is disabled"
        return _persist_payload(state_path, payload)

    active_lookback = int(lookback_days) if lookback_days is not None else max(60, int(settings.reconciliation.lookback_days))
    signals, signal_stats = _load_signal_rows(settings.reconciliation.signal_snapshot_dir, active_lookback)
    payload.update(signal_stats)
    if payload["snapshot_files_in_window"] <= 0:
        payload["status"] = "no_snapshots"
        payload["message"] = "No signal snapshots found for paper fill generation"
        return _persist_payload(state_path, payload)

    if payload["signals_total"] <= 0:
        payload["status"] = "no_signals"
        payload["message"] = "Signal snapshots were found, but all of them contained zero executable signals"
        return _persist_payload(state_path, payload)

    if not signals:
        payload["status"] = "no_valid_signals"
        payload["message"] = "Signal snapshots were found, but none of the signals passed paper-fill validation"
        return _persist_payload(state_path, payload)

    prices = _load_prices(settings.data.canonical_prices_path)
    if prices.empty:
        payload["status"] = "missing_prices"
        payload["message"] = "Daily prices are not available for paper fill generation"
        return _persist_payload(state_path, payload)

    existing = _load_existing_fills(settings.reconciliation.fills_csv_path)
    existing_trade_ids = set(existing.get("trade_id", pd.Series(dtype=str)).astype(str).str.strip().tolist())
    grouped_prices = {
        str(ticker): grp.reset_index(drop=True)
        for ticker, grp in prices.groupby("ticker", dropna=False)
    }

    new_rows: list[dict[str, Any]] = []
    for signal in signals:
        trade_id = f"PAPER:{signal['run_id']}:{signal['ticker']}:{signal['mode']}"
        if trade_id in existing_trade_ids:
            payload["skipped_existing"] += 1
            continue
        ticker_prices = grouped_prices.get(signal["ticker"])
        if ticker_prices is None or ticker_prices.empty:
            payload["pending_count"] += 1
            continue
        status, row = _simulate_fill(signal=signal, ticker_prices=ticker_prices, settings=settings)
        if status == "generated" and row is not None:
            new_rows.append(row)
        elif status.startswith("waiting"):
            payload["pending_count"] += 1
        else:
            payload["skipped_invalid"] += 1

    final_df = existing.copy()
    if new_rows:
        final_df = pd.concat([final_df, pd.DataFrame(new_rows)], ignore_index=True, sort=False)
        if "executed_at" in final_df.columns:
            final_df = final_df.sort_values(["executed_at", "ticker", "mode"], ascending=[True, True, True]).reset_index(drop=True)
        _write_fills_csv(settings.reconciliation.fills_csv_path, final_df)

    paper_only = final_df[final_df.get("trade_id", pd.Series(dtype=str)).astype(str).str.startswith("PAPER:")].copy()
    realized_r = pd.to_numeric(paper_only.get("realized_r"), errors="coerce").dropna()
    payload["generated_count"] = int(len(new_rows))
    payload["trade_count_total"] = int(len(paper_only))
    if not realized_r.empty:
        payload["win_rate_pct"] = round(float((realized_r > 0).mean() * 100.0), 2)
        payload["expectancy_r"] = round(float(realized_r.mean()), 4)
        payload["profit_factor_r"] = round(float(_profit_factor(realized_r)), 4)
    payload["recent_generated"] = [
        {
            "trade_id": str(row.get("trade_id", "")),
            "ticker": str(row.get("ticker", "")),
            "mode": str(row.get("mode", "")),
            "executed_at": str(row.get("executed_at", "")),
            "exit_reason": str(row.get("exit_reason", "")),
            "realized_r": _safe_float(row.get("realized_r"), 0.0),
            "pnl_idr": _safe_float(row.get("pnl_idr"), 0.0),
        }
        for row in new_rows[:10]
    ]

    if new_rows:
        payload["status"] = "ok"
        payload["message"] = f"Generated {len(new_rows)} new paper fills"
    else:
        payload["status"] = "no_new_fills"
        payload["message"] = "No new paper fills were ready to close"

    return _persist_payload(state_path, payload)
