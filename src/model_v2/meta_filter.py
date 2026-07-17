"""Meta filters used before Model V2 can influence live selection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings


PROFILE_COLUMNS = [
    "ticker",
    "mode",
    "edge_samples",
    "raw_win_rate",
    "raw_expectancy_r",
    "shrunk_p_win",
    "shrunk_expectancy_r",
    "prior_p_win",
    "prior_expectancy_r",
]


def _normalized_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ticker"] = out.get("ticker", pd.Series("", index=out.index)).astype(str).str.upper().str.strip()
    out["mode"] = out.get("mode", pd.Series("", index=out.index)).astype(str).str.lower().str.strip()
    return out


def _posterior(
    samples: int,
    wins: int,
    return_sum: float,
    prior_p_win: float,
    prior_expectancy_r: float,
    prior_strength: float,
) -> tuple[float, float]:
    strength = max(1.0, float(prior_strength))
    denominator = float(samples) + strength
    p_win = (float(wins) + (strength * float(prior_p_win))) / denominator
    expectancy = (float(return_sum) + (strength * float(prior_expectancy_r))) / denominator
    return float(p_win), float(expectancy)


def build_bayesian_ticker_edge_profile(
    trades: pd.DataFrame,
    settings: Settings,
) -> pd.DataFrame:
    """Build a shrinkage profile without permanent ticker blacklists."""
    path = Path(settings.model_v2.ticker_edge_profile_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if trades.empty or "realized_r" not in trades.columns:
        profile = pd.DataFrame(columns=PROFILE_COLUMNS)
        profile.to_csv(path, index=False)
        return profile

    source = _normalized_keys(trades)
    source["realized_r"] = pd.to_numeric(source["realized_r"], errors="coerce")
    source = source.dropna(subset=["realized_r"])
    rows: list[dict[str, Any]] = []
    prior_strength = float(settings.model_v2.ticker_edge_prior_strength)

    for mode, mode_df in source.groupby("mode", dropna=False):
        mode_returns = pd.to_numeric(mode_df["realized_r"], errors="coerce").dropna()
        prior_p_win = float((mode_returns > 0).mean()) if not mode_returns.empty else 0.5
        prior_expectancy = float(mode_returns.mean()) if not mode_returns.empty else 0.0
        for ticker, group in mode_df.groupby("ticker", dropna=False):
            returns = pd.to_numeric(group["realized_r"], errors="coerce").dropna()
            if returns.empty:
                continue
            samples = int(len(returns))
            wins = int((returns > 0).sum())
            shrunk_p_win, shrunk_expectancy = _posterior(
                samples=samples,
                wins=wins,
                return_sum=float(returns.sum()),
                prior_p_win=prior_p_win,
                prior_expectancy_r=prior_expectancy,
                prior_strength=prior_strength,
            )
            rows.append(
                {
                    "ticker": str(ticker).upper(),
                    "mode": str(mode).lower(),
                    "edge_samples": samples,
                    "raw_win_rate": round(float((returns > 0).mean()), 6),
                    "raw_expectancy_r": round(float(returns.mean()), 6),
                    "shrunk_p_win": round(shrunk_p_win, 6),
                    "shrunk_expectancy_r": round(shrunk_expectancy, 6),
                    "prior_p_win": round(prior_p_win, 6),
                    "prior_expectancy_r": round(prior_expectancy, 6),
                }
            )

    profile = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
    if not profile.empty:
        profile = profile.sort_values(
            ["shrunk_expectancy_r", "edge_samples"],
            ascending=[False, False],
        ).reset_index(drop=True)
    profile.to_csv(path, index=False)
    return profile


def apply_bayesian_ticker_edge_filter(
    candidates: pd.DataFrame,
    settings: Settings,
    profile: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Annotate live candidates and block only mature negative posterior edge."""
    if candidates.empty:
        return candidates.copy()
    out = _normalized_keys(candidates)
    if profile is None:
        path = Path(settings.model_v2.ticker_edge_profile_path)
        try:
            profile = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=PROFILE_COLUMNS)
        except (pd.errors.EmptyDataError, ValueError):
            profile = pd.DataFrame(columns=PROFILE_COLUMNS)

    if profile.empty:
        for column in PROFILE_COLUMNS:
            if column not in {"ticker", "mode"}:
                out[f"meta_{column}"] = 0.0
    else:
        profile_keys = _normalized_keys(profile)
        rename = {
            column: f"meta_{column}"
            for column in PROFILE_COLUMNS
            if column not in {"ticker", "mode"}
        }
        out = out.merge(
            profile_keys[PROFILE_COLUMNS].rename(columns=rename),
            on=["ticker", "mode"],
            how="left",
        )

    numeric_columns = [f"meta_{column}" for column in PROFILE_COLUMNS if column not in {"ticker", "mode"}]
    for column in numeric_columns:
        out[column] = pd.to_numeric(out.get(column, 0.0), errors="coerce").fillna(0.0)

    enough_samples = out["meta_edge_samples"] >= int(settings.model_v2.ticker_edge_min_samples)
    negative_posterior = (
        out["meta_shrunk_expectancy_r"]
        < float(settings.model_v2.ticker_edge_min_shrunk_expectancy_r)
    )
    blocked = enough_samples & negative_posterior
    out["meta_ticker_edge_action"] = "watch"
    out.loc[enough_samples & ~blocked, "meta_ticker_edge_action"] = "pass"
    out.loc[blocked, "meta_ticker_edge_action"] = "block"
    out["meta_ticker_edge_reason"] = "insufficient_ticker_history"
    out.loc[enough_samples & ~blocked, "meta_ticker_edge_reason"] = "posterior_edge_pass"
    out.loc[blocked, "meta_ticker_edge_reason"] = "negative_posterior_expectancy"
    return out


