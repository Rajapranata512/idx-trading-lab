from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_model_v2_accuracy_audit_panel_is_wired_to_static_dashboard() -> None:
    dashboard_js = (ROOT / "web" / "js" / "dashboard.js").read_text(encoding="utf-8")
    dashboard_css = (ROOT / "web" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert "model_v2_accuracy_audit.json" in dashboard_js
    assert "Model V2 Accuracy Audit" in dashboard_js
    assert "renderAccuracyAudit" in dashboard_js
    assert "Weak Tickers" in dashboard_js
    assert "Weak Regimes" in dashboard_js
    assert ".audit-metric-grid" in dashboard_css
    assert (ROOT / "web" / "reports" / "model_v2_accuracy_audit.json").exists()
