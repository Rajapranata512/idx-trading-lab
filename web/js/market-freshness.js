(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.IdxMarketFreshness = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
  const ZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;

  function parseDateKey(value) {
    const match = typeof value === "string" ? DATE_PATTERN.exec(value) : null;
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return dateKey(date) === value ? date : null;
  }

  function dateKey(date) {
    return date.toISOString().slice(0, 10);
  }

  function addDays(date, amount) {
    const copy = new Date(date.getTime());
    copy.setUTCDate(copy.getUTCDate() + amount);
    return copy;
  }

  function compareDates(left, right) {
    return left.getTime() - right.getTime();
  }

  function parseCutoff(value) {
    const match = /^(\d{2}):(\d{2})$/.exec(value || "");
    if (!match) return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (hours > 23 || minutes > 59) return null;
    return hours * 60 + minutes;
  }

  function jakartaParts(now) {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const parts = Object.fromEntries(
      formatter.formatToParts(now).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]),
    );
    return {
      date: `${parts.year}-${parts.month}-${parts.day}`,
      minutes: Number(parts.hour) * 60 + Number(parts.minute),
      timestamp: `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} WIB`,
    };
  }

  function normalizeCalendar(raw) {
    if (!raw || raw.market !== "IDX" || raw.timezone !== "Asia/Jakarta") return null;
    const validFrom = parseDateKey(raw.valid_from);
    const validUntil = parseDateKey(raw.valid_until);
    const cutoff = parseCutoff(raw.data_expected_after);
    if (!validFrom || !validUntil || compareDates(validFrom, validUntil) > 0 || cutoff === null) return null;

    const holidays = new Set();
    if (!Array.isArray(raw.holidays)) return null;
    for (const item of raw.holidays) {
      const value = typeof item === "string" ? item : item && item.date;
      if (!parseDateKey(value)) return null;
      holidays.add(value);
    }
    return { validFrom, validUntil, cutoff, holidays };
  }

  function isCovered(date, calendar) {
    return compareDates(date, calendar.validFrom) >= 0 && compareDates(date, calendar.validUntil) <= 0;
  }

  function isTradingDay(date, calendar) {
    const weekday = date.getUTCDay();
    return weekday !== 0 && weekday !== 6 && !calendar.holidays.has(dateKey(date));
  }

  function previousTradingDay(date, calendar) {
    let cursor = addDays(date, -1);
    while (isCovered(cursor, calendar)) {
      if (isTradingDay(cursor, calendar)) return cursor;
      cursor = addDays(cursor, -1);
    }
    return null;
  }

  function expectedCompletedSession(localDate, localMinutes, calendar) {
    if (!isCovered(localDate, calendar)) return null;
    if (isTradingDay(localDate, calendar) && localMinutes >= calendar.cutoff) return localDate;
    return previousTradingDay(localDate, calendar);
  }

  function countMissedSessions(dataDate, expectedDate, calendar) {
    if (compareDates(dataDate, expectedDate) >= 0) return 0;
    let count = 0;
    let cursor = addDays(dataDate, 1);
    while (compareDates(cursor, expectedDate) <= 0) {
      if (!isCovered(cursor, calendar)) return null;
      if (isTradingDay(cursor, calendar)) count += 1;
      cursor = addDays(cursor, 1);
    }
    return count;
  }

  function parsePipelineTimestamp(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    const normalized = ZONE_PATTERN.test(value.trim()) ? value.trim() : `${value.trim()}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatPipelineTimestamp(value) {
    const date = parsePipelineTimestamp(value);
    return date ? jakartaParts(date).timestamp : "Tidak tersedia";
  }

  function result(severity, message, details) {
    return Object.assign({ severity, message, isStale: severity !== "fresh" }, details);
  }

  function calculateFreshness(options) {
    const input = options || {};
    const now = input.now instanceof Date ? input.now : new Date(input.now || Date.now());
    const local = Number.isNaN(now.getTime()) ? null : jakartaParts(now);
    const calendar = normalizeCalendar(input.calendar);
    const dataDate = parseDateKey(input.dataDate);
    const pipelineDate = parsePipelineTimestamp(input.generatedAt);

    const base = {
      dataDate: dataDate ? dateKey(dataDate) : null,
      pipelineTimestampWib: pipelineDate ? jakartaParts(pipelineDate).timestamp : null,
      expectedDataDate: null,
      missedSessions: null,
    };

    if (!local) return result("critical", "Waktu sistem tidak valid; freshness data tidak dapat diverifikasi.", base);
    if (!calendar) return result("critical", "Kalender sesi IDX tidak tersedia atau tidak valid.", base);

    const localDate = parseDateKey(local.date);
    if (!localDate || !isCovered(localDate, calendar)) {
      return result("critical", `Kalender sesi IDX tidak mencakup ${local.date}.`, base);
    }

    const expectedDate = expectedCompletedSession(localDate, local.minutes, calendar);
    if (!expectedDate) return result("critical", "Sesi IDX terakhir tidak dapat ditentukan dari kalender.", base);
    base.expectedDataDate = dateKey(expectedDate);

    if (!dataDate) return result("critical", "Tanggal data pasar tidak tersedia atau tidak valid.", base);
    if (!isCovered(dataDate, calendar)) {
      return result("critical", `Tanggal data ${base.dataDate} berada di luar cakupan kalender IDX.`, base);
    }
    if (compareDates(dataDate, localDate) > 0) {
      return result("critical", `Tanggal data ${base.dataDate} berada di masa depan.`, base);
    }
    if (!isTradingDay(dataDate, calendar)) {
      return result("critical", `Tanggal data ${base.dataDate} bukan sesi perdagangan IDX.`, base);
    }

    const missed = countMissedSessions(dataDate, expectedDate, calendar);
    base.missedSessions = missed;
    if (missed === null) return result("critical", "Jarak sesi data tidak dapat diverifikasi dari kalender IDX.", base);
    if (missed >= 2) {
      return result(
        "critical",
        `Data tertinggal ${missed} sesi bursa: terakhir ${base.dataDate}, seharusnya ${base.expectedDataDate}.`,
        base,
      );
    }
    if (missed === 1) {
      return result(
        "warning",
        `Data tertinggal 1 sesi bursa: terakhir ${base.dataDate}, seharusnya ${base.expectedDataDate}.`,
        base,
      );
    }
    if (!pipelineDate) {
      return result("warning", "Data pasar terbaru, tetapi waktu pipeline tidak tersedia atau tidak valid.", base);
    }
    return result("fresh", "Data sesuai dengan sesi IDX terakhir yang telah selesai.", base);
  }

  return {
    calculateFreshness,
    formatPipelineTimestamp,
    _internal: {
      countMissedSessions,
      expectedCompletedSession,
      isTradingDay,
      jakartaParts,
      normalizeCalendar,
      parseDateKey,
      parsePipelineTimestamp,
    },
  };
});
