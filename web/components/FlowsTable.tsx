"use client";

import { useState } from "react";

import { ExplainDrawer } from "@/components/ExplainDrawer";
import { Alert } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import {
  DECISIONS, DECISION_ORDER, REASONS, downloadExport, endpoints, nextSort, useFlows, type FlowQuery,
} from "@/lib/results";
import type { Decision, Flow, Summary } from "@/lib/types";

const TAB = "rounded-md px-3 py-1.5 text-sm";

/** The server pages, filters and sorts; this keeps the query and shows one page of it. */
export function FlowsTable({ summary, query, onQueryChange }:
  { summary: Summary; query: FlowQuery; onQueryChange: (query: FlowQuery) => void }) {
  const id = summary.upload_id;
  const flows = useFlows(id, query);
  const [explaining, setExplaining] = useState<Flow | null>(null);
  const classes = Object.keys(summary.attack_breakdown).sort();
  const counts: Record<Decision, number> = {
    benign: summary.n_benign, unknown: summary.n_unknown, known_attack: summary.n_known_attack,
  };
  const set = (change: Partial<FlowQuery>) => onQueryChange({ ...query, page: 1, ...change });

  const total = flows.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / query.size));
  const first = (query.page - 1) * query.size;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by decision">
          {[undefined, ...DECISION_ORDER].map((d) => (
            <button key={d ?? "all"} role="tab" aria-selected={query.decision === d} onClick={() => set({ decision: d })}
                    className={`${TAB} ${query.decision === d
                      ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
              {d ? DECISIONS[d].label : "All"}{" "}
              <span className="tabular-nums text-slate-500">{formatNumber(d ? counts[d] : summary.n_flows)}</span>
            </button>
          ))}
        </div>
        {classes.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Class
            <select value={query.className ?? ""} onChange={(e) => set({ className: e.target.value || undefined })}
                    className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
              <option value="">All classes</option>
              {classes.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        )}
        <Download id={id} query={query} />
      </div>

      {flows.isError && <div className="p-4"><Alert>{flows.error.message}</Alert></div>}
      {flows.isPending && <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p>}
      {flows.data && (
        <div className={`overflow-x-auto ${flows.isPlaceholderData ? "opacity-60" : ""}`}>
          <table className="w-full text-left text-sm">
            <caption className="px-3 pt-2 text-left text-xs text-slate-500">
              Click a flow to see what drove its decision.
            </caption>
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader label="Row" column="row" query={query} onSort={set} />
                <th className="px-3 py-2 font-medium">Flow</th>
                <SortHeader label="Decision" column="decision" query={query} onSort={set} />
                <SortHeader label="Class" column="class_name" query={query} onSort={set} />
                <SortHeader label="Anomaly" column="anomaly_score" query={query} onSort={set} right
                            hint="Isolation Forest score: higher is more unusual than benign training traffic" />
                <SortHeader label="Imputed" column="imputed_cells" query={query} onSort={set} right
                            hint="Feature values that were missing or not numbers, filled in before predicting" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {flows.data.items.map((f) => (
                <Row key={f.row} flow={f} open={explaining?.row === f.row}
                     onExplain={() => setExplaining(f)} />
              ))}
            </tbody>
          </table>
          {flows.data.items.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-slate-500">No flows match these filters.</p>
          )}
        </div>
      )}

      {total > 0 && (
        <nav className="flex items-center justify-end gap-3 border-t border-slate-200 px-4 py-3 text-sm" aria-label="Pages">
          <span className="mr-auto text-slate-500">
            {formatNumber(first + 1)}–{formatNumber(Math.min(first + query.size, total))} of {formatNumber(total)}
          </span>
          <button disabled={query.page <= 1} onClick={() => onQueryChange({ ...query, page: query.page - 1 })}
                  className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Previous</button>
          <span className="text-slate-600">Page {formatNumber(query.page)} of {formatNumber(pages)}</span>
          <button disabled={query.page >= pages} onClick={() => onQueryChange({ ...query, page: query.page + 1 })}
                  className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Next</button>
        </nav>
      )}
      <ExplainDrawer uploadId={id} flow={explaining} onClose={() => setExplaining(null)} />
    </div>
  );
}

function SortHeader({ label, column, query, onSort, right = false, hint }: {
  label: string; column: string; query: FlowQuery; onSort: (change: Partial<FlowQuery>) => void;
  right?: boolean; hint?: string;
}) {
  const direction = query.sort === column ? "ascending" : query.sort === `-${column}` ? "descending" : "none";
  return (
    <th aria-sort={direction} className={`px-3 py-2 font-medium ${right ? "text-right" : ""}`} title={hint}>
      <button onClick={() => onSort({ sort: nextSort(query.sort, column) })}
              className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-slate-800">
        {label}
        <span aria-hidden className="w-2">{direction === "ascending" ? "▲" : direction === "descending" ? "▼" : ""}</span>
      </button>
    </th>
  );
}

/**
 * A click anywhere on the row explains it, unless the click ended a text selection (copying an
 * address). The row number is the button for keyboard users.
 */
function Row({ flow, open, onExplain }: { flow: Flow; open: boolean; onExplain: () => void }) {
  const ends = endpoints(flow.metadata);
  const decision = DECISIONS[flow.decision];
  return (
    <tr onClick={() => { if (!window.getSelection()?.toString()) onExplain(); }}
        className={`cursor-pointer ${open ? "bg-brand-50" : "hover:bg-slate-50"}`}>
      <td className="px-3 py-2">
        <button onClick={(e) => { e.stopPropagation(); onExplain(); }} aria-label={`Explain flow ${flow.row}`}
                className="tabular-nums text-brand-700 hover:underline">
          {flow.row}
        </button>
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        {ends ? <span className="font-mono text-xs">{ends}</span> : <span className="text-slate-400">—</span>}
        {flow.metadata.Timestamp && <span className="block text-xs text-slate-500">{flow.metadata.Timestamp}</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${decision.badge}`}>
          <span className={`h-2 w-2 rounded-full ${decision.swatch}`} aria-hidden />
          {decision.label}
        </span>
        {REASONS[flow.reason] && <span className="block text-xs text-slate-500">{REASONS[flow.reason]}</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2">{flow.class_name}</td>
      <td className="px-3 py-2 text-right tabular-nums">{flow.anomaly_score.toFixed(3)}</td>
      <td className={`px-3 py-2 text-right tabular-nums ${flow.imputed_cells ? "" : "text-slate-400"}`}>
        {formatNumber(flow.imputed_cells)}
      </td>
    </tr>
  );
}

/** The CSV of what the table is filtered to, in file order; optionally with the model's input features. */
function Download({ id, query }: { id: string; query: FlowQuery }) {
  const [features, setFeatures] = useState(false);
  const [error, setError] = useState<string>();
  const filtered = Boolean(query.decision || query.className);

  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 text-sm">
      <label className="flex items-center gap-1.5 text-slate-600">
        <input type="checkbox" checked={features} onChange={(e) => setFeatures(e.target.checked)} />
        Include model inputs
      </label>
      <button
        onClick={() => {
          setError(undefined);
          downloadExport(id, { decision: query.decision, className: query.className, features })
            .catch((e: Error) => setError(e.message));
        }}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50">
        Download {filtered ? "these flows" : "all flows"} (CSV)
      </button>
      {error && <span role="alert" className="text-xs text-red-600">{error}</span>}
    </div>
  );
}
