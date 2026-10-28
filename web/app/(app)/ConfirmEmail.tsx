"use client";

import { useState } from "react";

import { Alert, Button } from "@/components/ui";
import { authErrorMessage, resendVerification, useLogout } from "@/lib/auth";
import type { User } from "@/lib/types";

/**
 * Shown instead of the app while the account's email address awaits confirmation
 * (IDS_EMAIL_VERIFICATION). useMe asks again every few seconds, so the app opens by itself once the
 * link has been used, in another tab or on another device.
 */
export function ConfirmEmail({ user }: { user: User }) {
  const logout = useLogout();
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  async function resend() {
    setPending(true);
    setNote(null);
    try {
      const sent = await resendVerification();
      setNote({ tone: "success", text: `A new link is on its way to ${sent.sent_to}. Earlier links no longer work.` });
    } catch (e) {
      setNote({ tone: "error", text: authErrorMessage(e) });
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <span className="mb-6 text-2xl font-semibold text-brand-700">AI-IDS</span>
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold">Confirm your email address</h1>
        <p className="mt-2 text-sm text-slate-600">
          We sent a link to <strong className="break-all">{user.email}</strong>. Open it to start using AI-IDS;
          this page goes on by itself once you have.
        </p>
        <p className="mt-2 text-sm text-slate-500">Nothing there? Look in the spam folder, or send a new link.</p>
        {note && <div className="mt-4"><Alert tone={note.tone}>{note.text}</Alert></div>}
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <Button onClick={resend} pending={pending}>{pending ? "Sending…" : "Send a new link"}</Button>
          <button onClick={logout} className="text-sm font-medium text-slate-600 hover:underline">Sign out</button>
        </div>
      </div>
    </main>
  );
}
