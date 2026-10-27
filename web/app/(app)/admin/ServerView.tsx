"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Alert } from "@/components/ui";
import { REFRESH_MS, formatUptime, gib, useServerStatus } from "@/lib/admin";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { ServerStatus } from "@/lib/types";

const UPLOAD_STATUSES = ["queued", "converting", "predicting", "completed", "failed"];

export function ServerView() {
  const status = useServerStatus();

  if (status.isPending) return <p className="text-sm text-slate-500">Checking the server…</p>;
  if (!status.data) return <Alert>{status.error?.message ?? "No answer from the server."}</Alert>;

  const s = status.data;
  const workers = s.queue.workers ?? [];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">Server status</h1>
        <p className="text-sm text-slate-500" aria-live="polite">
          Checked {new Date(s.checked_at).toLocaleTimeString()} · refreshes every {REFRESH_MS / 1000} s
          {status.isError && <span className="text-red-700"> · the last refresh failed: {status.error.message}</span>}
        </p>
      </div>

      {s.warnings.length > 0 ? (
        <section aria-label="Problems" className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <h2 className="flex items-center gap-2 text-sm font-medium text-amber-900">
            <span className="h-2.5 w-2.5 rounded-full bg-status-warning" aria-hidden />
            {s.warnings.length === 1 ? "1 problem" : `${s.warnings.length} problems`}
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-6 text-sm text-amber-900">
            {s.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </section>
      ) : <Alert tone="success">No problems found.</Alert>}

      <section aria-label="Services" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Service name="API" ok detail={`Version ${s.api.version} · up ${formatUptime(s.api.uptime_s)}`}
                 note={`Answered by ${s.api.process}`} />
        <Service name="Database" ok={s.database.ok} detail={s.database.ok ? "Connected" : s.database.error} />
        <Service name="Redis" ok={s.redis.ok} detail={s.redis.ok ? "Connected" : s.redis.error} />
        <Service name="Workers" ok={s.queue.ok && workers.length > 0}
                 detail={!s.queue.ok ? (s.queue.error ?? "Not checked")
                   : workers.length ? `${workers.length} answering` : "None answering"}
                 note={workers.join(", ")} />
      </section>

      <section aria-label="Host" className="grid gap-4 sm:grid-cols-3">
        <Meter label="CPU" percent={s.system.cpu_percent} detail="All cores" />
        <Meter label="Memory" percent={s.system.ram_percent} high={s.system.ram_percent >= 90}
               detail={`${gib(s.system.ram_used_mb)} of ${gib(s.system.ram_total_mb)}`} />
        <Meter label="Disk (data volume)" percent={s.system.disk_percent} high={s.system.disk_warning}
               detail={`${s.system.disk_free_gb.toFixed(1)} GiB free of ${s.system.disk_total_gb.toFixed(0)} GiB`} />
        {s.system.gpus.map((g) => (
          <Meter key={g.name} label={`GPU · ${g.name}`} percent={g.utilization_percent}
                 detail={`${gib(g.memory_used_mb)} of ${gib(g.memory_total_mb)} memory`} />
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Jobs">
          <Facts items={[
            ["Waiting in the queue", formatNumber(s.queue.queued)],
            ["Running or reserved", formatNumber(s.queue.unacknowledged)],
            ...(s.uploads ? uploadFacts(s.uploads) : [["Uploads", "Database unreachable"] as [string, ReactNode]]),
          ]} />
        </Card>
        <Card title="Model">
          <ModelFacts model={s.model} />
        </Card>
      </div>
    </div>
  );
}

function uploadFacts(u: NonNullable<ServerStatus["uploads"]>): Array<[string, ReactNode]> {
  return [
    ...UPLOAD_STATUSES.map((st): [string, ReactNode] => [`Uploads ${st}`, formatNumber(u.by_status[st] ?? 0)]),
    ["Failed in the last 24 h", formatNumber(u.failed_last_24h)],
    ["Stuck (over 35 min)", <span key="stuck" className={u.stuck ? "text-red-700" : ""}>{formatNumber(u.stuck)}</span>],
  ];
}

function ModelFacts({ model }: { model: ServerStatus["model"] }) {
  const mismatch = model.loaded !== model.active_in_store;
  return (
    <div className="space-y-3">
      <Facts items={[
        ["Serving (this process)", <span key="l" className="font-mono text-xs">{model.loaded ?? "nothing"}</span>],
        ["Active in the database", <span key="a" className={`font-mono text-xs ${mismatch ? "text-red-700" : ""}`}>
          {model.active_in_store ?? "none"}</span>],
        ["Loaded", formatDateTime(model.loaded_at)],
        ["Processes on another version", model.lagging_processes == null ? "Unknown (no Redis)" : formatNumber(model.lagging_processes)],
      ]} />
      {model.last_error && <Alert>Last load failure: {model.last_error}</Alert>}
      <Link href="/admin/models" className="inline-block text-sm font-medium text-brand-700 hover:underline">
        Manage models →
      </Link>
    </div>
  );
}

/** One dependency: a status dot and its word, never the colour alone. */
function Service({ name, ok, detail, note }: { name: string; ok: boolean; detail?: string | null; note?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="flex items-center justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-slate-500">{name}</span>
        <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${ok ? "text-emerald-800" : "text-red-700"}`}>
          <span className={`h-2 w-2 rounded-full ${ok ? "bg-status-good" : "bg-status-critical"}`} aria-hidden />
          {ok ? "OK" : "Down"}
        </span>
      </p>
      <p className="mt-2 text-sm font-medium">{detail}</p>
      {note && <p className="mt-0.5 truncate text-xs text-slate-500" title={note}>{note}</p>}
    </div>
  );
}

/** A share of capacity: the number leads, the bar shows it, "High" says when it is too much. */
function Meter({ label, percent, detail, high = false }: { label: string; percent: number; detail: string; high?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{Math.round(percent)}%</span>
        {high && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-900">High</span>}
      </p>
      <div role="meter" aria-label={label} aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}
           className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${high ? "bg-status-warning" : "bg-viz-bar"}`}
             style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-slate-500">{detail}</p>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="space-y-2 text-sm">
      {items.map(([term, value]) => (
        <div key={term} className="flex justify-between gap-4">
          <dt className="text-slate-500">{term}</dt>
          <dd className="text-right font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
