from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import ipaddress
import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

from src.utils import load_env_file
from src.web.service import (
    RunJobManager,
    build_dashboard_snapshot,
    query_close_analysis,
    query_close_prices,
    query_signals,
    query_ticker_detail,
)


def _parse_allowlist(value: str) -> list[ipaddress._BaseNetwork]:
    items: list[ipaddress._BaseNetwork] = []
    for part in str(value or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if "/" in token:
                items.append(ipaddress.ip_network(token, strict=False))
            else:
                items.append(ipaddress.ip_network(f"{token}/32", strict=False))
        except ValueError:
            try:
                items.append(ipaddress.ip_network(f"{token}/128", strict=False))
            except ValueError:
                continue
    return items


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        static_dir: str | Path,
        reports_dir: str | Path,
        settings_path: str,
    ) -> None:
        super().__init__((host, port), DashboardRequestHandler)
        self.static_dir = Path(static_dir).resolve()
        self.reports_dir = Path(reports_dir).resolve()
        self.settings_path = settings_path
        self.job_manager = RunJobManager()
        self.auth_username = os.getenv("IDX_WEB_USERNAME", "").strip()
        self.auth_password = os.getenv("IDX_WEB_PASSWORD", "").strip()
        self.ops_login_allowlist = _parse_allowlist(os.getenv("IDX_WEB_OPS_LOGIN_ALLOWLIST", ""))
        self.ops_login_rate_limit_max_requests = _env_int("IDX_WEB_OPS_LOGIN_RATE_LIMIT_MAX_REQUESTS", default=12)
        self.ops_login_rate_limit_window_seconds = _env_int("IDX_WEB_OPS_LOGIN_RATE_LIMIT_WINDOW_SECONDS", default=60)
        self.auth_lockout_max_failures = _env_int("IDX_WEB_AUTH_LOCKOUT_MAX_FAILURES", default=5)
        self.auth_lockout_seconds = _env_int("IDX_WEB_AUTH_LOCKOUT_SECONDS", default=300)
        self._ops_login_hits: dict[str, list[float]] = {}
        self._ops_login_lock = threading.Lock()
        self._auth_failures: dict[str, list[float]] = {}
        self._auth_locked_until: dict[str, float] = {}
        self._auth_lock = threading.Lock()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "IDXTradingLabWeb/1.0"

    def _server(self) -> DashboardHTTPServer:
        return self.server  # type: ignore[return-value]

    def _premium_entrypoint(self) -> Path:
        return self._server().static_dir / "premium-dashboard.html"

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, text: str, content_type: str, status: int = HTTPStatus.OK) -> None:
        raw = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _resolve_static_path(self, request_path: str) -> Path | None:
        static_dir = self._server().static_dir
        rel = request_path.lstrip("/")
        target = (static_dir / rel).resolve()
        if str(target).startswith(str(static_dir)):
            return target
        return None

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        content_type, _ = mimetypes.guess_type(path.name)
        if not content_type:
            content_type = "application/octet-stream"
        raw = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def _is_loopback_client(self) -> bool:
        host = str(self.client_address[0] if self.client_address else "").strip().lower()
        return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")

    def _client_ip(self) -> str:
        return str(self.client_address[0] if self.client_address else "").strip()

    def _is_ops_login_ip_allowed(self) -> bool:
        srv = self._server()
        if not srv.ops_login_allowlist:
            return True
        try:
            ip_obj = ipaddress.ip_address(self._client_ip())
        except ValueError:
            return False
        return any(ip_obj in network for network in srv.ops_login_allowlist)

    def _consume_ops_login_rate_limit(self) -> bool:
        srv = self._server()
        now = time.time()
        window = float(srv.ops_login_rate_limit_window_seconds)
        with srv._ops_login_lock:
            hits = srv._ops_login_hits.get(self._client_ip(), [])
            hits = [stamp for stamp in hits if now - stamp <= window]
            if len(hits) >= srv.ops_login_rate_limit_max_requests:
                srv._ops_login_hits[self._client_ip()] = hits
                return False
            hits.append(now)
            srv._ops_login_hits[self._client_ip()] = hits
        return True

    def _is_auth_locked_out(self) -> bool:
        srv = self._server()
        now = time.time()
        client_ip = self._client_ip()
        with srv._auth_lock:
            locked_until = float(srv._auth_locked_until.get(client_ip, 0.0))
            if locked_until and locked_until > now:
                return True
            if locked_until and locked_until <= now:
                srv._auth_locked_until.pop(client_ip, None)
                srv._auth_failures.pop(client_ip, None)
        return False

    def _register_failed_auth_attempt(self) -> None:
        srv = self._server()
        now = time.time()
        client_ip = self._client_ip()
        window = float(srv.auth_lockout_seconds)
        with srv._auth_lock:
            attempts = srv._auth_failures.get(client_ip, [])
            attempts = [stamp for stamp in attempts if now - stamp <= window]
            attempts.append(now)
            srv._auth_failures[client_ip] = attempts
            if len(attempts) >= srv.auth_lockout_max_failures:
                srv._auth_locked_until[client_ip] = now + srv.auth_lockout_seconds

    def _clear_failed_auth_attempts(self) -> None:
        srv = self._server()
        client_ip = self._client_ip()
        with srv._auth_lock:
            srv._auth_failures.pop(client_ip, None)
            srv._auth_locked_until.pop(client_ip, None)

    def _operational_auth_enabled(self) -> bool:
        srv = self._server()
        return bool(srv.auth_username and srv.auth_password)

    def _has_valid_operational_auth(self) -> bool:
        if not self._operational_auth_enabled():
            return True
        if self._is_auth_locked_out():
            return False
        header = str(self.headers.get("Authorization", "")).strip()
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header.split(" ", 1)[1].strip()).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return False
        username, sep, password = raw.partition(":")
        if not sep:
            return False
        srv = self._server()
        is_valid = hmac.compare_digest(username, srv.auth_username) and hmac.compare_digest(password, srv.auth_password)
        if is_valid:
            self._clear_failed_auth_attempts()
            return True
        self._register_failed_auth_attempt()
        return False

    def _send_auth_required(self) -> None:
        if self._is_auth_locked_out():
            payload = json.dumps(
                {
                    "error": "Too many failed login attempts. Please wait before trying again."
                },
                ensure_ascii=True,
                indent=2,
            ).encode("utf-8")
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps({"error": "Authentication required for operational routes"}, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("WWW-Authenticate", 'Basic realm="IDX Trading Lab Ops"')
        self.end_headers()
        self.wfile.write(payload)

    def _require_operational_auth(self) -> bool:
        if self._has_valid_operational_auth():
            return True
        self._send_auth_required()
        return False

    def _requires_operational_auth(self, path: str) -> bool:
        if path in {
            "/report",
            "/api/report-html",
            "/api/close-analysis",
            "/api/close-prices",
        }:
            return True
        return path == "/api/jobs" or path.startswith("/api/jobs/")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path or "/"

        if path == "/ops-login.html":
            if not self._is_ops_login_ip_allowed():
                self._send_json({"error": "Forbidden"}, status=HTTPStatus.FORBIDDEN)
                return
            if not self._consume_ops_login_rate_limit():
                self._send_json({"error": "Too many requests"}, status=HTTPStatus.TOO_MANY_REQUESTS)
                return

        if self._requires_operational_auth(path) and not self._require_operational_auth():
            return

        if path.startswith("/api/"):
            self._handle_api_get(path=path, query=parse_qs(parsed.query))
            return

        self._handle_static(path=path)

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        srv = self._server()
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "idx-trading-lab-web",
                    "jobs": srv.job_manager.counts(),
                }
            )
            return

        if path == "/api/dashboard":
            self._send_json(build_dashboard_snapshot(reports_dir=srv.reports_dir, signal_limit=300))
            return

        if path == "/api/signals":
            mode = (query.get("mode", [""])[0] or "").strip()
            ticker = (query.get("ticker", [""])[0] or "").strip()
            min_score_raw = (query.get("min_score", [""])[0] or "").strip()
            limit_raw = (query.get("limit", ["100"])[0] or "100").strip()
            min_score = float(min_score_raw) if min_score_raw else None
            try:
                limit = max(1, int(limit_raw))
            except ValueError:
                limit = 100
            payload = query_signals(
                reports_dir=srv.reports_dir,
                mode=mode,
                min_score=min_score,
                ticker_query=ticker,
                limit=limit,
            )
            self._send_json(payload)
            return

        if path == "/api/close-analysis":
            ticker = (query.get("ticker", [""])[0] or "").strip()
            min_close_raw = (query.get("min_close", [""])[0] or "").strip()
            min_avg_volume_raw = (query.get("min_avg_volume", [""])[0] or "").strip()
            limit_raw = (query.get("limit", ["0"])[0] or "0").strip()
            min_close = float(min_close_raw) if min_close_raw else None
            min_avg_volume = float(min_avg_volume_raw) if min_avg_volume_raw else None
            try:
                limit = int(limit_raw)
            except ValueError:
                limit = 0
            payload = query_close_analysis(
                reports_dir=srv.reports_dir,
                ticker_query=ticker,
                min_close=min_close,
                min_avg_volume=min_avg_volume,
                limit=limit,
            )
            self._send_json(payload)
            return

        if path == "/api/close-prices":
            ticker = (query.get("ticker", [""])[0] or "").strip()
            start_date = (query.get("start_date", [""])[0] or "").strip()
            end_date = (query.get("end_date", [""])[0] or "").strip()
            limit_raw = (query.get("limit", ["0"])[0] or "0").strip()
            try:
                limit = int(limit_raw)
            except ValueError:
                limit = 0
            payload = query_close_prices(
                reports_dir=srv.reports_dir,
                ticker_query=ticker,
                start_date=start_date or None,
                end_date=end_date or None,
                limit=limit,
            )
            self._send_json(payload)
            return

        if path == "/api/ticker-detail":
            ticker = (query.get("ticker", [""])[0] or "").strip()
            bars_raw = (query.get("bars", ["180"])[0] or "180").strip()
            try:
                bars = max(20, min(1000, int(bars_raw)))
            except ValueError:
                bars = 180
            if not ticker:
                self._send_json({"error": "ticker query parameter is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            payload = query_ticker_detail(ticker=ticker, reports_dir=srv.reports_dir, bars=bars)
            self._send_json(payload)
            return

        if path == "/api/jobs":
            self._send_json({"items": srv.job_manager.list_jobs(limit=15), "counts": srv.job_manager.counts()})
            return

        if path.startswith("/api/jobs/"):
            job_id = path.split("/api/jobs/", 1)[1].strip()
            job = srv.job_manager.get(job_id)
            if job is None:
                self._send_json({"error": "Job not found", "job_id": job_id}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return

        if path == "/api/report-html":
            report_path = srv.reports_dir / "daily_report.html"
            if not report_path.exists():
                self._send_json({"error": "Report not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_text(report_path.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            return

        self._send_json({"error": "Unsupported endpoint"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run-daily":
            self._handle_run_daily_post()
            return
        self._send_json({"error": "Unsupported endpoint"}, status=HTTPStatus.NOT_FOUND)

    def _handle_run_daily_post(self) -> None:
        srv = self._server()
        if not self._require_operational_auth():
            return
        if not self._is_loopback_client():
            self._send_json(
                {"error": "run-daily is available only from localhost for safety"},
                status=HTTPStatus.FORBIDDEN,
            )
            return
        payload = self._read_json_body()
        skip_telegram = bool(payload.get("skip_telegram", True))
        job = srv.job_manager.submit(settings_path=srv.settings_path, skip_telegram=skip_telegram)
        self._send_json({"message": "run-daily submitted", "job": job}, status=HTTPStatus.ACCEPTED)

    def _handle_static(self, path: str) -> None:
        srv = self._server()
        if path in ("", "/", "/index.html", "/premium-dashboard", "/premium-dashboard.html"):
            self._serve_file(self._premium_entrypoint())
            return
        if path in ("/legacy-console", "/legacy-console.html"):
            self._send_json({"error": "Page not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path == "/report":
            report_path = srv.reports_dir / "daily_report.html"
            if report_path.exists():
                self._serve_file(report_path)
            else:
                self._send_json({"error": "Report not found"}, status=HTTPStatus.NOT_FOUND)
            return

        candidate = self._resolve_static_path(path)
        if candidate and candidate.exists() and candidate.is_file():
            self._serve_file(candidate)
            return

        if path.endswith(".html"):
            self._send_json({"error": "Page not found"}, status=HTTPStatus.NOT_FOUND)
            return

        # Frontend routing fallback: return the premium dashboard entry point.
        self._serve_file(self._premium_entrypoint())


def start_web_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    settings_path: str = "config/settings.json",
    reports_dir: str = "reports",
    static_dir: str | None = None,
    open_browser: bool = False,
) -> None:
    load_env_file()
    project_root = Path(__file__).resolve().parents[2]
    resolved_static = Path(static_dir).resolve() if static_dir else (project_root / "web").resolve()
    if not resolved_static.exists():
        raise FileNotFoundError(f"Static web directory not found: {resolved_static}")

    server = DashboardHTTPServer(
        host=host,
        port=port,
        static_dir=resolved_static,
        reports_dir=reports_dir,
        settings_path=settings_path,
    )
    url = f"http://{host}:{port}"
    print(json.dumps({"web_url": url, "static_dir": str(resolved_static)}, ensure_ascii=True))
    is_loopback_bind = host in {"127.0.0.1", "::1", "localhost"}
    if not is_loopback_bind and not (server.auth_username and server.auth_password):
        print(
            json.dumps(
                {
                    "warning": "Operational auth is disabled. Set IDX_WEB_USERNAME and IDX_WEB_PASSWORD before exposing this server publicly."
                },
                ensure_ascii=True,
            )
        )
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IDX Trading Lab Web Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--settings", default="config/settings.json")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--static-dir", default="")
    parser.add_argument("--open-browser", action="store_true")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    start_web_server(
        host=args.host,
        port=args.port,
        settings_path=args.settings,
        reports_dir=args.reports_dir,
        static_dir=(args.static_dir or None),
        open_browser=args.open_browser,
    )


if __name__ == "__main__":
    main()
