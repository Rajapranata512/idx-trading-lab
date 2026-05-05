from __future__ import annotations

import base64
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.web.server import DashboardHTTPServer


class DummyJobManager:
    def counts(self) -> dict[str, int]:
        return {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}

    def list_jobs(self, limit: int = 15) -> list[dict[str, object]]:
        return []

    def get(self, job_id: str) -> dict[str, object] | None:
        return None

    def submit(self, settings_path: str, skip_telegram: bool = True) -> dict[str, object]:
        return {
            "job_id": "job-test-001",
            "status": "queued",
            "submitted_at": "2026-03-26T00:00:00",
            "started_at": "",
            "ended_at": "",
            "result": None,
            "error": "",
        }


@contextmanager
def running_server(tmp_path: Path):
    static_dir = tmp_path / "web"
    reports_dir = tmp_path / "reports"
    static_dir.mkdir()
    reports_dir.mkdir()
    (static_dir / "index.html").write_text("legacy-home", encoding="utf-8")
    (static_dir / "premium-dashboard.html").write_text("premium-home", encoding="utf-8")
    (static_dir / "close-analysis.html").write_text("close-shell", encoding="utf-8")
    (static_dir / "ops-login.html").write_text("ops-login-shell", encoding="utf-8")
    (static_dir / "ops-report.html").write_text("ops-report-shell", encoding="utf-8")
    (reports_dir / "daily_report.html").write_text("<html>report</html>", encoding="utf-8")

    server = DashboardHTTPServer(
        host="127.0.0.1",
        port=0,
        static_dir=static_dir,
        reports_dir=reports_dir,
        settings_path="config/settings.json",
    )
    server.job_manager = DummyJobManager()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def http_call(base_url: str, path: str, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None):
    request = Request(f"{base_url}{path}", method=method, data=data, headers=headers or {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8")


def test_root_serves_premium_dashboard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("IDX_WEB_USERNAME", raising=False)
    monkeypatch.delenv("IDX_WEB_PASSWORD", raising=False)

    with running_server(tmp_path) as base_url:
        status_root, _, body_root = http_call(base_url, "/")
        status_index, _, body_index = http_call(base_url, "/index.html")
        status_legacy, _, body_legacy = http_call(base_url, "/legacy-console.html")
        status_ops_login, _, body_ops_login = http_call(base_url, "/ops-login.html")
        status_ops_report, _, body_ops_report = http_call(base_url, "/ops-report.html")

    assert status_root == 200
    assert body_root == "premium-home"
    assert status_index == 200
    assert body_index == "premium-home"
    assert status_legacy == 404
    assert "Page not found" in body_legacy
    assert status_ops_login == 200
    assert body_ops_login == "ops-login-shell"
    assert status_ops_report == 200
    assert body_ops_report == "ops-report-shell"


def test_operational_routes_require_basic_auth_when_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDX_WEB_USERNAME", "ops")
    monkeypatch.setenv("IDX_WEB_PASSWORD", "secret123")
    auth_value = base64.b64encode(b"ops:secret123").decode("ascii")

    with running_server(tmp_path) as base_url:
        status_jobs, headers_jobs, body_jobs = http_call(base_url, "/api/jobs")
        status_jobs_auth, _, body_jobs_auth = http_call(
            base_url,
            "/api/jobs",
            headers={"Authorization": f"Basic {auth_value}"},
        )
        status_run_daily, headers_run_daily, body_run_daily = http_call(
            base_url,
            "/api/run-daily",
            method="POST",
            data=json.dumps({"skip_telegram": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        status_close_analysis, headers_close_analysis, body_close_analysis = http_call(base_url, "/api/close-analysis")
        status_close_page, _, body_close_page = http_call(base_url, "/close-analysis.html")
        status_run_daily_auth, _, body_run_daily_auth = http_call(
            base_url,
            "/api/run-daily",
            method="POST",
            data=json.dumps({"skip_telegram": True}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth_value}",
            },
        )

    assert status_jobs == 401
    assert headers_jobs.get("WWW-Authenticate") == 'Basic realm="IDX Trading Lab Ops"'
    assert "Authentication required" in body_jobs

    assert status_jobs_auth == 200
    assert json.loads(body_jobs_auth)["items"] == []

    assert status_run_daily == 401
    assert headers_run_daily.get("WWW-Authenticate") == 'Basic realm="IDX Trading Lab Ops"'
    assert "Authentication required" in body_run_daily

    assert status_close_analysis == 401
    assert headers_close_analysis.get("WWW-Authenticate") == 'Basic realm="IDX Trading Lab Ops"'
    assert "Authentication required" in body_close_analysis

    assert status_close_page == 200
    assert body_close_page == "close-shell"

    assert status_run_daily_auth == 202
    assert json.loads(body_run_daily_auth)["job"]["job_id"] == "job-test-001"


def test_ops_login_allowlist_blocks_non_allowlisted_ip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("IDX_WEB_USERNAME", raising=False)
    monkeypatch.delenv("IDX_WEB_PASSWORD", raising=False)
    monkeypatch.setenv("IDX_WEB_OPS_LOGIN_ALLOWLIST", "10.10.10.10")

    with running_server(tmp_path) as base_url:
        status, _, body = http_call(base_url, "/ops-login.html")

    assert status == 403
    assert "Forbidden" in body


def test_ops_login_rate_limit_returns_429(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("IDX_WEB_USERNAME", raising=False)
    monkeypatch.delenv("IDX_WEB_PASSWORD", raising=False)
    monkeypatch.delenv("IDX_WEB_OPS_LOGIN_ALLOWLIST", raising=False)
    monkeypatch.setenv("IDX_WEB_OPS_LOGIN_RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("IDX_WEB_OPS_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")

    with running_server(tmp_path) as base_url:
        first_status, _, first_body = http_call(base_url, "/ops-login.html")
        second_status, _, second_body = http_call(base_url, "/ops-login.html")

    assert first_status == 200
    assert first_body == "ops-login-shell"
    assert second_status == 429
    assert "Too many requests" in second_body


def test_failed_auth_attempts_trigger_temporary_lockout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDX_WEB_USERNAME", "ops")
    monkeypatch.setenv("IDX_WEB_PASSWORD", "secret123")
    monkeypatch.setenv("IDX_WEB_AUTH_LOCKOUT_MAX_FAILURES", "2")
    monkeypatch.setenv("IDX_WEB_AUTH_LOCKOUT_SECONDS", "60")

    wrong_auth = base64.b64encode(b"ops:wrong-password").decode("ascii")
    right_auth = base64.b64encode(b"ops:secret123").decode("ascii")

    with running_server(tmp_path) as base_url:
        first_status, first_headers, first_body = http_call(
            base_url,
            "/api/jobs",
            headers={"Authorization": f"Basic {wrong_auth}"},
        )
        second_status, _, second_body = http_call(
            base_url,
            "/api/jobs",
            headers={"Authorization": f"Basic {wrong_auth}"},
        )
        third_status, _, third_body = http_call(
            base_url,
            "/api/jobs",
            headers={"Authorization": f"Basic {right_auth}"},
        )

    assert first_status == 401
    assert first_headers.get("WWW-Authenticate") == 'Basic realm="IDX Trading Lab Ops"'
    assert "Authentication required" in first_body
    assert second_status == 429
    assert "Too many failed login attempts" in second_body
    assert third_status == 429
    assert "Too many failed login attempts" in third_body
