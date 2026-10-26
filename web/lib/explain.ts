/**
 * One flow's explanation: the query behind the drawer, and the words and numbers it shows.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { retryServerErrors } from "@/lib/results";
import type { Attribution, Contribution, Explanation, Flow } from "@/lib/types";

const MINUS = "−";

/** "+0.82", "−0.31", and "0.00" without a sign. */
export function signed(value: number, digits = 2): string {
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return text;
  return `${value > 0 ? "+" : MINUS}${text}`;
}

/** A raw feature value: whole and large numbers in full, small ones to 3 decimals; null was imputed. */
export function formatValue(value: number | null | undefined): string {
  if (value == null) return "missing";
  if (Number.isInteger(value) || Math.abs(value) >= 1000) return formatNumber(Math.round(value));
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(value);
}

export const percentOf = (fraction: number) => `${(100 * fraction).toFixed(1)}%`;

/** The one-line reason for a decision. */
export function verdict(flow: Pick<Flow, "reason" | "class_name" | "confidence">): string {
  const sure = percentOf(flow.confidence);
  switch (flow.reason) {
    case "known":
      return `Known attack: the classifier is ${sure} sure this is ${flow.class_name}.`;
    case "low_confidence":
      return `Unknown: the classifier leans toward ${flow.class_name} (${sure}), but not enough to call it a known attack.`;
    case "anomalous":
      return `Unknown: benign to the classifier (${sure}), but unusual compared with benign training traffic.`;
    default:
      return `Benign: the classifier is ${sure} sure, and nothing about the flow is unusual.`;
  }
}

export interface Direction {
  label: string;
  alarm: boolean;          // evidence of an attack or of something unusual (red), else of benign or typical (blue)
}

/** What the two sides of the chart mean: a positive contribution pushes toward the target, a negative one away. */
export function directions(a: Attribution): { up: Direction; down: Direction } {
  if (a.target === "anomaly") {
    return { up: { label: "More unusual", alarm: true }, down: { label: "More typical", alarm: false } };
  }
  const name = a.class_name ?? `class ${a.class}`;
  const benign = Boolean(a.benign);
  return { up: { label: `Toward ${name}`, alarm: !benign }, down: { label: `Away from ${name}`, alarm: benign } };
}

/** The unit the contributions are in, for the footnote. */
export function scale(a: Attribution): string {
  if (a.output_space === "log_odds") return `log-odds of ${a.class_name}`;
  if (a.output_space === "probability") return `probability of ${a.class_name}`;
  return "the anomaly score";
}

/** "4.2 SD above benign (median 120)", for anomaly explanations. */
export function deviation(c: Contribution): string | null {
  if (c.deviation_sd == null) return null;
  const where = c.deviation_sd >= 0 ? "above" : "below";
  return `${Math.abs(c.deviation_sd).toFixed(1)} SD ${where} benign (median ${formatValue(c.benign_median)})`;
}

export function useExplanation(uploadId: string, row: number | null) {
  return useQuery({
    queryKey: ["uploads", uploadId, "explain", row],
    queryFn: () => api<Explanation>(`/uploads/${uploadId}/flows/${row}/explain`),
    enabled: row !== null,
    staleTime: Infinity,          // computed from stored results with the bundle that produced them
    retry: retryServerErrors,
  });
}
