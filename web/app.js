const THEME_KEY = "idx-trading-lab-theme";

const state = {
  dashboard: null,
  signals: [],
  filteredSignals: [],
  sortKey: "score",
  sortDir: "desc",
  activeJobId: "",
  pollHandle: null,
  autoRefreshHandle: null,
  selectedTicker: "",
  tickerDetail: null,
  theme: "light",
  resizeHandle: null,
  autoRefreshSeconds: 30,
};

const els = {
  refreshBtn: document.getElementById("refreshBtn"),
  runDailyBtn: document.getElementById("runDailyBtn"),
  themeToggleBtn: document.getElementById("themeToggleBtn"),
  mobileRefreshBtn: document.getElementById("mobileRefreshBtn"),
  systemBadge: document.getElementById("systemBadge"),
  lastUpdated: document.getElementById("lastUpdated"),
  asOfText: document.getElementById("asOfText"),
  signalMix: document.getElementById("signalMix"),
  mobileDock: document.getElementById("mobileDock"),
  mobileModeChips: document.getElementById("mobileModeChips"),
  modeFilter: document.getElementById("modeFilter"),
  scoreFilter: document.getElementById("scoreFilter"),
  tickerFilter: document.getElementById("tickerFilter"),
  signalsBody: document.getElementById("signalsBody"),
  executionBody: document.getElementById("executionBody"),
  runList: document.getElementById("runList"),
  gateStatus: document.getElementById("gateStatus"),
  regimeStatus: document.getElementById("regimeStatus"),
  killStatus: document.getElementById("killStatus"),
  promotionStatus: document.getElementById("promotionStatus"),
  closedLoopStatus: document.getElementById("closedLoopStatus"),
  closedLoopReason: document.getElementById("closedLoopReason"),
  jobStatus: document.getElementById("jobStatus"),
  toast: document.getElementById("toast"),
  kpiSignals: document.getElementById("kpiSignals"),
  kpiExecution: document.getElementById("kpiExecution"),
  kpiScore: document.getElementById("kpiScore"),
  kpiEventRisk: document.getElementById("kpiEventRisk"),
  eventRiskMeta: document.getElementById("eventRiskMeta"),
  eventRiskBody: document.getElementById("eventRiskBody"),
  detailTickerBadge: document.getElementById("detailTickerBadge"),
  detailSubtext: document.getElementById("detailSubtext"),
  detailSummary: document.getElementById("detailSummary"),
  reasonList: document.getElementById("reasonList"),
  intradayChart: document.getElementById("intradayChart"),
  detailTimeframe: document.getElementById("detailTimeframe"),
  chartLegend: document.getElementById("chartLegend"),
  dataFreshness: document.getElementById("dataFreshness"),
  autoRefreshInfo: document.getElementById("autoRefreshInfo"),
  pageLoader: document.getElementById("pageLoader"),
  loaderText: document.getElementById("loaderText"),
  errorBanner: document.getElementById("errorBanner"),
  errorText: document.getElementById("errorText"),
  retryLoadBtn: document.getElementById("retryLoadBtn"),
  decisionSummary: document.getElementById("decisionSummary"),
  decisionStatus: document.getElementById("decisionStatus"),
  decisionAction: document.getElementById("decisionAction"),
  decisionTradeReady: document.getElementById("decisionTradeReady"),
  decisionSignalTotal: document.getElementById("decisionSignalTotal"),
  decisionAllowedModes: document.getElementById("decisionAllowedModes"),
  decisionDataAge: document.getElementById("decisionDataAge"),
  decisionDataMaxDate: document.getElementById("decisionDataMaxDate"),
  whyNoSignalHint: document.getElementById("whyNoSignalHint"),
  whyNoSignalList: document.getElementById("whyNoSignalList"),
  operatorAlertMeta: document.getElementById("operatorAlertMeta"),
  operatorAlertList: document.getElementById("operatorAlertList"),
  swingAuditMeta: document.getElementById("swingAuditMeta"),
  swingAuditSummary: document.getElementById("swingAuditSummary"),
  swingAuditWeakspots: document.getElementById("swingAuditWeakspots"),
  paperFillsMeta: document.getElementById("paperFillsMeta"),
  paperFillsSummary: document.getElementById("paperFillsSummary"),
  paperFillsList: document.getElementById("paperFillsList"),
};

function fmtNum(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "-";
  }
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
  });
}

function fmtInt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "-";
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function fmtPct(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "-";
  }
  return `${n.toFixed(digits)}%`;
}

function fmtDateTime(value) {
  if (!value) {
    return "-";
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return String(value);
  }
  return dt.toLocaleString();
}

function modeLabel(mode) {
  const m = String(mode || "").trim().toLowerCase();
  if (m === "t1") {
    return "T+1";
  }
  if (m === "swing") {
    return "Swing";
  }
  if (m === "intraday") {
    return "Intraday";
  }
  return m || "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showToast(message, ms = 2600) {
  if (!els.toast) {
    return;
  }
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  window.clearTimeout(showToast._handle);
  showToast._handle = window.setTimeout(() => {
    els.toast.classList.add("hidden");
  }, ms);
}

function setPageLoader(visible, text = "Loading...") {
  if (!els.pageLoader) {
    return;
  }
  if (els.loaderText) {
    els.loaderText.textContent = text;
  }
  if (visible) {
    els.pageLoader.classList.remove("hidden");
  } else {
    els.pageLoader.classList.add("hidden");
  }
}

function setErrorBanner(message = "") {
  const clean = String(message || "").trim();
  if (!els.errorBanner || !els.errorText) {
    return;
  }
  if (!clean) {
    els.errorText.textContent = "";
    els.errorBanner.classList.add("hidden");
    return;
  }
  els.errorText.textContent = clean;
  els.errorBanner.classList.remove("hidden");
}

function isEditableTarget(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.hasAttribute("contenteditable");
}

