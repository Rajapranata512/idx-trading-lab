const state = {
  items: [],
  sortKey: "signal_score",
  sortDir: "desc",
  generatedAt: "",
  asOfDate: "",
  autoRefreshHandle: null,
  autoRefreshSeconds: 30,
};

const els = {
  tickerFilter: document.getElementById("tickerFilter"),
  minCloseFilter: document.getElementById("minCloseFilter"),
  minVolumeFilter: document.getElementById("minVolumeFilter"),
  limitFilter: document.getElementById("limitFilter"),
  applyBtn: document.getElementById("applyBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  closeBody: document.getElementById("closeBody"),
  kpiCount: document.getElementById("kpiCount"),
  kpiAvgClose: document.getElementById("kpiAvgClose"),
  kpiAvg5d: document.getElementById("kpiAvg5d"),
  kpiAvgVol: document.getElementById("kpiAvgVol"),
  generatedAt: document.getElementById("generatedAt"),
  asOfBadge: document.getElementById("asOfBadge"),
  liveRefreshInfo: document.getElementById("liveRefreshInfo"),
  liveFreshnessInfo: document.getElementById("liveFreshnessInfo"),
  liveCountInfo: document.getElementById("liveCountInfo"),
  closePageLoader: document.getElementById("closePageLoader"),
  closeLoaderText: document.getElementById("closeLoaderText"),
  toast: document.getElementById("toast"),
};

function fmtNum(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "-";
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showToast(message, ms = 2800) {
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
  if (!els.closePageLoader) {
    return;
  }
  if (els.closeLoaderText) {
    els.closeLoaderText.textContent = text;
  }
  if (visible) {
    els.closePageLoader.classList.remove("hidden");
  } else {
    els.closePageLoader.classList.add("hidden");
  }
}

function isEditableTarget(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.hasAttribute("contenteditable");
}

async function api(path) {
  if (window.opsAuth?.json) {
    try {
      return await window.opsAuth.json(path);
    } catch (err) {
      if (err?.unauthorized) {
        window.opsAuth.redirectToLogin("/close-analysis.html");
        throw new Error("Authentication required for close analysis.");
      }
      throw err;
    }
  }
  const response = await fetch(path);
  if (!response.ok) {
    const details = await response.text();
    throw new Error(details || `Request failed (${response.status})`);
  }
  return response.json();
}

function sortItems() {
  const dir = state.sortDir === "asc" ? 1 : -1;
  state.items.sort((a, b) => {
    const va = a?.[state.sortKey];
    const vb = b?.[state.sortKey];
    const na = Number(va);
    const nb = Number(vb);
    if (Number.isFinite(na) && Number.isFinite(nb)) {
      return (na - nb) * dir;
    }
    return String(va ?? "").localeCompare(String(vb ?? "")) * dir;
  });
}

function trendClass(value) {
  const t = String(value || "").toLowerCase();
  if (t === "uptrend") {
    return "trend-up";
  }
  if (t === "downtrend") {
    return "trend-down";
  }
  return "trend-flat";
}

function scoreClass(score) {
  const n = Number(score || 0);
  if (n >= 80) {
    return "high";
  }
  if (n >= 65) {
    return "medium";
  }
  return "low";
}

function renderTable() {
  if (!els.closeBody) {
    return;
  }
  if (!state.items.length) {
    els.closeBody.innerHTML = '<tr><td colspan="14">Tidak ada data sesuai filter.</td></tr>';
    return;
  }
  els.closeBody.innerHTML = state.items.map((row) => `
    <tr>
      <td><strong>${escapeHtml(row.ticker)}</strong></td>
      <td>${fmtNum(row.last_close, 2)}</td>
      <td class="${Number(row.chg_1d_pct) >= 0 ? "gain" : "loss"}">${fmtPct(row.chg_1d_pct, 2)}</td>
      <td class="${Number(row.chg_5d_pct) >= 0 ? "gain" : "loss"}">${fmtPct(row.chg_5d_pct, 2)}</td>
      <td class="${Number(row.chg_20d_pct) >= 0 ? "gain" : "loss"}">${fmtPct(row.chg_20d_pct, 2)}</td>
      <td>${fmtNum(row.ma20, 2)}</td>
      <td>${fmtNum(row.ma50, 2)}</td>
      <td class="${Number(row.dist_ma20_pct) >= 0 ? "gain" : "loss"}">${fmtPct(row.dist_ma20_pct, 2)}</td>
      <td class="${Number(row.dist_ma50_pct) >= 0 ? "gain" : "loss"}">${fmtPct(row.dist_ma50_pct, 2)}</td>
      <td>${fmtNum(row.avg_volume_20d, 0)}</td>
      <td>${fmtPct(row.volatility_20d_pct, 2)}</td>
      <td><span class="trend-tag ${trendClass(row.trend_state)}">${escapeHtml(row.trend_state || "-")}</span></td>
      <td>${escapeHtml(row.signal_mode || "-")}</td>
      <td><span class="score-chip ${scoreClass(row.signal_score)}">${fmtNum(row.signal_score, 2)}</span></td>
    </tr>
  `).join("");
}

function renderKpi() {
  const total = state.items.length;
  const avgClose = total ? state.items.reduce((acc, row) => acc + Number(row.last_close || 0), 0) / total : 0;
  const avg5d = total ? state.items.reduce((acc, row) => acc + Number(row.chg_5d_pct || 0), 0) / total : 0;
  const avgVol = total ? state.items.reduce((acc, row) => acc + Number(row.avg_volume_20d || 0), 0) / total : 0;
  if (els.kpiCount) {
    els.kpiCount.textContent = fmtNum(total, 0);
  }
  if (els.kpiAvgClose) {
    els.kpiAvgClose.textContent = fmtNum(avgClose, 2);
  }
  if (els.kpiAvg5d) {
    els.kpiAvg5d.textContent = fmtPct(avg5d, 2);
  }
  if (els.kpiAvgVol) {
    els.kpiAvgVol.textContent = fmtNum(avgVol, 0);
  }
  if (els.generatedAt) {
    els.generatedAt.textContent = `Generated: ${fmtDateTime(state.generatedAt)}`;
  }
  if (els.asOfBadge) {
    els.asOfBadge.textContent = `As of: ${state.asOfDate || "-"}`;
  }
  if (els.liveCountInfo) {
    els.liveCountInfo.textContent = `Rows: ${fmtNum(total, 0)}`;
  }
  if (els.liveRefreshInfo) {
    els.liveRefreshInfo.textContent = `Auto-refresh: ${fmtNum(state.autoRefreshSeconds, 0)}s`;
  }
  if (els.liveFreshnessInfo) {
    let freshness = "-";
    const dt = state.generatedAt ? new Date(state.generatedAt) : null;
    if (dt && !Number.isNaN(dt.getTime())) {
      const diffMin = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 60000));
      freshness = diffMin < 60 ? `${diffMin}m ago` : `${Math.floor(diffMin / 60)}h ago`;
    }
    els.liveFreshnessInfo.textContent = `Data freshness: ${freshness}`;
  }
}

