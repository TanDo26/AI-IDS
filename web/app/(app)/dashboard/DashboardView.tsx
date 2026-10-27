"use client";

import Link from "next/link";

import { UploadDropzone } from "@/components/UploadDropzone";
import { UploadsTable } from "@/components/UploadsTable";
import { Alert } from "@/components/ui";
import { useMe } from "@/lib/auth";
import { formatBytes, formatNumber } from "@/lib/format";
import { useNoActiveModel } from "@/lib/readiness";
import { isActive, useInvalidateUploads, useUploadStats, useUploads } from "@/lib/uploads";

export function DashboardView() {
  const me = useMe();
  const recent = useUploads(1, 5);
  const processing = recent.data?.items.some((u) => isActive(u.status)) ?? false;
  const stats = useUploadStats(processing);
  const invalidate = useInvalidateUploads();
  const noModel = useNoActiveModel();
  const s = stats.data;

  const cards = [
    { label: "Uploads", value: formatNumber(s?.uploads) },
    { label: "Flows analysed", value: formatNumber(s?.flows) },
    { label: "Known attacks", value: formatNumber(s?.known_attacks) },
    { label: "Unknown", value: formatNumber(s?.unknown), hint: "Low confidence or unusual: worth a look" },
    { label: "Data uploaded", value: formatBytes(s?.bytes) },
  ];

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Welcome, {me.data?.username}</h1>
      {noModel && <Alert tone="info">No model is active yet, so uploads can&apos;t be analysed. Ask an admin to activate one.</Alert>}
      {(recent.isError || stats.isError) && <Alert>{(recent.error ?? stats.error)?.message}</Alert>}

      <section aria-label="Your totals" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-4" title={c.hint}>
            <p className="text-xs uppercase tracking-wide text-slate-500">{c.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{s ? c.value : stats.isError ? "—" : "…"}</p>
          </div>
        ))}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">Quick upload</h2>
        <UploadDropzone disabled={noModel} onUploaded={() => invalidate()} />
      </section>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">Recent uploads</h2>
          <Link href="/uploads" className="text-sm font-medium text-brand-700 hover:underline">View all</Link>
        </div>
        {recent.data ? <UploadsTable uploads={recent.data.items} compact />
                     : <p className="px-4 py-8 text-center text-sm text-slate-500">
                         {recent.isError ? "Your uploads couldn't be loaded." : "Loading…"}
                       </p>}
      </section>
    </div>
  );
}
