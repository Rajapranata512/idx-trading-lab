from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import Settings
from src.model_v2.io import load_model_bundle
from src.model_v2.train import MODEL_FEATURES
from src.runtime import regime_bucket_from_features


def _safe_float_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").astype(float)


def _build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = {c: _safe_float_series(df, c) for c in MODEL_FEATURES}
    return pd.DataFrame(data, index=df.index)


def _fallback_prob(df: pd.DataFrame) -> pd.Series:
    score = _safe_float_series(df, "score").clip(lower=0.0, upper=100.0) / 100.0
    atr_pct = _safe_float_series(df, "atr_pct").abs()
    vol_penalty = (atr_pct / 15.0).clip(lower=0.0, upper=0.25)
    p = (score - vol_penalty).clip(lower=0.05, upper=0.95)
    return p


def _mode_threshold(settings: Settings, mode: str) -> float:
    if str(mode).lower() == "t1":
        return float(settings.model_v2.min_prob_threshold_t1)
    return float(settings.model_v2.min_prob_threshold_swing)


def _expected_r_from_profile(
    probs: pd.Series,
    regimes: pd.Series,
    metadata: dict[str, Any],
    fallback_avg_reward_r: float,
) -> pd.Series:
    profile = metadata.get("return_profile", {}) if isinstance(metadata, dict) else {}
    overall = profile.get("overall", {}) if isinstance(profile, dict) else {}
    by_regime = profile.get("by_regime", {}) if isinstance(profile, dict) else {}

    pos_default = float(overall.get("positive_mean_r", fallback_avg_reward_r) or fallback_avg_reward_r)
    neg_default = float(overall.get("negative_mean_r", -1.0) or -1.0)

    rows: list[float] = []
    for idx in probs.index:
        p = float(probs.loc[idx])
        regime = str(regimes.loc[idx]).strip().lower()
        regime_payload = by_regime.get(regime, {}) if isinstance(by_regime, dict) else {}
        pos_mean = float(regime_payload.get("positive_mean_r", pos_default) or pos_default)
        neg_mean = float(regime_payload.get("negative_mean_r", neg_default) or neg_default)
        rows.append((p * pos_mean) + ((1.0 - p) * neg_mean))
    return pd.Series(rows, index=probs.index, dtype=float)


def infer_shadow_scores(
    candidates: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if candidates.empty:
        return candidates.copy(), {"status": "empty", "message": "No candidates for shadow inference", "modes": {}}

    df = candidates.copy()
    if "mode" not in df.columns:
        df["mode"] = "unknown"
    x_all = _build_feature_frame(df)

    out_rows: list[pd.DataFrame] = []
    mode_meta: dict[str, Any] = {}
    avg_reward_r = (float(settings.risk.tp1_r_multiple) + float(settings.risk.tp2_r_multiple)) / 2.0

    for mode, idx in df.groupby(df["mode"].astype(str).str.lower()).groups.items():
        part = df.loc[idx].copy()
        x = x_all.loc[idx].copy()
        model, metadata = load_model_bundle(settings.model_v2.model_dir, mode)
        source = "fallback"
        if model is not None:
            try:
                p = model.predict_proba(x)[:, 1]
                p_win = pd.Series(p, index=part.index, dtype=float).clip(lower=0.01, upper=0.99)
                source = "model"
            except Exception:
                p_win = _fallback_prob(part)
                source = "fallback"
        else:
            p_win = _fallback_prob(part)

        regime_bucket = regime_bucket_from_features(part, settings=settings, default="risk_off")
        thresholds_by_regime = metadata.get("thresholds_by_regime", {}) if isinstance(metadata, dict) else {}
        default_threshold = float(thresholds_by_regime.get("default", _mode_threshold(settings, mode)))
        threshold_series = regime_bucket.map(
            lambda regime: float(thresholds_by_regime.get(str(regime).strip().lower(), default_threshold))
        ).fillna(default_threshold)

        part["shadow_p_win"] = p_win.round(4)
        part["shadow_confidence"] = part["shadow_p_win"]
        part["shadow_market_regime"] = regime_bucket
        part["shadow_expected_r"] = _expected_r_from_profile(
            probs=part["shadow_p_win"],
            regimes=regime_bucket,
            metadata=metadata if isinstance(metadata, dict) else {},
            fallback_avg_reward_r=avg_reward_r,
        ).round(4)
        part["shadow_threshold"] = threshold_series.round(4)
        part["shadow_recommended"] = part["shadow_p_win"] >= part["shadow_threshold"]
        part["shadow_model_source"] = source
        out_rows.append(part)

        mode_meta[mode] = {
            "rows": int(len(part)),
            "source": source,
            "threshold": float(default_threshold),
            "thresholds_by_regime": thresholds_by_regime if isinstance(thresholds_by_regime, dict) else {},
            "metadata": metadata,
        }

    out = pd.concat(out_rows, ignore_index=True, sort=False)
    out = out.sort_values(["shadow_expected_r", "shadow_p_win", "score"], ascending=[False, False, False]).reset_index(drop=True)
    out["shadow_rank"] = range(1, len(out) + 1)

    return out, {
        "status": "ok",
        "message": "Shadow inference completed",
        "modes": mode_meta,
        "rows": int(len(out)),
    }
