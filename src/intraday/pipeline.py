from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.features.compute_features import compute_features
from src.ingest.load_prices import load_intraday_from_provider
from src.report.render_report import write_signal_json
from src.risk.manager import apply_global_position_limit, propose_trade_plan
from src.strategy.intraday_model import score_intraday_candidates


def _ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _load_universe(path: str) -> list[str]:
    universe = pd.read_csv(path)
    if "ticker" not in universe.columns:
        raise ValueError("Universe file must contain 'ticker' column")
    return sorted(universe["ticker"].astype(str).str.upper().str.strip().unique().tolist())


def _merge_with_existing_intraday(
    out_path: str,
    incoming: pd.DataFrame,
    timeframe: str,
    max_rows_per_ticker: int,
) -> pd.DataFrame:
    path = Path(out_path)
    if not path.exists():
        out = incoming.sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    else:
        existing = pd.read_csv(path)
        if "timestamp" not in existing.columns and "date" in existing.columns:
            existing = existing.rename(columns={"date": "timestamp"})
        existing["timestamp"] = pd.to_datetime(existing["timestamp"], errors="coerce")
        if "timeframe" not in existing.columns:
            existing["timeframe"] = timeframe
        if "source" not in existing.columns:
            existing["source"] = "existing_csv"
        if "ingested_at" not in existing.columns:
            existing["ingested_at"] = datetime.utcnow().isoformat()
        keep_cols = ["timestamp", "ticker", "open", "high", "low", "close", "volume", "timeframe", "source", "ingested_at"]
        for col in keep_cols:
            if col not in existing.columns:
                existing[col] = None
        existing = existing[keep_cols].copy()
        merged = pd.concat([existing, incoming], ignore_index=True, sort=False)
        merged = merged.sort_values(["ticker", "timestamp", "ingested_at"])
        merged = merged.drop_duplicates(subset=["ticker", "timestamp", "timeframe"], keep="last")
        out = merged.reset_index(drop=True)

    if max_rows_per_ticker > 0 and not out.empty:
        out = out.sort_values(["ticker", "timestamp"]).groupby("ticker", as_index=False, group_keys=False).tail(max_rows_per_ticker)
        out = out.reset_index(drop=True)
    return out


def ingest_intraday_step(
    settings: Settings,
    timeframe: str | None = None,
    lookback_minutes: int | None = None,
    merge_existing: bool = True,
) -> dict[str, Any]:
    cfg = settings.data.intraday
    tf = str(timeframe or cfg.timeframe).strip().lower()
    tickers = _load_universe(settings.data.universe_csv_path)
    prices, source = load_intraday_from_provider(
        settings=settings,
        timeframe=tf,
        lookback_minutes=lookback_minutes,
        tickers=tickers,
    )
    prices = prices[prices["ticker"].isin(tickers)].sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    out_path = cfg.canonical_prices_path
    _ensure_parent(out_path)
    to_save = (
        _merge_with_existing_intraday(
            out_path=out_path,
            incoming=prices,
            timeframe=tf,
            max_rows_per_ticker=max(100, int(cfg.max_rows_per_ticker)),
        )
        if merge_existing
        else prices
    )
    to_save.to_csv(out_path, index=False)
    max_ts = pd.to_datetime(to_save["timestamp"], errors="coerce").max() if not to_save.empty else None
    min_ts = pd.to_datetime(to_save["timestamp"], errors="coerce").min() if not to_save.empty else None
    return {
        "rows": len(to_save),
        "rows_new": len(prices),
        "tickers": int(to_save["ticker"].nunique()) if not to_save.empty else 0,
        "source": source,
        "timeframe": tf,
        "max_timestamp": pd.Timestamp(max_ts).isoformat() if pd.notna(max_ts) else "",
        "min_timestamp": pd.Timestamp(min_ts).isoformat() if pd.notna(min_ts) else "",
        "out_path": out_path,
    }


