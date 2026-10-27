"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Alert, Button, Field } from "@/components/ui";
import { api, readCookie } from "@/lib/api";
import { authErrorMessage, useCompleteSignIn, useMe } from "@/lib/auth";
import { CSRF_COOKIE, nextPath } from "@/lib/session";
import type { TokenResponse } from "@/lib/types";
import { loginSchema, type LoginForm as Values } from "@/lib/validation";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = nextPath(params.get("next"));
  const completeSignIn = useCompleteSignIn(next);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(loginSchema),
  });

  // Already signed in (e.g. a bookmarked /login): go straight on. Only asked when a session may exist.
  const me = useMe({ enabled: Boolean(readCookie(CSRF_COOKIE)) });
  useEffect(() => {
    if (me.data) router.replace(next);
  }, [me.data, next, router]);

  async function onSubmit(values: Values) {
    setError(null);
    try {
      completeSignIn(await api<TokenResponse>("/auth/login", { json: values }));
    } catch (e) {
      setError(authErrorMessage(e));
    }
  }

  const signupHref = params.get("next") ? `/signup?next=${encodeURIComponent(next)}` : "/signup";
  return (
    <>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mb-6 mt-1 text-sm text-slate-500">Analyse network flows for known and unknown attacks</p>
      {params.get("expired") === "1" && !error && (
        <div className="mb-4"><Alert tone="info">Your session has ended. Please sign in again.</Alert></div>
      )}
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <Field label="Email" type="email" autoComplete="email" autoFocus {...register("email")}
               error={errors.email?.message} />
        <Field label="Password" type="password" autoComplete="current-password" {...register("password")}
               error={errors.password?.message} />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" pending={isSubmitting} className="w-full">
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-600">
        No account? <Link href={signupHref} className="font-medium text-brand-700 hover:underline">Create one</Link>
      </p>
    </>
  );
}
