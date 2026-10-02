import { API_BASE } from "../lib/api";

export function backendAlert() {
  alert(
    `Backend not reachable at ${API_BASE}\n\n` +
      "Start it first (keep the window open):\n" +
      "1. Double-click run.bat in the project folder, OR\n" +
      "2. In a terminal: cd backend\n" +
      "   py -3 -m uvicorn main:app --host 127.0.0.1 --port 8000"
  );
}

export function isNetworkError(error: unknown): boolean {
  if (!(error instanceof TypeError)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("failed to fetch") ||
    message.includes("networkerror") ||
    message.includes("load failed")
  );
}

export async function readApiError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => String(item)).join(", ");
    }
  } catch {
    // ignore JSON parse errors
  }
  return fallback;
}

export function showSubmitError(error: unknown, fallback: string) {
  if (isNetworkError(error)) {
    backendAlert();
    return;
  }
  const message = error instanceof Error ? error.message : fallback;
  alert(message || fallback);
}