def compute_intraday_features_step(settings: Settings) -> dict[str, Any]:
    cfg = settings.data.intraday
    prices = pd.read_csv(cfg.canonical_prices_path)
    if prices.empty:
        raise ValueError("No intraday bars available")
    if "timestamp" not in prices.columns and "date" in prices.columns:
        prices = prices.rename(columns={"date": "timestamp"})
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], errors="coerce")
    prices = prices.dropna(subset=["timestamp", "ticker"]).copy()
    timeframe = str(prices["timeframe"].iloc[0]) if "timeframe" in prices.columns and not prices.empty else cfg.timeframe

    base = prices.rename(columns={"timestamp": "date"})
    min_bars = 20
    ticker_counts = base.groupby("ticker").size()
    eligible_tickers = ticker_counts[ticker_counts >= min_bars].index.tolist()
    skipped_tickers = sorted([t for t in ticker_counts.index.tolist() if t not in set(eligible_tickers)])

    if not eligible_tickers:
        feats = pd.DataFrame(
            columns=[
                "timestamp",
                "ticker",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ret_1d",
                "ret_5d",
                "ret_20d",
                "ma_20",
                "ma_50",
                "ma_200",
                "vol_20d",
                "avg_vol_20d",
                "turnover",
                "turnover_20d",
                "rsi_14",
                "atr_14",
                "atr_pct",
                "timeframe",
            ]
        )
    else:
        base_eligible = base[base["ticker"].isin(eligible_tickers)].copy()
        feats = compute_features(base_eligible)
        feats = feats.rename(columns={"date": "timestamp"})
        feats["timeframe"] = timeframe

    out_path = "data/processed/features_intraday.parquet"
    _ensure_parent(out_path)
    feats.to_parquet(out_path, index=False)
    return {
        "rows": len(feats),
        "out_path": out_path,
        "timeframe": timeframe,
        "eligible_tickers": int(len(eligible_tickers)),
        "skipped_tickers": skipped_tickers[:20],
        "min_bars_per_ticker": min_bars,
    }


def score_intraday_step(settings: Settings) -> dict[str, Any]:
    cfg = settings.data.intraday
    feats = pd.read_parquet("data/processed/features_intraday.parquet")
    picks_raw = score_intraday_candidates(
        features=feats,
        min_avg_volume_20bars=float(cfg.min_avg_volume_20bars),
        top_n=int(cfg.top_n),
    )
    plan = propose_trade_plan(picks_raw, settings.risk)
    before_score = int(len(plan))
    min_score = float(cfg.min_live_score)
    if "score" in plan.columns:
        plan = plan[plan["score"] >= min_score].copy()
    after_score = int(len(plan))

    lot_size = int(settings.risk.position_lot)
    before_size = int(len(plan))
    if "size" in plan.columns:
        plan = plan[plan["size"] >= lot_size].copy()
    after_size = int(len(plan))

    mode_caps = {"intraday": int(settings.risk.max_positions_swing)}
    execution_plan = apply_global_position_limit(
        plan,
        max_positions=int(settings.risk.max_positions),
        max_positions_by_mode=mode_caps,
        mode_priority=["intraday", "swing", "t1"],
    )

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    plan.to_csv(reports_dir / "intraday_top.csv", index=False)
    execution_plan.to_csv(reports_dir / "intraday_execution_plan.csv", index=False)

    signal_cols = ["ticker", "mode", "score", "entry", "stop", "tp1", "tp2", "size", "reason", "timestamp", "timeframe"]
    signal_df = plan[[c for c in signal_cols if c in plan.columns]].copy()
    signal_path = write_signal_json(signal_df, str(reports_dir / "intraday_signal.json"))
    funnel = {
        "generated_at": datetime.utcnow().isoformat(),
        "timeframe": cfg.timeframe,
        "thresholds": {
            "min_live_score": min_score,
            "position_lot": lot_size,
            "max_positions": int(settings.risk.max_positions),
            "max_positions_intraday": int(settings.risk.max_positions_swing),
        },
        "counts": {
            "rank_candidates": int(len(picks_raw)),
            "before_score_filter": before_score,
            "after_score_filter": after_score,
            "before_size_filter": before_size,
            "after_size_filter": after_size,
            "execution_plan_count": int(len(execution_plan)),
            "signal_count": int(len(signal_df)),
        },
    }
    funnel_path = reports_dir / "intraday_signal_funnel.json"
    funnel_path.write_text(json.dumps(funnel, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "top": plan,
        "execution_plan": execution_plan,
        "signal_path": signal_path,
        "funnel_path": str(funnel_path),
        "funnel": funnel,
    }


def run_intraday_once(
    settings: Settings,
    lookback_minutes: int | None = None,
) -> dict[str, Any]:
    cfg = settings.data.intraday
    ingest = ingest_intraday_step(settings=settings, timeframe=cfg.timeframe, lookback_minutes=lookback_minutes, merge_existing=True)
    features = compute_intraday_features_step(settings=settings)
    score = score_intraday_step(settings=settings)
    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "timeframe": cfg.timeframe,
        "ingest": ingest,
        "features": features,
        "signals": {
            "signal_path": score["signal_path"],
            "execution_count": int(len(score["execution_plan"])),
            "signal_count": int(len(score["top"])),
        },
        "funnel_path": score["funnel_path"],
    }
    status_path = Path("reports/intraday_status.json")
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    return out
