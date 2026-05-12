const state = {
  nextPath: "",
  authenticated: false,
  authRequired: true,
  latestJobs: null,
  lockedOut: false,
};

const els = {
  loginForm: document.getElementById("loginForm"),
  usernameInput: document.getElementById("usernameInput"),
  passwordInput: document.getElementById("passwordInput"),
  loginBtn: document.getElementById("loginBtn"),
  logoutBtn: document.getElementById("logoutBtn"),
  authStatusBadge: document.getElementById("authStatusBadge"),
  authStatusText: document.getElementById("authStatusText"),
  opsModeBadge: document.getElementById("opsModeBadge"),
  opsHint: document.getElementById("opsHint"),
  openCloseAnalysisBtn: document.getElementById("openCloseAnalysisBtn"),
  openReportBtn: document.getElementById("openReportBtn"),
  refreshJobsBtn: document.getElementById("refreshJobsBtn"),
  runDailyBtn: document.getElementById("runDailyBtn"),
  jobCountsBadge: document.getElementById("jobCountsBadge"),
  jobCounts: document.getElementById("jobCounts"),
  jobList: document.getElementById("jobList"),
  toast: document.getElementById("toast"),
};

function showToast(message, ms = 2800) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  window.clearTimeout(showToast._handle);
  showToast._handle = window.setTimeout(() => els.toast.classList.add("hidden"), ms);
}

function setBadge(el, label, tone) {
  if (!el) return;
  el.textContent = label;
  el.className = `ops-status ${tone}`;
}

function renderJobCounts(counts) {
  if (!els.jobCounts) return;
  const values = {
    queued: Number(counts?.queued || 0),
    running: Number(counts?.running || 0),
    succeeded: Number(counts?.succeeded || 0),
    failed: Number(counts?.failed || 0),
  };
  els.jobCounts.innerHTML = Object.entries(values).map(([key, value]) => `
    <div>
      <span>${key}</span>
      <strong>${value.toLocaleString()}</strong>
    </div>
  `).join("");
  setBadge(els.jobCountsBadge, `Jobs ${values.running > 0 ? "active" : "idle"}`, values.running > 0 ? "warning" : "neutral");
}

function renderJobList(items) {
  if (!els.jobList) return;
  if (!Array.isArray(items) || !items.length) {
    els.jobList.innerHTML = "<li>No recent operational job entries found.</li>";
    return;
  }
  els.jobList.innerHTML = items.slice(0, 5).map((job) => {
    const status = String(job.status || "unknown");
    const error = String(job.error || "").trim();
    return `<li><strong>${job.job_id || "-"}</strong> - ${status}${error ? ` - ${error}` : ""}</li>`;
  }).join("");
}

function renderAuthState() {
  const token = window.opsAuth?.getToken?.() || "";
  const localhost = window.opsAuth?.isLocalhost?.();

  if (state.authenticated) {
    setBadge(els.authStatusBadge, "Authenticated", "success");
    els.authStatusText.textContent = state.authRequired
      ? "This tab has a valid operational session. Protected APIs will use the stored credential."
      : "Operational auth is currently disabled on this server, but this tab is still ready to access ops pages.";
  } else if (state.lockedOut) {
    setBadge(els.authStatusBadge, "Temporarily locked", "danger");
    els.authStatusText.textContent = "Too many failed login attempts were detected from this IP. Wait for the lockout window to expire before trying again.";
  } else {
    setBadge(els.authStatusBadge, state.authRequired ? "Signed out" : "No auth required", state.authRequired ? "neutral" : "warning");
    els.authStatusText.textContent = state.authRequired
      ? "Sign in to unlock protected operational APIs in this browser tab."
      : "This server is not enforcing operational auth right now. That is fine for localhost, but risky for public hosting.";
  }

  setBadge(
    els.opsModeBadge,
    localhost ? "Local operator browser" : "Remote browser",
    localhost ? "success" : "warning",
  );

  if (els.opsHint) {
    const nextNote = state.nextPath ? ` After authentication, the requested page will continue to ${state.nextPath}.` : "";
    els.opsHint.textContent = localhost
      ? `Run Daily is enabled from localhost only.${nextNote}`
      : `Run Daily remains disabled on non-localhost browsers for safety.${nextNote}`;
  }

  if (els.runDailyBtn) {
    els.runDailyBtn.disabled = !localhost || !state.authenticated || state.lockedOut;
  }
  if (els.openCloseAnalysisBtn) {
    els.openCloseAnalysisBtn.disabled = !state.authenticated || state.lockedOut;
  }
  if (els.openReportBtn) {
    els.openReportBtn.disabled = !state.authenticated || state.lockedOut;
  }
  if (els.refreshJobsBtn) {
    els.refreshJobsBtn.disabled = !state.authenticated || state.lockedOut;
  }
  if (els.loginBtn) {
    els.loginBtn.disabled = state.lockedOut;
  }
  if (!token && !state.authenticated) {
    renderJobCounts(null);
    renderJobList([]);
  }
}

