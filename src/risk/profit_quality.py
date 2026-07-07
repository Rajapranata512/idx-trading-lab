from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.utils import atomic_write_json


PROFILE_COLUMNS = [
    "ticker",
    "mode",
    "edge_samples",
    "edge_win_rate_pct",
    "edge_expectancy_r",
    "edge_profit_factor_r",
    "edge_avg_win_r",
    "edge_avg_loss_r",
    "edge_gross_profit_r",
    "edge_gross_loss_r",
    "edge_last_executed_at",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def _safe_series(values: Any, index: pd.Index, default: float = 0.0) -> pd.Series:
    if isinstance(values, pd.Series):
        series = pd.to_numeric(values, errors="coerce")
    else:
        series = pd.Series([values] * len(index), index=index)
        series = pd.to_numeric(series, errors="coerce")
    return pd.Series(series, index=index, dtype="float64").fillna(default)


def _profit_factor(realized_r: pd.Series) -> float:
    clean = pd.to_numeric(realized_r, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    gross_profit = float(clean[clean > 0].sum())
    gross_loss = float(-clean[clean < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _empty_profile() -> pd.DataFrame:
    return pd.DataFrame(columns=PROFILE_COLUMNS)


def build_ticker_edge_profile(details_csv_path: str | Path, profile_path: str | Path) -> pd.DataFrame:
    """Aggregate live reconciliation rows into ticker/mode edge statistics."""
    details_path = Path(details_csv_path)
    out_path = Path(profile_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not details_path.exists() or details_path.stat().st_size <= 2:
        profile = _empty_profile()
        profile.to_csv(out_path, index=False)
        return profile

    try:
        raw = pd.read_csv(details_path)
    except (pd.errors.EmptyDataError, ValueError):
        profile = _empty_profile()
        profile.to_csv(out_path, index=False)
        return profile

    if raw.empty or "ticker" not in raw.columns or "realized_r" not in raw.columns:
        profile = _empty_profile()
        profile.to_csv(out_path, index=False)
        return profile

    df = raw.copy()
    mode_col = "signal_mode" if "signal_mode" in df.columns else "mode" if "mode" in df.columns else ""
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["mode"] = df[mode_col].astype(str).str.lower().str.strip() if mode_col else ""
    df["realized_r"] = pd.to_numeric(df["realized_r"], errors="coerce")
    df = df.dropna(subset=["ticker", "realized_r"])
    df = df[df["ticker"].str.len() > 0].copy()
    if df.empty:
        profile = _empty_profile()
        profile.to_csv(out_path, index=False)
        return profile

    rows: list[dict[str, Any]] = []
    for (ticker, mode), grp in df.groupby(["ticker", "mode"], dropna=False):
        rr = pd.to_numeric(grp["realized_r"], errors="coerce").dropna()
        if rr.empty:
            continue
        wins = rr[rr > 0]
        losses = rr[rr < 0]
        last_executed_at = ""
        if "executed_at" in grp.columns:
            parsed = pd.to_datetime(grp["executed_at"], errors="coerce")
            if parsed.notna().any():
                last_executed_at = parsed.max().isoformat()
        rows.append(
            {
                "ticker": str(ticker).upper(),
                "mode": str(mode).lower(),
                "edge_samples": int(len(rr)),
                "edge_win_rate_pct": round(float((rr > 0).mean() * 100.0), 4),
                "edge_expectancy_r": round(float(rr.mean()), 6),
                "edge_profit_factor_r": round(_profit_factor(rr), 6),
                "edge_avg_win_r": round(float(wins.mean()), 6) if not wins.empty else 0.0,
                "edge_avg_loss_r": round(float(-losses.mean()), 6) if not losses.empty else 1.0,
                "edge_gross_profit_r": round(float(wins.sum()), 6) if not wins.empty else 0.0,
                "edge_gross_loss_r": round(float(-losses.sum()), 6) if not losses.empty else 0.0,
                "edge_last_executed_at": last_executed_at,
            }
        )

    profile = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
    if not profile.empty:
        profile = profile.sort_values(
            ["edge_expectancy_r", "edge_profit_factor_r", "edge_samples"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
    profile.to_csv(out_path, index=False)
    return profile


def _score_probability(df: pd.DataFrame, settings: Settings) -> pd.Series:
    score = _safe_series(df.get("score", 0.0), df.index, default=0.0)
    mode = df.get("mode", pd.Series([""] * len(df), index=df.index)).astype(str).str.lower()
    t1_threshold = max(1.0, float(settings.pipeline.min_live_score_t1))
    swing_threshold = max(1.0, float(settings.pipeline.min_live_score_swing))
    threshold = pd.Series(swing_threshold, index=df.index, dtype="float64")
    threshold = threshold.where(mode != "t1", t1_threshold)
    score_edge = ((score - threshold) / threshold.clip(lower=1.0)).clip(lower=-1.0, upper=1.0)
    return (0.50 + (score_edge * 0.12)).clip(lower=0.38, upper=0.64)


def _model_probability(df: pd.DataFrame, settings: Settings) -> tuple[pd.Series, pd.Series]:
    fallback = _score_probability(df, settings)
    if "shadow_p_win" not in df.columns:
        return fallback, pd.Series([False] * len(df), index=df.index)
    raw = pd.to_numeric(df["shadow_p_win"], errors="coerce")
    valid = raw.between(0.01, 0.99)
    out = fallback.where(~valid, raw)
    return out.astype(float), valid.fillna(False).astype(bool)


def _reward_loss_cost_r(df: pd.DataFrame, settings: Settings) -> tuple[pd.Series, pd.Series, pd.Series]:
    entry = _safe_series(df.get("entry", df.get("close", 0.0)), df.index, default=0.0)
    stop = _safe_series(df.get("stop", 0.0), df.index, default=0.0)
    tp2 = _safe_series(df.get("tp2", 0.0), df.index, default=0.0)
    risk_per_share = _safe_series(df.get("risk_per_share", entry - stop), df.index, default=0.0)
    risk_per_share = risk_per_share.where(risk_per_share > 0, entry - stop)
    risk_per_share = risk_per_share.clip(lower=1e-9)

    reward_r = ((tp2 - entry) / risk_per_share).replace([float("inf"), float("-inf")], float("nan"))
    reward_r = reward_r.where(reward_r > 0, float(settings.risk.tp2_r_multiple)).fillna(float(settings.risk.tp2_r_multiple))
    reward_r = reward_r.clip(lower=0.25, upper=5.0)

    loss_r = pd.Series([1.0] * len(df), index=df.index, dtype="float64")
    roundtrip_cost_pct = _safe_series(
        df.get("est_roundtrip_cost_pct", float(settings.backtest.buy_fee_pct) + float(settings.backtest.sell_fee_pct) + (2.0 * float(settings.backtest.slippage_pct))),
        df.index,
        default=0.0,
    ).clip(lower=0.0)
    risk_pct = ((risk_per_share / entry.clip(lower=1e-9)) * 100.0).replace([float("inf"), float("-inf")], float("nan"))
    cost_r = (roundtrip_cost_pct / risk_pct.clip(lower=1e-9)).replace([float("inf"), float("-inf")], float("nan"))
    cost_r = cost_r.fillna(0.0).clip(lower=0.0, upper=3.0)
    return reward_r, loss_r, cost_r


def _with_edge_columns(candidates: pd.DataFrame, profile: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    cfg = settings.pipeline.profit_quality
    df = candidates.copy()
    if df.empty:
        return df

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["mode"] = df["mode"].astype(str).str.lower().str.strip() if "mode" in df.columns else ""
    if profile.empty:
        for col in PROFILE_COLUMNS:
            if col not in {"ticker", "mode"}:
                df[col] = 0.0 if col != "edge_last_executed_at" else ""
    else:
        prof = profile.copy()
        prof["ticker"] = prof["ticker"].astype(str).str.upper().str.strip()
        prof["mode"] = prof["mode"].astype(str).str.lower().str.strip()
        df = df.merge(prof, on=["ticker", "mode"], how="left")

    numeric_edge_cols = [
        "edge_samples",
        "edge_win_rate_pct",
        "edge_expectancy_r",
        "edge_profit_factor_r",
        "edge_avg_win_r",
        "edge_avg_loss_r",
    ]
    for col in numeric_edge_cols:
        df[col] = pd.to_numeric(df.get(col, 0.0), errors="coerce").fillna(0.0)
    if "edge_last_executed_at" not in df.columns:
        df["edge_last_executed_at"] = ""
    else:
        df["edge_last_executed_at"] = df["edge_last_executed_at"].fillna("").astype(str)

    p_model, has_model_probability = _model_probability(df, settings)
    reward_r, loss_r, cost_r = _reward_loss_cost_r(df, settings)
    enough_samples = df["edge_samples"] >= int(cfg.min_ticker_samples)
    confidence = (df["edge_samples"] / max(1.0, float(cfg.strong_sample_size))).clip(lower=0.0, upper=1.0)
    confidence = confidence.where(enough_samples, 0.0).astype(float)

    profile_p = (df["edge_win_rate_pct"] / 100.0).clip(lower=0.0, upper=1.0)
    edge_avg_win = df["edge_avg_win_r"].where(df["edge_avg_win_r"] > 0.0, reward_r).clip(lower=0.1, upper=5.0)
    edge_avg_loss = df["edge_avg_loss_r"].where(df["edge_avg_loss_r"] > 0.0, loss_r).clip(lower=0.1, upper=5.0)
    ev_p_win = ((1.0 - confidence) * p_model) + (confidence * profile_p)
    ev_reward_r = ((1.0 - confidence) * reward_r) + (confidence * edge_avg_win)
    ev_loss_r = ((1.0 - confidence) * loss_r) + (confidence * edge_avg_loss)
    ev_expected_r = (ev_p_win * ev_reward_r) - ((1.0 - ev_p_win) * ev_loss_r) - cost_r

    gate_active = (
        enough_samples
        | (bool(cfg.gate_with_model_probability) & has_model_probability)
        | bool(cfg.gate_without_live_edge)
    )
    negative_edge = enough_samples & (
        (df["edge_expectancy_r"] < float(cfg.min_ticker_expectancy_r))
        | (df["edge_profit_factor_r"] < float(cfg.min_ticker_profit_factor_r))
    )
    low_ev = gate_active & (ev_expected_r < float(cfg.min_expected_r))
    blocked = low_ev | (bool(cfg.block_negative_edge) & negative_edge)

    reason = pd.Series(["profit_quality_pass"] * len(df), index=df.index, dtype="object")
    reason = reason.where(gate_active, "profit_quality_watch_insufficient_edge")
    reason = reason.where(~low_ev, "profit_quality_block_low_expected_r")
    reason = reason.where(~(bool(cfg.block_negative_edge) & negative_edge), "profit_quality_block_negative_ticker_edge")

    score = _safe_series(df.get("score", 0.0), df.index, default=0.0)
    adjustment = (ev_expected_r * float(cfg.score_adjustment_weight)).clip(
        lower=-float(cfg.max_score_adjustment),
        upper=float(cfg.max_score_adjustment),
    )

    df["edge_confidence"] = confidence.round(4)
    df["ev_p_win"] = ev_p_win.round(4)
    df["ev_reward_r"] = ev_reward_r.round(4)
    df["ev_loss_r"] = ev_loss_r.round(4)
    df["ev_cost_r"] = cost_r.round(4)
    df["ev_expected_r"] = ev_expected_r.round(4)
    df["profit_quality_score"] = (score + adjustment).round(4)
    df["profit_quality_action"] = blocked.map({True: "block", False: "pass"}).astype(str)
    df.loc[~gate_active & ~blocked, "profit_quality_action"] = "watch"
    df["profit_quality_reason"] = reason
    return df


def apply_profit_quality_gate(
    candidates: pd.DataFrame,
    settings: Settings,
    stage: str = "score",
    write_report: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cfg = settings.pipeline.profit_quality
    if not bool(cfg.enabled):
        info = {
            "generated_at": datetime.utcnow().isoformat(),
            "stage": stage,
            "status": "disabled",
            "enabled": False,
            "input_count": int(len(candidates)),
            "output_count": int(len(candidates)),
        }
        return candidates.copy(), info

    profile = build_ticker_edge_profile(
        details_csv_path=settings.reconciliation.details_csv_path,
        profile_path=cfg.profile_path,
    )
    enriched = _with_edge_columns(candidates, profile, settings)
    if enriched.empty:
        filtered = enriched.copy()
    else:
        filtered = enriched[enriched["profit_quality_action"] != "block"].copy()
        sort_col = "profit_quality_score" if "profit_quality_score" in filtered.columns else "score"
        if sort_col in filtered.columns:
            filtered = filtered.sort_values(sort_col, ascending=False).reset_index(drop=True)

    action_counts = (
        enriched.get("profit_quality_action", pd.Series(dtype=str)).astype(str).value_counts().to_dict()
        if not enriched.empty
        else {}
    )
    blocked = enriched[enriched.get("profit_quality_action", pd.Series(dtype=str)).astype(str) == "block"].copy() if not enriched.empty else pd.DataFrame()
    info = {
        "generated_at": datetime.utcnow().isoformat(),
        "stage": stage,
        "status": "ok",
        "enabled": True,
        "input_count": int(len(candidates)),
        "output_count": int(len(filtered)),
        "blocked_count": int(len(blocked)),
        "watch_count": int(action_counts.get("watch", 0)),
        "pass_count": int(action_counts.get("pass", 0)),
        "profile_path": str(cfg.profile_path),
        "profile_rows": int(len(profile)),
        "thresholds": {
            "min_expected_r": float(cfg.min_expected_r),
            "min_ticker_samples": int(cfg.min_ticker_samples),
            "strong_sample_size": int(cfg.strong_sample_size),
            "min_ticker_expectancy_r": float(cfg.min_ticker_expectancy_r),
            "min_ticker_profit_factor_r": float(cfg.min_ticker_profit_factor_r),
            "gate_without_live_edge": bool(cfg.gate_without_live_edge),
            "gate_with_model_probability": bool(cfg.gate_with_model_probability),
        },
        "blocked_preview": (
            blocked[
                [
                    c
                    for c in [
                        "ticker",
                        "mode",
                        "score",
                        "profit_quality_score",
                        "ev_expected_r",
                        "edge_samples",
                        "edge_expectancy_r",
                        "edge_profit_factor_r",
                        "profit_quality_reason",
                    ]
                    if c in blocked.columns
                ]
            ]
            .head(20)
            .to_dict(orient="records")
        ),
    }
    if write_report:
        report_payload = dict(info)
        report_payload["action_counts"] = action_counts
        atomic_write_json(cfg.report_path, json.loads(json.dumps(report_payload, default=str)))
    return filtered, info
