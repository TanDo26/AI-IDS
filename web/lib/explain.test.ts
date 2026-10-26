import { describe, expect, it } from "vitest";

import { deviation, directions, formatValue, scale, signed, verdict } from "@/lib/explain";
import { endpoints } from "@/lib/results";
import type { Attribution } from "@/lib/types";

const toward = (benign: boolean): Attribution => ({
  target: "class", class: benign ? 0 : 2, class_name: benign ? "Benign" : "DDoS", benign,
  output_space: "log_odds", base_value: 0.1, contributions: [],
});

describe("numbers", () => {
  it.each([[0.8234, "+0.82"], [-0.31, "−0.31"], [0, "0.00"], [-0.001, "0.00"], [12.345, "+12.35"]])(
    "signed(%f) = %s", (value, text) => expect(signed(value)).toBe(text));

  it.each([[null, "missing"], [1234567, "1,234,567"], [1234.56, "1,235"], [0.12345, "0.123"], [-3, "-3"], [80, "80"]])(
    "formatValue(%s) = %s", (value, text) => expect(formatValue(value)).toBe(text));

  it("describes deviations from benign", () => {
    expect(deviation({ feature: "f", value: 50, contribution: 1, benign_median: 10, deviation_sd: 4.24 }))
      .toBe("4.2 SD above benign (median 10)");
    expect(deviation({ feature: "f", value: 1, contribution: 1, benign_median: 10, deviation_sd: -0.5 }))
      .toBe("0.5 SD below benign (median 10)");
    expect(deviation({ feature: "f", value: 1, contribution: 1 })).toBeNull();
  });
});

describe("words", () => {
  it("gives a one-line reason per decision", () => {
    expect(verdict({ reason: "known", class_name: "DDoS", confidence: 0.991 }))
      .toBe("Known attack: the classifier is 99.1% sure this is DDoS.");
    expect(verdict({ reason: "low_confidence", class_name: "Botnet", confidence: 0.6 })).toMatch(/^Unknown: .*Botnet \(60\.0%\)/);
    expect(verdict({ reason: "anomalous", class_name: "Benign", confidence: 0.98 })).toMatch(/^Unknown: benign .*unusual/);
    expect(verdict({ reason: "benign", class_name: "Benign", confidence: 1 })).toMatch(/^Benign: .*100\.0%/);
  });

  it("colours evidence of an attack red, whichever side of zero it is on", () => {
    expect(directions(toward(false))).toEqual({
      up: { label: "Toward DDoS", alarm: true }, down: { label: "Away from DDoS", alarm: false } });
    expect(directions(toward(true))).toEqual({
      up: { label: "Toward Benign", alarm: false }, down: { label: "Away from Benign", alarm: true } });
    expect(directions({ ...toward(false), target: "anomaly", class: null, class_name: null, output_space: "anomaly_score" }))
      .toEqual({ up: { label: "More unusual", alarm: true }, down: { label: "More typical", alarm: false } });
  });

  it("names the unit", () => {
    expect(scale(toward(false))).toBe("log-odds of DDoS");
    expect(scale({ ...toward(true), output_space: "probability" })).toBe("probability of Benign");
    expect(scale({ ...toward(true), target: "anomaly", output_space: "anomaly_score" })).toBe("the anomaly score");
  });

  it("joins the endpoints", () => {
    expect(endpoints({ "Src IP": "10.0.0.1", "Src Port": "443", "Dst IP": "10.0.0.2", "Dst Port": null }))
      .toBe("10.0.0.1:443 → 10.0.0.2");
    expect(endpoints({ Timestamp: "x" })).toBeNull();
  });
});
