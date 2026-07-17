from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.analytics.signal_accuracy import (
    _bar_lookup,
    _calibration_summary,
    _candidate_signals,
    _false_positive_summary,
    _records,
    _signal_decay_summary,
    _simulate_signal,
    _summarize_trades,
    _volatility_bucket,
)
from src.config import Settings
from src.model_v2.predict import infer_shadow_scores
from src.utils import atomic_write_json


def _bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _group_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    columns = [
        *group_cols,
        "candidate_count",
        "v1_live_count",
        "v2_recommended_count",
        "v2_recommended_rate_pct",
        "all_precision_pct",
        "all_expectancy_r",
        "all_profit_factor_r",
        "v2_precision_pct",
        "v2_expectancy_r",
        "v2_profit_factor_r",
        "v2_avg_mae_r",
        "v2_avg_mfe_r",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for key, grp in df.groupby(group_cols, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = {col: str(value) for col, value in zip(group_cols, key_tuple)}
        all_summary = _summarize_trades(grp)
        v2_grp = grp[_bool_series(grp.get("v2_recommended", pd.Series(index=grp.index, dtype=bool)))].copy()
        v2_summary = _summarize_trades(v2_grp)
        row.update(
            {
                "candidate_count": int(len(grp)),
                "v1_live_count": int(_bool_series(grp.get("passes_live_threshold", pd.Series(index=grp.index, dtype=bool))).sum()),
                "v2_recommended_count": int(len(v2_grp)),
                "v2_recommended_rate_pct": round((len(v2_grp) / max(len(grp), 1)) * 100.0, 2),
                "all_precision_pct": all_summary.get("precision_pct", 0.0),
                "all_expectancy_r": all_summary.get("expectancy_r", 0.0),
                "all_profit_factor_r": all_summary.get("profit_factor_r", 0.0),
                "v2_precision_pct": v2_summary.get("precision_pct", 0.0),
                "v2_expectancy_r": v2_summary.get("expectancy_r", 0.0),
                "v2_profit_factor_r": v2_summary.get("profit_factor_r", 0.0),
                "v2_avg_mae_r": v2_summary.get("avg_mae_r", 0.0),
                "v2_avg_mfe_r": v2_summary.get("avg_mfe_r", 0.0),
            }
        )
        rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["v2_expectancy_r", "v2_profit_factor_r", "v2_recommended_count"], ascending=[True, True, False])
    return out.reset_index(drop=True)


def _precision_at_k(df: pd.DataFrame, top_k: list[int]) -> dict[str, Any]:
    if df.empty:
        return {"combined": [], "by_mode": {}}
    ranked = df.sort_values(["date", "mode", "shadow_expected_r", "shadow_p_win", "score"], ascending=[True, True, False, False, False]).copy()
    modes = sorted(ranked["mode"].dropna().astype(str).unique().tolist())

    def _one(source: pd.DataFrame, k: int) -> dict[str, Any]:
        top = source.groupby(["date", "mode"], dropna=False).head(int(k)).copy()
        summary = _summarize_trades(top)
        return {
            "k": int(k),
            "sample_count": int(summary.get("trade_count", 0)),
            "precision_pct": float(summary.get("precision_pct", 0.0)),
            "expectancy_r": float(summary.get("expectancy_r", 0.0)),
            "profit_factor_r": float(summary.get("profit_factor_r", 0.0)),
        }

    return {
        "combined": [_one(ranked, int(k)) for k in top_k],
        "by_mode": {
            mode: [_one(ranked[ranked["mode"] == mode].copy(), int(k)) for k in top_k]
            for mode in modes
        },
    }


def _threshold_candidates(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    grid = sorted({float(value) for value in settings.model_v2_accuracy.probability_threshold_grid})
    for mode, mode_df in df.groupby("mode", dropna=False):
        mode_name = str(mode)
        source_count = int(len(mode_df))
        for threshold in grid:
            selected = mode_df[_numeric(mode_df["shadow_p_win"]) >= threshold].copy()
            summary = _summarize_trades(selected)
            rows.append(
                {
                    "mode": mode_name,
                    "threshold": threshold,
                    "trade_count": int(summary.get("trade_count", 0)),
                    "selection_rate_pct": round((len(selected) / max(source_count, 1)) * 100.0, 2),
                    "precision_pct": summary.get("precision_pct", 0.0),
                    "expectancy_r": summary.get("expectancy_r", 0.0),
                    "profit_factor_r": summary.get("profit_factor_r", 0.0),
                    "avg_win_r": summary.get("avg_win_r", 0.0),
                    "avg_loss_r": summary.get("avg_loss_r", 0.0),
                    "avg_mae_r": summary.get("avg_mae_r", 0.0),
                    "avg_mfe_r": summary.get("avg_mfe_r", 0.0),
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["mode", "expectancy_r", "profit_factor_r", "trade_count"], ascending=[True, False, False, False])
    return out.reset_index(drop=True)


def _best_thresholds(thresholds: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    if thresholds.empty:
        return {}
    best: dict[str, Any] = {}
    min_trades = int(settings.model_v2_accuracy.min_trades_per_segment)
    for mode, grp in thresholds.groupby("mode", dropna=False):
        eligible = grp[_numeric(grp["trade_count"]) >= min_trades].copy()
        if eligible.empty:
            best[str(mode)] = {}
            continue
        eligible = eligible.sort_values(["expectancy_r", "profit_factor_r", "precision_pct", "trade_count"], ascending=[False, False, False, False])
        best[str(mode)] = _records(eligible.head(1))[0]
    return best


def _selection_comparison(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "v1_baseline": _summarize_trades(pd.DataFrame()),
            "v2_recommended": _summarize_trades(pd.DataFrame()),
            "overlap": _summarize_trades(pd.DataFrame()),
            "v1_only": _summarize_trades(pd.DataFrame()),
            "v2_only": _summarize_trades(pd.DataFrame()),
            "overlap_count": 0,
        }

    v1_mask = _bool_series(df.get("passes_live_threshold", pd.Series(index=df.index, dtype=bool)))
    v2_mask = _bool_series(df.get("v2_recommended", pd.Series(index=df.index, dtype=bool)))
    overlap = df[v1_mask & v2_mask].copy()
    return {
        "v1_baseline": _summarize_trades(df[v1_mask].copy()),
        "v2_recommended": _summarize_trades(df[v2_mask].copy()),
        "overlap": _summarize_trades(overlap),
        "v1_only": _summarize_trades(df[v1_mask & ~v2_mask].copy()),
        "v2_only": _summarize_trades(df[v2_mask & ~v1_mask].copy()),
        "overlap_count": int(len(overlap)),
        "v1_count": int(v1_mask.sum()),
        "v2_count": int(v2_mask.sum()),
    }


def _model_source_summary(df: pd.DataFrame, infer_info: dict[str, Any]) -> dict[str, Any]:
    sources = {}
    if not df.empty and "shadow_model_source" in df.columns:
        sources = {str(k): int(v) for k, v in df["shadow_model_source"].value_counts(dropna=False).to_dict().items()}
    mode_sources = {}
    for mode, payload in (infer_info.get("modes", {}) or {}).items():
        if isinstance(payload, dict):
            mode_sources[str(mode)] = {
                "source": str(payload.get("source", "")),
                "rows": int(payload.get("rows", 0) or 0),
                "threshold": payload.get("threshold"),
            }
    non_model_sources = [
        str(source)
        for source in sources.keys()
        if str(source).strip().lower() != "model"
    ]
    return {
        "candidate_sources": sources,
        "mode_sources": mode_sources,
        "has_fallback": bool(any(str(source).lower() == "fallback" for source in sources.keys())),
        "has_non_model": bool(non_model_sources),
        "non_model_sources": non_model_sources,
    }


def _build_v2_trade_rows(features: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, dict[str, Any], int]:
    cfg = settings.model_v2_accuracy
    max_rank = max([int(k) for k in cfg.precision_top_k] + [int(cfg.max_candidates_per_day), 1])
    candidates = _candidate_signals(features, settings, max_rank=max_rank)
    if candidates.empty:
        return pd.DataFrame(), {"status": "empty", "message": "No scored candidates", "modes": {}}, 0

    shadow_df, infer_info = infer_shadow_scores(candidates=candidates, settings=settings)
    if shadow_df.empty:
        return pd.DataFrame(), infer_info, int(len(candidates))

    shadow_df = shadow_df.copy()
    shadow_df["date"] = pd.to_datetime(shadow_df["date"], errors="coerce")
    shadow_df["mode"] = shadow_df["mode"].astype(str).str.lower().str.strip()
    shadow_df["ticker"] = shadow_df["ticker"].astype(str).str.upper().str.strip()
    shadow_df = shadow_df.sort_values(
        ["date", "mode", "shadow_expected_r", "shadow_p_win", "score"],
        ascending=[True, True, False, False, False],
    ).copy()
    shadow_df["v2_rank"] = shadow_df.groupby(["date", "mode"], dropna=False).cumcount() + 1

    bars = _bar_lookup(features)
    rows: list[dict[str, Any]] = []
    for _, signal in shadow_df.iterrows():
        outcome = _simulate_signal(signal, bars_by_ticker=bars, settings=settings)
        if outcome is None:
            continue
        outcome.update(
            {
                "v1_rank": int(signal.get("rank", 0) or 0),
                "v2_rank": int(signal.get("v2_rank", 0) or 0),
                "shadow_p_win": float(signal.get("shadow_p_win", 0.0) or 0.0),
                "shadow_expected_r": float(signal.get("shadow_expected_r", 0.0) or 0.0),
                "shadow_threshold": float(signal.get("shadow_threshold", 0.0) or 0.0),
                "v2_recommended": bool(signal.get("shadow_recommended", False)),
                "shadow_model_source": str(signal.get("shadow_model_source", "unknown")),
                "shadow_market_regime": str(signal.get("shadow_market_regime", "")),
            }
        )
        rows.append(outcome)

    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades, infer_info, int(len(candidates))
    if "regime_status" not in trades.columns:
        trades["regime_status"] = trades["shadow_market_regime"].replace("", "unknown")
    trades["regime_status"] = trades["regime_status"].fillna("unknown")
    trades["volatility_bucket"] = _volatility_bucket(trades["atr_pct"]).astype(str)
    return trades, infer_info, int(len(candidates))


def generate_model_v2_accuracy_audit(features: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    cfg = settings.model_v2_accuracy
    out_json = Path(cfg.output_json_path)
    by_ticker_path = Path(cfg.by_ticker_path)
    by_regime_path = Path(cfg.by_regime_path)
    threshold_path = Path(cfg.threshold_candidates_path)

    for path in [out_json, by_ticker_path, by_regime_path, threshold_path]:
        path.parent.mkdir(parents=True, exist_ok=True)

    trades, infer_info, candidate_count = _build_v2_trade_rows(features=features, settings=settings)
    if trades.empty:
        pd.DataFrame().to_csv(by_ticker_path, index=False)
        pd.DataFrame().to_csv(by_regime_path, index=False)
        pd.DataFrame().to_csv(threshold_path, index=False)
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "status": "no_trades",
            "message": "No complete Model V2 candidate outcomes available for audit",
            "input": {
                "feature_rows": int(len(features)),
                "candidate_count": int(candidate_count),
            },
            "infer": infer_info,
            "report_paths": {
                "json": str(out_json),
                "by_ticker_csv": str(by_ticker_path),
                "by_regime_csv": str(by_regime_path),
                "threshold_candidates_csv": str(threshold_path),
            },
        }
        atomic_write_json(out_json, payload)
        return payload

    by_ticker = _group_summary(trades, ["ticker"])
    by_regime = _group_summary(trades, ["mode", "regime_status"])
    thresholds = _threshold_candidates(trades, settings)
    by_ticker.to_csv(by_ticker_path, index=False)
    by_regime.to_csv(by_regime_path, index=False)
    thresholds.to_csv(threshold_path, index=False)

    v2_recommended = trades[_bool_series(trades["v2_recommended"])].copy()
    by_mode = {str(mode): _summarize_trades(grp) for mode, grp in trades.groupby("mode", dropna=False)}
    v2_by_mode = {str(mode): _summarize_trades(grp) for mode, grp in v2_recommended.groupby("mode", dropna=False)}
    source_summary = _model_source_summary(trades, infer_info)

    status = "blocked_non_model" if source_summary["has_non_model"] else "ok"
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "status": status,
        "message": (
            "Model V2 accuracy audit generated"
            if status == "ok"
            else "Model V2 accuracy audit blocked because at least one mode did not use a trained model"
        ),
        "input": {
            "feature_rows": int(len(features)),
            "candidate_count": int(candidate_count),
            "audited_trade_count": int(len(trades)),
            "v2_recommended_count": int(len(v2_recommended)),
            "active_modes": list(settings.pipeline.active_modes),
            "max_candidates_per_day": int(cfg.max_candidates_per_day),
            "precision_top_k": [int(k) for k in cfg.precision_top_k],
            "probability_threshold_grid": [float(x) for x in cfg.probability_threshold_grid],
        },
        "report_paths": {
            "json": str(out_json),
            "by_ticker_csv": str(by_ticker_path),
            "by_regime_csv": str(by_regime_path),
            "threshold_candidates_csv": str(threshold_path),
        },
        "infer": infer_info,
        "model_source": source_summary,
        "overall_candidates": _summarize_trades(trades),
        "v2_recommended": _summarize_trades(v2_recommended),
        "selection_comparison": _selection_comparison(trades),
        "by_mode": by_mode,
        "v2_by_mode": v2_by_mode,
        "precision_at_k": _precision_at_k(trades, cfg.precision_top_k),
        "calibration_all_candidates": _calibration_summary(trades, int(cfg.calibration_bins)),
        "calibration_v2_recommended": _calibration_summary(v2_recommended, int(cfg.calibration_bins)),
        "signal_decay_v2_recommended": _signal_decay_summary(v2_recommended, settings.signal_accuracy.decay_days),
        "best_thresholds": _best_thresholds(thresholds, settings),
        "false_positive_summary": _false_positive_summary(v2_recommended if not v2_recommended.empty else trades, int(cfg.min_trades_per_segment)),
        "by_ticker_preview": _records(by_ticker.head(20)),
        "by_regime": _records(by_regime),
        "threshold_candidates_preview": _records(thresholds.head(40)),
        "recent_v2_recommended": _records(v2_recommended.sort_values("date", ascending=False).head(30)),
    }
    atomic_write_json(out_json, payload)
    return payload
