from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.config import Settings
from src.model_v2.io import load_model_bundle, load_state, save_model_bundle, save_state
from src.runtime import active_modes as resolve_active_modes
from src.runtime import regime_bucket_from_features

# ---------------------------------------------------------------------------
# Optional strong learners — graceful fallback to LogReg if not installed.
# ---------------------------------------------------------------------------
try:
    import lightgbm as lgb  # type: ignore
    _HAS_LGB = True
except ImportError:
    _HAS_LGB = False

try:
    import xgboost as xgb  # type: ignore
    _HAS_XGB = True
except ImportError:
    _HAS_XGB = False

try:
    import optuna  # type: ignore
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _HAS_OPTUNA = True
except ImportError:
    _HAS_OPTUNA = False

# ---------------------------------------------------------------------------
# V2 feature list — expanded from 10 → 25 features.
# All features are lagged (computed on current bar from past data only).
# ---------------------------------------------------------------------------
MODEL_FEATURES = [
    # --- Original 10 ---
    "score",
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "atr_pct",
    "vol_20d",
    "avg_vol_20d",
    "close",
    "ma_20",
    "ma_50",
    # --- V2 additions ---
    "ma_slope_20",
    "ma_slope_50",
    "dist_ma_20",
    "dist_ma_50",
    "vol_ratio",
    "ret_5d_20d_ratio",
    "high_low_range",
    "close_position",
    "volume_ratio_20d",
    "rsi_14",
    "rsi_slope",
    "mfi_14",
    "obv_slope",
    "rank_ret_20d",
    "rank_vol_20d",
    "turnover_ratio_20d",
    "dist_high_20",
    "dist_low_20",
    "ma_gap_20_50",
    "ma_stack_bullish",
    "market_breadth_ma20_pct",
    "market_breadth_ma50_pct",
    "market_avg_ret20_pct",
    "market_median_atr_pct",
    "relative_ret_20d",
]

SWING_POSITIVE_RANK_CUTOFF = 0.65
REGIME_THRESHOLD_MIN_ROWS = 40


def _safe_float_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").astype(float)


def _build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = {c: _safe_float_series(df, c) for c in MODEL_FEATURES}
    return pd.DataFrame(data, index=df.index)


def _prepare_training_frame(
    train_df: pd.DataFrame,
    mode: str,
    settings: Settings,
) -> pd.DataFrame:
    out = train_df.copy()
    out["net_return"] = pd.to_numeric(out.get("net_return"), errors="coerce").fillna(0.0).astype(float)
    out["regime_bucket"] = regime_bucket_from_features(out, settings=settings, default="risk_off")
    out["target_rank_pct"] = (
        out.groupby("date")["net_return"].rank(method="average", pct=True).fillna(0.5)
        if "date" in out.columns
        else pd.Series([0.5] * len(out), index=out.index, dtype=float)
    )

    if str(mode).lower() == "swing":
        ranked_positive = (out["target_rank_pct"] >= SWING_POSITIVE_RANK_CUTOFF) & (out["net_return"] > 0)
        if ranked_positive.nunique() >= 2:
            out["y"] = ranked_positive.astype(int)
            out["label_strategy"] = f"ranked_expected_return_top_{int(SWING_POSITIVE_RANK_CUTOFF * 100)}pct"
        else:
            out["y"] = pd.to_numeric(out.get("y"), errors="coerce").fillna(0).astype(int)
            out["label_strategy"] = "binary_fallback_positive_net_return"
        sample_weight = out["net_return"].abs().clip(lower=0.2, upper=3.5) * (0.75 + out["target_rank_pct"])
    else:
        out["y"] = pd.to_numeric(out.get("y"), errors="coerce").fillna(0).astype(int)
        out["label_strategy"] = "binary_positive_net_return"
        sample_weight = out["net_return"].abs().clip(lower=0.25, upper=3.0)

    out["sample_weight"] = sample_weight.clip(lower=0.25, upper=4.0).astype(float)
    return out


def _fit_pipeline(
    pipeline: Pipeline,
    x: pd.DataFrame,
    y: pd.Series,
    sample_weight: pd.Series | None = None,
) -> None:
    if sample_weight is None:
        pipeline.fit(x, y)
        return
    try:
        pipeline.fit(x, y, clf__sample_weight=sample_weight.to_numpy())
    except TypeError:
        pipeline.fit(x, y)


