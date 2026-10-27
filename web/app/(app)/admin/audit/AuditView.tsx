"use client";

import { useState } from "react";

import { Pager } from "@/components/Pager";
import { Alert } from "@/components/ui";
import { ACTION_FILTERS, type AuditQuery, actionLabel, actorName, describeDetails, useAudit } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";

const PAGE_SIZE = 50;

export function AuditView({ initialTarget }: { initialTarget?: AuditQuery["target"] }) {
  const [query, setQuery] = useState<AuditQuery>({ page: 1, size: PAGE_SIZE, target: initialTarget });
  const audit = useAudit(query);
  const set = (change: Partial<AuditQuery>) => setQuery({ ...query, page: 1, ...change });
  // The actor's name for the filter chip, from any row of theirs
  const actor = audit.data?.items.find((e) => e.actor_id === query.actorId);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <div className="flex flex-wrap items-center gap-3">
        <select aria-label="Action" value={query.action ?? ""} onChange={(e) => set({ action: e.target.value || undefined })}
                className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
          {ACTION_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
        {query.actorId !== undefined && (
          <Chip label={`By ${actor ? actorName(actor) : `user #${query.actorId}`}`} onClear={() => set({ actorId: undefined })} />
        )}
        {query.target && (
          <Chip label={`On ${query.target.type} #${query.target.id}`} onClear={() => set({ target: undefined })} />
        )}
      </div>
      {audit.isError && <Alert>{audit.error.message}</Alert>}

      <section className="rounded-xl border border-slate-200 bg-white" aria-label="Entries">
        {!audit.data ? <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p>
          : audit.data.items.length === 0 ? <p className="px-4 py-8 text-center text-sm text-slate-500">Nothing recorded.</p>
          : (
            <div className={`overflow-x-auto ${audit.isPlaceholderData ? "opacity-60" : ""}`}>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">When</th>
                    <th className="px-4 py-2 font-medium">Who</th>
                    <th className="px-4 py-2 font-medium">What</th>
                    <th className="px-4 py-2 font-medium">Target</th>
                    <th className="px-4 py-2 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {audit.data.items.map((e) => <Row key={e.id} entry={e} onFilter={set} />)}
                </tbody>
              </table>
            </div>
          )}
        {audit.data && <Pager page={query.page} size={PAGE_SIZE} total={audit.data.total}
                              onPage={(page) => setQuery({ ...query, page })} />}
      </section>
    </div>
  );
}

/** Actor and target are buttons: following one narrows the log to it. */
function Row({ entry, onFilter }: { entry: AuditEntry; onFilter: (change: Partial<AuditQuery>) => void }) {
  return (
    <tr className="align-top">
      <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(entry.created_at)}</td>
      <td className="px-4 py-2">
        {entry.actor_id == null ? <span className="text-slate-500">{actorName(entry)}</span> : (
          <button onClick={() => onFilter({ actorId: entry.actor_id! })} title="Only this person's actions"
                  className="text-left text-brand-700 hover:underline">{actorName(entry)}</button>
        )}
      </td>
      <td className="px-4 py-2">
        <span className="block font-medium">{actionLabel(entry.action)}</span>
        <span className="block font-mono text-xs text-slate-500">{entry.action}</span>
      </td>
      <td className="whitespace-nowrap px-4 py-2">
        <button onClick={() => onFilter({ target: { type: entry.target_type, id: entry.target_id } })}
                title="Everything that happened to it" className="text-brand-700 hover:underline">
          {entry.target_type} #{entry.target_id}
        </button>
      </td>
      <td className="max-w-md px-4 py-2 text-slate-700">
        <span className="break-words">{describeDetails(entry)}</span>
      </td>
    </tr>
  );
}

function Chip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 py-1 pl-3 pr-1 text-sm text-brand-700">
      {label}
      <button onClick={onClear} aria-label={`Clear filter: ${label}`}
              className="rounded-full px-1.5 leading-none hover:bg-brand-600 hover:text-white">×</button>
    </span>
  );
}