async function api(path, options = {}) {
  const init = {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };
  const response = await fetch(path, init);
  if (!response.ok) {
    let details = "";
    try {
      details = await response.text();
    } catch {
      details = "";
    }
    throw new Error(details || `Request failed (${response.status})`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function preferredTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") {
    return stored;
  }
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function applyTheme(theme) {
  const clean = theme === "dark" ? "dark" : "light";
  state.theme = clean;
  document.documentElement.setAttribute("data-theme", clean);
  localStorage.setItem(THEME_KEY, clean);
  if (els.themeToggleBtn) {
    els.themeToggleBtn.textContent = clean === "dark" ? "Light Mode" : "Dark Mode";
  }
}

function initTheme() {
  applyTheme(preferredTheme());
}

function sortSignals(items) {
  const { sortKey, sortDir } = state;
  const dir = sortDir === "asc" ? 1 : -1;
  items.sort((a, b) => {
    const va = a?.[sortKey];
    const vb = b?.[sortKey];
    const na = Number(va);
    const nb = Number(vb);
    if (Number.isFinite(na) && Number.isFinite(nb)) {
      return (na - nb) * dir;
    }
    return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
  });
}

function applyFilters() {
  const mode = String(els.modeFilter?.value || "all").toLowerCase();
  const tickerQuery = String(els.tickerFilter?.value || "").trim().toUpperCase();
  const minScore = Number(els.scoreFilter?.value || 0);

  const filtered = state.signals.filter((row) => {
    const rowMode = String(row.mode || "").toLowerCase();
    const rowTicker = String(row.ticker || "").toUpperCase();
    const score = Number(row.score || 0);
    if (mode !== "all" && rowMode !== mode) {
      return false;
    }
    if (tickerQuery && !rowTicker.includes(tickerQuery)) {
      return false;
    }
    if (Number.isFinite(minScore) && score < minScore) {
      return false;
    }
    return true;
  });

  sortSignals(filtered);
  state.filteredSignals = filtered;
  renderSignals();
  updateModeChipState();
}

function renderSignals() {
  if (!els.signalsBody) {
    return;
  }
  if (!state.filteredSignals.length) {
    const preGateSignals = Number(state.dashboard?.funnel?.pre_gate?.signal_count || 0);
    const hasResearchCandidates = preGateSignals > 0;
    const message = hasResearchCandidates
      ? "No executable signal matched your filters. Research candidates may still exist, but they were blocked by the live gate."
      : "No signal matched your filters.";
    els.signalsBody.innerHTML = `<tr><td colspan="9">${escapeHtml(message)}</td></tr>`;
    return;
  }
  const rows = state.filteredSignals.map((row) => {
    const mode = String(row.mode || "").toLowerCase();
    const modeClass = `mode-${mode.replace(/[^a-z0-9_-]/g, "") || "na"}`;
    const score = Number(row.score || 0);
    const scoreClass = score >= 80 ? "high" : score >= 65 ? "medium" : "low";
    const ticker = String(row.ticker || "").toUpperCase();
    const selectedClass = ticker && ticker === state.selectedTicker ? "is-selected" : "";
    return `
      <tr class="signal-row ${selectedClass}" data-ticker="${escapeHtml(ticker)}">
        <td>${escapeHtml(ticker)}</td>
        <td><span class="mode-tag ${modeClass}">${escapeHtml(modeLabel(row.mode))}</span></td>
        <td><span class="score-chip ${scoreClass}">${fmtNum(row.score, 2)}</span></td>
        <td>${fmtNum(row.entry, 2)}</td>
        <td>${fmtNum(row.stop, 2)}</td>
        <td>${fmtNum(row.tp1, 2)}</td>
        <td>${fmtNum(row.tp2, 2)}</td>
        <td>${fmtInt(row.size)}</td>
        <td>${escapeHtml(row.reason)}</td>
      </tr>
    `;
  });
  els.signalsBody.innerHTML = rows.join("");
}

function renderExecution() {
  if (!els.executionBody) {
    return;
  }
  const items = state.dashboard?.execution_plan?.items || [];
  if (!items.length) {
    els.executionBody.innerHTML = '<tr><td colspan="6">No execution plan available.</td></tr>';
    return;
  }
  const rows = items.slice(0, 30).map((row) => `
    <tr>
      <td>${escapeHtml(row.ticker)}</td>
      <td>${escapeHtml(modeLabel(row.mode))}</td>
      <td>${fmtNum(row.score, 2)}</td>
      <td>${fmtNum(row.entry, 2)}</td>
      <td>${fmtNum(row.stop, 2)}</td>
      <td>${fmtInt(row.size)}</td>
    </tr>
  `);
  els.executionBody.innerHTML = rows.join("");
}

function eventRiskTone(statusRaw) {
  const status = String(statusRaw || "").trim().toUpperCase();
  if (status.includes("SUSPEND")) {
    return "bad";
  }
  if (status.includes("UMA") || status.includes("SPECIAL")) {
    return "warn";
  }
  return "neutral";
}

function renderEventRisk() {
  const eventRisk = state.dashboard?.event_risk || {};
  const itemsRaw = Array.isArray(eventRisk?.active_items) ? eventRisk.active_items : [];
  const items = itemsRaw
    .filter((row) => row && typeof row === "object")
    .map((row) => ({
      ticker: String(row.ticker || "").toUpperCase(),
      status: String(row.status || "-").toUpperCase(),
      startDate: String(row.start_date || "-"),
      endDate: String(row.end_date || "-"),
      source: String(row.source || "-"),
      reason: String(row.reason || "-"),
    }));

  const activeTotal = Number(eventRisk?.active_total ?? items.length ?? 0);
  const excludedTotal = Number(eventRisk?.excluded_total ?? 0);
  if (els.eventRiskMeta) {
    els.eventRiskMeta.textContent = `Active: ${fmtInt(activeTotal)} | Excluded: ${fmtInt(excludedTotal)}`;
    els.eventRiskMeta.className = `status-chip ${activeTotal > 0 ? "bad" : "ok"}`;
  }
  if (!els.eventRiskBody) {
    return;
  }
  if (!items.length) {
    els.eventRiskBody.innerHTML = "<tr><td colspan='6'>Tidak ada event-risk aktif saat ini.</td></tr>";
    return;
  }
  items.sort((a, b) => {
    const statusCmp = a.status.localeCompare(b.status);
    if (statusCmp !== 0) {
      return statusCmp;
    }
    return a.ticker.localeCompare(b.ticker);
  });
  els.eventRiskBody.innerHTML = items.map((row) => `
    <tr>
      <td>${escapeHtml(row.ticker)}</td>
      <td><span class="event-status ${eventRiskTone(row.status)}">${escapeHtml(row.status)}</span></td>
      <td>${escapeHtml(row.startDate)}</td>
      <td>${escapeHtml(row.endDate)}</td>
      <td>${escapeHtml(row.source)}</td>
      <td>${escapeHtml(row.reason)}</td>
    </tr>
  `).join("");
}

function pill(label, kind) {
  return `<span class="pill ${kind}">${escapeHtml(label)}</span>`;
}

function renderGate() {
  const gate = state.dashboard?.backtest?.gate_pass || {};
  const modeActivation = state.dashboard?.backtest?.mode_activation || {};
  const activeModes = Array.isArray(modeActivation?.active_modes) ? modeActivation.active_modes : [];
  const t1Enabled = !activeModes.length || activeModes.includes("t1");
  const swingEnabled = !activeModes.length || activeModes.includes("swing");
  const t1 = Boolean(gate?.t1);
  const swing = Boolean(gate?.swing);
  const qualityPass = Boolean(state.dashboard?.quality?.pass);
  const qualityStatus = String(state.dashboard?.quality?.status || "").toLowerCase();
  const qualityLabel = qualityPass ? "Quality: PASS" : `Quality: ${qualityStatus ? qualityStatus.toUpperCase() : "BLOCKED"}`;
  if (els.gateStatus) {
    els.gateStatus.innerHTML = [
      pill(`T+1: ${t1Enabled ? (t1 ? "PASS" : "BLOCKED") : "OFF"}`, t1Enabled ? (t1 ? "ok" : "bad") : "neutral"),
      pill(`Swing: ${swingEnabled ? (swing ? "PASS" : "BLOCKED") : "OFF"}`, swingEnabled ? (swing ? "ok" : "bad") : "neutral"),
      pill(qualityLabel, qualityPass ? "ok" : "bad"),
    ].join("");
  }

  const regime = String(state.dashboard?.kpi?.regime_status || "-");
  const kill = String(state.dashboard?.kpi?.kill_switch_status || "-");
  if (els.regimeStatus) {
    els.regimeStatus.className = `pill ${regime === "ok" ? "ok" : "neutral"}`;
    els.regimeStatus.textContent = `Regime: ${regime}`;
  }
  if (els.killStatus) {
    els.killStatus.className = `pill ${kill === "active" ? "bad" : "neutral"}`;
    els.killStatus.textContent = `Kill Switch: ${kill}`;
  }
  if (els.promotionStatus) {
    const promotion = state.dashboard?.backtest?.model_v2_promotion || {};
    const required = Boolean(promotion?.required_for_live);
    const gatePass = (promotion && typeof promotion === "object") ? (promotion.gate_pass || {}) : {};
    const modeKeysRaw = Object.keys(gatePass);
    const modeKeys = modeKeysRaw.length ? modeKeysRaw : ["t1", "swing"];
    const passedModes = modeKeys.filter((mode) => Boolean(gatePass?.[mode]));
    const hasPass = passedModes.length > 0;
    const passText = passedModes.length ? passedModes.map((mode) => modeLabel(mode)).join(", ") : "none";
    if (!required) {
      els.promotionStatus.className = "pill neutral";
      els.promotionStatus.textContent = "Promotion Gate: SHADOW";
    } else if (hasPass) {
      els.promotionStatus.className = "pill ok";
      els.promotionStatus.textContent = `Promotion Gate: PASS (${passText})`;
    } else {
      els.promotionStatus.className = "pill bad";
      els.promotionStatus.textContent = "Promotion Gate: BLOCKED";
    }
  }

  if (els.closedLoopStatus || els.closedLoopReason) {
    const closedLoop = state.dashboard?.closed_loop_retrain || {};
    const statusRaw = String(closedLoop?.status || "not_run").trim().toLowerCase();
    const message = String(closedLoop?.message || "").trim();
    const triggered = Boolean(closedLoop?.triggered);
    const reasonsRaw = Array.isArray(closedLoop?.reasons) ? closedLoop.reasons : [];
    const reasons = reasonsRaw
      .map((item) => String(item || "").trim().replaceAll("_", " "))
      .filter(Boolean);

    let badgeTone = "neutral";
    if (statusRaw === "triggered") {
      badgeTone = "ok";
    } else if (statusRaw === "error") {
      badgeTone = "bad";
    }

    let badgeLabel = "NOT RUN";
    if (statusRaw === "triggered") {
      badgeLabel = "TRIGGERED";
    } else if (statusRaw === "triggered_no_update") {
      badgeLabel = "TRIGGERED NO UPDATE";
    } else if (statusRaw === "skipped_no_trigger") {
      badgeLabel = "NO TRIGGER";
    } else if (statusRaw === "skipped_cooldown") {
      badgeLabel = "COOLDOWN";
    } else if (statusRaw === "skipped_disabled") {
      badgeLabel = "DISABLED";
    } else if (statusRaw === "skipped_no_reconciliation_summary") {
      badgeLabel = "WAITING RECON";
    } else if (statusRaw === "error") {
      badgeLabel = "ERROR";
    }

    if (els.closedLoopStatus) {
      els.closedLoopStatus.className = `pill ${badgeTone}`;
      els.closedLoopStatus.textContent = `Closed-loop Retrain: ${badgeLabel}${triggered ? " !" : ""}`;
    }

    if (els.closedLoopReason) {
      const evaluatedAt = fmtDateTime(closedLoop?.last_evaluated_at || "");
      const infoParts = [];
      if (Number.isFinite(Number(closedLoop?.live_samples)) && Number(closedLoop?.live_samples) > 0) {
        infoParts.push(`samples=${fmtInt(closedLoop?.live_samples)}`);
      }
      if (
        Number.isFinite(Number(closedLoop?.new_fills_since_last_trigger))
        && Number(closedLoop?.new_fills_since_last_trigger) > 0
      ) {
        infoParts.push(`new_fills=${fmtInt(closedLoop?.new_fills_since_last_trigger)}`);
      }
      if (evaluatedAt && evaluatedAt !== "-") {
        infoParts.push(`evaluated=${evaluatedAt}`);
      }
      const reasonText = reasons.length
        ? `Reason: ${reasons.join(", ")}`
        : `Reason: ${message || "No trigger reason available."}`;
      els.closedLoopReason.textContent = infoParts.length ? `${reasonText} | ${infoParts.join(" | ")}` : reasonText;
    }
  }
}

function renderOperatorAlerts() {
  const alertsRaw = Array.isArray(state.dashboard?.operator_alerts) ? state.dashboard.operator_alerts : [];
  const alerts = alertsRaw
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      severity: String(item.severity || "info").trim().toLowerCase(),
      title: String(item.title || "Untitled alert").trim(),
      message: String(item.message || "").trim(),
      code: String(item.code || "").trim(),
    }));

  const criticalCount = alerts.filter((item) => item.severity === "critical").length;
  const warnCount = alerts.filter((item) => item.severity === "warn").length;
  let metaTone = "neutral";
  if (criticalCount > 0) {
    metaTone = "bad";
  } else if (warnCount > 0) {
    metaTone = "neutral";
  } else if (alerts.length > 0) {
    metaTone = "ok";
  }
  if (els.operatorAlertMeta) {
    const label = alerts.length
      ? `Alerts: ${fmtInt(alerts.length)}`
      : "Alerts: none";
    els.operatorAlertMeta.className = `status-chip ${metaTone}`;
    els.operatorAlertMeta.textContent = label;
  }
  if (!els.operatorAlertList) {
    return;
  }
  if (!alerts.length) {
    els.operatorAlertList.innerHTML = `
      <article class="alert-card ok">
        <div class="alert-head">
          <span class="alert-badge ok">OK</span>
          <strong>No active operator alerts</strong>
        </div>
        <p>The latest run did not report operational caveats.</p>
      </article>
    `;
    return;
  }
  els.operatorAlertList.innerHTML = alerts.map((alert) => {
    const tone = alert.severity === "critical" ? "bad" : alert.severity === "warn" ? "warn" : "neutral";
    const badgeText = alert.severity === "critical" ? "CRITICAL" : alert.severity === "warn" ? "WARN" : "INFO";
    const foot = alert.code ? `<span class="alert-code">${escapeHtml(alert.code)}</span>` : "";
    return `
      <article class="alert-card ${tone}">
        <div class="alert-head">
          <span class="alert-badge ${tone}">${escapeHtml(badgeText)}</span>
          <strong>${escapeHtml(alert.title)}</strong>
        </div>
        <p>${escapeHtml(alert.message || "No message provided.")}</p>
        ${foot}
      </article>
    `;
  }).join("");
}

