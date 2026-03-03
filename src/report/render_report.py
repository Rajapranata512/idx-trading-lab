from __future__ import annotations

from jinja2 import Template
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>IDX Daily Signal Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; line-height: 1.4; }
    h1 { margin-bottom: 0; }
    .meta { color: #666; margin-top: 6px; margin-bottom: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 16px; }
    th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; }
    th { background: #f6f6f6; text-align: left; }
    .small { font-size: 12px; color: #555; }
    .section { margin-top: 28px; }
    .badge { display: inline-block; padding: 2px 8px; background: #f0f0f0; border-radius: 999px; font-size: 11px; }
  </style>
</head>
<body>
  <h1>IDX Daily Signal Report</h1>
  <div class="meta">Generated: {{ generated_at }}</div>
  <div class="meta">Run ID: {{ run_id }}</div>
  <div class="meta">Data source: {{ data_source }} | Max date: {{ max_data_date }}</div>
  <div class="meta">Universe: {{ universe_name }}</div>
  <p class="small">
    This report is research output, not financial advice. Always validate with your own risk rules.
  </p>

  <div class="section">
    <h2>Risk Summary</h2>
    <div class="small">
      risk/trade={{ risk_summary.risk_per_trade_pct }}% |
      max_positions={{ risk_summary.max_positions }} |
      daily_loss_stop={{ risk_summary.daily_loss_stop_r }}R |
      vol_target={{ risk_summary.vol_target_enabled }} (mode={{ risk_summary.vol_target_mode }}, ref ATR%={{ risk_summary.vol_target_ref_atr_pct }}, ref RV%={{ risk_summary.vol_target_ref_realized_pct }}, wRV={{ risk_summary.vol_target_realized_weight }}, cap={{ risk_summary.vol_target_cap_base }}) |
      regime_cap={{ risk_summary.vol_target_regime_cap_enabled }} (high={{ risk_summary.vol_target_regime_cap_high }}, stress={{ risk_summary.vol_target_regime_cap_stress }}) |
      max_position_exposure={{ risk_summary.max_position_exposure_pct }}%
    </div>
  </div>

  <div class="section">
    <h2>Top T+1 Picks <span class="badge">T+1</span></h2>
    <table>
      <thead>
        <tr>
          {% for c in table_columns %}
            <th>{{ c }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in top_t1_rows %}
          <tr>
            {% for c in table_columns %}
              <td>{{ row[c] }}</td>
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Top Swing Picks <span class="badge">1-4w</span></h2>
    <table>
      <thead>
        <tr>
          {% for c in table_columns %}
            <th>{{ c }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in top_swing_rows %}
          <tr>
            {% for c in table_columns %}
              <td>{{ row[c] }}</td>
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</body>
</html>
"""

def _normalized_records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    out = df.copy()
    numeric_cols = [
        "score",
        "entry",
        "stop",
        "tp1",
        "tp2",
        "size",
        "position_value",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = out[col].round(2)
    return out.to_dict(orient="records")


def render_html_report(
    top_t1: pd.DataFrame,
    top_swing: pd.DataFrame,
    out_path: str,
    run_id: str,
    data_source: str,
    max_data_date: str,
    universe_name: str,
    risk_summary: dict,
) -> str:
    template = Template(HTML_TEMPLATE)
    base_columns = [
        "rank",
        "ticker",
        "score",
        "entry",
        "stop",
        "tp1",
        "tp2",
        "size",
        "reason",
    ]
    optional_columns = [
        "vol_target_multiplier",
        "vol_target_market_regime",
        "vol_target_regime_cap",
    ]
    available_cols = set(top_t1.columns.tolist() + top_swing.columns.tolist())
    table_columns = base_columns + [c for c in optional_columns if c in available_cols]
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": run_id,
        "data_source": data_source,
        "max_data_date": max_data_date,
        "universe_name": universe_name,
        "risk_summary": risk_summary,
        "table_columns": table_columns,
        "top_t1_rows": _normalized_records(top_t1[table_columns]) if not top_t1.empty else [],
        "top_swing_rows": _normalized_records(top_swing[table_columns]) if not top_swing.empty else [],
    }
    html = template.render(**payload)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


def write_signal_json(df: pd.DataFrame, out_path: str) -> str:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = _normalized_records(df)
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "signals": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(out)