async function probeAuthState() {
  try {
    const payload = await fetch("/api/jobs");
    if (payload.status === 401) {
      state.authRequired = true;
      state.authenticated = false;
      state.lockedOut = false;
      return;
    }
    if (payload.status === 429) {
      state.authRequired = true;
      state.authenticated = false;
      state.lockedOut = true;
      return;
    }
    if (payload.ok) {
      state.authRequired = false;
      state.authenticated = true;
      state.lockedOut = false;
      const data = await payload.json();
      state.latestJobs = data;
      return;
    }
  } catch {}
  state.authRequired = true;
  state.authenticated = false;
}

async function refreshJobs() {
  try {
    const payload = await window.opsAuth.json("/api/jobs");
    state.latestJobs = payload;
    state.authenticated = true;
    state.lockedOut = false;
    renderJobCounts(payload.counts);
    renderJobList(payload.items);
    renderAuthState();
    return true;
  } catch (err) {
    if (err?.unauthorized) {
      window.opsAuth.clearToken();
      state.authenticated = false;
      state.lockedOut = false;
      renderAuthState();
      showToast("Authentication expired. Please sign in again.", 3600);
      return false;
    }
    if (err?.rateLimited || err?.status === 429) {
      window.opsAuth.clearToken();
      state.authenticated = false;
      state.lockedOut = true;
      renderAuthState();
      showToast("Too many failed login attempts. Please wait before trying again.", 4200);
      return false;
    }
    showToast(err.message || "Failed to load jobs.", 3600);
    return false;
  }
}

async function validateStoredToken() {
  const token = window.opsAuth?.getToken?.() || "";
  if (!token) {
    state.authenticated = !state.authRequired;
    state.lockedOut = false;
    renderAuthState();
    if (!state.authRequired) {
      await refreshJobs();
    }
    return;
  }
  const ok = await refreshJobs();
  if (ok && state.nextPath) {
    window.location.href = state.nextPath;
  }
}

async function onSubmit(event) {
  event.preventDefault();
  const username = String(els.usernameInput?.value || "").trim();
  const password = String(els.passwordInput?.value || "");
  if (!username || !password) {
    showToast("Please enter both username and password.", 3200);
    return;
  }
  state.lockedOut = false;
  els.loginBtn.disabled = true;
  try {
    const token = window.btoa(`${username}:${password}`);
    window.opsAuth.setToken(token);
    const ok = await refreshJobs();
    if (!ok) {
      return;
    }
    showToast("Operational session is ready.");
    els.passwordInput.value = "";
    if (state.nextPath) {
      window.location.href = state.nextPath;
    }
  } finally {
    els.loginBtn.disabled = false;
  }
}

function openReport() {
  if (!state.authenticated) {
    showToast("Please sign in first.", 3200);
    return;
  }
  window.location.href = "/ops-report.html";
}

async function runDaily() {
  if (!window.opsAuth.isLocalhost()) {
    showToast("Run Daily can only be triggered from localhost.", 3600);
    return;
  }
  els.runDailyBtn.disabled = true;
  try {
    const payload = await window.opsAuth.json("/api/run-daily", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skip_telegram: true }),
    });
    const jobId = payload?.job?.job_id || "-";
    showToast(`Run Daily submitted: ${jobId}`);
    await refreshJobs();
  } catch (err) {
    if (err?.unauthorized) {
      showToast("Please sign in first.", 3200);
      return;
    }
    showToast(err.message || "Run Daily submission failed.", 4200);
  } finally {
    renderAuthState();
  }
}

function logout() {
  window.opsAuth.clearToken();
  state.authenticated = false;
  state.latestJobs = null;
  state.lockedOut = false;
  renderAuthState();
  showToast("Operational session cleared.");
}

function init() {
  const params = new URLSearchParams(window.location.search);
  const next = String(params.get("next") || "").trim();
  state.nextPath = next && next !== "/ops-login.html" ? next : "";

  els.loginForm?.addEventListener("submit", onSubmit);
  els.logoutBtn?.addEventListener("click", logout);
  els.refreshJobsBtn?.addEventListener("click", refreshJobs);
  els.openCloseAnalysisBtn?.addEventListener("click", () => {
    window.location.href = "/close-analysis.html";
  });
  els.openReportBtn?.addEventListener("click", openReport);
  els.runDailyBtn?.addEventListener("click", runDaily);

  probeAuthState()
    .then(validateStoredToken)
    .catch(() => renderAuthState());
}

document.addEventListener("DOMContentLoaded", init);
