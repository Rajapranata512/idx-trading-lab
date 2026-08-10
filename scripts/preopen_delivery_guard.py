from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any
from urllib import parse, request
from zoneinfo import ZoneInfo


_ACTIVE_STATUSES = {"queued", "in_progress", "pending", "requested", "waiting"}


def _run_local_date(run: dict[str, Any], timezone_name: str) -> str:
    created_at = str(run.get("created_at", "")).strip()
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()


def decide_preopen_delivery(
    runs: list[dict[str, Any]],
    current_run_id: int,
    delivery_date: str,
    timezone_name: str = "Asia/Jakarta",
) -> dict[str, Any]:
    same_day: list[dict[str, Any]] = []
    for run in runs:
        try:
            run_id = int(run.get("id", 0) or 0)
            if run_id == int(current_run_id):
                continue
            if _run_local_date(run, timezone_name) != delivery_date:
                continue
        except (TypeError, ValueError):
            continue
        same_day.append(run)

    successful = [
        run
        for run in same_day
        if str(run.get("status", "")).lower() == "completed"
        and str(run.get("conclusion", "")).lower() == "success"
    ]
    active = [
        run
        for run in same_day
        if str(run.get("status", "")).lower() in _ACTIVE_STATUSES
    ]
    if successful:
        previous = max(successful, key=lambda row: str(row.get("created_at", "")))
        return {
            "should_send": False,
            "reason": "already_delivered",
            "previous_run_id": int(previous.get("id", 0) or 0),
            "delivery_date": delivery_date,
        }
    if active:
        previous = max(active, key=lambda row: str(row.get("created_at", "")))
        return {
            "should_send": False,
            "reason": "delivery_run_active",
            "previous_run_id": int(previous.get("id", 0) or 0),
            "delivery_date": delivery_date,
        }
    return {
        "should_send": True,
        "reason": "delivery_missing",
        "previous_run_id": 0,
        "delivery_date": delivery_date,
    }


def fetch_workflow_runs(
    api_url: str,
    repository: str,
    workflow: str,
    token: str,
) -> list[dict[str, Any]]:
    encoded_workflow = parse.quote(workflow, safe="")
    url = (
        f"{api_url.rstrip('/')}/repos/{repository}/actions/workflows/"
        f"{encoded_workflow}/runs?per_page=50"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "idx-trading-lab-preopen-guard",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with request.urlopen(request.Request(url, headers=headers), timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    runs = payload.get("workflow_runs", [])
    if not isinstance(runs, list):
        raise ValueError("GitHub workflow-runs response is not list-like")
    return [row for row in runs if isinstance(row, dict)]


def _write_github_output(result: dict[str, Any]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines = [
        f"should_send={'true' if result.get('should_send') else 'false'}",
        f"reason={result.get('reason', '')}",
        f"delivery_date={result.get('delivery_date', '')}",
        f"previous_run_id={result.get('previous_run_id', 0)}",
    ]
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotent Model V2 pre-open delivery guard")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--timezone", default="Asia/Jakarta")
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--on-api-error", choices=["send", "fail"], default="send")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "").strip()
    today = datetime.now(ZoneInfo(args.timezone)).date().isoformat()
    try:
        if not token:
            raise RuntimeError("GITHUB_TOKEN is missing")
        runs = fetch_workflow_runs(
            api_url=args.api_url,
            repository=args.repo,
            workflow=args.workflow,
            token=token,
        )
        result = decide_preopen_delivery(
            runs=runs,
            current_run_id=args.run_id,
            delivery_date=today,
            timezone_name=args.timezone,
        )
    except Exception as exc:
        if args.on_api_error == "fail":
            raise
        result = {
            "should_send": True,
            "reason": "guard_api_error_fail_open",
            "previous_run_id": 0,
            "delivery_date": today,
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    _write_github_output(result)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
