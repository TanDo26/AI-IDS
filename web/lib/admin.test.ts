import { describe, expect, it } from "vitest";

import {
  METRICS, activationSummary, best, describeSource, formatUptime, rate, rescanSummary, rollbackTarget,
} from "@/lib/admin";
import type { ModelVersion } from "@/lib/types";

function version(id: number, status: string, activated_at: string | null, metrics: Partial<ModelVersion["metrics"]> = {}): ModelVersion {
  return {
    id, bundle_id: `B-${id}`, status, invalid_reason: null, registered_at: "2026-10-01T00:00:00Z", activated_at,
    activated_by: null, source: null, classes: [], n_features: 52, metrics,
  };
}

const column = (key: string) => METRICS.find((m) => m.key === key)!;

describe("numbers", () => {
  it.each([[42, "42 s"], [60, "1 min"], [3599, "59 min"], [3600 * 5 + 720, "5 h 12 min"], [86400 * 3 + 3600 * 4 + 59, "3 d 4 h"]])(
    "uptime %i s -> %s", (s, text) => expect(formatUptime(s)).toBe(text));

  it.each([[1, "100.0%"], [0.9891, "98.9%"], [0.0101, "1.01%"], [0.0009, "0.09%"], [4.7e-5, "<0.01%"], [0, "0%"], [null, "—"]])(
    "rate %s -> %s", (v, text) => expect(rate(v)).toBe(text));
});

describe("comparison", () => {
  const versions = [
    version(1, "active", "2026-10-02T00:00:00Z", { macro_f1: 0.97, benign_fpr: 0.001, attack_as_unknown: 0.05 }),
    version(2, "available", null, { macro_f1: 0.95, benign_fpr: 0.0005, attack_as_unknown: 0.02 }),
    version(3, "invalid", null, { macro_f1: 0.99, benign_fpr: 0.0001 }),
  ];

  it("picks the best of the versions that could serve, in the column's direction, as displayed", () => {
    expect(best(versions, column("macro_f1"))).toBe("0.970");     // the invalid 0.99 doesn't count
    expect(best(versions, column("benign_fpr"))).toBe("0.05%");
  });

  it("has no best without a direction, with one candidate, or when the values look the same", () => {
    expect(best(versions, column("attack_as_unknown"))).toBeUndefined();
    expect(best(versions.slice(0, 1), column("macro_f1"))).toBeUndefined();
    expect(best([versions[0], { ...versions[1], metrics: { macro_f1: 0.97 } }], column("macro_f1"))).toBeUndefined();
    const close = [version(1, "active", null, { benign_as_unknown: 0.010099 }),
                   version(2, "available", null, { benign_as_unknown: 0.010061 })];
    expect(best(close, column("benign_as_unknown"))).toBeUndefined();   // both show 1.01%
  });

  it("describes the source experiment", () => {
    expect(describeSource({ experiment: "EXP-59", model: "xgboost", strategy: "class_weight", split: "random",
                            feature_selection: "none" })).toBe("EXP-59 · xgboost · class_weight · random split");
    expect(describeSource({ experiment: "EXP-68", model: "xgboost", strategy: null, split: "random",
                            feature_selection: "pearson" })).toBe("EXP-68 · xgboost · random split · pearson features");
    expect(describeSource(null)).toBe("—");
  });
});

describe("actions", () => {
  it("rolls back to the most recently active version that is still available", () => {
    const versions = [
      version(1, "active", "2026-10-05T00:00:00Z"),
      version(2, "available", "2026-10-03T00:00:00Z"),
      version(3, "available", "2026-10-04T00:00:00Z"),
      version(4, "invalid", "2026-10-04T12:00:00Z"),
      version(5, "available", null),
    ];
    expect(rollbackTarget(versions)?.id).toBe(3);
    expect(rollbackTarget([versions[0], versions[4]])).toBeUndefined();
  });

  it("summarises a rescan and an activation", () => {
    expect(rescanSummary({ added: ["B-2", "B-3"], verified: ["B-1", "B-2"], invalid: ["B-3"], retired: [], versions: [] }))
      .toBe("2 new (B-2, B-3), 2 passed their checks, 1 failed (B-3), 0 no longer in the store");
    const v = version(2, "active", "2026-10-06T00:00:00Z");
    expect(activationSummary({ version: v, previous: "B-1", changed: true, notified: true }))
      .toMatch(/^B-2 is now active \(was B-1\)\. API processes switch at once, workers at their next check/);
    expect(activationSummary({ version: v, previous: "B-1", changed: true, notified: false })).toMatch(/every process switches at its next check/);
    expect(activationSummary({ version: v, previous: "B-2", changed: false, notified: false })).toBe("B-2 was already active.");
  });
});
