/**
 * Admin pages: server status and model versions. The queries and actions, and how their numbers read.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { Activation, ModelMetrics, ModelVersion, ModelsOverview, RescanResult, ServerStatus } from "@/lib/types";

export const REFRESH_MS = 5000;

// ── numbers ──

/** "42 s", "12 min", "5 h 12 min", "3 d 4 h". */
export function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

/** A rate as a percentage, precise where it is small: 1 → "100.0%", 0.0009 → "0.09%", 4.7e-5 → "<0.01%". */
export function rate(value: number | null | undefined): string {
  if (value == null) return "—";
  const percent = 100 * value;
  if (percent === 0) return "0%";
  if (percent < 0.01) return "<0.01%";
  return `${percent.toFixed(percent < 10 ? 2 : 1)}%`;
}

const score = (value: number | null | undefined) => (value == null ? "—" : value.toFixed(3));
const milliseconds = (value: number | null | undefined) => (value == null ? "—" : `${value.toFixed(value < 10 ? 1 : 0)} ms`);

/** MiB from the API, as GiB with one decimal. */
export const gib = (mib: number) => `${(mib / 1024).toFixed(1)} GiB`;

export interface MetricColumn {
  key: keyof ModelMetrics;
  label: string;
  hint: string;
  format: (value: number | null | undefined) => string;
  better?: "higher" | "lower";      // unset: no "best" (sending an attack to an analyst is not worse or better)
}

/** The comparison table's columns, from each bundle's manifest (its test split at build time). */
export const METRICS: MetricColumn[] = [
  { key: "macro_f1", label: "Macro-F1", hint: "Known classes, test split", format: score, better: "higher" },
  { key: "attack_recall", label: "Attack recall", hint: "Attacks the classifier calls attacks", format: rate, better: "higher" },
  { key: "benign_fpr", label: "Benign FPR", hint: "Benign flows the classifier calls attacks", format: rate, better: "lower" },
  { key: "benign_as_unknown", label: "Benign → unknown", hint: "Open-set false alarms: benign flows sent to an analyst", format: rate, better: "lower" },
  { key: "attack_as_unknown", label: "Attack → unknown", hint: "Attacks sent to an analyst instead of being named", format: rate },
  { key: "attack_missed", label: "Attacks missed", hint: "Attacks that end up benign", format: rate, better: "lower" },
  { key: "latency_p50_ms", label: "p50", hint: "One flow on CPU, end to end, median", format: milliseconds, better: "lower" },
  { key: "latency_p95_ms", label: "p95", hint: "One flow on CPU, end to end, 95th percentile", format: milliseconds, better: "lower" },
  { key: "batch_flows_per_second", label: "Flows/s", hint: "Batch throughput on CPU",
    format: (v) => (v == null ? "—" : formatNumber(Math.round(v))), better: "higher" },
];

export const canServe = (v: ModelVersion) => v.status === "active" || v.status === "available";

/**
 * The best value of a column among versions that could serve, as displayed, or undefined when they
 * look the same: 1.01% next to 1.01% in bold would claim a difference nobody can see.
 */
export function best(versions: ModelVersion[], column: MetricColumn): string | undefined {
  if (!column.better) return undefined;
  const values = versions.filter(canServe).map((v) => v.metrics[column.key]).filter((v): v is number => v != null);
  const shown = new Set(values.map((v) => column.format(v)));
  if (values.length < 2 || shown.size < 2) return undefined;
  return column.format(column.better === "higher" ? Math.max(...values) : Math.min(...values));
}

/** "EXP-59 · xgboost · class_weight · random split". */
export function describeSource(source: ModelVersion["source"]): string {
  if (!source) return "—";
  const s = source as Record<string, string | null | undefined>;
  return [s.experiment, s.model, s.strategy, s.split && `${s.split} split`,
          s.feature_selection && s.feature_selection !== "none" && `${s.feature_selection} features`]
    .filter(Boolean).join(" · ");
}

/** What POST /admin/models/rollback will activate: the most recently active version still available. */
export function rollbackTarget(versions: ModelVersion[]): ModelVersion | undefined {
  return versions
    .filter((v) => v.status === "available" && v.activated_at)
    .sort((a, b) => Date.parse(b.activated_at!) - Date.parse(a.activated_at!))[0];
}

/** New bundles are counted once as new, and again as passing or failing their checks. */
export function rescanSummary(r: RescanResult): string {
  const part = (n: string[], what: string) => `${n.length} ${what}${n.length ? ` (${n.join(", ")})` : ""}`;
  return [part(r.added, "new"), `${r.verified.length} passed their checks`, part(r.invalid, "failed"),
          part(r.retired, "no longer in the store")].join(", ");
}

export function activationSummary(a: Activation): string {
  if (!a.changed) return `${a.version.bundle_id} was already active.`;
  // API processes listen for the Redis event; workers re-check on a timer and at the start of every job
  return `${a.version.bundle_id} is now active${a.previous ? ` (was ${a.previous})` : ""}. `
    + (a.notified ? "API processes switch at once, workers at their next check; the list below shows them catching up."
                  : "Redis didn't carry the news, so every process switches at its next check.");
}

// ── queries and actions ──

export function useServerStatus() {
  return useQuery({
    queryKey: ["admin", "server"],
    queryFn: () => api<ServerStatus>("/admin/server"),
    refetchInterval: REFRESH_MS,
  });
}

export function useModels() {
  return useQuery({
    queryKey: ["admin", "models"],
    queryFn: () => api<ModelsOverview>("/admin/models"),
    refetchInterval: REFRESH_MS,           // processes report their switch within seconds
  });
}

export function useModelActions() {
  const queryClient = useQueryClient();
  // The active model also decides whether uploads are accepted (/readyz)
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["admin"] }),
                                     queryClient.invalidateQueries({ queryKey: ["readyz"] })]);
  return {
    rescan: useMutation({
      mutationFn: () => api<RescanResult>("/admin/models/rescan", { method: "POST" }),
      onSettled: refresh,
    }),
    activate: useMutation({
      mutationFn: (versionId: number) => api<Activation>(`/admin/models/${versionId}/activate`, { method: "POST" }),
      onSettled: refresh,
    }),
    rollback: useMutation({
      mutationFn: () => api<Activation>("/admin/models/rollback", { method: "POST" }),
      onSettled: refresh,
    }),
  };
}
