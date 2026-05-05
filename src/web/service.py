from __future__ import annotations

import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import pandas as pd


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_compatible(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (int, str, bool)):
        return value
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return _json_compatible(value.item())
        except Exception:
            return str(value)
    return str(value)


def _sanitize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in records:
        clean = {str(k): _json_compatible(v) for k, v in row.items()}
        out.append(clean)
    return out


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv_df(path: Path, expected_cols: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=expected_cols or [])
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=expected_cols or [])
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None
    return df


def _records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    selected = df.head(limit).copy() if limit and limit > 0 else df.copy()
    return _sanitize_records(selected.to_dict(orient="records"))


def _mode_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in items:
        mode = str(row.get("mode", "")).strip().lower()
        if not mode:
            mode = "unknown"
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def query_signals(
    reports_dir: str | Path = "reports",
    mode: str | None = None,
    min_score: float | None = None,
    ticker_query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    base = Path(reports_dir)
    payload_daily = _read_json(base / "daily_signal.json", default={"generated_at": "", "signals": []})
    payload_intraday = _read_json(base / "intraday_signal.json", default={"generated_at": "", "signals": []})
    signals: list[dict[str, Any]] = []
    for source_name, payload in [("daily", payload_daily), ("intraday", payload_intraday)]:
        source_rows = payload.get("signals", []) if isinstance(payload, dict) else []
        if not isinstance(source_rows, list):
            continue
        for row in source_rows:
            if isinstance(row, dict):
                merged = dict(row)
                merged.setdefault("mode", source_name)
                merged["_signal_source"] = source_name
                signals.append(merged)

    selected: list[dict[str, Any]] = []
    mode_norm = (mode or "").strip().lower()
    ticker_norm = (ticker_query or "").strip().upper()
    min_score_value = _safe_float(min_score, default=float("-inf")) if min_score is not None else float("-inf")

    for raw in signals:
        row = dict(raw) if isinstance(raw, dict) else {}
        row_mode = str(row.get("mode", "")).strip().lower()
        row_ticker = str(row.get("ticker", "")).strip().upper()
        row_score = _safe_float(row.get("score"), default=float("-inf"))

        if mode_norm and mode_norm != "all" and row_mode != mode_norm:
            continue
        if ticker_norm and ticker_norm not in row_ticker:
            continue
        if row_score < min_score_value:
            continue
        selected.append(row)

    selected.sort(key=lambda x: _safe_float(x.get("score"), default=-1e18), reverse=True)
    bounded = selected[: max(1, limit)]
    return {
        "generated_at": payload_intraday.get("generated_at") or payload_daily.get("generated_at", ""),
        "total": len(selected),
        "count": len(bounded),
        "by_mode": _mode_counts(selected),
        "sources": {
            "daily_generated_at": payload_daily.get("generated_at", ""),
            "intraday_generated_at": payload_intraday.get("generated_at", ""),
            "daily_count": len(payload_daily.get("signals", [])) if isinstance(payload_daily.get("signals", []), list) else 0,
            "intraday_count": len(payload_intraday.get("signals", [])) if isinstance(payload_intraday.get("signals", []), list) else 0,
        },
        "items": _sanitize_records(bounded),
    }


def _latest_signal_map(reports_dir: Path) -> dict[str, dict[str, Any]]:
    signal_map: dict[str, dict[str, Any]] = {}
    payload_daily = _read_json(reports_dir / "daily_signal.json", default={"signals": []})
    payload_intraday = _read_json(reports_dir / "intraday_signal.json", default={"signals": []})
    for source_name, payload in [("daily", payload_daily), ("intraday", payload_intraday)]:
        rows = payload.get("signals", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            ticker = str(raw.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            score = _safe_float(raw.get("score"), default=float("-inf"))
            prev = signal_map.get(ticker)
            prev_score = _safe_float((prev or {}).get("score"), default=float("-inf"))
            if prev is None or score >= prev_score:
                row = dict(raw)
                row.setdefault("mode", source_name)
                signal_map[ticker] = row
    return signal_map


def query_close_analysis(
    reports_dir: str | Path = "reports",
    ticker_query: str | None = None,
    min_close: float | None = None,
    min_avg_volume: float | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    base = Path(reports_dir).resolve()
    prices_path = _resolve_data_path(base, "data/raw/prices_daily.csv")
    prices = _read_csv_df(
        prices_path,
        expected_cols=["date", "ticker", "open", "high", "low", "close", "volume"],
    )
    if prices.empty:
        return {
            "generated_at": _utc_now_iso(),
            "as_of_date": "",
            "total": 0,
            "count": 0,
            "filters": {
                "ticker_query": ticker_query or "",
                "min_close": min_close,
                "min_avg_volume": min_avg_volume,
                "limit": int(limit),
            },
            "items": [],
        }

    prices["ticker"] = prices.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().str.strip()
    prices["date"] = pd.to_datetime(prices.get("date"), errors="coerce")
    prices["close"] = pd.to_numeric(prices.get("close"), errors="coerce")
    prices["volume"] = pd.to_numeric(prices.get("volume"), errors="coerce")
    prices = prices.dropna(subset=["date", "ticker", "close"]).copy()
    if prices.empty:
        return {
            "generated_at": _utc_now_iso(),
            "as_of_date": "",
            "total": 0,
            "count": 0,
            "filters": {
                "ticker_query": ticker_query or "",
                "min_close": min_close,
                "min_avg_volume": min_avg_volume,
                "limit": int(limit),
            },
            "items": [],
        }

    ticker_norm = str(ticker_query or "").strip().upper()
    min_close_value = _safe_float(min_close, default=float("-inf")) if min_close is not None else float("-inf")
    min_avg_volume_value = (
        _safe_float(min_avg_volume, default=float("-inf")) if min_avg_volume is not None else float("-inf")
    )
    signal_map = _latest_signal_map(base)
    rows: list[dict[str, Any]] = []

    for ticker, grp in prices.sort_values(["ticker", "date"]).groupby("ticker", dropna=False):
        if ticker_norm and ticker_norm not in str(ticker):
            continue
        work = grp.tail(120).copy().reset_index(drop=True)
        closes = pd.to_numeric(work.get("close"), errors="coerce")
        volumes = pd.to_numeric(work.get("volume"), errors="coerce")
        if closes.empty:
            continue
        last_close = _safe_float(closes.iloc[-1], 0.0)
        if last_close < min_close_value:
            continue

        prev_close = _safe_float(closes.iloc[-2], 0.0) if len(closes) >= 2 else 0.0
        close_5 = _safe_float(closes.iloc[-6], 0.0) if len(closes) >= 6 else 0.0
        close_20 = _safe_float(closes.iloc[-21], 0.0) if len(closes) >= 21 else 0.0
        ma20 = _safe_float(closes.tail(20).mean(), 0.0) if len(closes) >= 20 else _safe_float(closes.mean(), 0.0)
        ma50 = _safe_float(closes.tail(50).mean(), 0.0) if len(closes) >= 50 else _safe_float(closes.mean(), 0.0)
        avg_vol_20 = (
            _safe_float(volumes.tail(20).mean(), 0.0)
            if len(volumes.dropna()) >= 20
            else _safe_float(volumes.mean(), 0.0)
        )
        if avg_vol_20 < min_avg_volume_value:
            continue

        ret = closes.pct_change().dropna()
        vol20 = _safe_float(ret.tail(20).std() * 100.0, 0.0) if not ret.empty else 0.0
        chg_1d = ((last_close / prev_close - 1.0) * 100.0) if prev_close > 0 else 0.0
        chg_5d = ((last_close / close_5 - 1.0) * 100.0) if close_5 > 0 else 0.0
        chg_20d = ((last_close / close_20 - 1.0) * 100.0) if close_20 > 0 else 0.0
        dist_ma20 = ((last_close / ma20 - 1.0) * 100.0) if ma20 > 0 else 0.0
        dist_ma50 = ((last_close / ma50 - 1.0) * 100.0) if ma50 > 0 else 0.0

        trend_state = "sideways"
        if last_close >= ma20 and ma20 >= ma50:
            trend_state = "uptrend"
        elif last_close <= ma20 and ma20 <= ma50:
            trend_state = "downtrend"

        latest_signal = signal_map.get(str(ticker), {})
        rows.append(
            {
                "ticker": str(ticker),
                "as_of_date": pd.Timestamp(work["date"].iloc[-1]).date().isoformat(),
                "last_close": round(last_close, 4),
                "prev_close": round(prev_close, 4),
                "chg_1d_pct": round(chg_1d, 4),
                "chg_5d_pct": round(chg_5d, 4),
                "chg_20d_pct": round(chg_20d, 4),
                "ma20": round(ma20, 4),
                "ma50": round(ma50, 4),
                "dist_ma20_pct": round(dist_ma20, 4),
                "dist_ma50_pct": round(dist_ma50, 4),
                "avg_volume_20d": round(avg_vol_20, 2),
                "volatility_20d_pct": round(vol20, 4),
                "trend_state": trend_state,
                "signal_mode": str(latest_signal.get("mode", "")).strip().lower(),
                "signal_score": round(_safe_float(latest_signal.get("score"), 0.0), 4),
            }
        )

    rows.sort(
        key=lambda r: (
            _safe_float(r.get("signal_score"), 0.0),
            _safe_float(r.get("chg_20d_pct"), 0.0),
            _safe_float(r.get("chg_5d_pct"), 0.0),
            _safe_float(r.get("chg_1d_pct"), 0.0),
        ),
        reverse=True,
    )
    effective_limit = int(limit) if str(limit).strip() else 0
    if effective_limit > 0:
        bounded = rows[:effective_limit]
    else:
        bounded = rows
    as_of = ""
    try:
        as_of = pd.to_datetime(prices["date"], errors="coerce").max().date().isoformat()
    except Exception:
        as_of = ""
    return {
        "generated_at": _utc_now_iso(),
        "as_of_date": as_of,
        "total": len(rows),
        "count": len(bounded),
        "filters": {
            "ticker_query": ticker_norm,
            "min_close": None if min_close is None else float(min_close_value),
            "min_avg_volume": None if min_avg_volume is None else float(min_avg_volume_value),
            "limit": effective_limit,
        },
        "items": _sanitize_records(bounded),
    }


def query_close_prices(
    reports_dir: str | Path = "reports",
    ticker_query: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    base = Path(reports_dir).resolve()
    prices_path = _resolve_data_path(base, "data/raw/prices_daily.csv")
    prices = _read_csv_df(
        prices_path,
        expected_cols=["date", "ticker", "open", "high", "low", "close", "volume"],
    )
    if prices.empty:
        return {
            "generated_at": _utc_now_iso(),
            "total": 0,
            "count": 0,
            "as_of_date": "",
            "min_date": "",
            "max_date": "",
            "filters": {
                "ticker_query": ticker_query or "",
                "start_date": start_date or "",
                "end_date": end_date or "",
                "limit": int(limit),
            },
            "items": [],
        }

    prices["ticker"] = prices.get("ticker", pd.Series(dtype=str)).astype(str).str.upper().str.strip()
    prices["date"] = pd.to_datetime(prices.get("date"), errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        prices[col] = pd.to_numeric(prices.get(col), errors="coerce")
    prices = prices.dropna(subset=["date", "ticker", "close"]).copy()

    ticker_norm = str(ticker_query or "").strip().upper()
    if ticker_norm:
        prices = prices[prices["ticker"].str.contains(ticker_norm, na=False)].copy()

    start_ts = pd.to_datetime(start_date, errors="coerce") if start_date else pd.NaT
    end_ts = pd.to_datetime(end_date, errors="coerce") if end_date else pd.NaT
    if not pd.isna(start_ts):
        prices = prices[prices["date"] >= pd.Timestamp(start_ts).normalize()].copy()
    if not pd.isna(end_ts):
        prices = prices[prices["date"] <= pd.Timestamp(end_ts).normalize()].copy()

    total = int(len(prices))
    if prices.empty:
        return {
            "generated_at": _utc_now_iso(),
            "total": 0,
            "count": 0,
            "as_of_date": "",
            "min_date": "",
            "max_date": "",
            "filters": {
                "ticker_query": ticker_norm,
                "start_date": start_date or "",
                "end_date": end_date or "",
                "limit": int(limit),
            },
            "items": [],
        }

    min_dt = pd.to_datetime(prices["date"], errors="coerce").min()
    max_dt = pd.to_datetime(prices["date"], errors="coerce").max()
    effective_limit = int(limit) if str(limit).strip() else 0
    prices = prices.sort_values(["date", "ticker"], ascending=[False, True]).copy()
    if effective_limit > 0:
        prices = prices.head(effective_limit).copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.date.astype(str)
    for col in ["open", "high", "low", "close"]:
        prices[col] = pd.to_numeric(prices[col], errors="coerce").round(4)
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce").round(0)

    return {
        "generated_at": _utc_now_iso(),
        "total": total,
        "count": int(len(prices)),
        "as_of_date": (max_dt.date().isoformat() if not pd.isna(max_dt) else ""),
        "min_date": (min_dt.date().isoformat() if not pd.isna(min_dt) else ""),
        "max_date": (max_dt.date().isoformat() if not pd.isna(max_dt) else ""),
        "filters": {
            "ticker_query": ticker_norm,
            "start_date": start_date or "",
            "end_date": end_date or "",
            "limit": effective_limit,
        },
        "items": _sanitize_records(prices.to_dict(orient="records")),
    }


def _resolve_data_path(reports_dir: Path, rel_path: str) -> Path:
    for root in [Path.cwd(), reports_dir.parent, reports_dir]:
        candidate = (root / rel_path).resolve()
        if candidate.exists():
            return candidate
    return (Path.cwd() / rel_path).resolve()


def _split_reason(reason_text: str) -> list[str]:
    clean = str(reason_text or "").replace("|", "+").replace(";", "+")
    out: list[str] = []
    for part in clean.split("+"):
        token = part.strip(" ,.-")
        if token:
            out.append(token)
    return out


def _reason_weight(token: str) -> int:
    t = token.lower()
    if "trend" in t or "ma" in t:
        return 35
    if "momentum" in t:
        return 28
    if "atr" in t or "volatil" in t:
        return 20
    if "volume" in t or "liquid" in t:
        return 17
    if "breakout" in t:
        return 22
    return 12


def _chart_points(df: pd.DataFrame, time_col: str) -> list[dict[str, Any]]:
    if df.empty:
        return []
    cols = ["open", "high", "low", "close", "volume"]
    work = df.copy()
    for c in cols:
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")
    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        ts = row.get(time_col)
        try:
            ts_iso = pd.Timestamp(ts).isoformat() if pd.notna(ts) else ""
        except Exception:
            ts_iso = str(ts or "")
        rows.append(
            {
                "ts": ts_iso,
                "open": _safe_float(row.get("open"), default=0.0),
                "high": _safe_float(row.get("high"), default=0.0),
                "low": _safe_float(row.get("low"), default=0.0),
                "close": _safe_float(row.get("close"), default=0.0),
                "volume": _safe_float(row.get("volume"), default=0.0),
            }
        )
    return rows


def query_ticker_detail(
    ticker: str,
    reports_dir: str | Path = "reports",
    bars: int = 180,
) -> dict[str, Any]:
    ticker_norm = str(ticker or "").strip().upper()
    if not ticker_norm:
        return {"error": "ticker is required", "ticker": ""}

    reports = Path(reports_dir).resolve()
    signal_payload = query_signals(reports_dir=reports, mode="all", ticker_query=ticker_norm, limit=200)
    signal_items = signal_payload.get("items", []) if isinstance(signal_payload, dict) else []
    latest_signal = signal_items[0] if signal_items else {}

    bars_limit = min(1000, max(20, int(bars or 180)))
    intraday_path = _resolve_data_path(reports, "data/raw/prices_intraday.csv")
    intraday_df = _read_csv_df(intraday_path, expected_cols=["timestamp", "ticker", "open", "high", "low", "close", "volume", "timeframe"])
    if "timestamp" not in intraday_df.columns and "date" in intraday_df.columns:
        intraday_df = intraday_df.rename(columns={"date": "timestamp"})
    if "timeframe" not in intraday_df.columns:
        intraday_df["timeframe"] = "5m"
    intraday_df["ticker"] = intraday_df.get("ticker", pd.Series(dtype=str)).astype(str).str.upper()
    intraday_df["timestamp"] = pd.to_datetime(intraday_df.get("timestamp"), errors="coerce")
    intraday_df = intraday_df[(intraday_df["ticker"] == ticker_norm) & (intraday_df["timestamp"].notna())].copy()
    intraday_df = intraday_df.sort_values("timestamp").tail(bars_limit)

    series_type = "intraday"
    timeframe = str(intraday_df["timeframe"].iloc[-1]) if not intraday_df.empty else "5m"
    time_col = "timestamp"
    used_df = intraday_df
    used_source = str(intraday_path).replace("\\", "/")

    if used_df.empty:
        daily_path = _resolve_data_path(reports, "data/raw/prices_daily.csv")
        daily_df = _read_csv_df(daily_path, expected_cols=["date", "ticker", "open", "high", "low", "close", "volume"])
        daily_df["ticker"] = daily_df.get("ticker", pd.Series(dtype=str)).astype(str).str.upper()
        daily_df["date"] = pd.to_datetime(daily_df.get("date"), errors="coerce")
        daily_df = daily_df[(daily_df["ticker"] == ticker_norm) & (daily_df["date"].notna())].copy()
        daily_df = daily_df.sort_values("date").tail(bars_limit)
        used_df = daily_df
        series_type = "daily"
        timeframe = "1d"
        time_col = "date"
        used_source = str(daily_path).replace("\\", "/")

    points = _chart_points(used_df, time_col=time_col)
    closes = [float(p["close"]) for p in points if math.isfinite(float(p.get("close", 0.0)))]
    highs = [float(p["high"]) for p in points if math.isfinite(float(p.get("high", 0.0)))]
    lows = [float(p["low"]) for p in points if math.isfinite(float(p.get("low", 0.0)))]
    volumes = [float(p["volume"]) for p in points if math.isfinite(float(p.get("volume", 0.0)))]
    first_close = closes[0] if closes else 0.0
    last_close = closes[-1] if closes else 0.0
    change_pct = ((last_close / first_close - 1.0) * 100.0) if first_close > 0 else 0.0

    reason_tokens = _split_reason(str(latest_signal.get("reason", "")))
    reason_breakdown = [
        {"factor": token, "weight": _reason_weight(token)}
        for token in reason_tokens
    ]

    return {
        "generated_at": _utc_now_iso(),
        "ticker": ticker_norm,
        "series_type": series_type,
        "timeframe": timeframe,
        "bar_count": int(len(points)),
        "latest_signal": latest_signal if isinstance(latest_signal, dict) else {},
        "levels": {
            "entry": _safe_float(latest_signal.get("entry"), default=0.0),
            "stop": _safe_float(latest_signal.get("stop"), default=0.0),
            "tp1": _safe_float(latest_signal.get("tp1"), default=0.0),
            "tp2": _safe_float(latest_signal.get("tp2"), default=0.0),
        },
        "stats": {
            "last_close": last_close,
            "change_pct": change_pct,
            "min_low": min(lows) if lows else 0.0,
            "max_high": max(highs) if highs else 0.0,
            "avg_volume": (sum(volumes) / len(volumes)) if volumes else 0.0,
        },
        "reason_breakdown": reason_breakdown,
        "chart": {
            "points": points,
            "price_min": min(lows) if lows else 0.0,
            "price_max": max(highs) if highs else 0.0,
            "has_data": bool(points),
        },
    }


def _extract_backtest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    gate_pass = payload.get("gate_pass", {}) if isinstance(payload, dict) else {}
    regime = payload.get("regime", {}) if isinstance(payload, dict) else {}
    kill_switch = payload.get("kill_switch", {}) if isinstance(payload, dict) else {}
    gate_components = payload.get("gate_components", {}) if isinstance(payload, dict) else {}
    model_v2_promotion = payload.get("model_v2_promotion", {}) if isinstance(payload, dict) else {}
    mode_activation = payload.get("mode_activation", {}) if isinstance(payload, dict) else {}
    return {
        "gate_pass": gate_pass if isinstance(gate_pass, dict) else {},
        "gate_components": gate_components if isinstance(gate_components, dict) else {},
        "regime": regime if isinstance(regime, dict) else {},
        "kill_switch": kill_switch if isinstance(kill_switch, dict) else {},
        "model_v2_promotion": model_v2_promotion if isinstance(model_v2_promotion, dict) else {},
        "mode_activation": mode_activation if isinstance(mode_activation, dict) else {},
        "metrics": metrics if isinstance(metrics, dict) else {},
    }


def _extract_closed_loop_retrain(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {
            "status": "not_run",
            "message": "Closed-loop retrain has not been evaluated yet",
            "triggered": False,
            "reasons": [],
            "last_evaluated_at": "",
            "last_triggered_at": "",
            "fills_in_window": 0,
            "new_fills_since_last_trigger": 0,
            "live_samples": 0,
            "live_profit_factor_r": 0.0,
            "live_expectancy_r": 0.0,
            "train_status": "",
        }

    status = str(payload.get("last_status", "")).strip().lower() or "not_run"
    message = str(payload.get("last_message", "")).strip()
    last_evaluated_at = str(payload.get("last_evaluated_at", "")).strip()
    last_triggered_at = str(payload.get("last_triggered_at", "")).strip()
    fills_in_window = max(0, _safe_int(payload.get("last_seen_fill_entries_total", 0), 0))
    trigger_fill_total = max(0, _safe_int(payload.get("last_trigger_fill_entries_total", 0), 0))
    new_fills_since_last_trigger = max(0, fills_in_window - trigger_fill_total)
    live_samples = max(0, _safe_int(payload.get("last_live_samples", 0), 0))
    live_profit_factor_r = _safe_float(payload.get("last_live_profit_factor_r", 0.0), default=0.0)
    live_expectancy_r = _safe_float(payload.get("last_live_expectancy_r", 0.0), default=0.0)
    train_status = str(payload.get("last_trigger_train_status", "")).strip()
    triggered = status in {"triggered", "triggered_no_update"}

    raw_reasons = payload.get("last_trigger_reasons", [])
    reasons: list[str] = []
    if triggered and isinstance(raw_reasons, list):
        reasons = [str(item).strip() for item in raw_reasons if str(item).strip()]

    return {
        "status": status,
        "message": message,
        "triggered": triggered,
        "reasons": reasons,
        "last_evaluated_at": last_evaluated_at,
        "last_triggered_at": last_triggered_at,
        "fills_in_window": fills_in_window,
        "new_fills_since_last_trigger": new_fills_since_last_trigger,
        "live_samples": live_samples,
        "live_profit_factor_r": live_profit_factor_r,
        "live_expectancy_r": live_expectancy_r,
        "train_status": train_status,
    }


def _load_recent_runs(reports_dir: Path, limit: int = 8) -> list[dict[str, Any]]:
    def _issue_category(level: str, message: str, detail: str) -> dict[str, str]:
        level_key = str(level).strip().upper()
        message_key = str(message).strip().lower()
        detail_text = str(detail).strip().lower()

        if level_key == "ERROR":
            if "stale" in detail_text:
                return {
                    "category": "critical_failure",
                    "label": "Critical failure",
                    "tone": "critical",
                    "summary": "Run failed because the input data was stale.",
                }
            return {
                "category": "critical_failure",
                "label": "Critical failure",
                "tone": "critical",
                "summary": "Run failed before producing a trustworthy output.",
            }

        if message_key == "live_gate_blocked":
            return {
                "category": "protective_warning",
                "label": "Protective warning",
                "tone": "protective",
                "summary": "Run completed. Trading was intentionally blocked by risk controls.",
            }

        return {
            "category": "operational_warning",
            "label": "Operational warning",
            "tone": "operational",
            "summary": "Run completed with a non-fatal issue that still needs review.",
        }

    def _issue_detail(message: str, extra: dict[str, Any]) -> str:
        if not isinstance(extra, dict):
            extra = {}

        raw_error = str(extra.get("error", "")).strip()
        if raw_error:
            return raw_error

        if message == "live_gate_blocked":
            parts: list[str] = []
            gate_pass = extra.get("gate_pass", {})
            if isinstance(gate_pass, dict):
                allowed = [str(mode) for mode, ok in gate_pass.items() if bool(ok)]
                blocked = [str(mode) for mode, ok in gate_pass.items() if not bool(ok)]
                if not allowed:
                    parts.append("No mode passed the live gate")
                elif blocked:
                    parts.append("Blocked modes: " + ", ".join(blocked))

            regime = extra.get("regime", {})
            if isinstance(regime, dict):
                regime_status = str(regime.get("status", "")).strip()
                regime_reason = str(regime.get("reason", "")).strip()
                if regime_status:
                    parts.append(f"Regime={regime_status}")
                if regime_reason:
                    parts.append(regime_reason)

            kill_switch = extra.get("kill_switch", {})
            if isinstance(kill_switch, dict):
                kill_status = str(kill_switch.get("status", "")).strip()
                if kill_status and kill_status.lower() not in {"clear", "inactive"}:
                    parts.append(f"Kill switch={kill_status}")

            return " | ".join(parts[:4]) or "Live gate blocked"

        compact_parts: list[str] = []
        for key, value in extra.items():
            if isinstance(value, (str, int, float, bool)) and str(value).strip():
                compact_parts.append(f"{key}={value}")
            if len(compact_parts) >= 4:
                break
        return " | ".join(compact_parts)

    def _issue_payload(level: str, message: str, extra: dict[str, Any]) -> dict[str, Any]:
        detail = _issue_detail(message=message, extra=extra if isinstance(extra, dict) else {})
        category = _issue_category(level=level, message=message, detail=detail)
        return {
            "level": str(level).upper(),
            "message": str(message).strip(),
            "detail": detail,
            "category": category["category"],
            "category_label": category["label"],
            "category_tone": category["tone"],
            "summary": category["summary"],
        }

    files = sorted(reports_dir.glob("run_log_*.json"), key=lambda p: p.name, reverse=True)
    by_run: dict[str, dict[str, Any]] = {}
    for path in files:
        payload = _read_json(path, default=[])
        if not isinstance(payload, list):
            continue
        for event in payload:
            if not isinstance(event, dict):
                continue
            run_id = str(event.get("run_id", "")).strip()
            if not run_id:
                continue
            run = by_run.setdefault(
                run_id,
                {
                    "file": path.name,
                    "run_id": run_id,
                    "started_at": "",
                    "ended_at": "",
                    "source": "",
                    "signals": 0,
                    "error_count": 0,
                    "warning_count": 0,
                    "events": 0,
                    "issues": [],
                },
            )
            ts = str(event.get("ts", "")).strip()
            if ts and (not run["started_at"] or ts < run["started_at"]):
                run["started_at"] = ts
            if ts and (not run["ended_at"] or ts > run["ended_at"]):
                run["ended_at"] = ts
            run["events"] += 1

            level = str(event.get("level", "")).upper()
            message = str(event.get("message", "")).strip()
            extra = event.get("extra", {})
            if message == "ingest_done" and isinstance(extra, dict):
                run["source"] = str(extra.get("source", run["source"])).strip()
            if isinstance(extra, dict) and message in {"live_gate_modes_allowed", "signal_snapshot_written"}:
                run["signals"] = max(run["signals"], _safe_int(extra.get("signal_count"), default=run["signals"]))

            if level == "ERROR":
                run["error_count"] += 1
                run["issues"].append(_issue_payload(level=level, message=message, extra=extra if isinstance(extra, dict) else {}))
            elif level == "WARN":
                run["warning_count"] += 1
                run["issues"].append(_issue_payload(level=level, message=message, extra=extra if isinstance(extra, dict) else {}))

    runs = list(by_run.values())
    for run in runs:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in run.get("issues", []):
            key = (
                str(issue.get("level", "")).strip(),
                str(issue.get("message", "")).strip(),
                str(issue.get("detail", "")).strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)
        run["issues"] = deduped
        if run["error_count"] > 0:
            run["status"] = "failed"
            run["status_category"] = "critical_failure"
            run["status_category_label"] = "Critical failure"
            run["status_tone"] = "critical"
            run["status_note"] = "Run failed before producing a valid output. Review the error details before trusting this run."
        elif run["warning_count"] > 0:
            run["status"] = "warning"
            issue_categories = {str(issue.get("category", "")).strip() for issue in deduped}
            if issue_categories and issue_categories.issubset({"protective_warning"}):
                run["status_category"] = "protective_warning"
                run["status_category_label"] = "Protective warning"
                run["status_tone"] = "protective"
                run["status_note"] = "Run completed normally. Trading was intentionally held back by the system's risk controls."
            else:
                run["status_category"] = "operational_warning"
                run["status_category_label"] = "Operational warning"
                run["status_tone"] = "operational"
                run["status_note"] = "Run completed, but there were non-fatal issues that still need operator review."
        else:
            run["status"] = "clean"
            run["status_category"] = "clean_run"
            run["status_category_label"] = "Clean run"
            run["status_tone"] = "clean"
            run["status_note"] = "Run completed without warnings or errors."

    runs.sort(key=lambda row: (str(row.get("started_at", "")), str(row.get("run_id", ""))), reverse=True)
    return runs[: max(1, limit)]


def _load_daily_summary(reports_dir: Path) -> dict[str, Any]:
    payload = _read_json(reports_dir / "n8n_last_summary.json", default={})
    return payload if isinstance(payload, dict) else {}


def _extract_quality(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {
            "status": "not_run",
            "pass": False,
            "reason_codes": [],
            "checks": {},
            "stats": {},
            "message": "Data quality report not available",
        }
    return {
        "status": str(payload.get("status", "")).strip() or "unknown",
        "pass": bool(payload.get("pass", False)),
        "reason_codes": payload.get("reason_codes", []) if isinstance(payload.get("reason_codes", []), list) else [],
        "checks": payload.get("checks", {}) if isinstance(payload.get("checks", {}), dict) else {},
        "stats": payload.get("stats", {}) if isinstance(payload.get("stats", {}), dict) else {},
        "message": str(payload.get("message", "")).strip(),
    }


def _extract_risk_budget(summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        summary = {}
    return {
        "status": str(summary.get("risk_budget_status", "")).strip() or "unknown",
        "risk_budget_pct": _safe_float(summary.get("risk_budget_pct"), 0.0),
        "effective_risk_per_trade_pct": _safe_float(summary.get("effective_risk_per_trade_pct"), 0.0),
        "hard_daily_stop_r": _safe_float(summary.get("hard_daily_stop_r"), 0.0),
        "hard_weekly_stop_r": _safe_float(summary.get("hard_weekly_stop_r"), 0.0),
    }


def _extract_paper_live_mode(summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        summary = {}
    return {
        "mode": str(summary.get("paper_live_mode", "")).strip() or "unknown",
        "rollout_phase": str(summary.get("rollout_phase", "")).strip(),
        "decision_version": str(summary.get("decision_version", "")).strip(),
    }


def _extract_mode_activation(summary: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    source = {}
    if isinstance(summary.get("mode_activation"), dict):
        source = summary.get("mode_activation", {})
    elif isinstance(backtest.get("mode_activation"), dict):
        source = backtest.get("mode_activation", {})
    active_modes = source.get("active_modes", []) if isinstance(source, dict) else []
    inactive_modes = source.get("inactive_modes", []) if isinstance(source, dict) else []
    return {
        "active_modes": [str(mode).strip().lower() for mode in active_modes if str(mode).strip()],
        "inactive_modes": [str(mode).strip().lower() for mode in inactive_modes if str(mode).strip()],
        "swing_only": bool(source.get("swing_only", False)) if isinstance(source, dict) else False,
    }


def _extract_operator_alerts(summary: dict[str, Any]) -> list[dict[str, str]]:
    raw_alerts = summary.get("operator_alerts", []) if isinstance(summary, dict) else []
    if not isinstance(raw_alerts, list):
        return []
    alerts: list[dict[str, str]] = []
    for raw in raw_alerts:
        if not isinstance(raw, dict):
            continue
        alerts.append(
            {
                "severity": str(raw.get("severity", "info")).strip().lower() or "info",
                "code": str(raw.get("code", "")).strip(),
                "title": str(raw.get("title", "")).strip(),
                "message": str(raw.get("message", "")).strip(),
            }
        )
    return alerts


def _extract_paper_fills(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    return {
        "status": str(payload.get("status", "")).strip() or "unknown",
        "message": str(payload.get("message", "")).strip(),
        "generated_count": _safe_int(payload.get("generated_count"), 0),
        "pending_count": _safe_int(payload.get("pending_count"), 0),
        "snapshot_files_total": _safe_int(payload.get("snapshot_files_total"), 0),
        "snapshot_files_in_window": _safe_int(payload.get("snapshot_files_in_window"), 0),
        "signals_total": _safe_int(payload.get("signals_total"), 0),
        "valid_signals": _safe_int(payload.get("valid_signals"), 0),
        "trade_count_total": _safe_int(payload.get("trade_count_total"), 0),
        "win_rate_pct": _safe_float(payload.get("win_rate_pct"), 0.0),
        "expectancy_r": _safe_float(payload.get("expectancy_r"), 0.0),
        "profit_factor_r": _safe_float(payload.get("profit_factor_r"), 0.0),
        "recent_generated": payload.get("recent_generated", []) if isinstance(payload.get("recent_generated", []), list) else [],
    }


def _extract_swing_audit(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    overall = payload.get("overall", {}) if isinstance(payload.get("overall", {}), dict) else {}
    return {
        "status": str(payload.get("status", "")).strip() or "unknown",
        "message": str(payload.get("message", "")).strip(),
        "group_source": str(payload.get("group_source", "")).strip() or "unclassified",
        "overall": overall,
        "by_regime": payload.get("by_regime", []) if isinstance(payload.get("by_regime", []), list) else [],
        "by_group": payload.get("by_group", []) if isinstance(payload.get("by_group", []), list) else [],
        "by_volatility": payload.get("by_volatility", []) if isinstance(payload.get("by_volatility", []), list) else [],
        "weak_spots": payload.get("weak_spots", []) if isinstance(payload.get("weak_spots", []), list) else [],
        "recent_trades": payload.get("recent_trades", []) if isinstance(payload.get("recent_trades", []), list) else [],
    }


def _extract_score_funnel(funnel_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(funnel_payload, dict):
        return {}
    nested = funnel_payload.get("score_funnel")
    if isinstance(nested, dict):
        return nested
    return funnel_payload


def _append_unique_reason(reasons: list[str], text: str) -> None:
    clean = str(text or "").strip()
    if not clean:
        return
    key = clean.lower()
    if any(r.lower() == key for r in reasons):
        return
    reasons.append(clean)


def _derive_decision(snapshot: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    gate_pass = snapshot.get("backtest", {}).get("gate_pass", {})
    gate_components = snapshot.get("backtest", {}).get("gate_components", {})
    model_v2_promotion = snapshot.get("backtest", {}).get("model_v2_promotion", {})
    mode_activation = snapshot.get("backtest", {}).get("mode_activation", {})
    if not isinstance(mode_activation, dict):
        mode_activation = {}
    active_modes = mode_activation.get("active_modes", []) if isinstance(mode_activation, dict) else []
    active_modes = [str(mode).strip().lower() for mode in active_modes if str(mode).strip()]
    gate_t1 = bool(gate_pass.get("t1"))
    gate_swing = bool(gate_pass.get("swing"))
    allowed_modes = []
    if gate_t1 and (not active_modes or "t1" in active_modes):
        allowed_modes.append("t1")
    if gate_swing and (not active_modes or "swing" in active_modes):
        allowed_modes.append("swing")

    signal_total = _safe_int(snapshot.get("signals", {}).get("total"), 0)
    event_excluded_total = _safe_int(snapshot.get("event_risk", {}).get("excluded_total"), 0)
    regime_status = str(snapshot.get("backtest", {}).get("regime", {}).get("status", "")).strip().lower()
    kill_status = str(snapshot.get("backtest", {}).get("kill_switch", {}).get("status", "")).strip().lower()
    kill_active = kill_status in {"active", "cooldown", "triggered"}
    regime_ok = regime_status in {"ok", "risk_on", "pass", "clear", "healthy"}

    promotion_required = bool(model_v2_promotion.get("required_for_live", False))
    promotion_gate_pass = model_v2_promotion.get("gate_pass", {}) if isinstance(model_v2_promotion, dict) else {}
    blocked_promotion_modes: list[str] = []
    if isinstance(gate_components, dict):
        for mode in ["t1", "swing"]:
            component = gate_components.get(mode, {})
            if not isinstance(component, dict):
                continue
            comp_required = bool(component.get("promotion_required", promotion_required))
            comp_ok = bool(component.get("promotion_gate_ok", True))
            if comp_required and not comp_ok:
                blocked_promotion_modes.append(mode)
    if (not blocked_promotion_modes) and promotion_required and isinstance(promotion_gate_pass, dict):
        blocked_promotion_modes = [
            mode for mode in ["t1", "swing"] if not bool(promotion_gate_pass.get(mode, False))
        ]

    summary_status = str(summary.get("status", "")).strip()
    summary_action = str(summary.get("action", "")).strip().upper()
    summary_reason = str(summary.get("action_reason", "")).strip()
    summary_ready = bool(summary.get("trade_ready", False))
    summary_modes = summary.get("allowed_modes")
    if isinstance(summary_modes, list) and summary_modes:
        allowed_modes = [str(m).strip().lower() for m in summary_modes if str(m).strip()]

    trade_ready = summary_ready if summary_status else (signal_total > 0 and bool(allowed_modes) and not kill_active and regime_ok)
    action = summary_action if summary_action in {"EXECUTE_MAX_3", "NO_TRADE"} else ("EXECUTE_MAX_3" if trade_ready else "NO_TRADE")

    if summary_status:
        status = summary_status
    elif trade_ready:
        status = "SUCCESS"
    elif kill_active:
        status = "KILL_SWITCH_ACTIVE"
    elif not regime_ok:
        status = "RISK_OFF_REGIME"
    elif promotion_required and blocked_promotion_modes:
        status = "MODEL_V2_PROMOTION_BLOCKED"
    elif not allowed_modes:
        status = "BLOCKED_BY_GATE"
    elif signal_total <= 0:
        status = "NO_SIGNAL"
    else:
        status = "NO_TRADE"

    reasons: list[str] = []
    if not trade_ready:
        _append_unique_reason(reasons, summary_reason)
        if signal_total <= 0:
            _append_unique_reason(reasons, "No executable signals found after filtering.")
        if not allowed_modes:
            blocked_text = ", ".join(active_modes) if active_modes else "all configured modes"
            _append_unique_reason(reasons, f"Live gate blocked all active modes: {blocked_text}.")
        if kill_active:
            _append_unique_reason(reasons, "Kill switch is active or cooldown is running.")
        if not regime_ok and regime_status:
            _append_unique_reason(reasons, f"Market regime is `{regime_status}` (risk-off).")
        if promotion_required and blocked_promotion_modes:
            blocked_text = ", ".join(sorted(blocked_promotion_modes))
            _append_unique_reason(reasons, f"Model v2 promotion gate blocked mode(s): {blocked_text}.")
            if isinstance(model_v2_promotion, dict):
                mode_payload = model_v2_promotion.get("modes", {})
                if isinstance(mode_payload, dict):
                    for mode in blocked_promotion_modes:
                        detail = mode_payload.get(mode, {})
                        if not isinstance(detail, dict):
                            continue
                        reason_list = detail.get("reasons", [])
                        if isinstance(reason_list, list) and reason_list:
                            _append_unique_reason(reasons, f"{mode.upper()}: {reason_list[0]}")
        if event_excluded_total > 0 and signal_total <= 0:
            _append_unique_reason(reasons, f"{event_excluded_total} candidates excluded by event-risk filter.")

        score_funnel = _extract_score_funnel(snapshot.get("funnel", {}))
        modes = score_funnel.get("modes", {}) if isinstance(score_funnel, dict) else {}
        dropped_score = 0
        dropped_event = 0
        for mode_key in ["t1", "swing"]:
            mode_data = modes.get(mode_key, {}) if isinstance(modes, dict) else {}
            dropped_score += _safe_int(mode_data.get("dropped_by_score"), 0)
            dropped_event += _safe_int(mode_data.get("dropped_by_event_risk"), 0)
        combined = score_funnel.get("combined", {}) if isinstance(score_funnel, dict) else {}
        dropped_size = _safe_int(combined.get("dropped_by_size_filter"), 0)
        if dropped_score > 0:
            _append_unique_reason(reasons, f"{dropped_score} candidates dropped by minimum score threshold.")
        if dropped_event > 0:
            _append_unique_reason(reasons, f"{dropped_event} candidates dropped by event-risk status.")
        if dropped_size > 0:
            _append_unique_reason(reasons, f"{dropped_size} candidates dropped by position size / lot filter.")

    if trade_ready and signal_total > 0:
        reasons = [f"{signal_total} signals available and at least one mode passed live gate."]

    primary_reason = reasons[0] if reasons else (summary_reason or "No blocking reason detected.")
    return {
        "status": status,
        "action": action,
        "trade_ready": bool(trade_ready),
        "action_reason": primary_reason,
        "why_no_signal": reasons if not trade_ready else [],
        "allowed_modes": allowed_modes,
        "signal_total": int(signal_total),
        "gate": {
            "t1": gate_t1,
            "swing": gate_swing,
        },
        "regime_status": regime_status,
        "kill_switch_status": kill_status,
        "event_excluded_total": int(event_excluded_total),
        "model_v2_promotion_required": promotion_required,
        "model_v2_promotion_gate_pass": promotion_gate_pass if isinstance(promotion_gate_pass, dict) else {},
        "model_v2_promotion_blocked_modes": blocked_promotion_modes,
        "data_age_days": _safe_int(summary.get("data_age_days"), -1) if summary else -1,
        "data_max_date": str(summary.get("data_max_date", "")) if summary else "",
        "source": "n8n_summary" if summary_status else "derived_snapshot",
        "mode_activation": mode_activation,
    }


def build_dashboard_snapshot(reports_dir: str | Path = "reports", signal_limit: int = 200) -> dict[str, Any]:
    base = Path(reports_dir)
    signal_payload = query_signals(reports_dir=base, limit=signal_limit)
    signal_all_items = signal_payload.get("items", [])
    signal_total = _safe_int(signal_payload.get("total"))
    signal_score_mean = 0.0
    if signal_all_items:
        signal_score_mean = round(
            sum(_safe_float(r.get("score"), default=0.0) for r in signal_all_items) / len(signal_all_items),
            2,
        )

    execution_df_daily = _read_csv_df(
        base / "execution_plan.csv",
        expected_cols=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"],
    )
    execution_df_intraday = _read_csv_df(
        base / "intraday_execution_plan.csv",
        expected_cols=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"],
    )
    execution_frames = [df for df in [execution_df_intraday, execution_df_daily] if not df.empty]
    if execution_frames:
        execution_df = pd.concat(execution_frames, ignore_index=True, sort=False)
    else:
        execution_df = pd.DataFrame(
            columns=["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason"]
        )
    top_t1_df = _read_csv_df(base / "top_t1.csv")
    top_swing_df = _read_csv_df(base / "top_swing.csv")
    top_intraday_df = _read_csv_df(base / "intraday_top.csv")
    event_active_df = _read_csv_df(base / "event_risk_active.csv")
    event_excluded_df = _read_csv_df(base / "event_risk_excluded.csv")
    intraday_status = _read_json(base / "intraday_status.json", default={})
    intraday_daemon_state = _read_json(base / "intraday_daemon_state.json", default={})

    backtest_raw = _read_json(base / "backtest_metrics.json", default={})
    funnel_live = _read_json(base / "signal_funnel_live.json", default={})
    if not funnel_live:
        funnel_live = _read_json(base / "signal_funnel.json", default={})
    closed_loop_state = _read_json(base / "model_v2_closed_loop_state.json", default={})
    quality_raw = _read_json(base / "data_quality_report.json", default={})
    paper_fills_raw = _read_json(base / "paper_fills_summary.json", default={})
    swing_audit_raw = _read_json(base / "swing_audit.json", default={})

    report_html = base / "daily_report.html"
    daily_summary = _load_daily_summary(base)
    quality = _extract_quality(quality_raw if isinstance(quality_raw, dict) else {})
    risk_budget = _extract_risk_budget(daily_summary if isinstance(daily_summary, dict) else {})
    paper_live_mode = _extract_paper_live_mode(daily_summary if isinstance(daily_summary, dict) else {})
    backtest_summary = _extract_backtest_summary(backtest_raw if isinstance(backtest_raw, dict) else {})
    mode_activation = _extract_mode_activation(daily_summary if isinstance(daily_summary, dict) else {}, backtest_summary)
    if isinstance(backtest_summary, dict):
        backtest_summary["mode_activation"] = mode_activation
    operator_alerts = _extract_operator_alerts(daily_summary if isinstance(daily_summary, dict) else {})
    paper_fills = _extract_paper_fills(paper_fills_raw if isinstance(paper_fills_raw, dict) else {})
    swing_audit = _extract_swing_audit(swing_audit_raw if isinstance(swing_audit_raw, dict) else {})

    snapshot = {
        "generated_at": _utc_now_iso(),
        "signals": {
            "generated_at": signal_payload.get("generated_at", ""),
            "total": signal_total,
            "avg_score": signal_score_mean,
            "by_mode": signal_payload.get("by_mode", {}),
            "items": signal_all_items,
        },
        "execution_plan": {
            "total": int(len(execution_df)),
            "items": _records(execution_df, limit=200),
        },
        "top_picks": {
            "t1_total": int(len(top_t1_df)),
            "swing_total": int(len(top_swing_df)),
            "intraday_total": int(len(top_intraday_df)),
            "t1_items": _records(top_t1_df, limit=100),
            "swing_items": _records(top_swing_df, limit=100),
            "intraday_items": _records(top_intraday_df, limit=100),
        },
        "backtest": backtest_summary,
        "funnel": funnel_live if isinstance(funnel_live, dict) else {},
        "event_risk": {
            "active_total": int(len(event_active_df)),
            "excluded_total": int(len(event_excluded_df)),
            "active_items": _records(event_active_df, limit=100),
            "excluded_items": _records(event_excluded_df, limit=100),
        },
        "operator_alerts": operator_alerts,
        "paper_fills": paper_fills,
        "swing_audit": swing_audit,
        "runs": _load_recent_runs(base, limit=8),
        "report": {
            "html_exists": report_html.exists(),
        },
        "intraday": {
            "status": intraday_status if isinstance(intraday_status, dict) else {},
            "daemon_state": intraday_daemon_state if isinstance(intraday_daemon_state, dict) else {},
        },
        "closed_loop_retrain": _extract_closed_loop_retrain(
            closed_loop_state if isinstance(closed_loop_state, dict) else {}
        ),
        "quality": quality,
        "risk_budget": risk_budget,
        "paper_live_mode": paper_live_mode,
        "summary": daily_summary,
    }
    snapshot["decision"] = _derive_decision(snapshot=snapshot, summary=daily_summary)
    snapshot["kpi"] = {
        "signal_total": signal_total,
        "execution_total": int(len(execution_df)),
        "event_active_total": int(len(event_active_df)),
        "event_excluded_total": int(len(event_excluded_df)),
        "signal_avg_score": signal_score_mean,
        "gate_pass": snapshot["backtest"].get("gate_pass", {}),
        "regime_status": snapshot["backtest"].get("regime", {}).get("status", ""),
        "kill_switch_status": snapshot["backtest"].get("kill_switch", {}).get("status", ""),
        "intraday_daemon_status": snapshot["intraday"].get("daemon_state", {}).get("status", ""),
        "intraday_signal_count": signal_payload.get("sources", {}).get("intraday_count", 0),
        "decision_action": snapshot["decision"].get("action", ""),
        "decision_trade_ready": bool(snapshot["decision"].get("trade_ready", False)),
        "model_v2_promotion_required": bool(
            snapshot["backtest"].get("model_v2_promotion", {}).get("required_for_live", False)
        ),
        "model_v2_promotion_pass_t1": bool(
            snapshot["backtest"].get("model_v2_promotion", {}).get("gate_pass", {}).get("t1", False)
        ),
        "model_v2_promotion_pass_swing": bool(
            snapshot["backtest"].get("model_v2_promotion", {}).get("gate_pass", {}).get("swing", False)
        ),
        "closed_loop_retrain_status": str(snapshot["closed_loop_retrain"].get("status", "")),
        "closed_loop_retrain_triggered": bool(snapshot["closed_loop_retrain"].get("triggered", False)),
        "quality_status": str(snapshot["quality"].get("status", "")),
        "quality_pass": bool(snapshot["quality"].get("pass", False)),
        "risk_budget_pct": _safe_float(snapshot["risk_budget"].get("risk_budget_pct"), 0.0),
        "risk_budget_status": str(snapshot["risk_budget"].get("status", "")),
        "paper_live_mode": str(snapshot["paper_live_mode"].get("mode", "")),
        "rollout_phase": str(snapshot["paper_live_mode"].get("rollout_phase", "")),
        "operator_alert_count": int(len(operator_alerts)),
        "paper_fill_trade_count": int(paper_fills.get("trade_count_total", 0)),
        "swing_audit_trade_count": _safe_int(swing_audit.get("overall", {}).get("trade_count"), 0),
    }
    return snapshot


def default_run_daily_runner(settings_path: str, skip_telegram: bool) -> dict[str, Any]:
    from src.cli import run_daily
    from src.config import load_settings

    settings = load_settings(settings_path)
    return run_daily(settings=settings, skip_telegram=skip_telegram, settings_path=settings_path)


@dataclass
class RunJob:
    job_id: str
    status: str
    submitted_at: str
    started_at: str = ""
    ended_at: str = ""
    settings_path: str = "config/settings.json"
    skip_telegram: bool = True
    result: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result": self.result,
            "error": self.error,
        }


class RunJobManager:
    def __init__(
        self,
        runner: Callable[[str, bool], dict[str, Any]] | None = None,
        max_workers: int = 1,
        max_history: int = 20,
    ) -> None:
        self._runner = runner or default_run_daily_runner
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_history = max(1, max_history)
        self._jobs: dict[str, RunJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def submit(self, settings_path: str, skip_telegram: bool = True) -> dict[str, Any]:
        job_id = uuid4().hex[:12]
        job = RunJob(
            job_id=job_id,
            status="queued",
            submitted_at=_utc_now_iso(),
            settings_path=str(settings_path),
            skip_telegram=bool(skip_telegram),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._trim_history_locked()
        self._executor.submit(self._run_job, job_id)
        return job.to_dict()

    def _trim_history_locked(self) -> None:
        while len(self._order) > self._max_history:
            stale_id = self._order.pop(0)
            self._jobs.pop(stale_id, None)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = _utc_now_iso()

        try:
            result = self._runner(job.settings_path, job.skip_telegram)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error = str(exc)
                job.ended_at = _utc_now_iso()
        else:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.status = "succeeded"
                job.result = result
                job.ended_at = _utc_now_iso()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def list_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            selected = self._order[-max(1, limit) :]
            selected.reverse()
            return [self._jobs[job_id].to_dict() for job_id in selected if job_id in self._jobs]

    def counts(self) -> dict[str, int]:
        with self._lock:
            out = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
            for job_id in self._order:
                job = self._jobs.get(job_id)
                if not job:
                    continue
                out[job.status] = out.get(job.status, 0) + 1
            return out
