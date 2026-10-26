"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { authErrorMessage, useCompleteSignIn } from "@/lib/auth";
import { nextPath } from "@/lib/session";
import type { TokenResponse } from "@/lib/types";
import { PASSWORD_MAX_BYTES, PASSWORD_MIN_BYTES, signupSchema, type SignupForm as Values } from "@/lib/validation";

export function SignupForm() {
  const params = useSearchParams();
  const next = nextPath(params.get("next"));
  const completeSignIn = useCompleteSignIn(next);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, setError: setFieldError, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(signupSchema),
  });

  async function onSubmit({ confirm: _, ...account }: Values) {
    setError(null);
    try {
      // The API signs the new account in straight away (201 + session cookies)
      completeSignIn(await api<TokenResponse>("/auth/signup", { json: account }));
    } catch (e) {
      // 409: "That email is already registered" / "That username is already registered"
      if (e instanceof ApiError && e.status === 409) {
        setFieldError(e.message.includes("username") ? "username" : "email", { message: e.message });
      } else {
        setError(authErrorMessage(e));
      }
    }
  }

  const loginHref = params.get("next") ? `/login?next=${encodeURIComponent(next)}` : "/login";
  return (
    <>
      <h1 className="text-xl font-semibold">Create an account</h1>
      <p className="mb-6 mt-1 text-sm text-slate-500">Upload flow CSVs and see what they contain</p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <Field label="Email" type="email" autoComplete="email" autoFocus {...register("email")}
               error={errors.email?.message} />
        <Field label="Username" autoComplete="username" {...register("username")}
               error={errors.username?.message} hint="3–64 characters: letters, digits, _ . -" />
        <Field label="Password" type="password" autoComplete="new-password" {...register("password")}
               error={errors.password?.message} hint={`${PASSWORD_MIN_BYTES}–${PASSWORD_MAX_BYTES} characters`} />
        <Field label="Repeat the password" type="password" autoComplete="new-password" {...register("confirm")}
               error={errors.confirm?.message} />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" pending={isSubmitting} className="w-full">
          {isSubmitting ? "Creating the account…" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-600">
        Already registered? <Link href={loginHref} className="font-medium text-brand-700 hover:underline">Sign in</Link>
      </p>
    </>
  );
}
