// Cookie names set by the API (src/api/auth/security.py)
export const CSRF_COOKIE = "ids_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

// Pages reachable without a session
export const PUBLIC_PATHS = ["/login", "/signup", "/healthz"];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * Where proxy.ts sends a page request, or null to let it through.
 *
 * The session cookies themselves are invisible here: ids_access is scoped to /api and ids_refresh
 * to /api/v1/auth. ids_csrf (path /, same lifetime as the refresh token, cleared on logout or a
 * failed refresh) is the signal that a session probably exists. The API decides for real: a page
 * whose calls come back 401 goes through refresh, then to /login.
 */
export function sessionRedirect(pathname: string, search: string, hasSession: boolean): string | null {
  if (hasSession || isPublicPath(pathname)) return null;
  const next = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
  return `/login${next}`;
}

/** A safe post-login destination: same-origin paths only, never back to a public page. */
export function nextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/dashboard";
  const path = raw.split("?")[0];
  return isPublicPath(path) ? "/dashboard" : raw;
}
