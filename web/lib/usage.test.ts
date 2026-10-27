import { describe, expect, it } from "vitest";

import { bucketDays, bucketLabel, dailyPath, niceMax, periodRange, sortRows, usagePath } from "@/lib/usage";
import type { UsageDay, UsageRow } from "@/lib/types";

const day = (iso: string, uploads = 1): UsageDay => ({ day: iso, uploads, bytes: 100 * uploads, flows: 10 * uploads,
                                                       processing_ms: 5 * uploads });

describe("periods", () => {
  const now = new Date("2026-10-27T03:00:00Z");

  it("counts today in, in UTC", () => {
    expect(periodRange(7, now)).toEqual({ from: "2026-10-21", to: "2026-10-27" });
    expect(periodRange(1, now)).toEqual({ from: "2026-10-27", to: "2026-10-27" });
    expect(periodRange(undefined, now)).toEqual({});
  });

  it("builds the paths", () => {
    expect(usagePath({})).toBe("/admin/usage");
    expect(usagePath({ from: "2026-10-21", to: "2026-10-27" })).toBe("/admin/usage?from=2026-10-21&to=2026-10-27");
    expect(dailyPath(4, { from: "2026-10-01" })).toBe("/admin/usage/4/daily?from=2026-10-01");
  });
});

describe("chart", () => {
  it("keeps days while they fit, and sums whole weeks beyond", () => {
    const month = Array.from({ length: 30 }, (_, i) => day(`2026-10-${String(i + 1).padStart(2, "0")}`));
    expect(bucketDays(month)).toHaveLength(30);
    const weeks = bucketDays(month, 10);
    expect(weeks.map((b) => b.uploads)).toEqual([7, 7, 7, 7, 2]);       // the last week is short
    expect(weeks[0]).toMatchObject({ start: "2026-10-01", end: "2026-10-07", bytes: 700, flows: 70, processing_ms: 35 });
  });

  it("labels days and weeks in UTC", () => {
    expect(bucketLabel({ start: "2026-10-06", end: "2026-10-06" })).toBe("Oct 6");
    expect(bucketLabel({ start: "2026-10-06", end: "2026-10-12" })).toBe("Oct 6 – Oct 12");
  });

  it.each([[0, 1], [3, 5], [10, 10], [11, 20], [0.4, 0.5], [123_456_789, 200_000_000], [7_200_000, 10_000_000]])(
    "niceMax(%f) = %f", (max, top) => expect(niceMax(max)).toBeCloseTo(top));
});

describe("table", () => {
  const row = (user_id: number, username: string, bytes: number): UsageRow => ({
    user_id, username, email: `${username}@x`, role: "user", is_active: true, uploads: 1, failed_uploads: 0,
    deleted_uploads: 0, bytes, flows: 0, processing_ms: 0, storage_bytes: 0 });
  const rows = [row(1, "carol", 5), row(2, "alice", 9), row(3, "bob", 5)];

  it("sorts by numbers and names, ties by id", () => {
    expect(sortRows(rows, "bytes", true).map((r) => r.user_id)).toEqual([2, 1, 3]);
    expect(sortRows(rows, "bytes", false).map((r) => r.user_id)).toEqual([1, 3, 2]);
    expect(sortRows(rows, "username", false).map((r) => r.username)).toEqual(["alice", "bob", "carol"]);
  });
});
