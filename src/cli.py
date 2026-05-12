from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest import BacktestCosts, pass_live_gate, run_backtest, run_walk_forward, simulate_mode_trades
from src.config import Settings, load_settings
from src.features.compute_features import compute_features
from src.ingest.load_prices import load_prices_csv, load_prices_from_provider
from src.model_v2 import (
    apply_model_v2_rollout_selection,
    evaluate_and_update_model_v2_promotion,
    run_model_v2_shadow,
)
from src.notify import build_daily_message, send_telegram_message
from src.report import (
    generate_weekly_kpi_dashboard,
    reconcile_live_signals,
    write_beginner_coaching_note,
    write_signal_snapshot,
)
from src.report.render_report import render_html_report, write_signal_json
from src.risk import maybe_auto_recalibrate_volatility_targets, maybe_auto_update_event_risk
from src.risk.manager import apply_global_position_limit, propose_trade_plan
from src.strategy import rank_all_modes, score_history_modes
from src.universe import maybe_auto_update_universe
from src.utils import JsonRunLogger


def _ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(out)


def _load_universe(path: str) -> list[str]:
    universe = pd.read_csv(path)
    if "ticker" not in universe.columns:
        raise ValueError("Universe file must contain 'ticker' column")
    return sorted(universe["ticker"].astype(str).str.upper().str.strip().unique().tolist())


def _merge_with_existing_prices(out_path: str, incoming: pd.DataFrame) -> pd.DataFrame:
    path = Path(out_path)
    if not path.exists():
        return incoming.sort_values(["ticker", "date"]).reset_index(drop=True)

    existing = pd.read_csv(path)
    existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
    if "source" not in existing.columns:
        existing["source"] = "existing_csv"
    if "ingested_at" not in existing.columns:
        existing["ingested_at"] = datetime.utcnow().isoformat()
    existing = existing[
        [
            "date",
            "ticker",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "ingested_at",
        ]
    ].copy()

    merged = pd.concat([existing, incoming], ignore_index=True, sort=False)
    merged = merged.sort_values(["ticker", "date", "ingested_at"])
    merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
    merged = merged.reset_index(drop=True)
    return merged


def ingest_daily(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    merge_existing: bool = True,
) -> dict[str, Any]:
    tickers = _load_universe(settings.data.universe_csv_path)
    prices, source = load_prices_from_provider(
        settings=settings,
        start_date=start_date,
        end_date=end_date,
        tickers=tickers,
    )
    prices = prices[prices["ticker"].isin(tickers)].sort_values(["ticker", "date"]).reset_index(drop=True)
    fetched_tickers = set(prices["ticker"].unique().tolist())
    missing_tickers = sorted(set(tickers) - fetched_tickers)

    out_path = settings.data.canonical_prices_path
    _ensure_parent(out_path)
    to_save = _merge_with_existing_prices(out_path, prices) if merge_existing else prices
    to_save.to_csv(out_path, index=False)
    return {
        "rows": len(to_save),
        "rows_new": len(prices),
        "tickers": int(to_save["ticker"].nunique()) if not to_save.empty else 0,
        "source": source,
        "max_data_date": to_save["date"].max().strftime("%Y-%m-%d") if not to_save.empty else "",
        "min_data_date": to_save["date"].min().strftime("%Y-%m-%d") if not to_save.empty else "",
        "missing_tickers_count": len(missing_tickers),
        "missing_tickers_sample": missing_tickers[:10],
        "out_path": out_path,
    }


def backfill_history(settings: Settings, years: int = 2, end_date: str | None = None) -> dict[str, Any]:
    if years < 1:
        raise ValueError("years must be >= 1")
    end_dt = pd.Timestamp(end_date).date() if end_date else datetime.utcnow().date()
    start_dt = end_dt - timedelta(days=365 * years)
    info = ingest_daily(
        settings=settings,
        start_date=start_dt.isoformat(),
        end_date=end_dt.isoformat(),
        merge_existing=True,
    )
    info["backfill_years"] = years
    info["backfill_start"] = start_dt.isoformat()
    info["backfill_end"] = end_dt.isoformat()
    return info


def compute_features_step(settings: Settings) -> dict[str, Any]:
    prices = load_prices_csv(settings.data.canonical_prices_path, source="canonical_csv")
    feats = compute_features(prices)
    out_path = "data/processed/features.parquet"
    _ensure_parent(out_path)
    feats.to_parquet(out_path, index=False)
    return {"rows": len(feats), "out_path": out_path}


