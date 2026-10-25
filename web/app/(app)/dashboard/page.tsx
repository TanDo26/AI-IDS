"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import type { Readiness } from "@/lib/types";

// Placeholder until feature/web-uploads: shows that the browser, the session and the API are connected
export default function DashboardPage() {
  const me = useMe();
  const ready = useQuery({ queryKey: ["readyz"], queryFn: () => api<Readiness>("/readyz").catch(readinessFromError) });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Welcome, {me.data?.username}</h1>
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-500">Service status</h2>
        {ready.data ? (
          <ul className="grid gap-3 sm:grid-cols-3">
            {Object.entries(ready.data.checks).map(([name, check]) => (
              <li key={name} className="flex items-center gap-2 text-sm">
                <span className={`h-2.5 w-2.5 rounded-full ${check.ok ? "bg-emerald-500" : "bg-red-500"}`} />
                <span className="capitalize">{name}</span>
                {name === "model" && typeof check.loaded === "string" && (
                  <span className="truncate text-slate-500">{check.loaded}</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">Checking…</p>
        )}
      </section>
    </div>
  );
}

// /readyz answers 503 with the same body when something is down; show it rather than an error
function readinessFromError(error: { detail?: unknown }): Readiness {
  const body = error.detail as Readiness | undefined;
  if (body?.checks) return body;
  throw error;
}