function queryString() {
  const params = new URLSearchParams();
  const ticker = String(els.tickerFilter?.value || "").trim();
  const minClose = Number(els.minCloseFilter?.value || 0);
  const minVolume = Number(els.minVolumeFilter?.value || 0);
  const limit = Number(els.limitFilter?.value || 0);
  if (ticker) {
    params.set("ticker", ticker);
  }
  if (Number.isFinite(minClose) && minClose > 0) {
    params.set("min_close", String(minClose));
  }
  if (Number.isFinite(minVolume) && minVolume > 0) {
    params.set("min_avg_volume", String(minVolume));
  }
  if (Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(limit));
  }
  return params.toString();
}

async function loadAnalysis({ silent = false } = {}) {
  if (!silent) {
    setPageLoader(true, "Refreshing close analysis...");
  }
  const qs = queryString();
  try {
    const payload = await api(`/api/close-analysis${qs ? `?${qs}` : ""}`);
    state.items = Array.isArray(payload.items) ? payload.items : [];
    state.generatedAt = String(payload.generated_at || "");
    state.asOfDate = String(payload.as_of_date || "");
    sortItems();
    renderKpi();
    renderTable();
    if (!silent) {
      showToast(`Data close analysis diperbarui (${state.items.length} ticker).`);
    }
  } finally {
    if (!silent) {
      setPageLoader(false);
    }
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
  if (els.liveRefreshInfo) {
    els.liveRefreshInfo.textContent = `Auto-refresh: ${fmtNum(intervalSec, 0)}s`;
  }
  state.autoRefreshHandle = window.setInterval(async () => {
    try {
      await loadAnalysis({ silent: true });
    } catch {
      // keep refreshing on transient API failures
    }
  }, intervalMs);
}

function bindSortHeaders() {
  document.querySelectorAll("#closeTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort");
      if (!key) {
        return;
      }
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = key === "ticker" ? "asc" : "desc";
      }
      sortItems();
      renderTable();
    });
  });
}

function bindEvents() {
  els.applyBtn?.addEventListener("click", async () => {
    try {
      await loadAnalysis();
    } catch (err) {
      showToast(`Gagal load data: ${String(err.message || err)}`, 4400);
    }
  });
  els.refreshBtn?.addEventListener("click", async () => {
    try {
      await loadAnalysis();
    } catch (err) {
      showToast(`Gagal refresh: ${String(err.message || err)}`, 4400);
    }
  });
  [els.tickerFilter, els.minCloseFilter, els.minVolumeFilter, els.limitFilter].forEach((input) => {
    input?.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        try {
          await loadAnalysis();
        } catch (err) {
          showToast(`Gagal load data: ${String(err.message || err)}`, 4400);
        }
      }
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
}

async function boot() {
  setPageLoader(true, "Loading close analysis...");
  bindSortHeaders();
  bindEvents();
  try {
    await loadAnalysis({ silent: true });
    startAutoRefresh(30);
  } catch (err) {
    showToast(`Initial load gagal: ${String(err.message || err)}`, 4400);
    startAutoRefresh(30);
  } finally {
    setPageLoader(false);
  }
}

boot();
