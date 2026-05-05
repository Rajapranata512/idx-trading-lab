import json
import os
from pathlib import Path
from src.web.service import build_dashboard_snapshot, query_ticker_detail

def export_static():
    reports_dir = Path("reports").resolve()
    web_dir = Path("web").resolve()
    
    # 1. Export Dashboard
    print("Exporting public_dashboard.json...")
    dashboard_payload = build_dashboard_snapshot(reports_dir=reports_dir, signal_limit=300)
    with open(web_dir / "public_dashboard.json", "w") as f:
        json.dump(dashboard_payload, f, indent=2)
    
    # 2. Export Ticker Details for all signals
    signals = dashboard_payload.get("signals", {}).get("items", [])
    print(f"Exporting details for {len(signals)} signals...")
    for sig in signals:
        ticker = sig.get("ticker")
        if ticker:
            try:
                detail = query_ticker_detail(ticker=ticker, reports_dir=reports_dir, bars=180)
                with open(web_dir / f"public_detail_{ticker}.json", "w") as f:
                    json.dump(detail, f, indent=2)
            except Exception as e:
                print(f"Error exporting {ticker}: {e}")
                
    print("Static export complete!")

if __name__ == "__main__":
    export_static()
