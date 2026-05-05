from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest import BacktestCosts
from src.config import Settings
from src.strategy import score_history_modes
from src.utils import atomic_write_json, atomic_write_text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _profit_factor(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    gross_profit = float(clean[clean > 0].sum())
    gross_loss = float(-clean[clean < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _summarize_bucket(df: pd.DataFrame, label_col: str, label_key: str) -> list[dict[str, Any]]:
    if df.empty or label_col not in df.columns:
        return []
    rows: list[dict[str, Any]] = []
    for label, grp in df.groupby(label_col, dropna=False):
        realized_r = pd.to_numeric(grp.get("realized_r"), errors="coerce").dropna()
        if realized_r.empty:
            continue
        rows.append(
            {
                label_key: str(label),
                "trade_count": int(len(realized_r)),
                "win_rate_pct": round(float((realized_r > 0).mean() * 100.0), 2),
                "expectancy_r": round(float(realized_r.mean()), 4),
                "profit_factor_r": round(float(_profit_factor(realized_r)), 4),
                "avg_return_pct": round(float(pd.to_numeric(grp.get("return_pct"), errors="coerce").mean()), 4),
                "avg_mae_r": round(float(pd.to_numeric(grp.get("mae_r"), errors="coerce").mean()), 4),
                "avg_mfe_r": round(float(pd.to_numeric(grp.get("mfe_r"), errors="coerce").mean()), 4),
                "median_score": round(float(pd.to_numeric(grp.get("score"), errors="coerce").median()), 4),
            }
        )
    rows.sort(key=lambda row: (-row["trade_count"], row[label_key]))
    return rows


def _volatility_bucket(series: pd.Series) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce")
    if clean.notna().sum() < 3 or clean.nunique(dropna=True) < 3:
        median = clean.median()
        return clean.apply(lambda value: "high" if pd.notna(value) and value >= median else "low")
    try:
        return pd.qcut(clean, q=3, labels=["low", "mid", "high"], duplicates="drop")
    except Exception:
        median = clean.median()
        return clean.apply(lambda value: "high" if pd.notna(value) and value >= median else "low")


def _load_universe_group_map(settings: Settings) -> tuple[dict[str, str], str]:
    path = Path(settings.data.universe_csv_path)
    if not path.exists():
        return {}, "unclassified"
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}, "unclassified"
    if "ticker" not in df.columns:
        return {}, "unclassified"
    group_source = "unclassified"
    for candidate in ["sector", "industry", "segment", "index"]:
        if candidate in df.columns:
            group_source = candidate
            break
    if group_source == "unclassified":
        return {}, group_source
    mapping = (
        df[["ticker", group_source]]
        .dropna(subset=["ticker"])
        .assign(
            ticker=lambda frame: frame["ticker"].astype(str).str.upper().str.strip(),
            group=lambda frame: frame[group_source].astype(str).str.strip(),
        )
    )
    return dict(zip(mapping["ticker"], mapping["group"])), group_source


def _daily_regime_table(features: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    regime_cfg = settings.regime
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "regime_status"])
    rows: list[dict[str, Any]] = []
    for date_value, grp in df.groupby("date", dropna=False):
        ma50_valid = grp.dropna(subset=["close", "ma_50"])
        ma20_valid = grp.dropna(subset=["close", "ma_20"])
        ret20_valid = grp.dropna(subset=["ret_20d"])
        atr_valid = grp.dropna(subset=["atr_pct"])
        breadth_ma50_pct = float((ma50_valid["close"] > ma50_valid["ma_50"]).mean() * 100.0) if len(ma50_valid) else 0.0
        breadth_ma20_pct = float((ma20_valid["close"] > ma20_valid["ma_20"]).mean() * 100.0) if len(ma20_valid) else 0.0
        avg_ret20_pct = float(ret20_valid["ret_20d"].mean() * 100.0) if len(ret20_valid) else 0.0
        median_atr_pct = float(atr_valid["atr_pct"].median()) if len(atr_valid) else 0.0
        checks = [
            breadth_ma50_pct >= float(regime_cfg.min_breadth_ma50_pct),
            breadth_ma20_pct >= float(regime_cfg.min_breadth_ma20_pct),
            avg_ret20_pct >= float(regime_cfg.min_avg_ret20_pct),
            median_atr_pct <= float(regime_cfg.max_median_atr_pct),
        ]
        rows.append(
            {
                "date": pd.Timestamp(date_value),
                "regime_status": "risk_on" if all(checks) else "risk_off",
                "breadth_ma50_pct": breadth_ma50_pct,
                "breadth_ma20_pct": breadth_ma20_pct,
                "avg_ret20_pct": avg_ret20_pct,
                "median_atr_pct": median_atr_pct,
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _build_trade_rows(
    features: pd.DataFrame,
    settings: Settings,
    costs: BacktestCosts,
) -> pd.DataFrame:
    scored = score_history_modes(features, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)
    scored = scored[
        (scored["mode"] == "swing")
        & (pd.to_numeric(scored["score"], errors="coerce") >= float(settings.pipeline.min_live_score_swing))
    ].copy()
    if scored.empty:
        return pd.DataFrame()

    scored["date"] = pd.to_datetime(scored["date"], errors="coerce")
    scored = scored.dropna(subset=["date", "ticker", "close"]).sort_values(["date", "score"], ascending=[True, False])
    trades = scored.groupby("date").head(1).copy().reset_index(drop=True)
    if trades.empty:
        return pd.DataFrame()

    bars = (
        features.copy()
        .assign(date=lambda frame: pd.to_datetime(frame["date"], errors="coerce"))
        .dropna(subset=["date", "ticker", "close", "high", "low"])
        .sort_values(["ticker", "date"])
        .drop_duplicates(subset=["ticker", "date"], keep="first")
        .reset_index(drop=True)
    )
    grouped = {str(ticker): grp.reset_index(drop=True) for ticker, grp in bars.groupby("ticker", dropna=False)}

    buy_cost = (float(costs.buy_fee_pct) + float(costs.slippage_pct)) / 100.0
    sell_cost = (float(costs.sell_fee_pct) + float(costs.slippage_pct)) / 100.0
    rows: list[dict[str, Any]] = []
    for _, trade in trades.iterrows():
        ticker = str(trade["ticker"]).strip().upper()
        ticker_bars = grouped.get(ticker)
        if ticker_bars is None or ticker_bars.empty:
            continue
        matches = ticker_bars.index[ticker_bars["date"] == pd.Timestamp(trade["date"])].tolist()
        if not matches:
            continue
        idx = int(matches[0])
        horizon_days = 10
        if idx + horizon_days >= len(ticker_bars):
            continue
        future_window = ticker_bars.iloc[idx + 1 : idx + horizon_days + 1].copy()
        if future_window.empty or len(future_window) < horizon_days:
            continue
        exit_bar = ticker_bars.iloc[idx + horizon_days]
        entry_close = _safe_float(trade.get("close"), 0.0)
        exit_close = _safe_float(exit_bar.get("close"), 0.0)
        if entry_close <= 0 or exit_close <= 0:
            continue
        atr = _safe_float(trade.get("atr_14"), entry_close * 0.05)
        stop_price = entry_close - (float(settings.risk.stop_atr_multiple) * atr)
        risk_per_share = max(entry_close - stop_price, entry_close * 0.005, 1e-9)
        entry_exec = entry_close * (1.0 + buy_cost)
        exit_exec = exit_close * (1.0 - sell_cost)
        realized_r = (exit_exec - entry_exec) / risk_per_share
        return_pct = ((exit_exec - entry_exec) / max(entry_exec, 1e-9)) * 100.0
        max_high = float(pd.to_numeric(future_window["high"], errors="coerce").max())
        min_low = float(pd.to_numeric(future_window["low"], errors="coerce").min())
        mfe_r = (max_high - entry_close) / risk_per_share if max_high > 0 else 0.0
        mae_r = (min_low - entry_close) / risk_per_share if min_low > 0 else 0.0
        rows.append(
            {
                "date": pd.Timestamp(trade["date"]).strftime("%Y-%m-%d"),
                "ticker": ticker,
                "score": round(_safe_float(trade.get("score"), 0.0), 4),
                "atr_pct": round(_safe_float(trade.get("atr_pct"), 0.0), 4),
                "avg_vol_20d": round(_safe_float(trade.get("avg_vol_20d"), 0.0), 2),
                "ret_20d": round(_safe_float(trade.get("ret_20d"), 0.0) * 100.0, 4),
                "realized_r": round(realized_r, 6),
                "return_pct": round(return_pct, 6),
                "mae_r": round(mae_r, 6),
                "mfe_r": round(mfe_r, 6),
                "entry_close": round(entry_close, 4),
                "exit_close": round(exit_close, 4),
                "exit_date": pd.Timestamp(exit_bar["date"]).strftime("%Y-%m-%d"),
            }
        )
    return pd.DataFrame(rows)


def generate_swing_audit_report(
    features: pd.DataFrame,
    settings: Settings,
    costs: BacktestCosts,
    out_path: str | Path = "reports/swing_audit.json",
) -> dict[str, Any]:
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    trades = _build_trade_rows(features=features, settings=settings, costs=costs)
    if trades.empty:
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "status": "no_trades",
            "message": "No swing trades available for audit",
            "overall": {},
            "by_regime": [],
            "by_group": [],
            "by_volatility": [],
            "weak_spots": [],
            "recent_trades": [],
            "group_source": "unclassified",
        }
        atomic_write_json(out_file, payload)
        atomic_write_text(out_file.with_suffix(".md"), "# Swing Audit\n\nNo swing trades available for audit.\n", encoding="utf-8")
        return payload

    regime_daily = _daily_regime_table(features=features, settings=settings)
    if not regime_daily.empty:
        regime_daily["date"] = pd.to_datetime(regime_daily["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        trades = trades.merge(regime_daily[["date", "regime_status"]], on="date", how="left")
    trades["regime_status"] = trades.get("regime_status", pd.Series(dtype=str)).fillna("risk_off")

    group_map, group_source = _load_universe_group_map(settings)
    trades["group_label"] = trades["ticker"].map(group_map).fillna("unknown")
    trades["volatility_bucket"] = _volatility_bucket(trades["atr_pct"]).astype(str)

    realized_r = pd.to_numeric(trades["realized_r"], errors="coerce").dropna()
    overall = {
        "trade_count": int(len(realized_r)),
        "win_rate_pct": round(float((realized_r > 0).mean() * 100.0), 2) if not realized_r.empty else 0.0,
        "expectancy_r": round(float(realized_r.mean()), 4) if not realized_r.empty else 0.0,
        "profit_factor_r": round(float(_profit_factor(realized_r)), 4) if not realized_r.empty else 0.0,
        "avg_return_pct": round(float(pd.to_numeric(trades["return_pct"], errors="coerce").mean()), 4),
        "avg_mae_r": round(float(pd.to_numeric(trades["mae_r"], errors="coerce").mean()), 4),
        "avg_mfe_r": round(float(pd.to_numeric(trades["mfe_r"], errors="coerce").mean()), 4),
        "median_score": round(float(pd.to_numeric(trades["score"], errors="coerce").median()), 4),
        "date_from": str(trades["date"].min()),
        "date_to": str(trades["date"].max()),
    }

    by_regime = _summarize_bucket(trades, "regime_status", "regime")
    by_group = _summarize_bucket(trades, "group_label", group_source if group_source != "unclassified" else "group")
    by_volatility = _summarize_bucket(trades, "volatility_bucket", "volatility_bucket")

    weak_spots: list[dict[str, Any]] = []
    for source_name, rows in [
        ("regime", by_regime),
        (group_source if group_source != "unclassified" else "group", by_group),
        ("volatility_bucket", by_volatility),
    ]:
        for row in rows:
            if int(row.get("trade_count", 0)) < 3:
                continue
            if float(row.get("expectancy_r", 0.0)) >= 0 and float(row.get("profit_factor_r", 0.0)) >= 1.0:
                continue
            label_key = next((key for key in row.keys() if key not in {"trade_count", "win_rate_pct", "expectancy_r", "profit_factor_r", "avg_return_pct", "avg_mae_r", "avg_mfe_r", "median_score"}), "bucket")
            weak_spots.append(
                {
                    "source": source_name,
                    "label": str(row.get(label_key, "")),
                    "trade_count": int(row.get("trade_count", 0)),
                    "expectancy_r": float(row.get("expectancy_r", 0.0)),
                    "profit_factor_r": float(row.get("profit_factor_r", 0.0)),
                }
            )
    weak_spots.sort(key=lambda item: (item["expectancy_r"], item["profit_factor_r"], -item["trade_count"]))

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "status": "ok",
        "message": "Swing audit generated",
        "group_source": group_source,
        "overall": overall,
        "by_regime": by_regime,
        "by_group": by_group,
        "by_volatility": by_volatility,
        "weak_spots": weak_spots[:5],
        "recent_trades": trades.sort_values("date", ascending=False).head(20).to_dict(orient="records"),
    }
    atomic_write_json(out_file, payload)

    md_lines = [
        "# Swing Audit",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- trade_count: {overall.get('trade_count', 0)}",
        f"- expectancy_r: {overall.get('expectancy_r', 0.0)}",
        f"- profit_factor_r: {overall.get('profit_factor_r', 0.0)}",
        f"- avg_mae_r: {overall.get('avg_mae_r', 0.0)}",
        f"- avg_mfe_r: {overall.get('avg_mfe_r', 0.0)}",
        f"- group_source: {group_source}",
        "",
        "## Weak Spots",
    ]
    if weak_spots:
        md_lines.extend(
            [
                f"- {item['source']}={item['label']} | trades={item['trade_count']} | expectancy_r={item['expectancy_r']:.4f} | profit_factor_r={item['profit_factor_r']:.4f}"
                for item in weak_spots[:5]
            ]
        )
    else:
        md_lines.append("- none")
    atomic_write_text(out_file.with_suffix(".md"), "\n".join(md_lines) + "\n", encoding="utf-8")
    return payload
