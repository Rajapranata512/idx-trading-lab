#!/usr/bin/env python3
"""Lightweight dashboard server for idx-trading-lab.

Usage:
    python scripts/serve_dashboard.py
    python scripts/serve_dashboard.py 9000   # custom port
"""
import http.server
import os
import sys
import webbrowser
from pathlib import Path

PORT = 8501
ROOT = Path(__file__).resolve().parent.parent


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, format, *args):
        if "/reports/" in self.path or self.path.endswith(".html"):
            super().log_message(format, *args)


def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    with http.server.HTTPServer(("127.0.0.1", port), DashboardHandler) as httpd:
        url = f"http://localhost:{port}/frontend/"
        print()
        print("  +-------------------------------------------+")
        print("  |       IDX Trading Lab Dashboard           |")
        print(f"  |  {url:<41s} |")
        print("  |  Press Ctrl+C to stop                     |")
        print("  +-------------------------------------------+")
        print()
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
