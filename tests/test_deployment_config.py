from __future__ import annotations

from pathlib import Path


def test_deployment_entrypoints_use_web_server_module() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "Dockerfile",
        root / "deploy/systemd/idx-web.service.example",
        root / "deploy/oracle/bootstrap_oracle.sh",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "src.web.server" in text
        assert "serve-web" not in text


def test_oracle_intraday_service_uses_daemon_module() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "deploy/oracle/bootstrap_oracle.sh").read_text(encoding="utf-8")

    assert "src.intraday.daemon" in text
    assert "run-intraday-daemon" not in text