function renderSwingAudit() {
  const audit = state.dashboard?.swing_audit || {};
  const overall = audit?.overall || {};
  const tradeCount = Number(overall?.trade_count || 0);
  const expectancy = Number(overall?.expectancy_r || 0);
  const pf = Number(overall?.profit_factor_r || 0);
  const weakSpots = Array.isArray(audit?.weak_spots) ? audit.weak_spots : [];

  if (els.swingAuditMeta) {
    const tone = tradeCount > 0 && expectancy >= 0 && pf >= 1 ? "ok" : tradeCount > 0 ? "bad" : "neutral";
    els.swingAuditMeta.className = `status-chip ${tone}`;
    els.swingAuditMeta.textContent = tradeCount > 0 ? `Trades: ${fmtInt(tradeCount)}` : "Audit: no trades";
  }
  if (els.swingAuditSummary) {
    if (tradeCount <= 0) {
      els.swingAuditSummary.textContent = String(audit?.message || "No swing audit data available yet.");
    } else {
      const source = String(audit?.group_source || "group").trim();
      els.swingAuditSummary.textContent = `Expectancy ${fmtNum(expectancy, 4)}R | PF ${fmtNum(pf, 4)} | Avg MAE ${fmtNum(overall?.avg_mae_r, 4)}R | Avg MFE ${fmtNum(overall?.avg_mfe_r, 4)}R | Group source: ${source}`;
    }
  }
  if (!els.swingAuditWeakspots) {
    return;
  }
  if (!weakSpots.length) {
    const message = tradeCount > 0
      ? "No weak bucket flagged by the latest swing audit."
      : "No audit details available yet.";
    els.swingAuditWeakspots.innerHTML = `<li class="reason-empty">${escapeHtml(message)}</li>`;
    return;
  }
  els.swingAuditWeakspots.innerHTML = weakSpots.map((item) => `
    <li class="why-item">
      <strong>${escapeHtml(String(item.source || "bucket"))}</strong> = ${escapeHtml(String(item.label || "-"))}
      <span> | trades=${fmtInt(item.trade_count)} | expectancy=${fmtNum(item.expectancy_r, 4)}R | PF=${fmtNum(item.profit_factor_r, 4)}</span>
    </li>
  `).join("");
}