def _profit_factor_from_returns(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    gross_profit = float(clean[clean > 0].sum())
    gross_loss = float(-clean[clean < 0].sum())
    if gross_loss <= 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _pick_probability_threshold(
    probs: pd.Series,
    returns: pd.Series,
    base_threshold: float,
) -> float:
    p = pd.to_numeric(probs, errors="coerce")
    r = pd.to_numeric(returns, errors="coerce")
    work = pd.DataFrame({"p": p, "r": r}).dropna()
    if len(work) < REGIME_THRESHOLD_MIN_ROWS:
        return float(base_threshold)

    lower = max(0.35, float(base_threshold) - 0.15)
    upper = min(0.85, float(base_threshold) + 0.15)
    thresholds = np.round(np.arange(lower, upper + 0.0001, 0.025), 3)
    candidates: list[tuple[tuple[float, float, float], float]] = []
    for threshold in thresholds:
        selected = work[work["p"] >= threshold]
        if len(selected) < max(10, min(REGIME_THRESHOLD_MIN_ROWS, len(work) // 6)):
            continue
        expectancy = float(selected["r"].mean())
        pf = float(_profit_factor_from_returns(selected["r"]))
        profitable = 1.0 if expectancy > 0 else 0.0
        candidates.append(((profitable, min(pf, 20.0), expectancy), float(threshold)))

    if not candidates:
        return float(base_threshold)
    candidates.sort(key=lambda row: row[0], reverse=True)
    return float(candidates[0][1])


def _build_return_profile(train_df: pd.DataFrame) -> dict[str, Any]:
    def _summary(frame: pd.DataFrame) -> dict[str, float]:
        returns = pd.to_numeric(frame.get("net_return"), errors="coerce").dropna()
        positives = returns[returns > 0]
        negatives = returns[returns <= 0]
        return {
            "mean_return_r": round(float(returns.mean()), 6) if not returns.empty else 0.0,
            "positive_mean_r": round(float(positives.mean()), 6) if not positives.empty else 0.0,
            "negative_mean_r": round(float(negatives.mean()), 6) if not negatives.empty else 0.0,
            "sample_count": int(len(returns)),
        }

    profile = {"overall": _summary(train_df), "by_regime": {}}
    if "regime_bucket" in train_df.columns:
        for regime, grp in train_df.groupby("regime_bucket", dropna=False):
            profile["by_regime"][str(regime)] = _summary(grp)
    return profile


def _calibrate_regime_thresholds(
    train_df: pd.DataFrame,
    probs: pd.Series,
    settings: Settings,
    mode: str,
) -> dict[str, float]:
    base = float(settings.model_v2.min_prob_threshold_t1 if str(mode).lower() == "t1" else settings.model_v2.min_prob_threshold_swing)
    work = train_df.copy()
    work["pred_prob"] = pd.to_numeric(probs, errors="coerce").astype(float)
    thresholds = {"default": round(base, 4)}
    if str(mode).lower() != "swing":
        return thresholds

    for regime in ["risk_on", "risk_off"]:
        subset = work[work.get("regime_bucket", "") == regime].copy()
        if len(subset) < REGIME_THRESHOLD_MIN_ROWS:
            thresholds[regime] = round(base, 4)
            continue
        thresholds[regime] = round(
            _pick_probability_threshold(
                probs=subset["pred_prob"],
                returns=subset["net_return"],
                base_threshold=base,
            ),
            4,
        )
    return thresholds


# ---------------------------------------------------------------------------
# Labeling — V2 with stop/TP simulation (falls back to V1 if import fails)
# ---------------------------------------------------------------------------
def _training_rows_for_mode(
    scored_history: pd.DataFrame,
    mode: str,
    horizon_days: int,
    roundtrip_cost_pct: float,
    stop_atr_mult: float = 2.0,
    tp1_r_mult: float = 1.0,
    train_lookback_days: int = 0,
) -> pd.DataFrame:
    """Build labeled training rows.

    Uses realistic intrabar stop/TP outcomes. Training fails closed when the
    labeling pipeline is unavailable so a future-close proxy cannot silently
    become a production model.
    """
    try:
        from src.model_v2.labeling import build_training_dataset

        v2_df = build_training_dataset(
            scored_history=scored_history,
            mode=mode,
            horizon_days=horizon_days,
            stop_atr_mult=stop_atr_mult,
            tp1_r_mult=tp1_r_mult,
            roundtrip_cost_pct=roundtrip_cost_pct,
            train_lookback_days=train_lookback_days,
        )
        if not v2_df.empty and "y" in v2_df.columns:
            return v2_df
        return pd.DataFrame()
    except Exception as exc:
        raise RuntimeError(f"realistic_labeling_failed:{mode}:{exc}") from exc


def _training_rows_v1(
    scored_history: pd.DataFrame,
    mode: str,
    horizon_days: int,
    roundtrip_cost_pct: float,
) -> pd.DataFrame:
    """Original V1 labeling (simple forward return > cost)."""
    if scored_history.empty:
        return pd.DataFrame()

    df = scored_history.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "mode", "close"]).copy()
    if df.empty:
        return pd.DataFrame()

    bars = df.sort_values(["ticker", "date"]).drop_duplicates(subset=["ticker", "date"], keep="first").copy()
    bars["fwd_close"] = bars.groupby("ticker")["close"].shift(-int(horizon_days))
    bars = bars[["ticker", "date", "fwd_close"]].copy()

    mode_df = df[df["mode"] == mode].copy()
    mode_df = mode_df.merge(bars, on=["ticker", "date"], how="left")
    mode_df = mode_df.dropna(subset=["fwd_close"]).copy()
    if mode_df.empty:
        return mode_df

    raw_ret = (mode_df["fwd_close"] - mode_df["close"]) / (mode_df["close"] + 1e-9)
    net_ret = raw_ret - (float(roundtrip_cost_pct) / 100.0)
    mode_df["y"] = (net_ret > 0).astype(int)
    mode_df["net_return"] = net_ret.astype(float)
    return mode_df


# ---------------------------------------------------------------------------
# Multi-model training — LogReg + LightGBM + XGBoost, pick best by CV AUC
# ---------------------------------------------------------------------------
def _build_logreg_pipeline() -> Pipeline:
    """Baseline logistic regression pipeline."""
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def _build_lgb_pipeline(params: dict[str, Any] | None = None) -> Pipeline | None:
    """LightGBM pipeline. Uses Optuna-tuned params if provided, else defaults."""
    if not _HAS_LGB:
        return None
    default_params = {
        "n_estimators": 300,
        "max_depth": 5,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_samples": 20,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "class_weight": "balanced",
        "verbose": -1,
        "n_jobs": 1,
    }
    if params:
        default_params.update(params)
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("clf", lgb.LGBMClassifier(**default_params)),
        ]
    )


