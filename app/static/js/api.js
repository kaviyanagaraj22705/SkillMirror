// Fetch wrapper: JSON in, normalized error envelope out (§7.7).

const DEFAULT_TIMEOUT_MS = 30_000;

function normalizeError(err) {
  if (err && typeof err === "object" && "code" in err && "message" in err) return err;
  return {
    status: 0,
    code: "NETWORK_ERROR",
    message: "Could not reach the server.",
    requestId: null,
    details: null,
  };
}

async function request(path, { body, method = "GET", timeoutMs = DEFAULT_TIMEOUT_MS, headers: extra } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = { ...(extra ?? {}) };
  const options = { method, signal: controller.signal, credentials: "same-origin" };

  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  options.headers = headers;

  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw normalizeError({
      status: 0,
      code: error?.name === "AbortError" ? "TIMEOUT" : "NETWORK_ERROR",
      message:
        error?.name === "AbortError"
          ? "The server took too long to respond."
          : "Could not reach the server. Is SkillMirror still running?",
      requestId: null,
      details: null,
    });
  } finally {
    clearTimeout(timer);
  }

  const requestId = response.headers.get("X-Request-ID");
  if (response.ok) {
    if (response.status === 204) return null;
    if (response.status === 303) return null;
    return response.json();
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Non-JSON error body (HTML error page or empty) — fall through to defaults.
  }

  throw normalizeError({
    status: response.status,
    code: payload?.error?.code ?? `HTTP_${response.status}`,
    message:
      payload?.error?.message ??
      (response.status === 404
        ? "That item no longer exists."
        : "Something went wrong on our side. The details are below."),
    requestId: payload?.error?.request_id ?? requestId,
    details: payload?.error?.details ?? null,
  });
}

export function getMeta() {
  return request("/api/meta");
}

export function postAnalysis(payload) {
  return request("/api/analyses", { method: "POST", body: payload });
}

export function postAnalysisFile(formData) {
  // Same endpoint as the no-JS form; the header selects a JSON answer (§8.6).
  return request("/api/analyses/form", {
    method: "POST",
    body: formData,
    headers: { "X-SkillMirror-Client": "spa" },
    timeoutMs: 120_000,
  });
}

export function getAnalysis(id) {
  return request(`/api/analyses/${encodeURIComponent(id)}`);
}

export function listAnalyses({ limit = 20, offset = 0 } = {}) {
  return request(`/api/analyses?limit=${limit}&offset=${offset}`);
}

export function deleteAnalysis(id) {
  return request(`/api/analyses/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getJob(id) {
  return request(`/api/jobs/${encodeURIComponent(id)}`);
}

export function cancelJob(id) {
  return request(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export function retryRoadmap(id, payload) {
  return request(`/api/analyses/${encodeURIComponent(id)}/roadmap`, {
    method: "POST",
    body: payload,
  });
}