function renderPaperFills() {
  const paper = state.dashboard?.paper_fills || {};
  const recent = Array.isArray(paper?.recent_generated) ? paper.recent_generated : [];
  const tradeCount = Number(paper?.trade_count_total || 0);
  const generatedCount = Number(paper?.generated_count || 0);
  const pendingCount = Number(paper?.pending_count || 0);
  const snapshotCount = Number(paper?.snapshot_files_in_window || 0);
  const signalCount = Number(paper?.signals_total || 0);
  const validSignals = Number(paper?.valid_signals || 0);
  const status = String(paper?.status || "").trim().toLowerCase();
  const message = String(paper?.message || "").trim();

  if (els.paperFillsMeta) {
    const tone = generatedCount > 0 ? "ok" : pendingCount > 0 ? "neutral" : tradeCount > 0 ? "ok" : "neutral";
    els.paperFillsMeta.className = `status-chip ${tone}`;
    els.paperFillsMeta.textContent = `Paper fills: ${fmtInt(tradeCount)}`;
  }
  if (els.paperFillsSummary) {
    const parts = [
      `status=${status || "-"}`,
      `snapshots=${fmtInt(snapshotCount)}`,
      `signals=${fmtInt(signalCount)}`,
      `valid=${fmtInt(validSignals)}`,
      `generated=${fmtInt(generatedCount)}`,
      `pending=${fmtInt(pendingCount)}`,
      `win_rate=${fmtPct(paper?.win_rate_pct, 2)}`,
      `expectancy=${fmtNum(paper?.expectancy_r, 4)}R`,
      `PF=${fmtNum(paper?.profit_factor_r, 4)}`,
    ];
    els.paperFillsSummary.textContent = parts.join(" | ");
  }
  if (!els.paperFillsList) {
    return;
  }
  if (!recent.length) {
    const fallback = generatedCount > 0
      ? "Paper fills were generated, but no recent sample is available."
      : (message || "No new paper fills were generated in the latest run.");
    els.paperFillsList.innerHTML = `<li class="reason-empty">${escapeHtml(fallback)}</li>`;
    return;
  }
  els.paperFillsList.innerHTML = recent.map((item) => `
    <li class="why-item">
      <strong>${escapeHtml(String(item.ticker || "-"))}</strong> ${escapeHtml(modeLabel(item.mode))}
      <span> | ${escapeHtml(String(item.exit_reason || "-"))} | ${fmtNum(item.realized_r, 4)}R | pnl=${fmtInt(item.pnl_idr)}</span>
    </li>
  `).join("");
}

function syncModeAvailability() {
  const modeActivation = state.dashboard?.backtest?.mode_activation || {};
  const activeModes = Array.isArray(modeActivation?.active_modes) ? modeActivation.active_modes : [];
  if (!activeModes.length) {
    return;
  }

  const applyLabel = (el, enabled, baseLabel) => {
    if (!el) {
      return;
    }
    const currentBase = el.dataset.baseLabel || baseLabel;
    el.dataset.baseLabel = currentBase;
    if ("disabled" in el) {
      el.disabled = !enabled;
    }
    el.textContent = enabled ? currentBase : `${currentBase} (off)`;
    el.classList.toggle("is-disabled", !enabled);
    if (!enabled) {
      el.setAttribute("aria-disabled", "true");
      el.title = `${currentBase} is currently frozen in active_modes`;
    } else {
      el.removeAttribute("aria-disabled");
      el.removeAttribute("title");
    }
  };

  const t1Enabled = activeModes.includes("t1");
  const swingEnabled = activeModes.includes("swing");
  applyLabel(els.modeFilter?.querySelector('option[value="t1"]'), t1Enabled, "T+1");
  applyLabel(els.modeFilter?.querySelector('option[value="swing"]'), swingEnabled, "Swing");
  applyLabel(els.mobileModeChips?.querySelector('button[data-mode="t1"]'), t1Enabled, "T+1");
  applyLabel(els.mobileModeChips?.querySelector('button[data-mode="swing"]'), swingEnabled, "Swing");

  const currentMode = String(els.modeFilter?.value || "all").toLowerCase();
  if ((currentMode === "t1" && !t1Enabled) || (currentMode === "swing" && !swingEnabled)) {
    if (els.modeFilter) {
      els.modeFilter.value = "all";
    }
  }
}

function decisionToneFromStatus(status) {
  const normalized = String(status || "").trim().toUpperCase();
  if (!normalized) {
    return "neutral";
  }
  if (normalized === "SUCCESS" || normalized === "TRADE_READY" || normalized === "READY") {
    return "ok";
  }
  if (
    normalized.includes("KILL")
    || normalized.includes("RISK_OFF")
    || normalized.includes("BLOCK")
    || normalized.includes("ERROR")
    || normalized.includes("FAIL")
  ) {
    return "bad";
  }
  if (normalized.includes("NO_SIGNAL") || normalized.includes("NO_TRADE")) {
    return "neutral";
  }
  return "neutral";
}

