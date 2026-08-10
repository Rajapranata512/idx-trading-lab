"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const watchdog = require("../web/api/preopen-watchdog.js");

function responseRecorder() {
  return {
    statusCode: null,
    body: null,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
  };
}

test("handler rejects requests without the Vercel cron secret", async () => {
  const previous = process.env.CRON_SECRET;
  process.env.CRON_SECRET = "expected-secret";
  const response = responseRecorder();

  try {
    await watchdog({ method: "GET", headers: {} }, response);
  } finally {
    if (previous === undefined) delete process.env.CRON_SECRET;
    else process.env.CRON_SECRET = previous;
  }

  assert.equal(response.statusCode, 401);
  assert.equal(response.body.status, "unauthorized");
});

test("handler reports missing GitHub token without calling the network", async () => {
  const previousSecret = process.env.CRON_SECRET;
  const previousToken = process.env.GITHUB_WATCHDOG_TOKEN;
  process.env.CRON_SECRET = "expected-secret";
  delete process.env.GITHUB_WATCHDOG_TOKEN;
  const response = responseRecorder();

  try {
    await watchdog(
      {
        method: "GET",
        headers: { authorization: "Bearer expected-secret" },
      },
      response,
    );
  } finally {
    if (previousSecret === undefined) delete process.env.CRON_SECRET;
    else process.env.CRON_SECRET = previousSecret;
    if (previousToken === undefined) delete process.env.GITHUB_WATCHDOG_TOKEN;
    else process.env.GITHUB_WATCHDOG_TOKEN = previousToken;
  }

  assert.equal(response.statusCode, 503);
  assert.equal(response.body.status, "watchdog_not_configured");
});