def annotate_historical_bayesian_edge(
    trades: pd.DataFrame,
    settings: Settings,
) -> pd.DataFrame:
    """Create leakage-safe historical ticker-edge decisions using prior rows."""
    if trades.empty or "realized_r" not in trades.columns:
        return trades.copy()
    source = _normalized_keys(trades)
    source["_original_index"] = source.index
    source["_date"] = pd.to_datetime(source.get("date"), errors="coerce")
    source["realized_r"] = pd.to_numeric(source["realized_r"], errors="coerce")
    source = source.sort_values(["_date", "mode", "ticker", "_original_index"]).copy()

    strength = float(settings.model_v2.ticker_edge_prior_strength)
    min_samples = int(settings.model_v2.ticker_edge_min_samples)
    min_expectancy = float(settings.model_v2.ticker_edge_min_shrunk_expectancy_r)
    ticker_state: dict[tuple[str, str], dict[str, float]] = {}
    mode_state: dict[str, dict[str, float]] = {}
    annotations: list[dict[str, Any]] = []

    for _, row in source.iterrows():
        ticker = str(row["ticker"])
        mode = str(row["mode"])
        key = (ticker, mode)
        ticker_stats = ticker_state.get(key, {"samples": 0.0, "wins": 0.0, "return_sum": 0.0})
        mode_stats = mode_state.get(mode, {"samples": 0.0, "wins": 0.0, "return_sum": 0.0})
        mode_samples = int(mode_stats["samples"])
        prior_p_win = (
            (mode_stats["wins"] + (strength * 0.5)) / (mode_stats["samples"] + strength)
            if mode_samples
            else 0.5
        )
        prior_expectancy = (
            mode_stats["return_sum"] / (mode_stats["samples"] + strength)
            if mode_samples
            else 0.0
        )
        samples = int(ticker_stats["samples"])
        shrunk_p_win, shrunk_expectancy = _posterior(
            samples=samples,
            wins=int(ticker_stats["wins"]),
            return_sum=float(ticker_stats["return_sum"]),
            prior_p_win=prior_p_win,
            prior_expectancy_r=prior_expectancy,
            prior_strength=strength,
        )
        blocked = samples >= min_samples and shrunk_expectancy < min_expectancy
        annotations.append(
            {
                "_original_index": row["_original_index"],
                "meta_edge_samples": samples,
                "meta_shrunk_p_win": round(shrunk_p_win, 6),
                "meta_shrunk_expectancy_r": round(shrunk_expectancy, 6),
                "meta_ticker_edge_action": (
                    "block" if blocked else ("pass" if samples >= min_samples else "watch")
                ),
            }
        )

        realized_r = float(row["realized_r"]) if pd.notna(row["realized_r"]) else 0.0
        is_win = 1.0 if realized_r > 0 else 0.0
        ticker_state[key] = {
            "samples": ticker_stats["samples"] + 1.0,
            "wins": ticker_stats["wins"] + is_win,
            "return_sum": ticker_stats["return_sum"] + realized_r,
        }
        mode_state[mode] = {
            "samples": mode_stats["samples"] + 1.0,
            "wins": mode_stats["wins"] + is_win,
            "return_sum": mode_stats["return_sum"] + realized_r,
        }

    annotation_df = pd.DataFrame(annotations).set_index("_original_index")
    out = trades.copy()
    for column in annotation_df.columns:
        out[column] = annotation_df[column].reindex(out.index)
    return out