def _build_xgb_pipeline(params: dict[str, Any] | None = None) -> Pipeline | None:
    """XGBoost pipeline. Uses Optuna-tuned params if provided, else defaults."""
    if not _HAS_XGB:
        return None
    default_params = {
        "n_estimators": 300,
        "max_depth": 5,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "scale_pos_weight": 1.0,
        "use_label_encoder": False,
        "eval_metric": "logloss",
        "verbosity": 0,
        "n_jobs": 1,
    }
    if params:
        default_params.update(params)
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("clf", xgb.XGBClassifier(**default_params)),
        ]
    )


# ---------------------------------------------------------------------------
# Optuna hyperparameter search — finds best params via time-based CV AUC
# ---------------------------------------------------------------------------
def _optuna_lgb_objective(
    trial: Any,
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    sample_weight: pd.Series | None,
    gap_dates: int,
) -> float:
    """Optuna objective for LightGBM hyperparameter search."""
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
    }
    pipe = _build_lgb_pipeline(params)
    if pipe is None:
        return 0.0
    return _time_cv_auc(
        pipe,
        X,
        y,
        dates,
        sample_weight=sample_weight,
        n_splits=3,
        gap_dates=gap_dates,
    )


def _optuna_xgb_objective(
    trial: Any,
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    sample_weight: pd.Series | None,
    gap_dates: int,
) -> float:
    """Optuna objective for XGBoost hyperparameter search."""
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 3, 15),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
    }
    pipe = _build_xgb_pipeline(params)
    if pipe is None:
        return 0.0
    return _time_cv_auc(
        pipe,
        X,
        y,
        dates,
        sample_weight=sample_weight,
        n_splits=3,
        gap_dates=gap_dates,
    )