function formatDecisionAction(actionRaw) {
  const normalized = String(actionRaw || "").trim().toUpperCase();
  if (!normalized) {
    return "-";
  }
  if (normalized === "EXECUTE_MAX_3") {
    return "Execute max 3";
  }
  if (normalized === "NO_TRADE") {
    return "No trade";
  }
  return normalized.replaceAll("_", " ");
}

function renderDecision() {
  const decision = state.dashboard?.decision || {};
  const riskBudget = state.dashboard?.risk_budget || {};
  const paperLiveMode = state.dashboard?.paper_live_mode || {};
  const status = String(decision.status || "UNKNOWN").trim().toUpperCase();
  const action = String(decision.action || "").trim().toUpperCase();
  const tradeReady = Boolean(decision.trade_ready);
  const actionReason = String(decision.action_reason || "").trim();
  const signalTotal = Number(decision.signal_total || 0);
  const allowedModes = Array.isArray(decision.allowed_modes) ? decision.allowed_modes : [];
  const dataAgeDays = Number(decision.data_age_days);
  const dataMaxDate = String(decision.data_max_date || "").trim();
  const riskBudgetPct = Number(riskBudget.risk_budget_pct || 0);
  const riskBudgetStatus = String(riskBudget.status || "-").trim();
  const modeText = String(paperLiveMode.mode || "-").trim();
  const rolloutPhase = String(paperLiveMode.rollout_phase || "-").trim();
  const decisionVersion = String(paperLiveMode.decision_version || "").trim();

  if (els.decisionSummary) {
    const fallback = tradeReady
      ? "Gate passed and signals are eligible for execution."
      : "Trade is currently blocked by one or more guardrails.";
    const summaryHead = actionReason || fallback;
    const summaryTail = [
      `risk_budget=${fmtPct(riskBudgetPct, 2)}`,
      `budget_status=${riskBudgetStatus || "-"}`,
      `mode=${modeText || "-"}`,
      `phase=${rolloutPhase || "-"}`,
      decisionVersion ? `decision=${decisionVersion}` : "",
    ]
      .filter(Boolean)
      .join(" | ");
    els.decisionSummary.textContent = summaryTail ? `${summaryHead} | ${summaryTail}` : summaryHead;
  }
  if (els.decisionStatus) {
    els.decisionStatus.className = `decision-status ${decisionToneFromStatus(status)}`;
    els.decisionStatus.textContent = `Status: ${status || "-"}`;
  }
  if (els.decisionAction) {
    const actionTone = action === "EXECUTE_MAX_3" ? "ok" : "neutral";
    els.decisionAction.className = `decision-status ${actionTone}`;
    els.decisionAction.textContent = `Action: ${formatDecisionAction(action)}`;
  }
  if (els.decisionTradeReady) {
    els.decisionTradeReady.className = `decision-status ${tradeReady ? "ok" : "bad"}`;
    els.decisionTradeReady.textContent = `Trade Ready: ${tradeReady ? "Yes" : "No"}`;
  }
  if (els.decisionSignalTotal) {
    els.decisionSignalTotal.textContent = fmtInt(signalTotal);
  }
  if (els.decisionAllowedModes) {
    const allowedModeText = allowedModes.length
      ? allowedModes.map((mode) => modeLabel(mode)).join(", ")
      : "none";
    els.decisionAllowedModes.textContent = allowedModeText;
  }
  if (els.decisionDataAge) {
    if (Number.isFinite(dataAgeDays) && dataAgeDays >= 0) {
      const suffix = dataAgeDays === 1 ? "day" : "days";
      els.decisionDataAge.textContent = `${fmtInt(dataAgeDays)} ${suffix}`;
    } else {
      els.decisionDataAge.textContent = "-";
    }
  }
  if (els.decisionDataMaxDate) {
    els.decisionDataMaxDate.textContent = dataMaxDate || "-";
  }
  if (els.whyNoSignalHint) {
    els.whyNoSignalHint.textContent = tradeReady
      ? "No blocking reason. Signals are ready to be reviewed for execution."
      : "Blocking reasons that currently prevent new execution:";
  }
  if (els.whyNoSignalList) {
    const reasonsRaw = Array.isArray(decision.why_no_signal) ? decision.why_no_signal : [];
    const reasons = reasonsRaw.map((item) => String(item || "").trim()).filter(Boolean);
    if (!reasons.length) {
      const fallback = tradeReady
        ? "No blocking reason detected."
        : "No explicit blocking reason reported by backend.";
      els.whyNoSignalList.innerHTML = `<li class="reason-empty">${escapeHtml(fallback)}</li>`;
      return;
    }
    els.whyNoSignalList.innerHTML = reasons
      .map((reason) => `<li class="why-item">${escapeHtml(reason)}</li>`)
      .join("");
  }
}

function renderKpi() {
  const kpi = state.dashboard?.kpi || {};
  if (els.kpiSignals) {
    els.kpiSignals.textContent = fmtInt(kpi.signal_total);
  }
  if (els.kpiExecution) {
    els.kpiExecution.textContent = fmtInt(kpi.execution_total);
  }
  if (els.kpiScore) {
    els.kpiScore.textContent = fmtNum(kpi.signal_avg_score, 2);
  }
  if (els.kpiEventRisk) {
    els.kpiEventRisk.textContent = fmtInt(kpi.event_active_total);
  }
}

function renderSystemMeta() {
  const dashboard = state.dashboard || {};
  const daemonStatusRaw = String(dashboard?.kpi?.intraday_daemon_status || "").toLowerCase();
  const killStatusRaw = String(dashboard?.kpi?.kill_switch_status || "").toLowerCase();
  const generatedAt = dashboard?.signals?.generated_at || dashboard?.generated_at || "";
  const byMode = dashboard?.signals?.by_mode || {};
  const mix = Object.entries(byMode)
    .map(([k, v]) => `${modeLabel(k)} ${fmtInt(v)}`)
    .join(" | ");

  if (els.lastUpdated) {
    els.lastUpdated.textContent = `Last update: ${fmtDateTime(generatedAt)}`;
  }
  if (els.asOfText) {
    els.asOfText.textContent = `As of: ${fmtDateTime(generatedAt)}`;
  }
  if (els.signalMix) {
    els.signalMix.textContent = `Mode mix: ${mix || "-"}`;
  }
  if (els.systemBadge) {
    let cls = "neutral";
    let label = "System: standby";
    if (killStatusRaw === "active") {
      cls = "bad";
      label = "System: defensive";
    } else if (daemonStatusRaw === "ok") {
      cls = "ok";
      label = "System: live";
    } else if (daemonStatusRaw === "error") {
      cls = "bad";
      label = "System: degraded";
    }
    els.systemBadge.className = `status-chip ${cls}`;
    els.systemBadge.textContent = label;
  }
  if (els.dataFreshness) {
    let freshness = "-";
    const dt = generatedAt ? new Date(generatedAt) : null;
    if (dt && !Number.isNaN(dt.getTime())) {
      const diffMs = Date.now() - dt.getTime();
      const diffMin = Math.max(0, Math.floor(diffMs / 60000));
      if (diffMin < 60) {
        freshness = `${diffMin}m ago`;
      } else {
        const diffHour = Math.floor(diffMin / 60);
        freshness = `${diffHour}h ago`;
      }
    }
    els.dataFreshness.textContent = `Data freshness: ${freshness}`;
  }
  if (els.autoRefreshInfo) {
    els.autoRefreshInfo.textContent = `Auto-refresh: ${fmtInt(state.autoRefreshSeconds)}s`;
  }
}

