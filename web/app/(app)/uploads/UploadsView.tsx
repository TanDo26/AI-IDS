"use client";

import Link from "next/link";
import { useState } from "react";

import { UploadsTable } from "@/components/UploadsTable";
import { Alert } from "@/components/ui";
import type { UploadStatus } from "@/lib/types";
import { useUploads } from "@/lib/uploads";

const PAGE_SIZE = 20;
const FILTERS: Array<{ label: string; status?: UploadStatus }> = [
  { label: "All" },
  { label: "Analysing", status: "predicting" },
  { label: "Queued", status: "queued" },
  { label: "Completed", status: "completed" },
  { label: "Failed", status: "failed" },
];

export function UploadsView() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<UploadStatus | undefined>();
  const uploads = useUploads(page, PAGE_SIZE, status);
  const pages = uploads.data ? Math.max(1, Math.ceil(uploads.data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Uploads</h1>
        <Link href="/uploads/new" className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          New upload
        </Link>
      </div>
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f.label} role="tab" aria-selected={status === f.status}
                  onClick={() => { setStatus(f.status); setPage(1); }}
                  className={`rounded-md px-3 py-1.5 text-sm ${status === f.status
                    ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
            {f.label}
          </button>
        ))}
      </div>
      {uploads.isError && <Alert>{uploads.error.message}</Alert>}
      <section className="rounded-xl border border-slate-200 bg-white">
        {uploads.data ? <UploadsTable uploads={uploads.data.items} />
                      : <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p>}
      </section>
      {uploads.data && uploads.data.total > PAGE_SIZE && (
        <nav className="flex items-center justify-end gap-3 text-sm" aria-label="Pages">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}
                  className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Previous</button>
          <span className="text-slate-600">Page {page} of {pages}</span>
          <button disabled={page >= pages} onClick={() => setPage(page + 1)}
                  className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Next</button>
        </nav>
      )}
    </div>
  );
}
