"use strict";

const DEFAULT_REPOSITORY = "Rajapranata512/idx-trading-lab";
const DEFAULT_WORKFLOW = "model-v2-shadow-preopen.yml";
const API_VERSION = "2022-11-28";
const ACTIVE_STATUSES = new Set(["queued", "in_progress", "pending", "requested", "waiting"]);

function dateInTimezone(value, timeZone = "Asia/Jakarta") {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function inspectRuns(runs, today, timeZone = "Asia/Jakarta") {
  const sameDay = runs.filter((run) => {
    if (!run || !run.created_at) return false;
    return dateInTimezone(run.created_at, timeZone) === today;
  });
  const successful = sameDay.find(
    (run) => run.status === "completed" && run.conclusion === "success",
  );
  if (successful) {
    return { action: "none", reason: "already_delivered", runId: successful.id };
  }
  const active = sameDay.find((run) => ACTIVE_STATUSES.has(String(run.status || "")));
  if (active) {
    return { action: "none", reason: "delivery_run_active", runId: active.id };
  }
  return { action: "dispatch", reason: "delivery_missing", runId: null };
}

async function githubRequest(path, token, options = {}) {
  const response = await fetch(`https://api.github.com${path}`, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "idx-trading-lab-vercel-watchdog",
      "X-GitHub-Api-Version": API_VERSION,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 300);
    throw new Error(`GitHub API ${response.status}: ${detail}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function handler(request, response) {
  if (request.method !== "GET") {
    return response.status(405).json({ ok: false, status: "method_not_allowed" });
  }

  const cronSecret = String(process.env.CRON_SECRET || "");
  const authorization = String(request.headers.authorization || "");
  if (!cronSecret || authorization !== `Bearer ${cronSecret}`) {
    return response.status(401).json({ ok: false, status: "unauthorized" });
  }

  const token = String(process.env.GITHUB_WATCHDOG_TOKEN || "");
  if (!token) {
    return response.status(503).json({
      ok: false,
      status: "watchdog_not_configured",
      message: "GITHUB_WATCHDOG_TOKEN is missing",
    });
  }

  const repository = String(process.env.GITHUB_WATCHDOG_REPOSITORY || DEFAULT_REPOSITORY);
  const workflow = String(process.env.GITHUB_WATCHDOG_WORKFLOW || DEFAULT_WORKFLOW);
  const encodedWorkflow = encodeURIComponent(workflow);
  const today = dateInTimezone(new Date(), "Asia/Jakarta");

  try {
    const payload = await githubRequest(
      `/repos/${repository}/actions/workflows/${encodedWorkflow}/runs?per_page=30`,
      token,
    );
    const decision = inspectRuns(payload.workflow_runs || [], today);
    if (decision.action === "none") {
      return response.status(200).json({
        ok: true,
        status: decision.reason,
        delivery_date: today,
        run_id: decision.runId,
      });
    }

    await githubRequest(
      `/repos/${repository}/actions/workflows/${encodedWorkflow}/dispatches`,
      token,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { force_send: "false" } }),
      },
    );
    return response.status(202).json({
      ok: true,
      status: "fallback_dispatched",
      delivery_date: today,
    });
  } catch (error) {
    return response.status(502).json({
      ok: false,
      status: "github_api_error",
      message: String(error && error.message ? error.message : error),
    });
  }
}

module.exports = handler;
module.exports._internal = { dateInTimezone, inspectRuns };