function renderRuns() {
  if (!els.runList) {
    return;
  }
  const items = state.dashboard?.runs || [];
  if (!items.length) {
    els.runList.innerHTML = "<li class='run-item'>No run history found.</li>";
    return;
  }
  els.runList.innerHTML = items.map((row) => {
    const errorCount = Number(row.error_count || 0);
    const warningCount = Number(row.warning_count || 0);
    const status = String(row.status || "").trim().toLowerCase();
    const issues = Array.isArray(row.issues) ? row.issues : [];
    const statusClass = status === "failed" ? "error" : status === "warning" ? "warn" : "ok";
    const statusText = status === "failed" ? "failed" : status === "warning" ? "warning" : "clean";
    const statusTone = String(row.status_tone || "").trim().toLowerCase();
    const categoryText = String(row.status_category_label || "").trim() || (status === "failed" ? "Critical failure" : status === "warning" ? "Operational warning" : "Clean run");
    const categoryClass = statusTone === "critical"
      ? "critical"
      : statusTone === "protective"
        ? "protective"
        : statusTone === "operational"
          ? "operational"
          : "neutral";
    const statusNote = String(row.status_note || "").trim();
    const issueLabel = `${fmtInt(issues.length)} ${issues.length === 1 ? "issue" : "issues"}`;
    const issueBlock = issues.length ? `
      <details class="run-details">
        <summary>View ${escapeHtml(issueLabel)}</summary>
        <ul class="run-issues">
          ${issues.map((issue) => `
            <li class="run-issue">
              <div class="run-issue-tags">
                <span class="run-issue-badge ${String(issue.level || "").toLowerCase() === "error" ? "error" : "warn"}">${escapeHtml(String(issue.level || "-"))}</span>
                <span class="run-issue-badge kind ${escapeHtml(String(issue.category_tone || "").toLowerCase() || "neutral")}">${escapeHtml(String(issue.category_label || "Issue"))}</span>
              </div>
              <strong>${escapeHtml(String(issue.message || "").replaceAll("_", " "))}</strong>
              <span>${escapeHtml(String(issue.detail || "No detail available."))}</span>
            </li>
          `).join("")}
        </ul>
      </details>
    ` : "";
    return `
      <li class="run-item ${escapeHtml(status || "clean")}">
        <div class="run-main">
          <span>${escapeHtml(row.run_id || row.file)}</span>
          <div class="run-badges">
            <span class="badge ${statusClass}">${escapeHtml(statusText)}</span>
            <span class="badge category ${categoryClass}">${escapeHtml(categoryText)}</span>
          </div>
        </div>
        <div class="run-sub">
          source=${escapeHtml(row.source || "-")} | signals=${fmtInt(row.signals)} | events=${fmtInt(row.events)} | errors=${fmtInt(errorCount)} | warnings=${fmtInt(warningCount)}
        </div>
        <div class="run-sub">
          started=${escapeHtml(fmtDateTime(row.started_at))} | ended=${escapeHtml(fmtDateTime(row.ended_at))}
        </div>
        ${statusNote ? `<div class="run-note">${escapeHtml(statusNote)}</div>` : ""}
        ${issueBlock}
      </li>
    `;
  }).join("");
}

function setJobLine(text) {
  if (els.jobStatus) {
    els.jobStatus.textContent = text;
  }
}

function readCssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function drawIntradayChart(detail) {
  const canvas = els.intradayChart;
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const cssWidth = Math.max(320, canvas.clientWidth || 900);
  const cssHeight = Math.max(220, canvas.clientHeight || 300);
  const pixelWidth = Math.floor(cssWidth * dpr);
  const pixelHeight = Math.floor(cssHeight * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const bg = readCssVar("--chart-bg", "rgba(255,255,255,0.66)");
  const grid = readCssVar("--chart-grid", "rgba(44, 73, 59, 0.15)");
  const line = readCssVar("--chart-line", "#1a8b61");
  const fill = readCssVar("--chart-fill", "rgba(26, 139, 97, 0.15)");
  const text = readCssVar("--chart-text", "#3f5c4e");

  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  const points = detail?.chart?.points || [];
  if (!Array.isArray(points) || points.length < 2) {
    ctx.fillStyle = text;
    ctx.font = "600 13px Manrope";
    ctx.fillText("No chart data for selected ticker.", 14, 24);
    return;
  }

  const lows = points.map((p) => Number(p.low || p.close || 0)).filter((n) => Number.isFinite(n));
  const highs = points.map((p) => Number(p.high || p.close || 0)).filter((n) => Number.isFinite(n));
  const closes = points.map((p) => Number(p.close || 0)).filter((n) => Number.isFinite(n));
  if (!lows.length || !highs.length || !closes.length) {
    ctx.fillStyle = text;
    ctx.font = "600 13px Manrope";
    ctx.fillText("Invalid chart values.", 14, 24);
    return;
  }

  let minPrice = Math.min(...lows);
  let maxPrice = Math.max(...highs);
  if (!(maxPrice > minPrice)) {
    minPrice -= 1;
    maxPrice += 1;
  }
  const padY = (maxPrice - minPrice) * 0.08;
  minPrice -= padY;
  maxPrice += padY;
  const range = maxPrice - minPrice;

  const left = 48;
  const right = 14;
  const top = 16;
  const bottom = 34;
  const plotW = cssWidth - left - right;
  const plotH = cssHeight - top - bottom;

  ctx.strokeStyle = grid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = top + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(cssWidth - right, y);
    ctx.stroke();
    const price = maxPrice - (range * i) / 4;
    ctx.fillStyle = text;
    ctx.font = "600 11px Manrope";
    ctx.fillText(fmtNum(price, 0), 6, y + 4);
  }

  const xAt = (idx) => left + (plotW * idx) / Math.max(1, points.length - 1);
  const yAt = (price) => top + ((maxPrice - price) / range) * plotH;

  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xAt(i);
    const y = yAt(Number(p.close || 0));
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });

  ctx.lineWidth = 2;
  ctx.strokeStyle = line;
  ctx.stroke();

  ctx.lineTo(xAt(points.length - 1), top + plotH);
  ctx.lineTo(xAt(0), top + plotH);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();

  const levelDefs = [
    { key: "entry", color: readCssVar("--chart-entry", "#1a7ad9") },
    { key: "stop", color: readCssVar("--chart-stop", "#c54447") },
    { key: "tp1", color: readCssVar("--chart-tp1", "#2f9342") },
    { key: "tp2", color: readCssVar("--chart-tp2", "#36754b") },
  ];
  levelDefs.forEach((lv) => {
    const value = Number(detail?.levels?.[lv.key] || 0);
    if (!Number.isFinite(value) || value <= 0 || value < minPrice || value > maxPrice) {
      return;
    }
    const y = yAt(value);
    ctx.save();
    ctx.setLineDash([5, 5]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = lv.color;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(cssWidth - right, y);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = lv.color;
    ctx.font = "700 11px Manrope";
    ctx.fillText(lv.key.toUpperCase(), cssWidth - right - 36, y - 4);
  });

  const lastClose = closes[closes.length - 1];
  const lastX = xAt(points.length - 1);
  const lastY = yAt(lastClose);
  ctx.fillStyle = line;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  ctx.fill();
}

