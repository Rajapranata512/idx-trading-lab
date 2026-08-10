"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const freshness = require("../web/js/market-freshness.js");
const calendar = require("../web/idx_market_calendar.json");

function evaluate(dataDate, now, generatedAt = "2026-08-07T13:46:00Z") {
  return freshness.calculateFreshness({ dataDate, generatedAt, calendar, now });
}

test("Friday data remains fresh before the Monday completion cutoff", () => {
  const result = evaluate("2026-08-07", "2026-08-10T01:00:00Z");

  assert.equal(result.severity, "fresh");
  assert.equal(result.expectedDataDate, "2026-08-07");
  assert.equal(result.missedSessions, 0);
});

test("Friday data is one missed session after the Monday cutoff", () => {
  const result = evaluate("2026-08-07", "2026-08-10T14:00:00Z");

  assert.equal(result.severity, "warning");
  assert.equal(result.expectedDataDate, "2026-08-10");
  assert.equal(result.missedSessions, 1);
});

test("Friday data is critical after two completed trading sessions", () => {
  const result = evaluate("2026-08-07", "2026-08-11T14:00:00Z");

  assert.equal(result.severity, "critical");
  assert.equal(result.expectedDataDate, "2026-08-11");
  assert.equal(result.missedSessions, 2);
});

test("IDX holiday does not increase missed trading sessions", () => {
  const result = evaluate("2026-08-14", "2026-08-17T14:00:00Z");

  assert.equal(result.severity, "fresh");
  assert.equal(result.expectedDataDate, "2026-08-14");
});

test("first session after a holiday is expected only after the cutoff", () => {
  const before = evaluate("2026-08-14", "2026-08-18T01:00:00Z");
  const after = evaluate("2026-08-14", "2026-08-18T14:00:00Z");

  assert.equal(before.expectedDataDate, "2026-08-14");
  assert.equal(before.severity, "fresh");
  assert.equal(after.expectedDataDate, "2026-08-18");
  assert.equal(after.severity, "warning");
});

test("missing pipeline timestamp is visible as a warning", () => {
  const result = evaluate("2026-08-07", "2026-08-10T01:00:00Z", "");

  assert.equal(result.severity, "warning");
  assert.match(result.message, /waktu pipeline/i);
});

test("legacy timezone-naive pipeline timestamps are interpreted as UTC", () => {
  const result = evaluate("2026-08-07", "2026-08-10T01:00:00Z", "2026-08-07T13:46:00");

  assert.equal(result.pipelineTimestampWib, "2026-08-07 20:46:00 WIB");
});

test("calendar coverage and invalid market dates fail closed", () => {
  const outOfRange = evaluate("2026-12-30", "2027-01-04T01:00:00Z");
  const holidayData = evaluate("2026-08-17", "2026-08-18T01:00:00Z");
  const futureData = evaluate("2026-08-11", "2026-08-10T01:00:00Z");

  assert.equal(outOfRange.severity, "critical");
  assert.match(outOfRange.message, /tidak mencakup/i);
  assert.equal(holidayData.severity, "critical");
  assert.match(holidayData.message, /bukan sesi perdagangan/i);
  assert.equal(futureData.severity, "critical");
  assert.match(futureData.message, /masa depan/i);
});
test("missing and malformed core metadata fails closed", () => {
  const missingDate = freshness.calculateFreshness({
    dataDate: "",
    generatedAt: "2026-08-07T13:46:00Z",
    calendar,
    now: "2026-08-10T01:00:00Z",
  });
  const missingCalendar = freshness.calculateFreshness({
    dataDate: "2026-08-07",
    generatedAt: "2026-08-07T13:46:00Z",
    calendar: null,
    now: "2026-08-10T01:00:00Z",
  });
  const invalidTimestamp = evaluate("2026-08-07", "2026-08-10T01:00:00Z", "not-a-time");

  assert.equal(missingDate.severity, "critical");
  assert.match(missingDate.message, /tanggal data pasar/i);
  assert.equal(missingCalendar.severity, "critical");
  assert.match(missingCalendar.message, /kalender sesi IDX/i);
  assert.equal(invalidTimestamp.severity, "warning");
  assert.match(invalidTimestamp.message, /waktu pipeline/i);
});
