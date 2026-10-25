"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ApiError, api, readCookie } from "@/lib/api";
import { ME_KEY } from "@/lib/auth";
import { CSRF_COOKIE, nextPath } from "@/lib/session";
import type { TokenResponse } from "@/lib/types";

// A minimal sign-in form; validation, sign-up and the account page come with feature/web-auth
function LoginForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const next = nextPath(useSearchParams().get("next"));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      const session = await api<TokenResponse>("/auth/login", {
        json: { email: form.get("email"), password: form.get("password") },
      });
      if (!readCookie(CSRF_COOKIE)) {
        // The API's cookies are Secure: over plain http (other than localhost) the browser drops them,
        // and every page would bounce back here without a word
        setError("Signed in, but the browser refused the session cookies. Open the site over HTTPS "
                 + "(or http://localhost), or set IDS_COOKIE_SECURE=false for plain-http access.");
        setPending(false);
        return;
      }
      queryClient.setQueryData(ME_KEY, session.user);
      router.replace(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Can't reach the server");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <label className="block">
        <span className="text-sm font-medium text-slate-700">Email</span>
        <input name="email" type="email" required autoComplete="email" autoFocus
               className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600" />
      </label>
      <label className="block">
        <span className="text-sm font-medium text-slate-700">Password</span>
        <input name="password" type="password" required autoComplete="current-password"
               className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600" />
      </label>
      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <button type="submit" disabled={pending}
              className="w-full rounded-md bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60">
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold">AI-IDS</h1>
        <p className="mb-6 text-sm text-slate-500">Sign in to analyse network flows</p>
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
