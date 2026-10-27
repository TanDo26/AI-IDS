import { describe, expect, it } from "vitest";

import { captureFacts, exportPath, flowsPath, nextSort, percent } from "@/lib/results";

describe("capture facts", () => {
  it("says what was read, and what was left out only when something was", () => {
    const clean = { packets: 11763, ipv4: 11763, flows: 1688, short_flows: 0, skipped: {}, extract_ms: 420 };
    expect(captureFacts(clean)).toEqual([
      ["Flows extracted", "1,688 from 11,763 packets", expect.any(String)],
      ["Flow extraction", "420 ms"],
    ]);
    const facts = captureFacts({ ...clean, short_flows: 25, skipped: { ipv6: 8, not_ip: 10 } });
    expect(facts.map(([term, value]) => [term, value])).toEqual([
      ["Flows extracted", "1,688 from 11,763 packets"],
      ["Single-packet flows", "25 left out"],
      ["Packets not used", "18"],
      ["Flow extraction", "420 ms"],
    ]);
    expect(facts[2][2]).toMatch(/^8 IPv6, 10 not IP\. Only IPv4/);
  });
});

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
