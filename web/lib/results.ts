/**
 * One upload's results: the queries behind /uploads/[id], and how decisions are shown.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { API_BASE, ApiError, api } from "@/lib/api";
import { formatDuration, formatNumber } from "@/lib/format";
import type { CaptureStats, Decision, Flow, FlowPage, Summary, Upload } from "@/lib/types";
import { isActive } from "@/lib/uploads";

export const DECISIONS: Record<Decision, { label: string; swatch: string; badge: string; hint: string }> = {
  benign: {
    label: "Benign", swatch: "bg-status-good", badge: "bg-emerald-50 text-emerald-800",
    hint: "Normal traffic, and nothing unusual about it",
  },
  unknown: {
    label: "Unknown", swatch: "bg-status-warning", badge: "bg-amber-50 text-amber-900",
    hint: "Needs an analyst: an attack the model couldn't name confidently, or benign-looking but unusual",
  },
  known_attack: {
    label: "Known attack", swatch: "bg-status-critical", badge: "bg-red-50 text-red-800",
    hint: "Matches an attack type the model was trained on",
  },
};
// Benign, unknown, known attack: also the order of the stacked bar (see globals.css)
export const DECISION_ORDER: Decision[] = ["benign", "unknown", "known_attack"];

export const REASONS: Record<string, string> = {
  low_confidence: "low confidence",
  anomalous: "anomalous",
};

export interface FlowQuery {
  page: number;
  size: number;
  decision?: Decision;
  className?: string;
  sort: string;                  // a sortable column, "-" first for descending
}

export function percent(part: number, total: number): string {
  if (!total) return "0%";
  const value = (100 * part) / total;
  return `${value > 0 && value < 0.1 ? "<0.1" : value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== false) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function flowsPath(id: string, q: FlowQuery): string {
  return `/uploads/${id}/flows${query({ page: q.page, size: q.size, decision: q.decision, class_name: q.className, sort: q.sort })}`;
}

export function exportPath(id: string, q: Pick<FlowQuery, "decision" | "className"> & { features?: boolean }): string {
  return `/uploads/${id}/export.csv${query({ decision: q.decision, class_name: q.className, features: q.features })}`;
}

/** Clicking a column: sort by it ascending, then descending, then back to file order. */
export function nextSort(current: string, column: string): string {
  if (current === column) return `-${column}`;
  if (current === `-${column}`) return "row";
  return column;
}

/** Start a CSV download. The session is refreshed first: a plain link can't, and would save a 401 instead. */
export async function downloadExport(id: string, q: Parameters<typeof exportPath>[1]) {
  await api("/auth/me");
  window.location.assign(`${API_BASE}${exportPath(id, q)}`);
}

const SKIPPED: Record<string, string> = {
  ipv6: "IPv6", not_ip: "not IP", malformed: "damaged", unsupported_link: "unsupported link type",
};

/** What the flow extractor read from an uploaded capture, as [term, value, hint] rows. */
export function captureFacts(c: CaptureStats): Array<[string, string, string?]> {
  const facts: Array<[string, string, string?]> = [
    ["Flows extracted", `${formatNumber(c.flows)} from ${formatNumber(c.packets)} packets`,
     "IPv4 TCP, UDP and ICMP flows, cut the way CICFlowMeter cuts them"],
  ];
  if (c.short_flows) {
    facts.push(["Single-packet flows", `${formatNumber(c.short_flows)} left out`,
                "The training data has no single-packet flows, so the models can't judge them"]);
  }
  const skipped = Object.entries(c.skipped).filter(([, n]) => n > 0);
  if (skipped.length) {
    const total = skipped.reduce((sum, [, n]) => sum + n, 0);
    facts.push(["Packets not used", formatNumber(total),
                `${skipped.map(([reason, n]) => `${formatNumber(n)} ${SKIPPED[reason] ?? reason}`).join(", ")}. `
                + "Only IPv4 forms flows, as in the training data"]);
  }
  facts.push(["Flow extraction", formatDuration(c.extract_ms)]);
  return facts;
}

/** "10.0.0.1:443 → 10.0.0.2:80" from the flow's metadata, or null if the upload had no addresses. */
export function endpoints(metadata: Flow["metadata"]): string | null {
  const side = (ip?: string | null, port?: string | null) => (ip ? (port ? `${ip}:${port}` : ip) : "?");
  if (!metadata["Src IP"] && !metadata["Dst IP"]) return null;
  return `${side(metadata["Src IP"], metadata["Src Port"])} → ${side(metadata["Dst IP"], metadata["Dst Port"])}`;
}

// A 4xx won't change by asking again
export const retryServerErrors = (failures: number, error: Error) =>
  !(error instanceof ApiError && error.status < 500) && failures < 2;

export function useUpload(id: string) {
  return useQuery({
    queryKey: ["uploads", id],
    queryFn: () => api<Upload>(`/uploads/${id}`),
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? 1500 : false),
    retry: retryServerErrors,
  });
}

// Only asked for once the upload is completed: until then the API answers 409
export function useSummary(id: string) {
  return useQuery({
    queryKey: ["uploads", id, "summary"],
    queryFn: () => api<Summary>(`/uploads/${id}/summary`),
    staleTime: Infinity,          // results never change once completed
  });
}

export function useFlows(id: string, q: FlowQuery) {
  return useQuery({
    queryKey: ["uploads", id, "flows", q],
    queryFn: () => api<FlowPage>(flowsPath(id, q)),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}
