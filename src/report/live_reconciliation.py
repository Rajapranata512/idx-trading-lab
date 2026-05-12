from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.utils import atomic_write_json, atomic_write_text

REQUIRED_FILLS_SCHEMA = [
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _safe_mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    numeric = pd.to_numeric(series, errors="coerce")
    value = numeric.mean()
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_median(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    numeric = pd.to_numeric(series, errors="coerce")
    value = numeric.median()
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_sum(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    numeric = pd.to_numeric(series, errors="coerce")
    value = numeric.sum()
    if pd.isna(value):
        return 0.0
    return float(value)


def _profit_factor(realized_r: pd.Series) -> float:
    if realized_r.empty:
        return 0.0
    s = pd.to_numeric(realized_r, errors="coerce").dropna()
    if s.empty:
        return 0.0
    gross_profit = float(s[s > 0].sum())
    gross_loss = float(-s[s < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    return atomic_write_json(path, payload)


def _canonical_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _canonical_mode(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, "", "NaT"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


def _coalesce_column(raw: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in raw.columns:
            return raw[name]
    return pd.Series([None] * len(raw), index=raw.index)


def write_signal_snapshot(
    run_id: str,
    signals: pd.DataFrame,
    out_dir: str | Path,
    generated_at: str | None = None,
) -> str:
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)

    payload_signals: list[dict[str, Any]] = []
    if not signals.empty:
        keep_cols = [
            "ticker",
            "mode",
            "score",
            "entry",
            "stop",
            "tp1",
            "tp2",
            "size",
            "reason",
            "liq_bucket",
            "est_slippage_pct",
            "est_roundtrip_cost_pct",
        ]
        cols = [c for c in keep_cols if c in signals.columns]
        out = signals[cols].copy()
        for c in ["score", "entry", "stop", "tp1", "tp2", "est_slippage_pct", "est_roundtrip_cost_pct"]:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce").round(6)
        if "size" in out.columns:
            out["size"] = pd.to_numeric(out["size"], errors="coerce").fillna(0).astype(int)
        payload_signals = out.to_dict(orient="records")

    payload = {
        "generated_at": generated_at or datetime.utcnow().isoformat(),
        "run_id": run_id,
        "signal_count": int(len(payload_signals)),
        "signals": payload_signals,
    }
    out_path = path / f"signals_{run_id}.json"
    return atomic_write_json(out_path, payload)


def _load_signal_snapshots(snapshot_dir: str | Path, lookback_days: int) -> tuple[pd.DataFrame, dict[str, int]]:
    base = Path(snapshot_dir)
    meta = {
        "snapshot_files_total": 0,
        "snapshot_files_in_window": 0,
        "snapshot_files_with_signals": 0,
    }
    if not base.exists():
        return pd.DataFrame(), meta
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(lookback_days)))
    rows: list[dict[str, Any]] = []
    for path in sorted(base.glob("signals_*.json")):
        meta["snapshot_files_total"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        signal_ts = _parse_dt(payload.get("generated_at"))
        if signal_ts is None:
            continue
        if signal_ts < cutoff:
            continue
        meta["snapshot_files_in_window"] += 1
        run_id = str(payload.get("run_id", "")).strip()
        signals = payload.get("signals", [])
        if not isinstance(signals, list):
            continue
        if len(signals) > 0:
            meta["snapshot_files_with_signals"] += 1
        for idx, row in enumerate(signals):
            if not isinstance(row, dict):
                continue
            ticker = _canonical_ticker(row.get("ticker"))
            if not ticker:
                continue
            mode = _canonical_mode(row.get("mode"))
            rows.append(
                {
                    "signal_id": f"{run_id}:{ticker}:{mode}:{idx}",
                    "run_id": run_id,
                    "signal_time": signal_ts,
                    "ticker": ticker,
                    "mode": mode,
                    "score": _safe_float(row.get("score"), 0.0),
                    "entry": _safe_float(row.get("entry"), 0.0),
                    "stop": _safe_float(row.get("stop"), 0.0),
                    "tp1": _safe_float(row.get("tp1"), 0.0),
                    "tp2": _safe_float(row.get("tp2"), 0.0),
                    "size": int(_safe_float(row.get("size"), 0.0)),
                    "est_roundtrip_cost_pct": _safe_float(row.get("est_roundtrip_cost_pct"), 0.0),
                    "liq_bucket": str(row.get("liq_bucket", "")).strip().lower(),
                }
            )
    if not rows:
        return pd.DataFrame(), meta
    return pd.DataFrame(rows).sort_values(["signal_time", "score"], ascending=[False, False]).reset_index(drop=True), meta


def _load_fills(fills_path: str | Path, lookback_days: int) -> pd.DataFrame:
    path = Path(fills_path)
    if not path.exists():
        return pd.DataFrame()

    raw = pd.read_csv(path)
    if raw.empty:
        return pd.DataFrame()
    missing_schema = [col for col in REQUIRED_FILLS_SCHEMA if col not in raw.columns]
    if missing_schema:
        raise ValueError(
            "trade_fills schema mismatch. Missing required columns: " + ", ".join(missing_schema)
        )

    out = pd.DataFrame(index=raw.index)
    out["executed_at"] = pd.to_datetime(raw["executed_at"], errors="coerce")
    out["ticker"] = raw["ticker"].astype(str).str.upper().str.strip()
    out["mode"] = raw["mode"].astype(str).str.lower().str.strip()
    out["side"] = raw["side"].astype(str).str.upper().str.strip()
    out["qty"] = pd.to_numeric(raw["qty"], errors="coerce")
    out["price"] = pd.to_numeric(raw["price"], errors="coerce")
    out["fee_idr"] = pd.to_numeric(raw["fee_idr"], errors="coerce")
    if "cost_pct" in raw.columns:
        out["cost_pct"] = pd.to_numeric(raw["cost_pct"], errors="coerce")
    else:
        out["cost_pct"] = pd.Series([float("nan")] * len(raw), index=raw.index)
    out["realized_r"] = pd.to_numeric(raw["realized_r"], errors="coerce")
    out["pnl_idr"] = pd.to_numeric(raw["pnl_idr"], errors="coerce")
    out["trade_id"] = raw["trade_id"].astype(str).str.strip()
    out["run_id"] = raw["run_id"].astype(str).str.strip()

    out = out.dropna(subset=["executed_at", "ticker", "price"]).copy()
    if out.empty:
        return pd.DataFrame()
    if getattr(out["executed_at"].dt, "tz", None) is not None:
        out["executed_at"] = out["executed_at"].dt.tz_convert(None)

    cutoff = datetime.utcnow() - timedelta(days=max(1, int(lookback_days)))
    out = out[out["executed_at"] >= cutoff].copy()
    if out.empty:
        return pd.DataFrame()

    out["qty"] = out["qty"].fillna(0.0)
    out["fee_idr"] = out["fee_idr"].fillna(0.0)
    out["trade_id"] = out["trade_id"].fillna("")
    out["run_id"] = out["run_id"].fillna("")
    return out.reset_index(drop=True)


def _aggregate_entry_fills(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame()
    df = fills.copy()

    has_side = df["side"].str.len().gt(0).any()
    if has_side:
        entry_side = {"BUY", "B", "LONG", "OPEN", "ENTRY"}
        df = df[df["side"].isin(entry_side)].copy()
    if df.empty:
        return pd.DataFrame()

    df["mode"] = df["mode"].fillna("")
    fallback_key = (
        df["executed_at"].dt.strftime("%Y-%m-%d") + "|" + df["ticker"] + "|" + df["mode"].replace("", "unknown")
    )
    has_trade_id = df["trade_id"].str.len().gt(0)
    df["trade_key"] = df["trade_id"].where(has_trade_id, fallback_key)

    rows: list[dict[str, Any]] = []
    for key, grp in df.groupby("trade_key", dropna=False):
        qty = pd.to_numeric(grp["qty"], errors="coerce").fillna(0.0)
        price = pd.to_numeric(grp["price"], errors="coerce").fillna(0.0)
        qty_for_vwap = qty.where(qty > 0, 1.0)
        notional = (price * qty_for_vwap).sum()
        qty_total = float(qty.where(qty > 0, 0.0).sum())
        if qty_total <= 0:
            qty_total = float(qty_for_vwap.sum())
        vwap = float(notional / max(qty_for_vwap.sum(), 1e-9))
        fee_total = float(pd.to_numeric(grp["fee_idr"], errors="coerce").fillna(0.0).sum())
        cost_pct_col = pd.to_numeric(grp["cost_pct"], errors="coerce")
        if cost_pct_col.notna().any():
            cost_pct = float(cost_pct_col.mean())
        else:
            cost_pct = float((fee_total / max(notional, 1e-9)) * 100.0)

        mode_values = grp["mode"].astype(str).str.strip()
        mode_values = mode_values[mode_values.str.len() > 0]
        mode = str(mode_values.mode().iloc[0]) if not mode_values.empty else ""

        realized_r_col = pd.to_numeric(grp["realized_r"], errors="coerce")
        realized_r = float(realized_r_col.mean()) if realized_r_col.notna().any() else float("nan")
        pnl_idr = float(pd.to_numeric(grp["pnl_idr"], errors="coerce").fillna(0.0).sum())
        run_id_values = grp["run_id"].astype(str).str.strip()
        run_id_values = run_id_values[run_id_values.str.len() > 0]

        rows.append(
            {
                "trade_key": str(key),
                "executed_at": pd.to_datetime(grp["executed_at"], errors="coerce").min(),
                "ticker": _canonical_ticker(grp["ticker"].iloc[0]),
                "mode": _canonical_mode(mode),
                "qty": int(round(qty_total)),
                "entry_price_exec": vwap,
                "notional_idr": float(notional),
                "fee_idr": fee_total,
                "realized_entry_cost_pct": cost_pct,
                "realized_r": realized_r,
                "pnl_idr": pnl_idr,
                "run_id_hint": str(run_id_values.iloc[0]) if not run_id_values.empty else "",
                "fill_rows": int(len(grp)),
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["executed_at"] = pd.to_datetime(out["executed_at"], errors="coerce")
    return out.sort_values("executed_at").reset_index(drop=True)


def _match_entries_to_signals(
    entries: pd.DataFrame,
    signals: pd.DataFrame,
    max_signal_lag_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if entries.empty:
        return pd.DataFrame(), pd.DataFrame()
    if signals.empty:
        return pd.DataFrame(), entries.copy()

    used_signal_ids: set[str] = set()
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for _, entry in entries.sort_values("executed_at").iterrows():
        et = pd.to_datetime(entry.get("executed_at"), errors="coerce")
        if pd.isna(et):
            unmatched.append(entry.to_dict())
            continue

        ticker = _canonical_ticker(entry.get("ticker"))
        mode = _canonical_mode(entry.get("mode"))
        candidates = signals[signals["ticker"] == ticker].copy()
        if mode:
            candidates = candidates[candidates["mode"] == mode].copy()

        if candidates.empty:
            unmatched.append(entry.to_dict())
            continue

        candidates["lag_days"] = (et - pd.to_datetime(candidates["signal_time"], errors="coerce")).dt.total_seconds() / 86400.0
        candidates = candidates[(candidates["lag_days"] >= 0.0) & (candidates["lag_days"] <= float(max_signal_lag_days))].copy()
        if candidates.empty:
            unmatched.append(entry.to_dict())
            continue
        candidates = candidates[~candidates["signal_id"].isin(used_signal_ids)].copy()
        if candidates.empty:
            unmatched.append(entry.to_dict())
            continue

        pick = candidates.sort_values(["lag_days", "signal_time", "score"], ascending=[True, False, False]).iloc[0]
        used_signal_ids.add(str(pick["signal_id"]))

        entry_price_plan = _safe_float(pick.get("entry"), 0.0)
        entry_price_exec = _safe_float(entry.get("entry_price_exec"), 0.0)
        slippage_pct = ((entry_price_exec - entry_price_plan) / max(entry_price_plan, 1e-9)) * 100.0
        matched.append(
            {
                "trade_key": str(entry.get("trade_key", "")),
                "executed_at": et.isoformat(),
                "lag_days": round(_safe_float(pick.get("lag_days"), 0.0), 4),
                "signal_id": str(pick.get("signal_id", "")),
                "signal_run_id": str(pick.get("run_id", "")),
                "ticker": ticker,
                "signal_mode": _canonical_mode(pick.get("mode")),
                "fill_mode": mode,
                "score": round(_safe_float(pick.get("score"), 0.0), 4),
                "entry_price_plan": round(entry_price_plan, 4),
                "entry_price_exec": round(entry_price_exec, 4),
                "entry_slippage_pct": round(slippage_pct, 4),
                "qty": int(_safe_float(entry.get("qty"), 0.0)),
                "notional_idr": round(_safe_float(entry.get("notional_idr"), 0.0), 2),
                "est_roundtrip_cost_pct": round(_safe_float(pick.get("est_roundtrip_cost_pct"), 0.0), 4),
                "realized_entry_cost_pct": round(_safe_float(entry.get("realized_entry_cost_pct"), 0.0), 4),
                "cost_diff_pct": round(
                    _safe_float(entry.get("realized_entry_cost_pct"), 0.0) - _safe_float(pick.get("est_roundtrip_cost_pct"), 0.0),
                    4,
                ),
                "fee_idr": round(_safe_float(entry.get("fee_idr"), 0.0), 2),
                "realized_r": round(_safe_float(entry.get("realized_r"), float("nan")), 4),
                "pnl_idr": round(_safe_float(entry.get("pnl_idr"), 0.0), 2),
                "liq_bucket": str(pick.get("liq_bucket", "")),
            }
        )

    matched_df = pd.DataFrame(matched)
    unmatched_df = pd.DataFrame(unmatched)
    return matched_df, unmatched_df


def _mode_kpi(matched: pd.DataFrame) -> list[dict[str, Any]]:
    if matched.empty:
        return []

    rows: list[dict[str, Any]] = []
    for mode, grp in matched.groupby("signal_mode"):
        rr = pd.to_numeric(grp.get("realized_r"), errors="coerce").dropna()
        win_rate = float((rr > 0).mean() * 100.0) if not rr.empty else 0.0
        rows.append(
            {
                "mode": str(mode),
                "matched_entries": int(len(grp)),
                "avg_entry_slippage_pct": round(_safe_mean(grp.get("entry_slippage_pct", pd.Series(dtype=float))), 4),
                "avg_abs_entry_slippage_pct": round(
                    _safe_mean(pd.to_numeric(grp.get("entry_slippage_pct", pd.Series(dtype=float)), errors="coerce").abs()),
                    4,
                ),
                "avg_est_roundtrip_cost_pct": round(_safe_mean(grp.get("est_roundtrip_cost_pct", pd.Series(dtype=float))), 4),
                "avg_realized_entry_cost_pct": round(
                    _safe_mean(grp.get("realized_entry_cost_pct", pd.Series(dtype=float))),
                    4,
                ),
                "realized_samples": int(len(rr)),
                "win_rate_pct": round(win_rate, 2),
                "expectancy_r": round(_safe_mean(rr), 4) if not rr.empty else 0.0,
                "profit_factor_r": round(_profit_factor(rr), 4) if not rr.empty else 0.0,
            }
        )
    rows.sort(key=lambda x: x["mode"])
    return rows


def _summary_payload(
    settings: Settings,
    lookback_days: int,
    fills_path: str,
    snapshot_meta: dict[str, int],
    signals: pd.DataFrame,
    entry_fills: pd.DataFrame,
    matched: pd.DataFrame,
    unmatched: pd.DataFrame,
) -> dict[str, Any]:
    signal_count = int(len(signals))
    fill_count = int(len(entry_fills))
    matched_count = int(len(matched))
    matched_signal_count = int(matched["signal_id"].nunique()) if not matched.empty else 0
    unmatched_signal_count = max(0, signal_count - matched_signal_count)
    unmatched_fill_count = int(len(unmatched))
    entry_match_rate = (matched_count / fill_count * 100.0) if fill_count else 0.0
    signal_exec_rate = (matched_signal_count / signal_count * 100.0) if signal_count else 0.0

    rr = pd.to_numeric(matched.get("realized_r"), errors="coerce").dropna() if not matched.empty else pd.Series(dtype=float)
    win_rate = float((rr > 0).mean() * 100.0) if not rr.empty else 0.0

    snapshots_in_window = int(snapshot_meta.get("snapshot_files_in_window", 0))
    if snapshots_in_window == 0:
        status = "no_snapshots"
        message = "No snapshot files found in lookback window"
    elif signal_count == 0:
        status = "no_signals"
        message = "Snapshot files found, but all have zero executable signals"
    elif fill_count == 0:
        status = "no_fills"
        message = "No entry fills found in lookback window"
    elif matched_count == 0:
        status = "no_match"
        message = "No fills could be matched to recent signals"
    else:
        status = "ok"
        message = "Live reconciliation completed"

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "status": status,
        "message": message,
        "lookback_days": int(lookback_days),
        "fills_csv_path": fills_path,
        "snapshot_dir": settings.reconciliation.signal_snapshot_dir,
        "counts": {
            "snapshot_files_total": int(snapshot_meta.get("snapshot_files_total", 0)),
            "snapshot_files_in_window": snapshots_in_window,
            "snapshot_files_with_signals": int(snapshot_meta.get("snapshot_files_with_signals", 0)),
            "signals_total": signal_count,
            "fill_entries_total": fill_count,
            "matched_entries": matched_count,
            "matched_signals": matched_signal_count,
            "unmatched_signals": unmatched_signal_count,
            "unmatched_fill_entries": unmatched_fill_count,
        },
        "coverage": {
            "entry_match_rate_pct": round(float(entry_match_rate), 2),
            "signal_execution_rate_pct": round(float(signal_exec_rate), 2),
            "avg_signal_lag_days": round(_safe_mean(matched.get("lag_days", pd.Series(dtype=float))), 4),
            "median_signal_lag_days": round(_safe_median(matched.get("lag_days", pd.Series(dtype=float))), 4),
        },
        "cost_kpi": {
            "avg_entry_slippage_pct": round(_safe_mean(matched.get("entry_slippage_pct", pd.Series(dtype=float))), 4),
            "avg_abs_entry_slippage_pct": round(
                _safe_mean(pd.to_numeric(matched.get("entry_slippage_pct", pd.Series(dtype=float)), errors="coerce").abs()),
                4,
            ),
            "avg_est_roundtrip_cost_pct": round(_safe_mean(matched.get("est_roundtrip_cost_pct", pd.Series(dtype=float))), 4),
            "avg_realized_entry_cost_pct": round(_safe_mean(matched.get("realized_entry_cost_pct", pd.Series(dtype=float))), 4),
            "avg_cost_diff_pct": round(_safe_mean(matched.get("cost_diff_pct", pd.Series(dtype=float))), 4),
            "total_fee_idr": round(_safe_sum(matched.get("fee_idr", pd.Series(dtype=float))), 2),
        },
        "realized_kpi": {
            "samples": int(len(rr)),
            "win_rate_pct": round(float(win_rate), 2),
            "expectancy_r": round(_safe_mean(rr), 4) if not rr.empty else 0.0,
            "profit_factor_r": round(_profit_factor(rr), 4) if not rr.empty else 0.0,
            "total_pnl_idr": round(_safe_sum(matched.get("pnl_idr", pd.Series(dtype=float))), 2),
        },
        "by_mode": _mode_kpi(matched),
    }


def _summary_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("counts", {})
    coverage = payload.get("coverage", {})
    cost = payload.get("cost_kpi", {})
    realized = payload.get("realized_kpi", {})
    lines = [
        "# Live Reconciliation KPI",
        "",
        f"- generated_at: {payload.get('generated_at', '')}",
        f"- status: {payload.get('status', '')}",
        f"- message: {payload.get('message', '')}",
        f"- lookback_days: {payload.get('lookback_days', 0)}",
        f"- fills_csv_path: {payload.get('fills_csv_path', '')}",
        "",
        "## Coverage",
        f"- signals_total: {counts.get('signals_total', 0)}",
        f"- fill_entries_total: {counts.get('fill_entries_total', 0)}",
        f"- matched_entries: {counts.get('matched_entries', 0)}",
        f"- unmatched_fill_entries: {counts.get('unmatched_fill_entries', 0)}",
        f"- entry_match_rate_pct: {coverage.get('entry_match_rate_pct', 0)}",
        f"- signal_execution_rate_pct: {coverage.get('signal_execution_rate_pct', 0)}",
        "",
        "## Cost KPI",
        f"- avg_entry_slippage_pct: {cost.get('avg_entry_slippage_pct', 0)}",
        f"- avg_abs_entry_slippage_pct: {cost.get('avg_abs_entry_slippage_pct', 0)}",
        f"- avg_est_roundtrip_cost_pct: {cost.get('avg_est_roundtrip_cost_pct', 0)}",
        f"- avg_realized_entry_cost_pct: {cost.get('avg_realized_entry_cost_pct', 0)}",
        f"- avg_cost_diff_pct: {cost.get('avg_cost_diff_pct', 0)}",
        f"- total_fee_idr: {cost.get('total_fee_idr', 0)}",
        "",
        "## Realized KPI",
        f"- samples: {realized.get('samples', 0)}",
        f"- win_rate_pct: {realized.get('win_rate_pct', 0)}",
        f"- expectancy_r: {realized.get('expectancy_r', 0)}",
        f"- profit_factor_r: {realized.get('profit_factor_r', 0)}",
        f"- total_pnl_idr: {realized.get('total_pnl_idr', 0)}",
    ]
    return "\n".join(lines) + "\n"


def reconcile_live_signals(
    settings: Settings,
    fills_path: str | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    cfg = settings.reconciliation
    active_lookback = int(lookback_days) if lookback_days is not None else int(cfg.lookback_days)
    active_fills_path = fills_path or cfg.fills_csv_path

    signals, snapshot_meta = _load_signal_snapshots(cfg.signal_snapshot_dir, active_lookback)
    schema_error = ""
    try:
        fills = _load_fills(active_fills_path, active_lookback)
    except Exception as exc:
        schema_error = str(exc)
        fills = pd.DataFrame()

    if schema_error:
        summary = {
            "generated_at": datetime.utcnow().isoformat(),
            "status": "error_schema",
            "message": schema_error,
            "lookback_days": int(active_lookback),
            "fills_csv_path": active_fills_path,
            "snapshot_dir": settings.reconciliation.signal_snapshot_dir,
            "counts": {
                "snapshot_files_total": int(snapshot_meta.get("snapshot_files_total", 0)),
                "snapshot_files_in_window": int(snapshot_meta.get("snapshot_files_in_window", 0)),
                "snapshot_files_with_signals": int(snapshot_meta.get("snapshot_files_with_signals", 0)),
                "signals_total": int(len(signals)),
                "fill_entries_total": 0,
                "matched_entries": 0,
                "matched_signals": 0,
                "unmatched_signals": int(len(signals)),
                "unmatched_fill_entries": 0,
            },
            "coverage": {
                "entry_match_rate_pct": 0.0,
                "signal_execution_rate_pct": 0.0,
                "avg_signal_lag_days": 0.0,
                "median_signal_lag_days": 0.0,
            },
            "cost_kpi": {
                "avg_entry_slippage_pct": 0.0,
                "avg_abs_entry_slippage_pct": 0.0,
                "avg_est_roundtrip_cost_pct": 0.0,
                "avg_realized_entry_cost_pct": 0.0,
                "avg_cost_diff_pct": 0.0,
                "total_fee_idr": 0.0,
            },
            "realized_kpi": {
                "samples": 0,
                "win_rate_pct": 0.0,
                "expectancy_r": 0.0,
                "profit_factor_r": 0.0,
                "total_pnl_idr": 0.0,
            },
            "by_mode": [],
            "required_schema": REQUIRED_FILLS_SCHEMA,
        }
        details_csv_path = Path(cfg.details_csv_path)
        details_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(details_csv_path, index=False)
        unmatched_csv_path = Path(cfg.unmatched_entries_csv_path)
        unmatched_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(unmatched_csv_path, index=False)
        out_json_path = _write_json(cfg.output_json_path, summary)
        out_md = Path(cfg.output_markdown_path)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_md, _summary_markdown(summary), encoding="utf-8")
        return {
            "status": summary.get("status", "error"),
            "message": summary.get("message", ""),
            "json_path": out_json_path,
            "markdown_path": str(out_md),
            "details_csv_path": str(details_csv_path),
            "unmatched_csv_path": str(unmatched_csv_path),
            "summary": summary,
        }

    entries = _aggregate_entry_fills(fills)
    matched, unmatched = _match_entries_to_signals(entries, signals, int(cfg.max_signal_lag_days))
    summary = _summary_payload(
        settings=settings,
        lookback_days=active_lookback,
        fills_path=active_fills_path,
        snapshot_meta=snapshot_meta,
        signals=signals,
        entry_fills=entries,
        matched=matched,
        unmatched=unmatched,
    )

    details_csv_path = Path(cfg.details_csv_path)
    details_csv_path.parent.mkdir(parents=True, exist_ok=True)
    matched.to_csv(details_csv_path, index=False)

    unmatched_csv_path = Path(cfg.unmatched_entries_csv_path)
    unmatched_csv_path.parent.mkdir(parents=True, exist_ok=True)
    unmatched.to_csv(unmatched_csv_path, index=False)

    out_json_path = _write_json(cfg.output_json_path, summary)
    out_md = Path(cfg.output_markdown_path)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_md, _summary_markdown(summary), encoding="utf-8")

    return {
        "status": summary.get("status", "error"),
        "message": summary.get("message", ""),
        "json_path": out_json_path,
        "markdown_path": str(out_md),
        "details_csv_path": str(details_csv_path),
        "unmatched_csv_path": str(unmatched_csv_path),
        "summary": summary,
    }