function renderTickerDetail() {
  const detail = state.tickerDetail;
  if (!detail || detail.error) {
    if (els.detailTickerBadge) {
      els.detailTickerBadge.className = "status-chip neutral";
      els.detailTickerBadge.textContent = "No ticker selected";
    }
    if (els.detailSubtext) {
      els.detailSubtext.textContent = "Klik baris signal untuk melihat chart intraday dan breakdown alasan.";
    }
    if (els.detailSummary) {
      els.detailSummary.innerHTML = `
        <div class="detail-stat"><span>Last Close</span><strong>-</strong></div>
        <div class="detail-stat"><span>Change</span><strong>-</strong></div>
        <div class="detail-stat"><span>Avg Volume</span><strong>-</strong></div>
        <div class="detail-stat"><span>Signal Score</span><strong>-</strong></div>
      `;
    }
    if (els.reasonList) {
      els.reasonList.innerHTML = `<li class="reason-empty">${escapeHtml(detail?.error || "Belum ada data detail ticker.")}</li>`;
    }
    if (els.detailTimeframe) {
      els.detailTimeframe.textContent = "Timeframe: -";
    }
    if (els.chartLegend) {
      els.chartLegend.textContent = "Pilih ticker untuk menampilkan chart.";
    }
    drawIntradayChart({ chart: { points: [] } });
    return;
  }

  const ticker = String(detail.ticker || state.selectedTicker || "").toUpperCase();
  const signal = detail.latest_signal || {};
  const signalMode = modeLabel(signal.mode || detail.series_type || "-");
  if (els.detailTickerBadge) {
    els.detailTickerBadge.className = "status-chip ok";
    els.detailTickerBadge.textContent = `${ticker} | ${signalMode}`;
  }
  if (els.detailSubtext) {
    const reason = String(signal.reason || "").trim();
    els.detailSubtext.textContent = reason || "No explicit reason text from current signal.";
  }
  if (els.detailSummary) {
    els.detailSummary.innerHTML = `
      <div class="detail-stat">
        <span>Last Close</span>
        <strong>${fmtNum(detail?.stats?.last_close, 2)}</strong>
      </div>
      <div class="detail-stat">
        <span>Change</span>
        <strong class="${Number(detail?.stats?.change_pct || 0) >= 0 ? "gain" : "loss"}">${fmtPct(detail?.stats?.change_pct, 2)}</strong>
      </div>
      <div class="detail-stat">
        <span>Avg Volume</span>
        <strong>${fmtInt(detail?.stats?.avg_volume)}</strong>
      </div>
      <div class="detail-stat">
        <span>Signal Score</span>
        <strong>${fmtNum(signal.score, 2)}</strong>
      </div>
    `;
  }

  const reasonItems = Array.isArray(detail.reason_breakdown) ? detail.reason_breakdown : [];
  if (els.reasonList) {
    if (!reasonItems.length) {
      els.reasonList.innerHTML = "<li class='reason-empty'>No factor breakdown available.</li>";
    } else {
      els.reasonList.innerHTML = reasonItems.map((r) => {
        const factor = escapeHtml(r.factor || "-");
        const weight = Math.max(0, Math.min(100, Number(r.weight || 0)));
        return `
          <li class="reason-item">
            <div class="reason-line">
              <span>${factor}</span>
              <span>${fmtInt(weight)}%</span>
            </div>
            <div class="reason-meter"><span style="width:${weight}%"></span></div>
          </li>
        `;
      }).join("");
    }
  }

  if (els.detailTimeframe) {
    els.detailTimeframe.textContent = `Timeframe: ${escapeHtml(detail.timeframe || "-")}`;
  }
  if (els.chartLegend) {
    els.chartLegend.textContent = `Bars ${fmtInt(detail.bar_count)} | Range ${fmtNum(detail?.stats?.min_low, 2)} - ${fmtNum(detail?.stats?.max_high, 2)}`;
  }
  drawIntradayChart(detail);
}

async function loadTickerDetail(ticker, { silent = false } = {}) {
  const tickerNorm = String(ticker || "").trim().toUpperCase();
  if (!tickerNorm) {
    state.tickerDetail = null;
    renderTickerDetail();
    return;
  }
  try {
    const payload = await api(`/api/ticker-detail?ticker=${encodeURIComponent(tickerNorm)}&bars=180`);
    state.tickerDetail = payload;
    renderTickerDetail();
  } catch (err) {
    state.tickerDetail = { error: String(err.message || err) };
    renderTickerDetail();
    if (!silent) {
      showToast(`Ticker detail failed: ${String(err.message || err)}`, 4200);
    }
  }
}

function stopPolling() {
  if (state.pollHandle) {
    window.clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
}

function startAutoRefresh(seconds = 30) {
  const intervalSec = Math.max(10, Number(seconds || 30));
  state.autoRefreshSeconds = intervalSec;
  const intervalMs = intervalSec * 1000;
  if (state.autoRefreshHandle) {
    window.clearInterval(state.autoRefreshHandle);
    state.autoRefreshHandle = null;
  }
  if (els.autoRefreshInfo) {
    els.autoRefreshInfo.textContent = `Auto-refresh: ${fmtInt(intervalSec)}s`;
  }
  state.autoRefreshHandle = window.setInterval(async () => {
    try {
      await loadDashboard({ silent: true });
      if (state.selectedTicker) {
        await loadTickerDetail(state.selectedTicker, { silent: true });
      }
    } catch {
      // Keep running; transient network errors are expected in dashboard polling.
    }
  }, intervalMs);
}

async function pollJob(jobId) {
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const status = String(job.status || "unknown");
    if (status === "running" || status === "queued") {
      setJobLine(`Job ${job.job_id} is ${status}...`);
      return;
    }
    if (status === "succeeded") {
      stopPolling();
      setJobLine(`Job ${job.job_id} finished successfully.`);
      showToast("Pipeline completed. Dashboard refreshed.");
      await loadDashboard();
      if (state.selectedTicker) {
        await loadTickerDetail(state.selectedTicker, { silent: true });
      }
      return;
    }
    stopPolling();
    setJobLine(`Job ${job.job_id} failed: ${job.error || "unknown error"}`);
    showToast(`Pipeline failed: ${job.error || "unknown error"}`, 4200);
  } catch (err) {
    stopPolling();
    setJobLine(`Failed to poll job: ${String(err.message || err)}`);
  }
}

function startPolling(jobId) {
  stopPolling();
  state.activeJobId = jobId;
  pollJob(jobId);
  state.pollHandle = window.setInterval(() => {
    pollJob(jobId);
  }, 2200);
}

