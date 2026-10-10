// "" (empty) means "same origin" - used when the dashboard is served by nginx
// in front of the API. The `??` matters: `||` would turn "" into the default.
export const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

// Only needed when the backend runs with API_KEY set (protects write actions).
// NOTE: anything in a browser bundle is visible to its users - for a real
// plant put the dashboard behind your reverse proxy / SSO as well.
const API_KEY = import.meta.env.VITE_API_KEY || "";

export async function apiGet(path, signal) {
  const response = await fetch(`${API_BASE}${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

export async function apiSend(method, path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(API_KEY ? { "X-API-Key": API_KEY } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
    } catch {
      // not JSON - keep the generic message
    }
    throw new Error(detail);
  }
  return response.json();
}
