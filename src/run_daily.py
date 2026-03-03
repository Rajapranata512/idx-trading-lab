from __future__ import annotations

import argparse
import json

from src.cli import run_daily
from src.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Backward-compatible daily runner")
    parser.add_argument("--settings", default="config/settings.json")
    parser.add_argument("--skip-telegram", action="store_true")
    args = parser.parse_args()

    settings = load_settings(args.settings)
    result = run_daily(settings=settings, skip_telegram=args.skip_telegram, settings_path=args.settings)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
