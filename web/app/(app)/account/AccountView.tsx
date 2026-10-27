"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { ME_KEY, authErrorMessage, useMe } from "@/lib/auth";
import type { TokenResponse } from "@/lib/types";
import {
  PASSWORD_MAX_BYTES, PASSWORD_MIN_BYTES, passwordChangeSchema, type PasswordChangeForm as Values,
} from "@/lib/validation";

const when = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : "—";

export function AccountView() {
  const { data: user } = useMe();   // loaded by the app shell before this renders
  if (!user) return null;

  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-2xl font-semibold">Account</h1>
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-500">Profile</h2>
        <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
          <dt className="text-slate-500">Email</dt><dd>{user.email}</dd>
          <dt className="text-slate-500">Username</dt><dd>{user.username}</dd>
          <dt className="text-slate-500">Role</dt><dd className="capitalize">{user.role}</dd>
          <dt className="text-slate-500">Member since</dt><dd>{when(user.created_at)}</dd>
          <dt className="text-slate-500">Last sign-in</dt><dd>{when(user.last_login_at)}</dd>
        </dl>
      </section>
      <PasswordChange />
    </div>
  );
}

function PasswordChange() {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(passwordChangeSchema),
  });

  async function onSubmit({ confirm: _, ...change }: Values) {
    setResult(null);
    try {
      // New session cookies come back; every other session's refresh token is revoked
      const session = await api<TokenResponse>("/auth/password", { json: change });
      queryClient.setQueryData(ME_KEY, session.user);
      reset();
      setResult({ tone: "success", text: "Password changed. Your other sessions end within 15 minutes, "
                                          + "when their access token expires." });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setError("current_password", { message: e.message });   // "Current password is incorrect"
      } else {
        setResult({ tone: "error", text: authErrorMessage(e) });
      }
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-500">Change password</h2>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="max-w-sm space-y-4">
        <Field label="Current password" type="password" autoComplete="current-password"
               {...register("current_password")} error={errors.current_password?.message} />
        <Field label="New password" type="password" autoComplete="new-password" {...register("new_password")}
               error={errors.new_password?.message} hint={`${PASSWORD_MIN_BYTES}–${PASSWORD_MAX_BYTES} characters`} />
        <Field label="Repeat the new password" type="password" autoComplete="new-password" {...register("confirm")}
               error={errors.confirm?.message} />
        {result && <Alert tone={result.tone}>{result.text}</Alert>}
        <Button type="submit" pending={isSubmitting}>{isSubmitting ? "Saving…" : "Change password"}</Button>
      </form>
    </section>
  );
}
