"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { ApiError, api, readCookie } from "@/lib/api";
import { CSRF_COOKIE } from "@/lib/session";
import type { TokenResponse, User, VerificationSent, VerifyEmailResponse } from "@/lib/types";

export const ME_KEY = ["me"] as const;
export const VERIFY_POLL_MS = 5_000;

/** The signed-in user. Role and active status come from the API on every call, never from a cookie.
 *  While the email address awaits confirmation, it is asked again every few seconds, so the app opens
 *  by itself once the link has been used (often in another tab or on a phone). */
export function useMe({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ME_KEY, queryFn: () => api<User>("/auth/me"), staleTime: 60_000, enabled,
    refetchInterval: (query) => (query.state.data?.needs_email_verification ? VERIFY_POLL_MS : false),
  });
}

/** A new verification link for the signed-in user (earlier ones stop working). */
export function resendVerification() {
  return api<VerificationSent>("/auth/verify-email/resend", { method: "POST" });
}

/** Confirm an address with the token of its link; needs no session. */
export function verifyEmail(token: string) {
  return api<VerifyEmailResponse>("/auth/verify-email", { json: { token } });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      queryClient.clear();
      window.location.assign("/login");   // a full load: no data of this user survives in memory
    }
  };
}

export class CookiesRefused extends Error {
  constructor() {
    // The API's cookies are Secure: over plain http (other than localhost) the browser drops them,
    // and every page would bounce back to /login without a word
    super("Signed in, but the browser refused the session cookies. Open the site over HTTPS "
          + "(or http://localhost), or set IDS_COOKIE_SECURE=false for plain-http access.");
    this.name = "CookiesRefused";
  }
}

/** After a successful sign-in or sign-up: make sure the session stuck, then go on to `next`. */
export function useCompleteSignIn(next: string) {
  const router = useRouter();
  const queryClient = useQueryClient();
  return (session: TokenResponse) => {
    if (!readCookie(CSRF_COOKIE)) throw new CookiesRefused();
    queryClient.setQueryData(ME_KEY, session.user);
    router.replace(next);
  };
}

/** A sentence for a failed auth request. */
export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return error.retryAfter
      ? `Too many attempts. Try again in ${error.retryAfter} s.`
      : "Too many attempts. Try again in a minute.";
  }
  if (error instanceof ApiError || error instanceof CookiesRefused) return error.message;
  return "Can't reach the server. Check your connection and try again.";
}
