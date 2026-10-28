"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui";
import { readCookie } from "@/lib/api";
import { ME_KEY, authErrorMessage, verifyEmail } from "@/lib/auth";
import { CSRF_COOKIE } from "@/lib/session";

type State =
  | { status: "pending" }
  | { status: "done"; email: string }
  | { status: "failed"; message: string };

const linkClass = "font-medium text-brand-700 hover:underline";

/** The page an email's verification link opens. No session needed: it may open on another device. */
export function VerifyEmail() {
  const token = useSearchParams().get("token");
  const queryClient = useQueryClient();
  const [state, setState] = useState<State>(token ? { status: "pending" }
    : { status: "failed", message: "This link is incomplete. Open it from the email again." });
  // Read after hydration: the server can't see cookies, and a mismatch would be a console error
  const [signedIn, setSignedIn] = useState(false);
  const sent = useRef(false);

  useEffect(() => {
    setSignedIn(!!readCookie(CSRF_COOKIE));
    // Once, also when React runs effects twice in development (a second use would still succeed)
    if (!token || sent.current) return;
    sent.current = true;
    verifyEmail(token).then(
      (r) => {
        setState({ status: "done", email: r.email });
        queryClient.invalidateQueries({ queryKey: ME_KEY });
      },
      (e) => setState({ status: "failed", message: authErrorMessage(e) }),
    );
  }, [token, queryClient]);

  if (state.status === "pending") {
    return <h1 className="text-xl font-semibold">Confirming your email address…</h1>;
  }
  if (state.status === "done") {
    return (
      <>
        <h1 className="text-xl font-semibold">Email address confirmed</h1>
        <p className="mb-6 mt-2 text-sm text-slate-600">{state.email} is confirmed. You can use AI-IDS now.</p>
        <Link href={signedIn ? "/dashboard" : "/login"} className={linkClass}>
          {signedIn ? "Continue to the dashboard" : "Sign in"}
        </Link>
      </>
    );
  }
  return (
    <>
      <h1 className="text-xl font-semibold">The address isn&apos;t confirmed</h1>
      <div className="mb-6 mt-4"><Alert>{state.message}</Alert></div>
      <p className="text-sm text-slate-600">
        {signedIn
          ? <><Link href="/dashboard" className={linkClass}>Back to AI-IDS</Link>, where you can send a new link.</>
          : <><Link href="/login" className={linkClass}>Sign in</Link> to send a new link.</>}
      </p>
    </>
  );
}
