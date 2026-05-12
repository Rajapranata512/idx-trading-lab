(function () {
  const STORAGE_KEY = "idxOpsBasicAuth";

  function getToken() {
    try {
      return window.sessionStorage.getItem(STORAGE_KEY) || "";
    } catch {
      return "";
    }
  }

  function setToken(token) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, token || "");
    } catch {}
  }

  function clearToken() {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {}
  }

  function authHeaders(extraHeaders = {}) {
    const token = getToken();
    return token
      ? { Authorization: `Basic ${token}`, ...extraHeaders }
      : { ...extraHeaders };
  }

  function isLocalhost() {
    const host = String(window.location.hostname || "").trim().toLowerCase();
    return host === "127.0.0.1" || host === "::1" || host === "localhost";
  }

  function redirectToLogin(nextPath) {
    const next = nextPath || `${window.location.pathname}${window.location.search || ""}`;
    const target = `/ops-login.html?next=${encodeURIComponent(next)}`;
    window.location.href = target;
  }

  async function request(path, options = {}) {
    const headers = authHeaders(options.headers || {});
    const response = await fetch(path, { ...options, headers });
    if (response.status === 401) {
      const error = new Error("Authentication required");
      error.unauthorized = true;
      error.status = 401;
      throw error;
    }
    if (response.status === 429) {
      let message = "Too many attempts. Please wait before trying again.";
      try {
        message = await response.text();
      } catch {}
      const error = new Error(message);
      error.rateLimited = true;
      error.status = 429;
      throw error;
    }
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        message = await response.text();
      } catch {}
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return response;
  }

  async function json(path, options = {}) {
    const response = await request(path, options);
    return response.json();
  }

  async function text(path, options = {}) {
    const response = await request(path, options);
    return response.text();
  }

  window.opsAuth = {
    getToken,
    setToken,
    clearToken,
    authHeaders,
    isLocalhost,
    redirectToLogin,
    request,
    json,
    text,
  };
})();
