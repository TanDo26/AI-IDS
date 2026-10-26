/**
 * The one way the browser talks to the API (/api/v1, same origin).
 *
 * - Cookies go along automatically (credentials: "same-origin"); nothing is kept in localStorage.
 * - POST/PUT/PATCH/DELETE carry X-CSRF-Token, copied from the readable ids_csrf cookie.
 * - A 401 that asks for authentication (WWW-Authenticate: a missing, expired or invalid access
 *   token) triggers one refresh, shared by every request that hit it at the same time, and one
 *   retry. Other 401s answer what the user typed (wrong password) and are returned as they are.
 *   If the refresh fails, the session is over: onSessionExpired runs (default: go to /login).
 * - Errors become ApiError with FastAPI's `detail` turned into a readable message.
 */
import { CSRF_COOKIE, CSRF_HEADER, isPublicPath } from "@/lib/session";

export const API_BASE = "/api/v1";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Never refreshed, whatever they answer: they are the session's own endpoints
const NO_REFRESH = ["/auth/login", "/auth/signup", "/auth/refresh", "/auth/logout"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
    public readonly retryAfter?: number,   // seconds, from Retry-After (429)
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  method?: string;
  json?: unknown;                 // sent as application/json
  body?: BodyInit;                // e.g. FormData
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  for (const part of document.cookie.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return undefined;
}

/** FastAPI errors: {"detail": "text"}, {"detail": {"message": ...}} or a 422 list of {loc, msg}. */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String(detail.message);
  return status >= 500 ? "The server had a problem; please try again." : `Request failed (${status})`;
}

export function defaultSessionExpired() {
  const { pathname, search } = window.location;
  if (!isPublicPath(pathname)) {
    window.location.assign(`/login?next=${encodeURIComponent(pathname + search)}&expired=1`);
  }
}

let sessionExpiredHandler = defaultSessionExpired;

/** Replace what happens when the session is over (tests, or a custom notice). */
export function onSessionExpired(handler: () => void) {
  sessionExpiredHandler = handler;
}

/** The session is over (for requests made outside apiFetch, e.g. uploads with progress). */
export function expireSession() {
  sessionExpiredHandler();
}

function send(path: string, method: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
  }
  return fetch(`${API_BASE}${path}`, { method, headers, body, credentials: "same-origin", signal: options.signal });
}

let refreshing: Promise<boolean> | null = null;

/** Rotate the refresh token. Concurrent callers share one request: a refresh token works once. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= send("/auth/refresh", "POST", {})
    .then((r) => r.ok, () => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** fetch() through the session rules; the caller reads the body (downloads, streams). */
export async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  const method = (options.method ?? (options.json !== undefined || options.body ? "POST" : "GET")).toUpperCase();
  const response = await send(path, method, options);
  const asksForAuth = response.status === 401 && response.headers.has("WWW-Authenticate");
  if (!asksForAuth || NO_REFRESH.some((p) => path.startsWith(p))) return response;
  if (await refreshSession()) return send(path, method, options);
  sessionExpiredHandler();
  return response;
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** JSON request; resolves with the parsed body (undefined for 204), rejects with ApiError. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await apiFetch(path, options);
  const body = await readBody(response);
  if (!response.ok) {
    const retryAfter = Number(response.headers.get("Retry-After")) || undefined;
    throw new ApiError(response.status, errorMessage(body, response.status), body, retryAfter);
  }
  return body as T;
}
