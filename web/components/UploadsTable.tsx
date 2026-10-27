"use client";

import Link from "next/link";
import { useState } from "react";

import { UploadStatus } from "@/components/UploadStatus";
import { formatBytes, formatDateTime, formatDuration, formatNumber } from "@/lib/format";
import type { Upload } from "@/lib/types";
import { isActive, useDeleteUpload } from "@/lib/uploads";

export function UploadsTable({ uploads, compact = false }: { uploads: Upload[]; compact?: boolean }) {
  if (uploads.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-slate-500">No uploads yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">File</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 text-right font-medium">Flows</th>
            {!compact && <th className="px-4 py-2 text-right font-medium">Size</th>}
            <th className="px-4 py-2 font-medium">Uploaded</th>
            {!compact && <th className="px-4 py-2 text-right font-medium">Processing</th>}
            {!compact && <th className="px-4 py-2" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {uploads.map((u) => <Row key={u.id} upload={u} compact={compact} />)}
        </tbody>
      </table>
    </div>
  );
}

function Row({ upload, compact }: { upload: Upload; compact: boolean }) {
  return (
    <tr data-upload-id={upload.id}>
      <td className="max-w-xs px-4 py-2">
        <Link href={`/uploads/${upload.id}`} title={upload.original_filename}
              className="block truncate font-medium text-brand-700 hover:underline">
          {upload.original_filename}
        </Link>
        {upload.status === "failed" && upload.error && (
          <span className="block text-xs text-red-600">{upload.error}</span>
        )}
      </td>
      <td className="px-4 py-2"><UploadStatus upload={upload} /></td>
      <td className="px-4 py-2 text-right tabular-nums">{formatNumber(upload.n_flows)}</td>
      {!compact && <td className="px-4 py-2 text-right tabular-nums">{formatBytes(upload.size_bytes)}</td>}
      <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(upload.created_at)}</td>
      {!compact && <td className="px-4 py-2 text-right tabular-nums">{formatDuration(upload.processing_ms)}</td>}
      {!compact && <td className="px-4 py-2 text-right"><DeleteButton upload={upload} /></td>}
    </tr>
  );
}

function DeleteButton({ upload }: { upload: Upload }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteUpload();
  if (remove.isPending) return <span className="text-xs text-slate-500">Deleting…</span>;
  if (!confirming) {
    return (
      <button onClick={() => setConfirming(true)} className="text-xs text-slate-500 hover:text-red-600"
              title={isActive(upload.status) ? "Stops the analysis and deletes the file" : "Deletes the file and its results"}>
        Delete
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <span className="text-slate-600">Delete?</span>
      <button onClick={() => remove.mutate(upload.id)} className="font-medium text-red-600 hover:underline">Yes</button>
      <button onClick={() => setConfirming(false)} className="text-slate-500 hover:underline">No</button>
    </span>
  );
}