def _optuna_search(
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    sample_weight: pd.Series | None,
    n_trials: int = 25,
    gap_dates: int = 0,
) -> list[tuple[str, Pipeline, float, dict[str, Any]]]:
    """Run Optuna search for LightGBM and XGBoost, return tuned pipelines.

    Returns a list of (name, fitted_pipeline, cv_auc, best_params) tuples.
    """
    if not _HAS_OPTUNA:
        return []

    results: list[tuple[str, Pipeline, float, dict[str, Any]]] = []

    # --- LightGBM Optuna search ---
    if _HAS_LGB:
        try:
            study_lgb = optuna.create_study(direction="maximize")
            study_lgb.optimize(
                lambda trial: _optuna_lgb_objective(
                    trial, X, y, dates, sample_weight, gap_dates
                ),
                n_trials=n_trials,
                show_progress_bar=False,
            )
            best_lgb_params = study_lgb.best_params
            best_lgb_pipe = _build_lgb_pipeline(best_lgb_params)
            if best_lgb_pipe is not None:
                results.append(
                    ("lightgbm_optuna", best_lgb_pipe, study_lgb.best_value, best_lgb_params)
                )
        except Exception:
            pass

    # --- XGBoost Optuna search ---
    if _HAS_XGB:
        try:
            study_xgb = optuna.create_study(direction="maximize")
            study_xgb.optimize(
                lambda trial: _optuna_xgb_objective(
                    trial, X, y, dates, sample_weight, gap_dates
                ),
                n_trials=n_trials,
                show_progress_bar=False,
            )
            best_xgb_params = study_xgb.best_params
            best_xgb_pipe = _build_xgb_pipeline(best_xgb_params)
            if best_xgb_pipe is not None:
                results.append(
                    ("xgboost_optuna", best_xgb_pipe, study_xgb.best_value, best_xgb_params)
                )
        except Exception:
            pass

    return results


def _time_cv_auc(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    dates: pd.Series,
    sample_weight: pd.Series | None = None,
    n_splits: int = 3,
    gap_dates: int = 0,
) -> float:
    """Simple time-based cross-validation to estimate AUC.

    Splits by date quantiles so training always precedes validation. A purge
    gap prevents horizon labels near the split from leaking into validation.
    """
    date_vals = pd.to_datetime(dates, errors="coerce").values
    unique_dates = np.sort(np.unique(date_vals[~pd.isna(date_vals)]))
    if len(unique_dates) < n_splits + 1:
        return 0.0

    fold_size = len(unique_dates) // (n_splits + 1)
    aucs: list[float] = []

    for fold in range(n_splits):
        train_end_idx = (fold + 1) * fold_size
        val_start_idx = train_end_idx + max(0, int(gap_dates))
        val_end_idx = min(val_start_idx + fold_size, len(unique_dates))

        if val_end_idx <= val_start_idx:
            continue

        train_cutoff = unique_dates[train_end_idx - 1]
        val_start_date = unique_dates[val_start_idx]
        val_end_date = unique_dates[val_end_idx - 1]

        train_mask = date_vals <= train_cutoff
        val_mask = (date_vals >= val_start_date) & (date_vals <= val_end_date)

        X_train, y_train = X[train_mask], y[train_mask]
        X_val, y_val = X[val_mask], y[val_mask]
        sw_train = sample_weight[train_mask] if sample_weight is not None else None

        if len(y_train) < 30 or y_train.nunique() < 2:
            continue
        if len(y_val) < 10 or y_val.nunique() < 2:
            continue

        try:
            from sklearn.base import clone
            model = clone(pipeline)
            _fit_pipeline(model, X_train, y_train, sample_weight=sw_train)
            p = model.predict_proba(X_val)[:, 1]
            aucs.append(float(roc_auc_score(y_val, p)))
        except Exception:
            continue

    return float(np.mean(aucs)) if aucs else 0.0


