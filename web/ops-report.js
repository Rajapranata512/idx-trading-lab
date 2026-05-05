const els = {
  reportFrame: document.getElementById("reportFrame"),
  reportStatusBadge: document.getElementById("reportStatusBadge"),
  reportHint: document.getElementById("reportHint"),
  refreshReportBtn: document.getElementById("refreshReportBtn"),
  openRawReportBtn: document.getElementById("openRawReportBtn"),
  toast: document.getElementById("toast"),
};

function showToast(message, ms = 2800) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  window.clearTimeout(showToast._handle);
  showToast._handle = window.setTimeout(() => els.toast.classList.add("hidden"), ms);
}

function setStatus(label, tone = "neutral") {
  if (!els.reportStatusBadge) return;
  els.reportStatusBadge.textContent = label;
  els.reportStatusBadge.className = `ops-status ${tone}`;
}

async function loadReport() {
  setStatus("Loading report", "neutral");
  if (els.reportHint) {
    els.reportHint.textContent = "Refreshing protected report content...";
  }
  try {
    const html = await window.opsAuth.text("/api/report-html");
    if (els.reportFrame) {
      els.reportFrame.srcdoc = html;
    }
    setStatus("Report ready", "success");
    if (els.reportHint) {
      els.reportHint.textContent = "Protected report loaded successfully.";
    }
  } catch (err) {
    if (err?.unauthorized) {
      window.opsAuth.redirectToLogin("/ops-report.html");
      return;
    }
    setStatus("Report failed", "danger");
    if (els.reportHint) {
      els.reportHint.textContent = err.message || "Failed to load report.";
    }
    showToast(err.message || "Failed to load report.", 3600);
  }
}

async function openRawReport() {
  try {
    const html = await window.opsAuth.text("/api/report-html");
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    showToast("Raw protected report opened in a new tab.");
  } catch (err) {
    if (err?.unauthorized) {
      window.opsAuth.redirectToLogin("/ops-report.html");
      return;
    }
    showToast(err.message || "Failed to open raw report.", 3600);
  }
}

function init() {
  if (!window.opsAuth?.getToken?.()) {
    window.opsAuth.redirectToLogin("/ops-report.html");
    return;
  }
  els.refreshReportBtn?.addEventListener("click", loadReport);
  els.openRawReportBtn?.addEventListener("click", openRawReport);
  loadReport();
}

document.addEventListener("DOMContentLoaded", init);
