import { NextResponse, type NextRequest } from "next/server";

import { CSRF_COOKIE, sessionRedirect } from "@/lib/session";

/** Pages need a session: without one, go to /login?next=<page>. The API still checks every call. */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const target = sessionRedirect(pathname, search, request.cookies.has(CSRF_COOKIE));
  return target ? NextResponse.redirect(new URL(target, request.url)) : NextResponse.next();
}

export const config = {
  // Never /api: in `next dev` uploads pass through here, and proxy buffers (and cuts) bodies over 10 MB.
  // Nor Next's own assets.
  matcher: ["/((?!api/|_next/static|_next/image|favicon\\.ico|favicon\\.svg).*)"],
};