def _chronological_partition_indices(
    prepared: pd.DataFrame,
    gap_dates: int,
) -> tuple[pd.Index, pd.Index, pd.Index]:
    """Split unique dates into disjoint fit, calibration, and test windows."""
    if "date" not in prepared.columns:
        return prepared.index, pd.Index([]), pd.Index([])

    parsed_dates = pd.to_datetime(prepared["date"], errors="coerce")
    unique_dates = np.sort(parsed_dates.dropna().unique())
    holdout_dates = max(2, len(unique_dates) // 5)
    gap = max(0, int(gap_dates))

    test_start = len(unique_dates) - holdout_dates
    cal_end = test_start - gap
    cal_start = cal_end - holdout_dates
    fit_end = cal_start - gap
    if fit_end < 12 or cal_start < 0 or test_start <= cal_end:
        return prepared.index, pd.Index([]), pd.Index([])

    fit_dates = set(unique_dates[:fit_end])
    cal_dates = set(unique_dates[cal_start:cal_end])
    test_dates = set(unique_dates[test_start:])
    fit_idx = prepared.index[parsed_dates.isin(fit_dates)]
    cal_idx = prepared.index[parsed_dates.isin(cal_dates)]
    test_idx = prepared.index[parsed_dates.isin(test_dates)]
    if min(len(fit_idx), len(cal_idx), len(test_idx)) < 20:
        return prepared.index, pd.Index([]), pd.Index([])
    return fit_idx, cal_idx, test_idx


def _train_one_mode(
    train_df: pd.DataFrame,
    mode: str,
    settings: Settings,
    horizon_days: int,
) -> tuple[Any, dict[str, Any]]:
    """Train multiple candidate models, pick best by time-based CV AUC.

    Uses Optuna hyperparameter auto-tuning when available to search for
    the best LightGBM/XGBoost configuration.  Falls back to static
    parameters (and ultimately to LogReg) when Optuna is not installed.

    Returns the best fitted pipeline + metadata.
    """
    prepared = _prepare_training_frame(train_df=train_df, mode=mode, settings=settings)
    x = _build_feature_frame(prepared)
    y = pd.to_numeric(prepared["y"], errors="coerce").fillna(0).astype(int)
    sample_weight = pd.to_numeric(prepared.get("sample_weight"), errors="coerce").fillna(1.0).astype(float)
    if y.nunique() < 2:
        raise ValueError("Need at least 2 classes for training")

    dates = prepared["date"] if "date" in prepared.columns else pd.Series(range(len(prepared)))
    n_optuna_trials = int(getattr(settings.model_v2, "optuna_trials", 25))
    fit_idx, cal_idx, test_idx = _chronological_partition_indices(
        prepared,
        gap_dates=horizon_days,
    )
    x_fit = x.loc[fit_idx]
    y_fit = y.loc[fit_idx]
    dates_fit = dates.loc[fit_idx]
    sample_weight_fit = sample_weight.loc[fit_idx]
    if y_fit.nunique() < 2:
        raise ValueError("Need at least 2 classes in chronological fit window")

    # --- Build candidate pipelines (static defaults) ---
    candidates: list[tuple[str, Pipeline]] = [("logreg", _build_logreg_pipeline())]
    lgb_pipe = _build_lgb_pipeline()
    if lgb_pipe is not None:
        candidates.append(("lightgbm", lgb_pipe))
    xgb_pipe = _build_xgb_pipeline()
    if xgb_pipe is not None:
        candidates.append(("xgboost", xgb_pipe))

    # --- Evaluate static candidates via time-based CV ---
    results: list[tuple[str, Pipeline, float]] = []
    for name, pipe in candidates:
        try:
            cv_auc = _time_cv_auc(
                pipe,
                x_fit,
                y_fit,
                dates_fit,
                sample_weight=sample_weight_fit,
                n_splits=3,
                gap_dates=horizon_days,
            )
            results.append((name, pipe, cv_auc))
        except Exception:
            continue

    # --- Optuna hyperparameter search (if available) ---
    optuna_best_params: dict[str, Any] = {}
    optuna_used = False
    if _HAS_OPTUNA and n_optuna_trials > 0 and len(x_fit) >= 100:
        try:
            optuna_results = _optuna_search(
                X=x_fit,
                y=y_fit,
                dates=dates_fit,
                sample_weight=sample_weight_fit,
                n_trials=n_optuna_trials,
                gap_dates=horizon_days,
            )
            for name, pipe, cv_auc, best_params in optuna_results:
                results.append((name, pipe, cv_auc))
                optuna_best_params[name] = best_params
            if optuna_results:
                optuna_used = True
        except Exception:
            pass

    if not results:
        raise ValueError("All candidate models failed during CV evaluation")

    # Pick winner by highest CV AUC
    results.sort(key=lambda r: r[2], reverse=True)
    winner_name, winner_pipe, winner_cv_auc = results[0]

    # Keep calibration and test windows disjoint from base-model fitting.
    _fit_pipeline(winner_pipe, x_fit, y_fit, sample_weight=sample_weight_fit)

    # --- Calibration ---
    calibrated_model = winner_pipe  # default: uncalibrated
    calibration_info: dict[str, Any] = {
        "calibrated": False,
        "evaluated_on_holdout": False,
        "fit_rows": int(len(fit_idx)),
        "calibration_rows": int(len(cal_idx)),
        "test_rows": int(len(test_idx)),
        "purge_gap_dates": int(horizon_days),
    }
    threshold_frame = prepared.loc[fit_idx]
    threshold_probs: pd.Series | None = None
    try:
        from src.model_v2.calibration import calibrate_model, evaluate_calibration

        if len(cal_idx) >= 20 and len(test_idx) >= 20:
            x_cal = x.loc[cal_idx]
            y_cal = y.loc[cal_idx].to_numpy()
            x_test = x.loc[test_idx]
            y_test = y.loc[test_idx].to_numpy()
        else:
            x_cal = pd.DataFrame()
            y_cal = np.array([])
            x_test = pd.DataFrame()
            y_test = np.array([])

        if (
            len(y_cal) >= 20
            and len(np.unique(y_cal)) >= 2
            and len(y_test) >= 20
            and len(np.unique(y_test)) >= 2
        ):
            calibrated_model = calibrate_model(winner_pipe, x_cal, y_cal, method="isotonic")
            is_calibrated = getattr(calibrated_model, "calibrator", None) is not None
            p_test = calibrated_model.predict_proba(x_test)[:, 1]
            test_diag = evaluate_calibration(y_test, p_test, n_bins=5)
            calibration_info.update(
                {
                    "calibrated": bool(is_calibrated),
                    "evaluated_on_holdout": bool(is_calibrated),
                    "ece": test_diag["ece"],
                    "holdout_auc": round(float(roc_auc_score(y_test, p_test)), 4),
                }
            )
            threshold_frame = prepared.loc[cal_idx]
            threshold_probs = pd.Series(
                calibrated_model.predict_proba(x_cal)[:, 1],
                index=cal_idx,
                dtype=float,
            )
    except Exception as exc:
        calibration_info["error"] = f"{type(exc).__name__}:{exc}"

    # --- Train metrics ---
    p_train = calibrated_model.predict_proba(x_fit)[:, 1]
    auc_train = float(roc_auc_score(y_fit, p_train)) if y_fit.nunique() > 1 else 0.5
    if threshold_probs is None:
        threshold_probs = pd.Series(p_train, index=fit_idx, dtype=float)
    thresholds_by_regime = _calibrate_regime_thresholds(
        threshold_frame,
        threshold_probs,
        settings=settings,
        mode=mode,
    )
    return_profile = _build_return_profile(prepared.loc[fit_idx])

    model_comparison = {
        name: round(auc, 4) for name, _, auc in results
    }

    metadata = {
        "train_rows": int(len(train_df)),
        "fit_rows": int(len(fit_idx)),
        "positive_rate": float(y_fit.mean()),
        "auc_train": round(auc_train, 4),
        "features": MODEL_FEATURES,
        "model_type": winner_name,
        "cv_auc": round(winner_cv_auc, 4),
        "model_comparison": model_comparison,
        "calibration": calibration_info,
        "available_models": [name for name, _, _ in results],
        "label_strategy": str(prepared.get("label_strategy", pd.Series(["binary_positive_net_return"])).iloc[0]),
        "thresholds_by_regime": thresholds_by_regime,
        "return_profile": return_profile,
        "target_rank_positive_cutoff": SWING_POSITIVE_RANK_CUTOFF if str(mode).lower() == "swing" else None,
        "optuna_used": optuna_used,
        "optuna_trials": n_optuna_trials if optuna_used else 0,
        "optuna_best_params": optuna_best_params.get(winner_name, {}),
    }
    return calibrated_model, metadata


def maybe_auto_train_model_v2(
    scored_history: pd.DataFrame,
    settings: Settings,
    force: bool = False,
) -> dict[str, Any]:
    cfg = settings.model_v2
    state = load_state(cfg.state_path)
    now = datetime.utcnow()

    status = "skipped_disabled"
    message = "Model v2 auto-train disabled"
    if not cfg.enabled or not cfg.auto_train_enabled:
        return {
            "status": status,
            "message": message,
            "updated": False,
            "state_path": cfg.state_path,
            "modes": {},
        }

    active_modes = resolve_active_modes(settings)
    missing_artifact_modes: list[str] = []
    for mode in active_modes:
        model, metadata = load_model_bundle(cfg.model_dir, mode)
        if model is None or not metadata:
            missing_artifact_modes.append(str(mode))

    if not force:
        last_at = state.get("last_success_at", "")
        if last_at and not missing_artifact_modes:
            try:
                last_dt = datetime.fromisoformat(last_at)
                if (now - last_dt) < timedelta(days=max(1, int(cfg.auto_train_interval_days))):
                    return {
                        "status": "skipped_interval",
                        "message": f"Last model_v2 training still within {cfg.auto_train_interval_days} days interval",
                        "updated": False,
                        "state_path": cfg.state_path,
                        "modes": state.get("modes", {}),
                        "artifact_check": {
                            "ready": True,
                            "missing_modes": [],
                            "forced_retrain": False,
                        },
                    }
            except Exception:
                pass

    roundtrip_cost_pct = (
        float(settings.backtest.buy_fee_pct) +
        float(settings.backtest.sell_fee_pct) +
        (2.0 * float(settings.backtest.slippage_pct))
    )

    mode_horizons = {
        "t1": int(cfg.horizon_days_t1),
        "swing": int(cfg.horizon_days_swing),
    }
    modes_cfg = {mode: horizon for mode, horizon in mode_horizons.items() if mode in active_modes}
    per_mode: dict[str, Any] = {}
    errors: list[str] = []

    for mode, horizon_days in modes_cfg.items():
        train_df = _training_rows_for_mode(
            scored_history=scored_history,
            mode=mode,
            horizon_days=horizon_days,
            roundtrip_cost_pct=roundtrip_cost_pct,
            stop_atr_mult=float(settings.risk.stop_atr_multiple),
            tp1_r_mult=float(settings.risk.tp1_r_multiple),
            train_lookback_days=int(cfg.train_lookback_days),
        )

        if len(train_df) < int(cfg.min_train_rows_per_mode):
            per_mode[mode] = {
                "status": "skipped_min_rows",
                "rows": int(len(train_df)),
                "min_rows": int(cfg.min_train_rows_per_mode),
            }
            continue

        try:
            model, metadata = _train_one_mode(
                train_df=train_df,
                mode=mode,
                settings=settings,
                horizon_days=horizon_days,
            )
            saved = save_model_bundle(
                model_dir=cfg.model_dir,
                mode=mode,
                model=model,
                metadata={
                    **metadata,
                    "mode": mode,
                    "horizon_days": int(horizon_days),
                    "trained_at": now.isoformat(),
                },
            )
            per_mode[mode] = {
                "status": "trained",
                "rows": int(len(train_df)),
                **metadata,
                **saved,
            }
        except Exception as exc:
            per_mode[mode] = {
                "status": "error",
                "rows": int(len(train_df)),
                "error": str(exc),
            }
            errors.append(f"{mode}: {exc}")

    trained_modes = [m for m, info in per_mode.items() if info.get("status") == "trained"]
    updated = len(trained_modes) > 0
    if updated:
        status = "updated"
        message = f"Model v2 trained for modes: {', '.join(trained_modes)}"
        state_payload = {
            "last_success_at": now.isoformat(),
            "updated": True,
            "modes": per_mode,
        }
        save_state(cfg.state_path, state_payload)
    else:
        status = "skipped_no_update"
        message = "No mode met minimum train rows or training failed"
        state_payload = {
            "last_success_at": state.get("last_success_at", ""),
            "updated": False,
            "modes": per_mode,
            "last_attempt_at": now.isoformat(),
            "errors": errors,
        }
        save_state(cfg.state_path, state_payload)

    remaining_missing_modes: list[str] = []
    for mode in active_modes:
        model, metadata = load_model_bundle(cfg.model_dir, mode)
        if model is None or not metadata:
            remaining_missing_modes.append(str(mode))

    return {
        "status": status,
        "message": message,
        "updated": updated,
        "state_path": cfg.state_path,
        "model_dir": cfg.model_dir,
        "modes": per_mode,
        "errors": errors,
        "artifact_check": {
            "ready": not remaining_missing_modes,
            "missing_modes": remaining_missing_modes,
            "forced_retrain": bool(missing_artifact_modes and not force),
        },
    }