async function runDailyPipeline() {
  if (!els.runDailyBtn) {
    return;
  }
  els.runDailyBtn.disabled = true;
  try {
    const payload = await api("/api/run-daily", {
      method: "POST",
      body: JSON.stringify({ skip_telegram: true }),
    });
    const jobId = payload?.job?.job_id;
    if (!jobId) {
      throw new Error("Job ID not returned by server");
    }
    setJobLine(`Job ${jobId} submitted. Waiting...`);
    showToast("Pipeline job submitted.");
    startPolling(jobId);
  } catch (err) {
    setJobLine(`Failed to submit job: ${String(err.message || err)}`);
    showToast(`Submit failed: ${String(err.message || err)}`, 4200);
  } finally {
    els.runDailyBtn.disabled = false;
  }
}

function bindSortHandlers() {
  document.querySelectorAll("#signalsTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort");
      if (!key) {
        return;
      }
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = key === "score" ? "desc" : "asc";
      }
      applyFilters();
    });
  });
}

function bindSignalRowClicks() {
  els.signalsBody?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const row = target.closest("tr[data-ticker]");
    if (!row) {
      return;
    }
    const ticker = String(row.getAttribute("data-ticker") || "").toUpperCase();
    if (!ticker) {
      return;
    }
    state.selectedTicker = ticker;
    applyFilters();
    loadTickerDetail(ticker);
    if (window.innerWidth <= 900) {
      const detailEl = document.getElementById("detailSection");
      detailEl?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
}

function updateModeChipState() {
  const activeMode = String(els.modeFilter?.value || "all").toLowerCase();
  els.mobileModeChips?.querySelectorAll("button[data-mode]").forEach((btn) => {
    const mode = String(btn.getAttribute("data-mode") || "").toLowerCase();
    if (mode === activeMode) {
      btn.classList.add("is-active");
    } else {
      btn.classList.remove("is-active");
    }
  });
}

function bindMobileModeChips() {
  els.mobileModeChips?.querySelectorAll("button[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = String(btn.getAttribute("data-mode") || "all").toLowerCase();
      if (els.modeFilter) {
        els.modeFilter.value = mode;
      }
      applyFilters();
    });
  });
}

function bindMobileDock() {
  els.mobileDock?.querySelectorAll("button[data-scroll-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = String(btn.getAttribute("data-scroll-target") || "");
      if (!targetId) {
        return;
      }
      const el = document.getElementById(targetId);
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

async function loadDashboard({ silent = false } = {}) {
  if (!silent) {
    setPageLoader(true, "Refreshing dashboard data...");
  }
  try {
    const snapshot = await api("/api/dashboard");
    setErrorBanner("");
    state.dashboard = snapshot;
    state.signals = snapshot?.signals?.items || [];
    renderSystemMeta();
    renderKpi();
    renderGate();
    renderOperatorAlerts();
    renderSwingAudit();
    renderPaperFills();
    renderEventRisk();
    renderDecision();
    renderExecution();
    renderRuns();
    syncModeAvailability();
    applyFilters();
    if (!state.pollHandle && !state.activeJobId && !silent) {
      const daemonStatus = state.dashboard?.kpi?.intraday_daemon_status;
      if (daemonStatus) {
        setJobLine(`No active job | intraday daemon: ${daemonStatus}`);
      } else {
        setJobLine("No active job");
      }
    }
  } catch (err) {
    const message = String(err.message || err);
    setErrorBanner(`Unable to load /api/dashboard: ${message}`);
    setJobLine(`Failed to load dashboard: ${message}`);
    if (!silent) {
      showToast(`Dashboard load failed: ${message}`, 4200);
    }
    throw err;
  } finally {
    if (!silent) {
      setPageLoader(false);
    }
  }
}

function bindEvents() {
  els.refreshBtn?.addEventListener("click", async () => {
    try {
      await loadDashboard();
      if (state.selectedTicker) {
        await loadTickerDetail(state.selectedTicker, { silent: true });
      }
      showToast("Dashboard data updated.");
    } catch (err) {
      showToast(`Refresh failed: ${String(err.message || err)}`, 4200);
    }
  });
  els.mobileRefreshBtn?.addEventListener("click", async () => {
    try {
      await loadDashboard();
      if (state.selectedTicker) {
        await loadTickerDetail(state.selectedTicker, { silent: true });
      }
      showToast("Dashboard data updated.");
    } catch (err) {
      showToast(`Refresh failed: ${String(err.message || err)}`, 4200);
    }
  });
  els.retryLoadBtn?.addEventListener("click", async () => {
    try {
      await loadDashboard();
      if (state.selectedTicker) {
        await loadTickerDetail(state.selectedTicker, { silent: true });
      }
      showToast("Retry succeeded.");
    } catch {
      // Error banner + toast already handled in loadDashboard.
    }
  });
  els.runDailyBtn?.addEventListener("click", runDailyPipeline);
  els.themeToggleBtn?.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
    renderTickerDetail();
  });
  els.modeFilter?.addEventListener("change", applyFilters);
  els.scoreFilter?.addEventListener("input", applyFilters);
  els.tickerFilter?.addEventListener("input", applyFilters);
  bindMobileModeChips();
  bindMobileDock();
  bindSignalRowClicks();
  document.querySelectorAll(".command-chip[href^='#']").forEach((anchor) => {
    anchor.addEventListener("click", (event) => {
      const href = anchor.getAttribute("href") || "";
      if (!href.startsWith("#")) {
        return;
      }
      const target = document.querySelector(href);
      if (!target) {
        return;
      }
      event.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  document.addEventListener("keydown", (event) => {
    if (isEditableTarget(event.target)) {
      return;
    }
    if (event.key === "/") {
      event.preventDefault();
      els.tickerFilter?.focus();
      els.tickerFilter?.select();
      return;
    }
    if (event.key.toLowerCase() === "r" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      els.refreshBtn?.click();
    }
  });
  window.addEventListener("resize", () => {
    window.clearTimeout(state.resizeHandle);
    state.resizeHandle = window.setTimeout(() => renderTickerDetail(), 120);
  });
}

async function boot() {
  setPageLoader(true, "Loading dashboard...");
  initTheme();
  bindSortHandlers();
  bindEvents();
  try {
    await loadDashboard();
    if (!state.selectedTicker && state.filteredSignals.length > 0) {
      state.selectedTicker = String(state.filteredSignals[0].ticker || "").toUpperCase();
      applyFilters();
    }
    if (state.selectedTicker) {
      await loadTickerDetail(state.selectedTicker, { silent: true });
    } else {
      renderTickerDetail();
    }
    const daemonPoll = Number(state.dashboard?.intraday?.daemon_state?.poll_seconds || 30);
    const webRefresh = Number(state.dashboard?.intraday?.status?.poll_seconds || daemonPoll || 30);
    startAutoRefresh(webRefresh);
  } catch (err) {
    setJobLine(`Failed to load dashboard: ${String(err.message || err)}`);
    showToast(`Initial load failed: ${String(err.message || err)}`, 4200);
    renderTickerDetail();
    startAutoRefresh(30);
  } finally {
    setPageLoader(false);
  }
}

boot();
