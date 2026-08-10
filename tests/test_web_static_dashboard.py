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

def test_market_session_freshness_is_wired_to_static_dashboard() -> None:
    index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    dashboard_js = (ROOT / "web" / "js" / "dashboard.js").read_text(encoding="utf-8")
    freshness_js = ROOT / "web" / "js" / "market-freshness.js"
    calendar = ROOT / "web" / "idx_market_calendar.json"

    assert 'src="js/market-freshness.js"' in index_html
    assert index_html.index("js/market-freshness.js") < index_html.index("js/dashboard.js")
    assert "data_quality_report.json" in dashboard_js
    assert "idx_market_calendar.json" in dashboard_js
    assert "calculateFreshness" in dashboard_js
    assert "qualityBanner" in dashboard_js
    assert "Freshness tanggal pasar dinilai terpisah" in dashboard_js
    assert freshness_js.exists()
    assert calendar.exists()
