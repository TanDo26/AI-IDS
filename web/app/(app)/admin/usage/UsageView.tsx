"use client";

import { useState } from "react";

import { DailyChart } from "@/components/DailyChart";
import { Alert } from "@/components/ui";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";
import type { UsageRow } from "@/lib/types";
import {
  ALL_TIME_CHART_DAYS, MEASURES, type Measure, PERIODS, type UsageColumn, bucketDays, periodRange, sortRows,
  useDailyUsage, useUsage,
} from "@/lib/usage";

const TAB = "rounded-md px-3 py-1.5 text-sm";
const tab = (on: boolean) => `${TAB} ${on ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`;

const COLUMNS: Array<{ key: UsageColumn; label: string; format?: (v: number) => string; hint?: string }> = [
  { key: "username", label: "User" },
  { key: "uploads", label: "Uploads", format: formatNumber },
  { key: "failed_uploads", label: "Failed", format: formatNumber },
  { key: "deleted_uploads", label: "Deleted", format: formatNumber, hint: "Deleted by their owner; still counted" },
  { key: "bytes", label: "Data uploaded", format: formatBytes },
  { key: "flows", label: "Flows", format: formatNumber },
  { key: "processing_ms", label: "Processing", format: formatDuration },
  { key: "storage_bytes", label: "Storage now", format: formatBytes,
    hint: "Held right now, whatever the period: raw files not yet purged, plus results" },
];

export function UsageView({ initialUser }: { initialUser?: number }) {
  const [periodKey, setPeriodKey] = useState("30d");
  const period = PERIODS.find((p) => p.key === periodKey)!;
  const range = periodRange(period.days);
  const usage = useUsage(range);
  const [sort, setSort] = useState<{ column: UsageColumn; descending: boolean }>({ column: "bytes", descending: true });
  const [chosen, setChosen] = useState<number | undefined>(initialUser);
  const [measure, setMeasure] = useState<Measure>("uploads");

  const rows = usage.data ? sortRows(usage.data.users, sort.column, sort.descending) : [];
  // Until someone is chosen, chart the heaviest user of the period
  const selected = rows.find((r) => r.user_id === chosen) ?? usage.data?.users[0];
  const daily = useDailyUsage(selected?.user_id, periodRange(period.days ?? ALL_TIME_CHART_DAYS));
  const t = usage.data?.totals;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Usage</h1>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.key} role="tab" aria-selected={p.key === periodKey} onClick={() => setPeriodKey(p.key)}
                    className={tab(p.key === periodKey)}>{p.label}</button>
          ))}
        </div>
      </div>
      {usage.isError && <Alert>{usage.error.message}</Alert>}

      <section aria-label="Totals" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <Tile label="Uploads" value={t ? formatNumber(t.uploads) : "…"}
              note={t && `${formatNumber(t.failed_uploads)} failed · ${formatNumber(t.deleted_uploads)} deleted`} />
        <Tile label="Data uploaded" value={t ? formatBytes(t.bytes) : "…"} />
        <Tile label="Flows analysed" value={t ? formatNumber(t.flows) : "…"} />
        <Tile label="Processing time" value={t ? formatDuration(t.processing_ms) : "…"} />
        <Tile label="Storage now" value={t ? formatBytes(t.storage_bytes) : "…"} note="Whatever the period" />
      </section>

      <section className="rounded-xl border border-slate-200 bg-white" aria-label="Per user">
        {!usage.data ? <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p> : (
          <div className={`overflow-x-auto ${usage.isPlaceholderData ? "opacity-60" : ""}`}>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {COLUMNS.map((c) => {
                    const on = sort.column === c.key;
                    return (
                      <th key={c.key} title={c.hint} aria-sort={on ? (sort.descending ? "descending" : "ascending") : "none"}
                          className={`px-3 py-2 font-medium ${c.format ? "text-right" : ""}`}>
                        <button className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-slate-800"
                                onClick={() => setSort({ column: c.key, descending: on ? !sort.descending : c.key !== "username" })}>
                          {c.label}<span aria-hidden className="w-2">{on ? (sort.descending ? "▼" : "▲") : ""}</span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <UserRow key={r.user_id} row={r} selected={r.user_id === selected?.user_id}
                           onSelect={() => setChosen(r.user_id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected && (
        <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Daily activity">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            {/* Only the label is in capitals: usernames are case-sensitive */}
            <h2 className="text-sm text-slate-500">
              <span className="font-medium uppercase tracking-wide">Daily activity</span> ·{" "}
              <span className="font-medium text-slate-900">{selected.username}</span> ·{" "}
              {period.days ? period.label.toLowerCase() : `last ${ALL_TIME_CHART_DAYS} days`}
            </h2>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Measure">
              {(Object.keys(MEASURES) as Measure[]).map((m) => (
                <button key={m} role="tab" aria-selected={m === measure} onClick={() => setMeasure(m)}
                        className={tab(m === measure)}>{MEASURES[m].label}</button>
              ))}
            </div>
          </div>
          {daily.isError && <Alert>{daily.error.message}</Alert>}
          {daily.data ? <DailyChart buckets={bucketDays(daily.data.days)} measure={measure} />
                      : !daily.isError && <p className="py-10 text-center text-sm text-slate-500">Loading…</p>}
        </section>
      )}
    </div>
  );
}

/** The username is the button that charts this user, so the keyboard can reach it too. */
function UserRow({ row, selected, onSelect }: { row: UsageRow; selected: boolean; onSelect: () => void }) {
  return (
    <tr onClick={onSelect} className={`cursor-pointer ${selected ? "bg-brand-50" : "hover:bg-slate-50"}`}>
      {COLUMNS.map((c) => c.key === "username" ? (
        <td key={c.key} className="px-3 py-2">
          <button onClick={(e) => { e.stopPropagation(); onSelect(); }} aria-pressed={selected}
                  className="font-medium text-brand-700 hover:underline">{row.username}</button>
          <span className="block text-xs text-slate-500">{row.email}{row.is_active ? "" : " · deactivated"}</span>
        </td>
      ) : (
        <td key={c.key} className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${row[c.key] ? "" : "text-slate-400"}`}>
          {c.format!(row[c.key] as number)}
        </td>
      ))}
    </tr>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-0.5 text-xs text-slate-500">{note}</p>}
    </div>
  );
}
