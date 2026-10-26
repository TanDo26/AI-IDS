import { describe, expect, it } from "vitest";

import { exportPath, flowsPath, nextSort, percent } from "@/lib/results";

describe("paths", () => {
  it("builds the flows query, leaving out unset filters", () => {
    expect(flowsPath("u1", { page: 2, size: 50, sort: "-confidence" })).toBe(
      "/uploads/u1/flows?page=2&size=50&sort=-confidence");
    expect(flowsPath("u1", { page: 1, size: 50, sort: "row", decision: "known_attack", className: "DoS Hulk" })).toBe(
      "/uploads/u1/flows?page=1&size=50&decision=known_attack&class_name=DoS+Hulk&sort=row");
  });

  it("builds the export link", () => {
    expect(exportPath("u1", {})).toBe("/uploads/u1/export.csv");
    expect(exportPath("u1", { decision: "unknown", features: true })).toBe(
      "/uploads/u1/export.csv?decision=unknown&features=true");
    expect(exportPath("u1", { className: "Web Attack - XSS", features: false })).toBe(
      "/uploads/u1/export.csv?class_name=Web+Attack+-+XSS");
  });
});

describe("sorting", () => {
  it("cycles ascending, descending, file order", () => {
    expect(nextSort("row", "confidence")).toBe("confidence");
    expect(nextSort("confidence", "confidence")).toBe("-confidence");
    expect(nextSort("-confidence", "confidence")).toBe("row");
    expect(nextSort("-anomaly_score", "confidence")).toBe("confidence");
  });
});

describe("percent", () => {
  it.each([[0, 0, "0%"], [1, 3, "33%"], [5, 1000, "0.5%"], [1, 10_000, "<0.1%"], [7, 7, "100%"], [0, 9, "0.0%"]])(
    "%i of %i -> %s", (part, total, text) => expect(percent(part, total)).toBe(text));
});
