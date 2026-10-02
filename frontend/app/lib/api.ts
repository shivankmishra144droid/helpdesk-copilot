// Single place for backend URL + request headers. Override per machine in
// frontend/.env.local:
//   NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
//   NEXT_PUBLIC_API_TOKEN=<same value as backend COPILOT_API_TOKEN>   (optional)
// NEXT_PUBLIC_API_BASE=/api makes the browser call this app's own origin; the
// rewrite in next.config.ts then proxies to the backend (single-container deploy).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN;

/**
 * fetch() wrapper for the backend. The custom X-Copilot-Client header forces a
 * CORS preflight, so other websites can't fire state-changing requests at the
 * local backend (the backend rejects writes without it).
 */
export function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  // Only writes need it; keeping GETs header-free avoids a preflight per poll.
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-Copilot-Client", "web");
    if (API_TOKEN) headers.set("X-API-Token", API_TOKEN);
  }
  // Callers pass either a path ("/search") or a URL already built from API_BASE.
  const alreadyPrefixed = /^https?:\/\//.test(input) || input.startsWith(`${API_BASE}/`);
  const url = alreadyPrefixed ? input : `${API_BASE}${input}`;
  return fetch(url, { ...init, headers });
}
