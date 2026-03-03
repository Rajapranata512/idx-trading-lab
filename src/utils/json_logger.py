from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonRunLogger:
    def __init__(self, run_id: str, out_dir: str = "reports") -> None:
        self.run_id = run_id
        self.events: list[dict[str, Any]] = []
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def event(self, level: str, event: str, **extra: Any) -> None:
        self.events.append(
            {
                "ts": datetime.utcnow().isoformat(),
                "run_id": self.run_id,
                "level": level,
                "message": event,
                "extra": extra,
            }
        )

    def save(self) -> str:
        date_key = datetime.utcnow().strftime("%Y%m%d")
        out_path = self.out_dir / f"run_log_{date_key}.json"
        prior: list[dict[str, Any]] = []
        if out_path.exists():
            try:
                loaded = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    prior = loaded
            except Exception:
                prior = []
        payload = prior + self.events
        out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return str(out_path)
