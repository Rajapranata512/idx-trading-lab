"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const watchdog = require("../web/api/preopen-watchdog.js");

const { dateInTimezone, inspectRuns } = watchdog._internal;

test("dateInTimezone uses the Jakarta delivery date", () => {
  assert.equal(dateInTimezone("2026-07-19T17:30:00Z"), "2026-07-20");
});

test("inspectRuns does not dispatch after a successful same-day run", () => {
  const result = inspectRuns(
    [
      {
        id: 10,
        created_at: "2026-07-20T01:06:00Z",
        status: "completed",
        conclusion: "success",
      },
    ],
    "2026-07-20",
  );

  assert.deepEqual(result, {
    action: "none",
    reason: "already_delivered",
    runId: 10,
  });
});

test("inspectRuns waits while another same-day run is active", () => {
  const result = inspectRuns(
    [
      {
        id: 11,
        created_at: "2026-07-20T01:15:00Z",
        status: "in_progress",
        conclusion: null,
      },
    ],
    "2026-07-20",
  );

  assert.equal(result.action, "none");
  assert.equal(result.reason, "delivery_run_active");
});

test("inspectRuns retries when same-day runs only failed", () => {
  const result = inspectRuns(
    [
      {
        id: 9,
        created_at: "2026-07-20T01:06:00Z",
        status: "completed",
        conclusion: "failure",
      },
    ],
    "2026-07-20",
  );

  assert.equal(result.action, "dispatch");
  assert.equal(result.reason, "delivery_missing");
});

test("inspectRuns ignores a success from the previous Jakarta date", () => {
  const result = inspectRuns(
    [
      {
        id: 8,
        created_at: "2026-07-19T01:06:00Z",
        status: "completed",
        conclusion: "success",
      },
    ],
    "2026-07-20",
  );

  assert.equal(result.action, "dispatch");
});
