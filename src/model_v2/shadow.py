from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import Settings
from src.model_v2.predict import infer_shadow_scores
from src.model_v2.train import maybe_auto_train_model_v2
from src.utils import atomic_write_json


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    return atomic_write_json(path, payload)


def _to_signal_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    keep = [
        "ticker",
        "mode",
        "score",
        "shadow_rank",
        "shadow_p_win",
        "shadow_expected_r",
        "shadow_threshold",
        "shadow_recommended",
        "shadow_model_source",
        "entry",
        "stop",
        "tp1",
        "tp2",
        "size",
    ]
    cols = [c for c in keep if c in df.columns]
    out = df[cols].copy()
    for col in ["score", "shadow_p_win", "shadow_expected_r", "shadow_threshold", "entry", "stop", "tp1", "tp2"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(4)
    if "size" in out.columns:
        out["size"] = pd.to_numeric(out["size"], errors="coerce").fillna(0).astype(int)
    return out.to_dict(orient="records")


def _ab_test_payload(v1: pd.DataFrame, v2: pd.DataFrame, max_positions: int) -> dict[str, Any]:
    def _safe_mean(series: pd.Series) -> float:
        numeric = pd.to_numeric(series, errors="coerce")
        value = numeric.mean()
        if pd.isna(value):
            return 0.0
        return float(value)

    v1_top = v1.sort_values("score", ascending=False).head(max_positions).copy() if "score" in v1.columns else v1.head(max_positions).copy()
    if "shadow_p_win" in v2.columns:
        v2_ranked = v2.sort_values("shadow_p_win", ascending=False).copy()
    else:
        v2_ranked = v2.copy()

    v2_reco = v2_ranked[v2_ranked.get("shadow_recommended", False) == True].copy() if "shadow_recommended" in v2_ranked.columns else v2_ranked
    if v2_reco.empty:
        v2_reco = v2_ranked
    v2_top = v2_reco.head(max_positions).copy()

    set_v1 = set(v1_top.get("ticker", pd.Series(dtype=str)).astype(str).tolist())
    set_v2 = set(v2_top.get("ticker", pd.Series(dtype=str)).astype(str).tolist())
    overlap = sorted(set_v1 & set_v2)
    union = sorted(set_v1 | set_v2)
    only_v1 = sorted(set_v1 - set_v2)
    only_v2 = sorted(set_v2 - set_v1)
    jaccard = (len(overlap) / len(union)) if union else 0.0

    payload = {
        "max_positions": int(max_positions),
        "v1_top": v1_top.get("ticker", pd.Series(dtype=str)).astype(str).tolist(),
        "v2_top": v2_top.get("ticker", pd.Series(dtype=str)).astype(str).tolist(),
        "overlap_count": int(len(overlap)),
        "overlap_tickers": overlap,
        "only_v1": only_v1,
        "only_v2": only_v2,
        "jaccard_overlap": round(float(jaccard), 4),
        "v1_avg_score": round(_safe_mean(v1_top.get("score", pd.Series(dtype=float))), 4),
        "v2_avg_p_win": round(_safe_mean(v2_top.get("shadow_p_win", pd.Series(dtype=float))), 4),
    }
    return payload


def run_model_v2_shadow(
    settings: Settings,
    scored_history: pd.DataFrame,
    candidates: pd.DataFrame,
    run_id: str,
) -> dict[str, Any]:
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    train_info = maybe_auto_train_model_v2(scored_history=scored_history, settings=settings, force=False)
    shadow_df, infer_info = infer_shadow_scores(candidates=candidates, settings=settings)

    csv_path = reports_dir / "model_v2_shadow_signals.csv"
    json_path = reports_dir / "model_v2_shadow_signals.json"
    ab_path = reports_dir / "model_v2_ab_test.json"

    if shadow_df.empty:
        shadow_df.to_csv(csv_path, index=False)
        signal_payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "signals": [],
            "infer": infer_info,
            "train": train_info,
        }
        _write_json(json_path, signal_payload)
        ab_payload = _ab_test_payload(candidates, shadow_df, settings.risk.max_positions)
        _write_json(ab_path, {"generated_at": datetime.utcnow().isoformat(), "run_id": run_id, **ab_payload})
        return {
            "status": "empty",
            "message": "No shadow signals",
            "shadow_csv_path": str(csv_path),
            "shadow_json_path": str(json_path),
            "ab_test_path": str(ab_path),
            "train": train_info,
            "infer": infer_info,
        }

    shadow_df.to_csv(csv_path, index=False)
    signal_payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "signals": _to_signal_rows(shadow_df),
        "infer": infer_info,
        "train": train_info,
    }
    _write_json(json_path, signal_payload)

    ab_payload = _ab_test_payload(candidates, shadow_df, settings.risk.max_positions)
    _write_json(ab_path, {"generated_at": datetime.utcnow().isoformat(), "run_id": run_id, **ab_payload})

    return {
        "status": "ok",
        "message": "Model v2 shadow inference completed",
        "shadow_csv_path": str(csv_path),
        "shadow_json_path": str(json_path),
        "ab_test_path": str(ab_path),
        "rows": int(len(shadow_df)),
        "train": train_info,
        "infer": infer_info,
        "ab_test": ab_payload,
    }
