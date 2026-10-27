/**
 * Usage per user over a period, and one user's days as a chart.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";
import type { DailyUsage, Usage, UsageDay, UsageRow } from "@/lib/types";

export const PERIODS: Array<{ key: string; label: string; days?: number }> = [
  { key: "7d", label: "Last 7 days", days: 7 },
  { key: "30d", label: "Last 30 days", days: 30 },
  { key: "90d", label: "Last 90 days", days: 90 },
  { key: "all", label: "All time" },
];

// The API serves at most 366 days of daily rows, so "all time" charts the last year
export const ALL_TIME_CHART_DAYS = 365;

export interface Range {
  from?: string;               // inclusive UTC days, YYYY-MM-DD
  to?: string;
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/** The last `days` UTC days, today included; open (all time) without a number. */
export function periodRange(days: number | undefined, now = new Date()): Range {
  if (!days) return {};
  const start = new Date(now);
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return { from: isoDay(start), to: isoDay(now) };
}

function withRange(path: string, range: Range): string {
  const params = new URLSearchParams();
  if (range.from) params.set("from", range.from);
  if (range.to) params.set("to", range.to);
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

export const usagePath = (range: Range) => withRange("/admin/usage", range);
export const dailyPath = (userId: number, range: Range) => withRange(`/admin/usage/${userId}/daily`, range);

export type Measure = "uploads" | "bytes" | "flows" | "processing_ms";

export const MEASURES: Record<Measure, { label: string; format: (value: number) => string }> = {
  uploads: { label: "Uploads", format: formatNumber },
  bytes: { label: "Data uploaded", format: formatBytes },
  flows: { label: "Flows", format: formatNumber },
  processing_ms: { label: "Processing time", format: formatDuration },
};

export interface Bucket extends Record<Measure, number> {
  start: string;
  end: string;
}

/** Days as they are, or weeks when there would be too many bars to read (the last week may be short). */
export function bucketDays(days: UsageDay[], maxBars = 92): Bucket[] {
  const size = days.length > maxBars ? 7 : 1;
  const buckets: Bucket[] = [];
  for (let i = 0; i < days.length; i += size) {
    const chunk = days.slice(i, i + size);
    const total = (m: Measure) => chunk.reduce((sum, d) => sum + d[m], 0);
    buckets.push({ start: chunk[0].day, end: chunk[chunk.length - 1].day,
                   uploads: total("uploads"), bytes: total("bytes"), flows: total("flows"),
                   processing_ms: total("processing_ms") });
  }
  return buckets;
}

const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** "Oct 6", or "Oct 6 – Oct 12" for a week. */
export function bucketLabel(bucket: Pick<Bucket, "start" | "end">): string {
  const day = (iso: string) => DAY.format(new Date(`${iso}T00:00:00Z`));
  return bucket.start === bucket.end ? day(bucket.start) : `${day(bucket.start)} – ${day(bucket.end)}`;
}

/** A round top for the axis: the smallest 1, 2 or 5 × 10^k at or above the largest value. */
export function niceMax(max: number): number {
  if (max <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(max));
  return [1, 2, 5, 10].map((step) => step * power).find((top) => top >= max)!;
}

export type UsageColumn = "username" | "uploads" | "failed_uploads" | "deleted_uploads" | "bytes" | "flows"
  | "processing_ms" | "storage_bytes";

/** Every user is in the response, so the table sorts in the browser; ties keep a stable order. */
export function sortRows(rows: UsageRow[], column: UsageColumn, descending: boolean): UsageRow[] {
  return [...rows].sort((a, b) => {
    const x = a[column], y = b[column];
    const order = typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number);
    return (descending ? -order : order) || a.user_id - b.user_id;
  });
}

export function useUsage(range: Range) {
  return useQuery({
    queryKey: ["admin", "usage", range],
    queryFn: () => api<Usage>(usagePath(range)),
    placeholderData: keepPreviousData,
  });
}

export function useDailyUsage(userId: number | undefined, range: Range) {
  return useQuery({
    queryKey: ["admin", "usage", userId, "daily", range],
    queryFn: () => api<DailyUsage>(dailyPath(userId!, range)),
    enabled: userId !== undefined,
    placeholderData: keepPreviousData,
  });
}