def _apply_liquidity_cost_estimate(plan: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    if plan.empty:
        return plan.copy()

    df = plan.copy()
    avg_vol_source = df["avg_vol_20d"] if "avg_vol_20d" in df.columns else pd.Series(0.0, index=df.index)
    avg_vol = pd.to_numeric(avg_vol_source, errors="coerce").fillna(0.0)
    mid_th = float(settings.backtest.liq_bucket_mid_avg_volume_20d)
    high_th = float(settings.backtest.liq_bucket_high_avg_volume_20d)

    df["liq_bucket"] = "low"
    df.loc[avg_vol >= mid_th, "liq_bucket"] = "mid"
    df.loc[avg_vol >= high_th, "liq_bucket"] = "high"

    slip_base = float(settings.backtest.slippage_pct)
    mult_map = {
        "low": float(settings.backtest.slippage_multiplier_low_liq),
        "mid": float(settings.backtest.slippage_multiplier_mid_liq),
        "high": float(settings.backtest.slippage_multiplier_high_liq),
    }
    mult = df["liq_bucket"].map(mult_map).fillna(float(settings.backtest.slippage_multiplier_mid_liq))
    df["est_slippage_pct"] = (slip_base * mult).round(4)
    roundtrip_base = float(settings.backtest.buy_fee_pct) + float(settings.backtest.sell_fee_pct)
    df["est_roundtrip_cost_pct"] = (
        roundtrip_base +
        (2.0 * pd.to_numeric(df["est_slippage_pct"], errors="coerce").fillna(slip_base))
    ).round(4)
    return df


def score_step(settings: Settings) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    top_t1_raw, top_swing_raw, _ = rank_all_modes(
        features=feats,
        min_avg_volume_20d=settings.pipeline.min_avg_volume_20d,
        top_n_per_mode=settings.pipeline.top_n_per_mode,
    )

    plan_t1 = propose_trade_plan(top_t1_raw, settings.risk)
    plan_swing = propose_trade_plan(top_swing_raw, settings.risk)
    lot_size = int(settings.risk.position_lot)
    t1_small_size_pre = int((plan_t1["size"] < lot_size).sum()) if "size" in plan_t1.columns else 0
    swing_small_size_pre = int((plan_swing["size"] < lot_size).sum()) if "size" in plan_swing.columns else 0

    # Live execution guardrails by mode-specific minimum score.
    min_score_t1 = float(settings.pipeline.min_live_score_t1)
    min_score_swing = float(settings.pipeline.min_live_score_swing)
    t1_before_score = int(len(plan_t1))
    swing_before_score = int(len(plan_swing))
    if "score" in plan_t1.columns:
        plan_t1 = plan_t1[plan_t1["score"] >= min_score_t1].copy()
    if "score" in plan_swing.columns:
        plan_swing = plan_swing[plan_swing["score"] >= min_score_swing].copy()
    t1_after_score = int(len(plan_t1))
    swing_after_score = int(len(plan_swing))

    plan_t1, plan_swing, event_risk_info = _apply_event_risk_filter(
        plan_t1=plan_t1,
        plan_swing=plan_swing,
        settings=settings,
    )
    t1_after_event = int(len(plan_t1))
    swing_after_event = int(len(plan_swing))

    combined_before_size = pd.concat([plan_t1, plan_swing], ignore_index=True, sort=False)
    combined_plan = combined_before_size.copy()
    size_removed = 0
    if "size" in combined_plan.columns:
        size_removed = int((combined_plan["size"] < lot_size).sum())
        combined_plan = combined_plan[combined_plan["size"] >= lot_size].copy()
    combined_after_size = int(len(combined_plan))
    combined_plan = combined_plan.sort_values("score", ascending=False).head(
        settings.pipeline.top_n_combined
    ).reset_index(drop=True)
    combined_after_topn = int(len(combined_plan))
    combined_plan = _apply_liquidity_cost_estimate(combined_plan, settings)
    mode_caps = {
        "t1": int(settings.risk.max_positions_t1),
        "swing": int(settings.risk.max_positions_swing),
    }
    mode_priority = [str(m).strip().lower() for m in settings.risk.execution_mode_priority if str(m).strip()]
    execution_plan = apply_global_position_limit(
        combined_plan,
        settings.risk.max_positions,
        max_positions_by_mode=mode_caps,
        mode_priority=mode_priority,
    )
    execution_count = int(len(execution_plan))

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    plan_t1.to_csv(reports_dir / "top_t1.csv", index=False)
    plan_swing.to_csv(reports_dir / "top_swing.csv", index=False)
    combined_plan.to_csv(reports_dir / "daily_report.csv", index=False)
    execution_plan.to_csv(reports_dir / "execution_plan.csv", index=False)

    signal_cols = [
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
    signal_df = combined_plan[[c for c in signal_cols if c in combined_plan.columns]].copy()
    signal_path = write_signal_json(signal_df, str(reports_dir / "daily_signal.json"))
    signal_funnel = {
        "generated_at": datetime.utcnow().isoformat(),
        "thresholds": {
            "min_live_score_t1": min_score_t1,
            "min_live_score_swing": min_score_swing,
            "position_lot": lot_size,
            "top_n_combined": int(settings.pipeline.top_n_combined),
            "max_positions": int(settings.risk.max_positions),
            "max_positions_t1": int(settings.risk.max_positions_t1),
            "max_positions_swing": int(settings.risk.max_positions_swing),
            "execution_mode_priority": mode_priority,
            "liq_bucket_mid_avg_volume_20d": float(settings.backtest.liq_bucket_mid_avg_volume_20d),
            "liq_bucket_high_avg_volume_20d": float(settings.backtest.liq_bucket_high_avg_volume_20d),
            "slippage_pct_base": float(settings.backtest.slippage_pct),
        },
        "modes": {
            "t1": {
                "rank_candidates": int(len(top_t1_raw)),
                "after_score_filter": t1_after_score,
                "after_event_risk": t1_after_event,
                "small_size_before_filter": t1_small_size_pre,
                "dropped_by_score": max(0, t1_before_score - t1_after_score),
                "dropped_by_event_risk": max(0, t1_after_score - t1_after_event),
            },
            "swing": {
                "rank_candidates": int(len(top_swing_raw)),
                "after_score_filter": swing_after_score,
                "after_event_risk": swing_after_event,
                "small_size_before_filter": swing_small_size_pre,
                "dropped_by_score": max(0, swing_before_score - swing_after_score),
                "dropped_by_event_risk": max(0, swing_after_score - swing_after_event),
            },
        },
        "combined": {
            "before_size_filter": int(len(combined_before_size)),
            "dropped_by_size_filter": size_removed,
            "after_size_filter": combined_after_size,
            "after_top_n_combined": combined_after_topn,
            "execution_plan_count": execution_count,
            "signal_count": int(len(signal_df)),
            "avg_roundtrip_cost_est_pct": round(
                float(pd.to_numeric(combined_plan.get("est_roundtrip_cost_pct", pd.Series(dtype=float)), errors="coerce").mean() or 0.0),
                4,
            ),
        },
        "event_risk": event_risk_info,
    }
    signal_funnel_path = _write_json(reports_dir / "signal_funnel.json", signal_funnel)
    return {
        "top_t1": plan_t1,
        "top_swing": plan_swing,
        "combined_plan": combined_plan,
        "execution_plan": execution_plan,
        "signal_path": signal_path,
        "signal_funnel": signal_funnel,
        "signal_funnel_path": signal_funnel_path,
        "event_risk": event_risk_info,
    }


def _apply_live_score_filters(scored: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    min_score_t1 = float(settings.pipeline.min_live_score_t1)
    min_score_swing = float(settings.pipeline.min_live_score_swing)
    return scored[
        (
            (scored["mode"] == "t1") &
            (scored["score"] >= min_score_t1)
        ) |
        (
            (scored["mode"] == "swing") &
            (scored["score"] >= min_score_swing)
        )
    ].copy()


def _load_event_risk_active(settings: Settings, as_of_date: str | None = None) -> pd.DataFrame:
    cfg = settings.pipeline.event_risk
    path = Path(cfg.blacklist_csv_path)
    if not path.exists():
        # Public repo may track a sample file while live file is ignored for daily updates.
        sample_path = path.with_name(f"{path.stem}.sample{path.suffix}")
        if sample_path.exists():
            path = sample_path
        else:
            return pd.DataFrame(columns=["ticker", "status", "reason", "start_date", "end_date", "updated_at"])

    raw = pd.read_csv(path)
    if "ticker" not in raw.columns:
        raise ValueError("Event blacklist file must contain 'ticker' column")

    df = raw.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["status"] = df.get("status", "").astype(str).str.upper().str.strip()
    df["reason"] = df.get("reason", "").astype(str)
    df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
    df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")
    df["updated_at"] = pd.to_datetime(df.get("updated_at"), errors="coerce")

    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.utcnow()
    if getattr(as_of, "tzinfo", None) is not None:
        as_of = as_of.tz_convert(None)
    as_of = as_of.normalize()
    statuses = {str(s).upper().strip() for s in cfg.active_statuses}
    status_ok = df["status"].isin(statuses) if statuses else pd.Series([True] * len(df), index=df.index)

    in_window = (
        (df["start_date"].isna() | (df["start_date"] <= as_of))
        & (df["end_date"].isna() | (df["end_date"] >= as_of))
    )

    no_window = df["start_date"].isna() & df["end_date"].isna()
    recency_cutoff = as_of - pd.Timedelta(days=max(0, int(cfg.default_active_days)))
    recent_if_no_window = df["updated_at"].isna() | (df["updated_at"] >= recency_cutoff)
    active = status_ok & ((~no_window & in_window) | (no_window & recent_if_no_window))

    out = df[active].copy()
    if out.empty:
        return out
    out = out.sort_values(["ticker", "status", "updated_at"], ascending=[True, True, False]).reset_index(drop=True)
    return out


def _apply_event_risk_filter(
    plan_t1: pd.DataFrame,
    plan_swing: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = settings.pipeline.event_risk
    as_of_date = ""
    if not plan_t1.empty and "date" in plan_t1.columns:
        max_dt = pd.to_datetime(plan_t1["date"], errors="coerce").max()
        if pd.notna(max_dt):
            as_of_date = pd.Timestamp(max_dt).strftime("%Y-%m-%d")
    elif not plan_swing.empty and "date" in plan_swing.columns:
        max_dt = pd.to_datetime(plan_swing["date"], errors="coerce").max()
        if pd.notna(max_dt):
            as_of_date = pd.Timestamp(max_dt).strftime("%Y-%m-%d")

    info: dict[str, Any] = {
        "enabled": bool(cfg.enabled),
        "status": "disabled",
        "message": "Event risk filter disabled",
        "path": cfg.blacklist_csv_path,
        "as_of_date": as_of_date,
        "active_events": 0,
        "excluded_count": 0,
        "excluded_tickers": [],
        "excluded_t1": 0,
        "excluded_swing": 0,
    }

    empty_cols = ["ticker", "mode", "score", "reason", "block_status", "block_reason"]
    excluded_all = pd.DataFrame(columns=empty_cols)

    if not cfg.enabled:
        Path("reports").mkdir(parents=True, exist_ok=True)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
        return plan_t1, plan_swing, info

    try:
        active = _load_event_risk_active(settings=settings, as_of_date=as_of_date or None)
        info["active_events"] = int(len(active))
        if active.empty:
            info["status"] = "ok"
            info["message"] = "No active event-risk entries"
            Path("reports").mkdir(parents=True, exist_ok=True)
            excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
            return plan_t1, plan_swing, info

        ticker_map = (
            active.groupby("ticker", as_index=False)
            .agg(
                block_status=("status", lambda s: "|".join(sorted({str(x) for x in s if str(x)}))),
                block_reason=("reason", lambda s: " ; ".join([str(x).strip() for x in s if str(x).strip()][:3])),
            )
        )
        banned = set(ticker_map["ticker"].tolist())

        filtered_t1 = plan_t1[~plan_t1["ticker"].isin(banned)].copy()
        filtered_swing = plan_swing[~plan_swing["ticker"].isin(banned)].copy()

        ex_t1 = plan_t1[plan_t1["ticker"].isin(banned)].copy()
        ex_swing = plan_swing[plan_swing["ticker"].isin(banned)].copy()
        if not ex_t1.empty:
            ex_t1 = ex_t1.merge(ticker_map, on="ticker", how="left")
        if not ex_swing.empty:
            ex_swing = ex_swing.merge(ticker_map, on="ticker", how="left")
        excluded_all = pd.concat([ex_t1, ex_swing], ignore_index=True, sort=False)
        excluded_all = excluded_all.sort_values(["score"], ascending=False).reset_index(drop=True) if not excluded_all.empty else excluded_all

        Path("reports").mkdir(parents=True, exist_ok=True)
        active.to_csv("reports/event_risk_active.csv", index=False)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)

        excluded_tickers = sorted(set(excluded_all["ticker"].tolist())) if not excluded_all.empty else []
        info.update(
            {
                "status": "ok",
                "message": "Event-risk filter applied",
                "excluded_count": int(len(excluded_all)),
                "excluded_tickers": excluded_tickers,
                "excluded_t1": int(len(ex_t1)),
                "excluded_swing": int(len(ex_swing)),
            }
        )
        return filtered_t1, filtered_swing, info
    except Exception as exc:
        info["status"] = "error"
        info["message"] = str(exc)
        if cfg.fail_on_error:
            raise
        Path("reports").mkdir(parents=True, exist_ok=True)
        excluded_all.to_csv("reports/event_risk_excluded.csv", index=False)
        return plan_t1, plan_swing, info


def _safe_datetime(value: Any) -> datetime | None:
    if value in (None, "", "NaT"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).to_pydatetime()


def _profit_factor_from_returns(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    gross_profit = float(returns[returns > 0].sum())
    gross_loss_abs = float((-returns[returns < 0]).sum())
    if gross_loss_abs <= 1e-12:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss_abs


def _evaluate_market_regime(features: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    regime_cfg = settings.regime
    df = features.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker"]).copy()
    if df.empty:
        return {
            "enabled": bool(regime_cfg.enabled),
            "as_of_date": "",
            "pass": not regime_cfg.enabled,
            "status": "disabled" if not regime_cfg.enabled else "no_data",
            "reason": "Regime disabled" if not regime_cfg.enabled else "No valid feature rows",
            "values": {
                "breadth_ma50_pct": 0.0,
                "breadth_ma20_pct": 0.0,
                "avg_ret20_pct": 0.0,
                "median_atr_pct": 0.0,
                "sample_tickers": 0,
            },
            "thresholds": {
                "min_breadth_ma50_pct": float(regime_cfg.min_breadth_ma50_pct),
                "min_breadth_ma20_pct": float(regime_cfg.min_breadth_ma20_pct),
                "min_avg_ret20_pct": float(regime_cfg.min_avg_ret20_pct),
                "max_median_atr_pct": float(regime_cfg.max_median_atr_pct),
            },
            "checks": {},
        }

    latest_date = pd.Timestamp(df["date"].max())
    latest = df[df["date"] == latest_date].copy()

    ma50_valid = latest.dropna(subset=["close", "ma_50"])
    ma20_valid = latest.dropna(subset=["close", "ma_20"])
    ret20_valid = latest.dropna(subset=["ret_20d"])
    atr_valid = latest.dropna(subset=["atr_pct"])

    breadth_ma50_pct = float((ma50_valid["close"] > ma50_valid["ma_50"]).mean() * 100.0) if len(ma50_valid) else 0.0
    breadth_ma20_pct = float((ma20_valid["close"] > ma20_valid["ma_20"]).mean() * 100.0) if len(ma20_valid) else 0.0
    avg_ret20_pct = float(ret20_valid["ret_20d"].mean() * 100.0) if len(ret20_valid) else 0.0
    median_atr_pct = float(atr_valid["atr_pct"].median()) if len(atr_valid) else 0.0

    checks = {
        "breadth_ma50_ok": breadth_ma50_pct >= float(regime_cfg.min_breadth_ma50_pct),
        "breadth_ma20_ok": breadth_ma20_pct >= float(regime_cfg.min_breadth_ma20_pct),
        "avg_ret20_ok": avg_ret20_pct >= float(regime_cfg.min_avg_ret20_pct),
        "median_atr_ok": median_atr_pct <= float(regime_cfg.max_median_atr_pct),
    }

    if not regime_cfg.enabled:
        regime_pass = True
        status = "disabled"
        reason = "Regime disabled"
    else:
        regime_pass = bool(all(checks.values()))
        status = "risk_on" if regime_pass else "risk_off"
        failed_checks = [k for k, ok in checks.items() if not ok]
        reason = "All regime checks passed" if regime_pass else f"Failed checks: {', '.join(failed_checks)}"

    return {
        "enabled": bool(regime_cfg.enabled),
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "pass": regime_pass,
        "status": status,
        "reason": reason,
        "values": {
            "breadth_ma50_pct": breadth_ma50_pct,
            "breadth_ma20_pct": breadth_ma20_pct,
            "avg_ret20_pct": avg_ret20_pct,
            "median_atr_pct": median_atr_pct,
            "sample_tickers": int(latest["ticker"].nunique()),
        },
        "thresholds": {
            "min_breadth_ma50_pct": float(regime_cfg.min_breadth_ma50_pct),
            "min_breadth_ma20_pct": float(regime_cfg.min_breadth_ma20_pct),
            "min_avg_ret20_pct": float(regime_cfg.min_avg_ret20_pct),
            "max_median_atr_pct": float(regime_cfg.max_median_atr_pct),
        },
        "checks": checks,
    }


def _evaluate_kill_switch(scored_live: pd.DataFrame, costs: BacktestCosts, settings: Settings) -> dict[str, Any]:
    cfg = settings.guardrail
    mode_horizon = {"t1": 1, "swing": 10}
    rolling_trades = max(1, int(cfg.rolling_trades))
    min_trades = max(1, int(cfg.min_rolling_trades))
    min_pf = float(cfg.min_rolling_pf)
    min_expectancy = float(cfg.min_rolling_expectancy)

    modes_payload: dict[str, Any] = {}
    triggered_modes: list[str] = []

    for mode, horizon_days in mode_horizon.items():
        trades = simulate_mode_trades(
            scored_features=scored_live,
            mode=mode,
            horizon_days=horizon_days,
            costs=costs,
        )
        recent = trades.tail(rolling_trades).copy()
        returns = recent["return"].astype(float) if "return" in recent.columns else pd.Series(dtype=float)
        trade_count = int(len(recent))

        rolling_pf = _profit_factor_from_returns(returns)
        rolling_expectancy = float(returns.mean()) if trade_count else 0.0

        triggered = False
        reason = "guardrail_disabled"
        if cfg.kill_switch_enabled:
            if trade_count < min_trades:
                reason = "insufficient_recent_trades"
            else:
                pf_fail = rolling_pf < min_pf
                exp_fail = rolling_expectancy < min_expectancy
                triggered = bool(pf_fail or exp_fail)
                if triggered:
                    failed = []
                    if pf_fail:
                        failed.append("rolling_pf")
                    if exp_fail:
                        failed.append("rolling_expectancy")
                    reason = "triggered_by_" + "_and_".join(failed)
                    triggered_modes.append(mode)
                else:
                    reason = "healthy_recent_performance"

        modes_payload[mode] = {
            "trades_recent": trade_count,
            "rolling_window": rolling_trades,
            "rolling_pf": rolling_pf,
            "rolling_expectancy": rolling_expectancy,
            "triggered": triggered,
            "reason": reason,
        }

    return {
        "enabled": bool(cfg.kill_switch_enabled),
        "thresholds": {
            "rolling_trades": rolling_trades,
            "min_rolling_trades": min_trades,
            "min_rolling_pf": min_pf,
            "min_rolling_expectancy": min_expectancy,
            "cooldown_days": int(cfg.cooldown_days),
        },
        "triggered": bool(triggered_modes),
        "triggered_modes": sorted(triggered_modes),
        "modes": modes_payload,
    }


def _apply_kill_switch_cooldown(
    kill_eval: dict[str, Any],
    settings: Settings,
    as_of_date: str | None,
    persist_state: bool = False,
) -> dict[str, Any]:
    state_path = Path("reports/kill_switch_state.json")
    as_of_dt = _safe_datetime(as_of_date) or datetime.utcnow()
    as_of = as_of_dt.date()

    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    prev_active_modes = sorted({str(x) for x in (previous.get("active_modes") or [])})
    prev_until_dt = _safe_datetime(previous.get("cooldown_until"))
    prev_in_cooldown = bool(prev_until_dt and as_of <= prev_until_dt.date() and prev_active_modes)

    enabled = bool(kill_eval.get("enabled", False))
    triggered_modes = sorted({str(x) for x in (kill_eval.get("triggered_modes") or [])})

    status = "disabled"
    cooldown_until: datetime | None = None
    active_modes: list[str] = []
    if not enabled:
        status = "disabled"
    elif triggered_modes:
        status = "triggered"
        cooldown_until = datetime.combine(as_of, datetime.min.time()) + timedelta(days=max(0, int(settings.guardrail.cooldown_days)))
        active_modes = sorted(set(prev_active_modes if prev_in_cooldown else []).union(triggered_modes))
    elif prev_in_cooldown:
        status = "cooldown"
        cooldown_until = prev_until_dt
        active_modes = prev_active_modes
    else:
        status = "clear"

    payload = {
        "enabled": enabled,
        "status": status,
        "as_of_date": as_of.isoformat(),
        "active": bool(active_modes),
        "active_modes": active_modes,
        "triggered_modes_today": triggered_modes,
        "cooldown_until": cooldown_until.strftime("%Y-%m-%d") if cooldown_until else "",
        "state_path": str(state_path),
    }

    if persist_state:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.utcnow().isoformat(),
                    "as_of_date": as_of.isoformat(),
                    "status": status,
                    "active_modes": active_modes,
                    "cooldown_until": payload["cooldown_until"],
                    "triggered_modes_today": triggered_modes,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

    return payload


def walk_forward_step(settings: Settings) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    scored = score_history_modes(feats, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)
    costs = BacktestCosts(
        buy_fee_pct=settings.backtest.buy_fee_pct,
        sell_fee_pct=settings.backtest.sell_fee_pct,
        slippage_pct=settings.backtest.slippage_pct,
    )
    wf = run_walk_forward(
        scored_features=scored,
        costs=costs,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
        train_days=settings.validation.train_days,
        test_days=settings.validation.test_days,
        step_days=settings.validation.step_days,
        min_train_trades=settings.validation.min_train_trades,
        threshold_grid_t1=settings.validation.threshold_grid_t1,
        threshold_grid_swing=settings.validation.threshold_grid_swing,
    )

    out_path = Path("reports/walk_forward_metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat(),
                "walk_forward": wf,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return wf


def backtest_step(settings: Settings, persist_guardrail_state: bool = False) -> dict[str, Any]:
    feats = pd.read_parquet("data/processed/features.parquet")
    scored_full = score_history_modes(feats, min_avg_volume_20d=settings.pipeline.min_avg_volume_20d)

    # Keep backtest and live policy consistent by applying the same min-score filters.
    scored_live = _apply_live_score_filters(scored_full, settings)

    costs = BacktestCosts(
        buy_fee_pct=settings.backtest.buy_fee_pct,
        sell_fee_pct=settings.backtest.sell_fee_pct,
        slippage_pct=settings.backtest.slippage_pct,
    )
    results = run_backtest(
        scored_live,
        costs=costs,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
    )

    gate_insample = {
        mode: pass_live_gate(
            metrics=metrics,
            profit_factor_min=settings.backtest.profit_factor_min,
            expectancy_min=settings.backtest.expectancy_min,
            max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
            min_trades=settings.backtest.min_trades_for_promotion,
        )
        for mode, metrics in results.items()
    }

    wf = run_walk_forward(
        scored_features=scored_full,
        costs=costs,
        equity_allocation_pct=settings.backtest.equity_allocation_pct,
        train_days=settings.validation.train_days,
        test_days=settings.validation.test_days,
        step_days=settings.validation.step_days,
        min_train_trades=settings.validation.min_train_trades,
        threshold_grid_t1=settings.validation.threshold_grid_t1,
        threshold_grid_swing=settings.validation.threshold_grid_swing,
    )

    wf_modes = wf.get("modes", {})
    wf_summary_t1 = (wf_modes.get("t1", {}) or {}).get("summary", {})
    wf_summary_swing = (wf_modes.get("swing", {}) or {}).get("summary", {})
    wf_n_folds = int(wf.get("n_folds", 0))

    gate_oos = {
        "t1": bool(
            wf_n_folds >= settings.validation.min_folds and
            pass_live_gate(
                metrics=wf_summary_t1,
                profit_factor_min=settings.backtest.profit_factor_min,
                expectancy_min=settings.backtest.expectancy_min,
                max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
                min_trades=settings.validation.min_oos_trades,
            )
        ),
        "swing": bool(
            wf_n_folds >= settings.validation.min_folds and
            pass_live_gate(
                metrics=wf_summary_swing,
                profit_factor_min=settings.backtest.profit_factor_min,
                expectancy_min=settings.backtest.expectancy_min,
                max_drawdown_pct_limit=settings.backtest.max_drawdown_pct_limit,
                min_trades=settings.validation.min_oos_trades,
            )
        ),
    }

    if settings.validation.use_walk_forward_gate:
        gate_model = {
            mode: bool(gate_insample.get(mode, False) and gate_oos.get(mode, False))
            for mode in ["t1", "swing"]
        }
    else:
        gate_model = gate_insample

    regime = _evaluate_market_regime(feats, settings)
    kill_eval = _evaluate_kill_switch(scored_live, costs=costs, settings=settings)
    kill_state = _apply_kill_switch_cooldown(
        kill_eval=kill_eval,
        settings=settings,
        as_of_date=regime.get("as_of_date"),
        persist_state=persist_guardrail_state,
    )

    kill_active_modes = set(kill_state.get("active_modes") or [])
    gate_components = {}
    gate_final = {}
    for mode in ["t1", "swing"]:
        model_ok = bool(gate_model.get(mode, False))
        regime_ok = bool(regime.get("pass", False))
        kill_ok = mode not in kill_active_modes
        final_ok = bool(model_ok and regime_ok and kill_ok)
        gate_components[mode] = {
            "model_gate_ok": model_ok,
            "regime_ok": regime_ok,
            "kill_switch_ok": kill_ok,
            "final_ok": final_ok,
        }
        gate_final[mode] = final_ok

    out_payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "equity_allocation_pct": settings.backtest.equity_allocation_pct,
        "min_live_score_t1": settings.pipeline.min_live_score_t1,
        "min_live_score_swing": settings.pipeline.min_live_score_swing,
        "validation": {
            "use_walk_forward_gate": settings.validation.use_walk_forward_gate,
            "train_days": settings.validation.train_days,
            "test_days": settings.validation.test_days,
            "step_days": settings.validation.step_days,
            "min_folds": settings.validation.min_folds,
            "min_train_trades": settings.validation.min_train_trades,
            "min_oos_trades": settings.validation.min_oos_trades,
        },
        "metrics": results,
        "walk_forward": wf,
        "regime": regime,
        "kill_switch_eval": kill_eval,
        "kill_switch": kill_state,
        "gate_pass_insample": gate_insample,
        "gate_pass_oos": gate_oos,
        "gate_pass_model": gate_model,
        "gate_components": gate_components,
        "gate_pass": gate_final,
    }
    out_path = Path("reports/backtest_metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    wf_path = Path("reports/walk_forward_metrics.json")
    wf_path.write_text(
        json.dumps(
            {
                "generated_at": out_payload["generated_at"],
                "walk_forward": wf,
                "gate_pass_oos": gate_oos,
                "gate_pass_model": gate_model,
                "gate_pass": gate_final,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_payload


def send_telegram_step(settings: Settings, run_id: str, data_status: str | None = None) -> bool:
    signal_path = Path("reports/daily_signal.json")
    if not signal_path.exists():
        return False
    payload = json.loads(signal_path.read_text(encoding="utf-8"))
    signals = payload.get("signals", [])
    top = signals[:3]
    top_lines = [
        f"{row.get('mode', '')}:{row.get('ticker', '')} score={row.get('score', '')} entry={row.get('entry', '')} stop={row.get('stop', '')}"
        for row in top
    ]

    risk_summary = (
        f"risk/trade={settings.risk.risk_per_trade_pct}% | "
        f"max_positions={settings.risk.max_positions} | "
        f"mode_caps=t1:{settings.risk.max_positions_t1},swing:{settings.risk.max_positions_swing} | "
        f"daily_loss_stop={settings.risk.daily_loss_stop_r}R"
    )
    status_line = data_status or f"signals={len(signals)}"
    message = build_daily_message(run_id=run_id, top_lines=top_lines, risk_summary=risk_summary, data_status=status_line)
    return send_telegram_message(
        message=message,
        bot_token_env=settings.notifications.telegram_bot_token_env,
        chat_id_env=settings.notifications.telegram_chat_id_env,
    )


def reconcile_live_step(
    settings: Settings,
    fills_path: str | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    return reconcile_live_signals(
        settings=settings,
        fills_path=fills_path,
        lookback_days=lookback_days,
    )


def run_daily(
    settings: Settings,
    skip_telegram: bool = False,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = JsonRunLogger(run_id=run_id, out_dir="reports")
    try:
        logger.event("INFO", "start_run", command="run-daily")
        universe_update = maybe_auto_update_universe(settings=settings, force=False)
        logger.event("INFO", "universe_update_done", **universe_update)

        ingest_info = ingest_daily(settings)
        logger.event("INFO", "ingest_done", **ingest_info)

        feat_info = compute_features_step(settings)
        logger.event("INFO", "features_done", **feat_info)

        vol_recalibration = maybe_auto_recalibrate_volatility_targets(
            settings=settings,
            settings_path=settings_path,
            force=False,
            features_path=feat_info["out_path"],
        )
        logger.event("INFO", "volatility_recalibration_done", **vol_recalibration)

        event_risk_update = maybe_auto_update_event_risk(settings=settings, force=False)
        logger.event("INFO", "event_risk_update_done", **event_risk_update)

        score_info = score_step(settings)
        top_t1: pd.DataFrame = score_info["top_t1"]
        top_swing: pd.DataFrame = score_info["top_swing"]
        event_risk_info = score_info.get("event_risk", {})
        logger.event("INFO", "event_risk_filtered", **event_risk_info)

        shadow_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Model v2 shadow mode disabled",
        }
        if settings.model_v2.enabled and settings.model_v2.shadow_mode:
            try:
                feats_for_shadow = pd.read_parquet(feat_info["out_path"])
                scored_hist_shadow = score_history_modes(
                    feats_for_shadow,
                    min_avg_volume_20d=settings.pipeline.min_avg_volume_20d,
                )
                shadow_info = run_model_v2_shadow(
                    settings=settings,
                    scored_history=scored_hist_shadow,
                    candidates=score_info.get("combined_plan", pd.DataFrame()),
                    run_id=run_id,
                )
                logger.event("INFO", "model_v2_shadow_done", **shadow_info)
            except Exception as exc:
                shadow_info = {
                    "status": "error",
                    "message": str(exc),
                }
                logger.event("WARN", "model_v2_shadow_failed", error=str(exc))

        promotion_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Model v2 promotion disabled",
            "live_active": False,
            "rollout_pct": 0,
        }
        if settings.model_v2.enabled and settings.model_v2.promotion.enabled:
            try:
                promotion_info = evaluate_and_update_model_v2_promotion(settings)
                logger.event("INFO", "model_v2_promotion_evaluated", **promotion_info)
            except Exception as exc:
                promotion_info = {
                    "status": "error",
                    "message": str(exc),
                    "live_active": False,
                    "rollout_pct": 0,
                }
                logger.event("WARN", "model_v2_promotion_failed", error=str(exc))

        risk_summary = {
            "risk_per_trade_pct": settings.risk.risk_per_trade_pct,
            "max_positions": settings.risk.max_positions,
            "max_positions_t1": settings.risk.max_positions_t1,
            "max_positions_swing": settings.risk.max_positions_swing,
            "execution_mode_priority": settings.risk.execution_mode_priority,
            "daily_loss_stop_r": settings.risk.daily_loss_stop_r,
            "vol_target_enabled": settings.risk.volatility_targeting_enabled,
            "vol_target_ref_atr_pct": settings.risk.volatility_reference_atr_pct,
            "vol_target_ref_realized_pct": settings.risk.volatility_reference_realized_pct,
            "vol_target_mode": settings.risk.volatility_targeting_mode,
            "vol_target_realized_weight": settings.risk.volatility_realized_weight,
            "vol_target_cap_base": settings.risk.volatility_cap_multiplier,
            "vol_target_regime_cap_enabled": settings.risk.volatility_market_regime_cap_enabled,
            "vol_target_regime_cap_high": settings.risk.volatility_market_regime_high_max_mult,
            "vol_target_regime_cap_stress": settings.risk.volatility_market_regime_stress_max_mult,
            "max_position_exposure_pct": settings.risk.max_position_exposure_pct,
        }
        report_path = render_html_report(
            top_t1=top_t1,
            top_swing=top_swing,
            out_path="reports/daily_report.html",
            run_id=run_id,
            data_source=ingest_info["source"],
            max_data_date=ingest_info["max_data_date"],
            universe_name="LQ45+IDX30",
            risk_summary=risk_summary,
        )
        logger.event("INFO", "report_done", report_path=report_path, signal_path=score_info["signal_path"])

        bt = backtest_step(settings, persist_guardrail_state=True)
        logger.event(
            "INFO",
            "backtest_done",
            metrics=bt.get("metrics", {}),
            gate_pass=bt.get("gate_pass", {}),
            regime=bt.get("regime", {}),
            kill_switch=bt.get("kill_switch", {}),
        )

        gate_pass = bt.get("gate_pass", {})
        allowed_modes = sorted([mode for mode, ok in gate_pass.items() if bool(ok)])
        filtered_combined = pd.DataFrame()
        filtered_execution = pd.DataFrame()
        signal_cols = [
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
            "shadow_p_win",
            "shadow_expected_r",
            "shadow_threshold",
            "shadow_recommended",
            "model_v2_live_selected",
            "model_v2_rollout_pct",
        ]
        signal_df = pd.DataFrame(columns=signal_cols)
        rollout_info: dict[str, Any] = {
            "status": "not_applied",
            "message": "Rollout not evaluated",
            "rollout_pct": int(promotion_info.get("rollout_pct", 0) or 0),
            "live_active": bool(promotion_info.get("live_active", False)),
        }
        if not allowed_modes:
            empty_signals = pd.DataFrame(
                columns=signal_cols
            )
            write_signal_json(empty_signals, "reports/daily_signal.json")
            pd.DataFrame(columns=empty_signals.columns).to_csv("reports/execution_plan.csv", index=False)
            rollout_info = {
                "status": "blocked_by_gate",
                "message": "Live gate blocked all modes",
                "rollout_pct": int(promotion_info.get("rollout_pct", 0) or 0),
                "live_active": bool(promotion_info.get("live_active", False)),
                "selected_count": 0,
            }
            logger.event(
                "WARN",
                "live_gate_blocked",
                gate_pass=gate_pass,
                gate_components=bt.get("gate_components", {}),
                regime=bt.get("regime", {}),
                kill_switch=bt.get("kill_switch", {}),
            )
        else:
            combined_plan: pd.DataFrame = score_info["combined_plan"]
            execution_plan: pd.DataFrame = score_info["execution_plan"]

            filtered_combined = combined_plan[combined_plan["mode"].isin(allowed_modes)].copy()
            filtered_execution = execution_plan[execution_plan["mode"].isin(allowed_modes)].copy()

            # Promotion gate applies only after base risk/model gates have passed.
            if settings.model_v2.enabled and settings.model_v2.promotion.enabled:
                try:
                    filtered_combined, promoted_selection, rollout_info = apply_model_v2_rollout_selection(
                        filtered_combined=filtered_combined,
                        settings=settings,
                        promotion_info=promotion_info,
                        shadow_csv_path=shadow_info.get("shadow_csv_path", ""),
                    )
                    if bool(promotion_info.get("live_active", False)):
                        filtered_execution = promoted_selection.copy()
                        signal_df = filtered_execution[[c for c in signal_cols if c in filtered_execution.columns]].copy()
                    else:
                        signal_df = filtered_combined[[c for c in signal_cols if c in filtered_combined.columns]].copy()
                except Exception as exc:
                    rollout_info = {
                        "status": "error",
                        "message": str(exc),
                        "rollout_pct": int(promotion_info.get("rollout_pct", 0) or 0),
                        "live_active": bool(promotion_info.get("live_active", False)),
                    }
                    logger.event("WARN", "model_v2_rollout_failed", error=str(exc))
                    signal_df = filtered_combined[[c for c in signal_cols if c in filtered_combined.columns]].copy()
            else:
                signal_df = filtered_combined[[c for c in signal_cols if c in filtered_combined.columns]].copy()

            filtered_combined.to_csv("reports/daily_report.csv", index=False)
            filtered_execution.to_csv("reports/execution_plan.csv", index=False)
            write_signal_json(signal_df, "reports/daily_signal.json")
            logger.event(
                "INFO",
                "live_gate_modes_allowed",
                allowed_modes=allowed_modes,
                signal_count=int(len(signal_df)),
                rollout=rollout_info,
            )

        snapshot_info: dict[str, Any] = {"status": "ok", "path": "", "signal_count": int(len(signal_df))}
        try:
            snapshot_path = write_signal_snapshot(
                run_id=run_id,
                signals=signal_df,
                out_dir=settings.reconciliation.signal_snapshot_dir,
            )
            snapshot_info["path"] = snapshot_path
            logger.event("INFO", "signal_snapshot_written", path=snapshot_path, signal_count=int(len(signal_df)))
        except Exception as exc:
            snapshot_info = {"status": "error", "path": "", "signal_count": int(len(signal_df)), "message": str(exc)}
            logger.event("WARN", "signal_snapshot_failed", error=str(exc))
            if settings.reconciliation.fail_on_error:
                raise

        reconciliation_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Live reconciliation disabled",
        }
        if settings.reconciliation.enabled and settings.reconciliation.auto_reconcile_on_run_daily:
            try:
                reconciliation_info = reconcile_live_step(settings=settings)
                logger.event(
                    "INFO",
                    "live_reconciliation_done",
                    status=reconciliation_info.get("status", ""),
                    message=reconciliation_info.get("message", ""),
                    json_path=reconciliation_info.get("json_path", ""),
                    details_csv_path=reconciliation_info.get("details_csv_path", ""),
                )
            except Exception as exc:
                reconciliation_info = {"status": "error", "message": str(exc)}
                logger.event("WARN", "live_reconciliation_failed", error=str(exc))
                if settings.reconciliation.fail_on_error:
                    raise
        elif settings.reconciliation.enabled:
            reconciliation_info = {
                "status": "skipped_auto_disabled",
                "message": "Auto reconciliation on run-daily disabled",
            }

        pre_gate_df: pd.DataFrame = score_info.get("combined_plan", pd.DataFrame())
        post_gate_df: pd.DataFrame = filtered_combined
        pre_by_mode: dict[str, int] = {}
        post_by_mode: dict[str, int] = {}
        if not pre_gate_df.empty and "mode" in pre_gate_df.columns:
            pre_by_mode = {str(k): int(v) for k, v in pre_gate_df["mode"].value_counts().to_dict().items()}
        if not post_gate_df.empty and "mode" in post_gate_df.columns:
            post_by_mode = {str(k): int(v) for k, v in post_gate_df["mode"].value_counts().to_dict().items()}

        live_funnel_payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "gate_pass": gate_pass,
            "allowed_modes": allowed_modes,
            "pre_gate": {
                "combined_plan_count": int(len(pre_gate_df)),
                "execution_plan_count": int(len(score_info.get("execution_plan", pd.DataFrame()))),
                "signal_count": int(len(pre_gate_df)),
                "by_mode": pre_by_mode,
            },
            "post_gate": {
                "combined_plan_count": int(len(filtered_combined)),
                "execution_plan_count": int(len(filtered_execution)),
                "signal_count": int(len(signal_df)),
                "by_mode": post_by_mode,
            },
            "status": {
                "regime": bt.get("regime", {}).get("status", ""),
                "kill_switch": bt.get("kill_switch", {}).get("status", ""),
            },
        }
        if "signal_funnel" in score_info:
            live_funnel_payload["score_funnel"] = score_info["signal_funnel"]
        live_funnel_path = _write_json("reports/signal_funnel_live.json", live_funnel_payload)
        logger.event("INFO", "signal_funnel_written", path=live_funnel_path, post_gate_signals=int(len(signal_df)))

        telegram_ok: bool | None = None
        if not skip_telegram:
            signal_count = 0
            signal_path = Path("reports/daily_signal.json")
            if signal_path.exists():
                payload = json.loads(signal_path.read_text(encoding="utf-8"))
                signal_count = len(payload.get("signals", []))
            status = (
                f"source={ingest_info['source']} | max_date={ingest_info['max_data_date']} "
                f"| signals={signal_count} | regime={bt.get('regime', {}).get('status', '-')} "
                f"| kill={bt.get('kill_switch', {}).get('status', '-')} "
                f"| vol_recalib={vol_recalibration.get('status', '-')} "
                f"| event_upd={event_risk_update.get('status', '-')} "
                f"| event_excl={event_risk_info.get('excluded_count', 0)}"
            )
            telegram_ok = send_telegram_step(settings, run_id=run_id, data_status=status)
            logger.event("INFO", "telegram_done", ok=telegram_ok)
        else:
            logger.event("INFO", "telegram_skipped", ok=None)

        weekly_kpi_info: dict[str, Any] = {
            "status": "disabled",
            "message": "Coaching dashboard disabled",
        }
        beginner_note_path = ""
        if settings.coaching.enabled:
            try:
                weekly_kpi_info = generate_weekly_kpi_dashboard(settings)
                logger.event("INFO", "weekly_kpi_generated", **weekly_kpi_info)
            except Exception as exc:
                weekly_kpi_info = {"status": "error", "message": str(exc)}
                logger.event("WARN", "weekly_kpi_failed", error=str(exc))

            try:
                if not allowed_modes:
                    coach_status = "NO_TRADE"
                    coach_reason = "Mode blocked by risk gate"
                elif signal_df.empty:
                    coach_status = "NO_SIGNAL"
                    coach_reason = "No executable signal after filters"
                else:
                    coach_status = "SUCCESS"
                    coach_reason = "Trade candidates available"
                beginner_note_path = write_beginner_coaching_note(
                    out_path=settings.coaching.beginner_note_path,
                    run_id=run_id,
                    status=coach_status,
                    action_reason=coach_reason,
                    signals=signal_df,
                )
                logger.event("INFO", "beginner_coaching_written", path=beginner_note_path)
            except Exception as exc:
                logger.event("WARN", "beginner_coaching_failed", error=str(exc))

        return {
            "run_id": run_id,
            "report_path": report_path,
            "signal_path": score_info["signal_path"],
            "telegram_ok": telegram_ok,
            "backtest": bt,
            "event_risk": event_risk_info,
            "event_risk_update": event_risk_update,
            "volatility_recalibration": vol_recalibration,
            "universe_update": universe_update,
            "model_v2_shadow": shadow_info,
            "model_v2_promotion": promotion_info,
            "model_v2_rollout": rollout_info,
            "weekly_kpi": weekly_kpi_info,
            "beginner_note_path": beginner_note_path,
            "signal_snapshot": snapshot_info,
            "live_reconciliation": reconciliation_info,
        }
    except Exception as exc:
        logger.event("ERROR", "run_failed", error=str(exc))
        raise
    finally:
        log_path = logger.save()
        print(f"[run-log] {log_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IDX Trading Lab CLI")
    parser.add_argument("--settings", default="config/settings.json", help="Path to runtime settings JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest-daily", help="Ingest daily prices from provider")
    p_ingest.add_argument("--start-date", default=None)
    p_ingest.add_argument("--end-date", default=None)
    p_ingest.add_argument("--no-merge", action="store_true")

    p_backfill = sub.add_parser("backfill-history", help="Backfill 1-2+ years historical prices")
    p_backfill.add_argument("--years", type=int, default=2)
    p_backfill.add_argument("--end-date", default=None)

    p_uni = sub.add_parser("update-universe", help="Update LQ45/IDX30 universe using configured sources")
    p_uni.add_argument("--force", action="store_true", help="Ignore interval and force update attempt")
    p_event = sub.add_parser("update-event-risk", help="Update event-risk blacklist using configured sources")
    p_event.add_argument("--force", action="store_true", help="Ignore interval and force update attempt")
    p_recal = sub.add_parser(
        "recalibrate-volatility",
        help="Auto-recalibrate volatility reference targets using recent feature history",
    )
    p_recal.add_argument("--force", action="store_true", help="Ignore interval and force recalibration attempt")

    sub.add_parser("compute-features", help="Compute features and save parquet")
    sub.add_parser("score", help="Score T+1 and Swing picks, write reports/daily_signal.json")
    sub.add_parser("backtest", help="Run bar-based backtest on scored history")
    sub.add_parser("walk-forward", help="Run walk-forward out-of-sample validation")
    sub.add_parser("model-v2-promotion", help="Evaluate model_v2 promotion state (step-up / rollback)")
    p_recon = sub.add_parser("reconcile-live", help="Reconcile live fills vs signal snapshots and generate KPI report")
    p_recon.add_argument("--fills-path", default=None, help="Optional CSV path for broker fills")
    p_recon.add_argument("--lookback-days", type=int, default=None, help="Optional lookback override")

    p_notify = sub.add_parser("send-telegram", help="Send Telegram summary")
    p_notify.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))

    p_run = sub.add_parser("run-daily", help="Execute full daily pipeline")
    p_run.add_argument("--skip-telegram", action="store_true")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    settings = load_settings(args.settings)

    if args.command == "ingest-daily":
        out = ingest_daily(
            settings,
            start_date=args.start_date,
            end_date=args.end_date,
            merge_existing=not args.no_merge,
        )
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "backfill-history":
        out = backfill_history(settings, years=args.years, end_date=args.end_date)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "update-universe":
        out = maybe_auto_update_universe(settings=settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "update-event-risk":
        out = maybe_auto_update_event_risk(settings=settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "recalibrate-volatility":
        out = maybe_auto_recalibrate_volatility_targets(settings=settings, settings_path=args.settings, force=args.force)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "compute-features":
        out = compute_features_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "score":
        out = score_step(settings)
        print(json.dumps({"signal_path": out["signal_path"]}, ensure_ascii=True, indent=2))
        return
    if args.command == "backtest":
        out = backtest_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "walk-forward":
        out = walk_forward_step(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "model-v2-promotion":
        out = evaluate_and_update_model_v2_promotion(settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "reconcile-live":
        out = reconcile_live_step(settings, fills_path=args.fills_path, lookback_days=args.lookback_days)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return
    if args.command == "send-telegram":
        ok = send_telegram_step(settings, run_id=args.run_id)
        print(json.dumps({"ok": ok}, ensure_ascii=True, indent=2))
        return
    if args.command == "run-daily":
        out = run_daily(settings, skip_telegram=args.skip_telegram, settings_path=args.settings)
        print(json.dumps(out, ensure_ascii=True, indent=2))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
