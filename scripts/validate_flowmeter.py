"""
Parity check of the flow extractor (src/flowmeter) against the reference CICFlowMeter at 13a0615.

    python scripts/validate_flowmeter.py --pcap capture.pcap --reference capture.pcap_Flow.csv
    python scripts/validate_flowmeter.py --pcap capture.pcap --reference ref.csv --bundle model_store/<id>

The reference CSV is the Java tool's output for the same capture (docker/cicflowmeter.Dockerfile builds
it; see README "Flow extractor"). Both sides keep every flow, single-packet ones included, unless
--min-packets says otherwise. Flows are matched on Flow ID + start time, ties in order of duration and
packet counts.

The report gives the flow counts, the share matched, and per feature the share of values within 1e-6
relative error and the largest error. Pass: >= 99% of flows matched and >= 99.9% of feature values
within tolerance. With --bundle, both sides are predicted with that bundle and the decisions compared.
Exit code 0 on pass, 1 on fail.
"""
import sys
import json
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.flowmeter import FEATURES, METADATA, extract_flows
from src.inference.schema import JAVA_TO_TRAINING

RTOL = 1e-6
PASS_FLOWS, PASS_VALUES = 0.99, 0.999
ENDPOINTS = ["Src IP", "Src Port", "Dst IP", "Dst Port"]
KEY = ["Flow ID", "start", "nth"]
# The reference reads some ARP frames as IPv4: the ARP header's bytes become these addresses
ARP_AS_IPV4 = "8.6.0.1-8.0.6.4-"


def read_reference(path, min_packets) -> pd.DataFrame:
    ref = pd.read_csv(path, dtype=str, keep_default_na=False).rename(columns=JAVA_TO_TRAINING)
    ref = ref[ref["Flow ID"] != "Flow ID"]                    # some versions repeat the header
    missing = [c for c in (*METADATA, *FEATURES) if c not in ref.columns]
    if missing:
        sys.exit(f"The reference lacks {len(missing)} column(s): {', '.join(missing)}")
    values = ref[list(FEATURES)].replace({"Infinity": "inf", "-Infinity": "-inf"})
    ref[list(FEATURES)] = values.apply(pd.to_numeric, errors="coerce").astype("float64")
    ref = ref[ref["Total Fwd Packets"] + ref["Total Backward Packets"] >= min_packets]
    return ref.reset_index(drop=True)


def keyed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(start=pd.to_datetime(df["Timestamp"], format="ISO8601"))
    df = df.sort_values(["Flow ID", "start", "Flow Duration", "Total Fwd Packets", "Total Backward Packets"],
                        kind="stable")
    return df.assign(nth=df.groupby(["Flow ID", "start"]).cumcount()).reset_index(drop=True)


def compare(ref: pd.DataFrame, ours: pd.DataFrame, details: int) -> dict:
    ref, ours = keyed(ref), keyed(ours)
    pairs = ref.merge(ours, on=KEY, suffixes=("_ref", "_ours"))
    n_ref, n_ours, n_matched = len(ref), len(ours), len(pairs)
    report = {"reference_flows": n_ref, "our_flows": n_ours, "matched": n_matched,
              "matched_share": n_matched / max(n_ref, n_ours, 1)}

    def unmatched(side, other):
        rows = side.merge(other[KEY], on=KEY, how="left", indicator=True)
        rows = rows[rows["_merge"] == "left_only"]
        return [f"{r['Flow ID']} @ {r['Timestamp']} ({int(r['Total Fwd Packets'])}+{int(r['Total Backward Packets'])} pkts)"
                + (" - ARP frames the reference reads as IPv4; not replicated" if r["Flow ID"].startswith(ARP_AS_IPV4) else "")
                for _, r in rows.head(details).iterrows()]
    report["only_in_reference"], report["only_in_ours"] = unmatched(ref, ours), unmatched(ours, ref)

    report["endpoint_mismatches"] = {c: int((pairs[f"{c}_ref"].astype(str) != pairs[f"{c}_ours"].astype(str)).sum())
                                     for c in ENDPOINTS}
    features, within_total = {}, 0
    for name in FEATURES:
        a, b = pairs[f"{name}_ref"].to_numpy(), pairs[f"{name}_ours"].to_numpy()
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        finite = np.isfinite(a) & np.isfinite(b)
        scale = np.maximum(np.abs(a), np.abs(b))
        with np.errstate(invalid="ignore", divide="ignore"):
            rel = np.where(finite & ~same, np.abs(a - b) / scale, 0.0)
        within = same | (finite & (rel <= RTOL))
        within_total += int(within.sum())
        entry = {"equal": float(same.mean()) if len(a) else 1.0, "within": float(within.mean()) if len(a) else 1.0,
                 "max_rel_error": float(np.where(within, rel, np.where(finite, rel, np.inf)).max()) if len(a) else 0.0}
        if details and not within.all():
            bad = pairs.loc[~within, ["Flow ID", "Timestamp_ref", f"{name}_ref", f"{name}_ours"]].head(details)
            entry["examples"] = bad.astype(str).values.tolist()
        features[name] = entry
    report["features"] = features
    report["values_within"] = within_total / max(n_matched * len(FEATURES), 1)
    report["passed"] = report["matched_share"] >= PASS_FLOWS and report["values_within"] >= PASS_VALUES
    return report


def compare_predictions(bundle_path, ref: pd.DataFrame, ours: pd.DataFrame) -> dict:
    from src.inference.bundle import load_bundle
    from src.inference.engine import InferenceEngine

    engine = InferenceEngine(load_bundle(bundle_path))
    sides = []
    for df in (ref, ours):
        df = keyed(df)
        predicted = engine.predict(df[list(FEATURES)])
        sides.append(df[KEY].assign(decision=predicted["decision"].to_numpy(),
                                    class_name=predicted["class_name"].to_numpy()))
    pairs = sides[0].merge(sides[1], on=KEY, suffixes=("_ref", "_ours"))
    return {
        "bundle": engine.bundle.bundle_id,
        "decisions_reference": dict(Counter(sides[0]["decision"])),
        "decisions_ours": dict(Counter(sides[1]["decision"])),
        "decision_agreement": float((pairs["decision_ref"] == pairs["decision_ours"]).mean()),
        "class_agreement": float((pairs["class_name_ref"] == pairs["class_name_ours"]).mean()),
    }


def print_report(report, stats):
    print(f"Capture: {stats.get('packets', 0):,} packets, {stats.get('ipv4', 0):,} IPv4"
          + "".join(f", {k} {v:,}" for k, v in stats.items() if k in ("ipv6", "not_ip", "malformed") and v))
    print(f"Flows: reference {report['reference_flows']:,}, ours {report['our_flows']:,}, "
          f"matched {report['matched']:,} ({report['matched_share']:.4%})")
    for side in ("only_in_reference", "only_in_ours"):
        for line in report[side]:
            print(f"  {side.replace('_', ' ')}: {line}")
    if any(report["endpoint_mismatches"].values()):
        print(f"  endpoint mismatches: {report['endpoint_mismatches']}")
    off = {k: v for k, v in report["features"].items() if v["within"] < 1}
    print(f"Feature values within {RTOL:g}: {report['values_within']:.5%}"
          f" ({len(FEATURES) - len(off)}/{len(FEATURES)} features on every flow)")
    for name, v in sorted(off.items(), key=lambda kv: kv[1]["within"]):
        print(f"  {name:<26} within {v['within']:.4%}  equal {v['equal']:.4%}  max rel error {v['max_rel_error']:.3g}")
        for example in v.get("examples", []):
            print(f"      {example}")
    if "predictions" in report:
        p = report["predictions"]
        print(f"Predictions with {p['bundle']}: decisions agree on {p['decision_agreement']:.4%} of matched flows, "
              f"classes on {p['class_agreement']:.4%}")
        print(f"  reference {p['decisions_reference']}")
        print(f"  ours      {p['decisions_ours']}")
    print("PASS" if report["passed"] else "FAIL",
          f"(needs >= {PASS_FLOWS:.0%} of flows matched and >= {PASS_VALUES:.1%} of values within tolerance)")


def main(args) -> int:
    ref = read_reference(args.reference, args.min_packets)
    stats = Counter()
    features, metadata = extract_flows(args.pcap, min_packets=args.min_packets, stats=stats)
    ours = pd.concat([metadata, features], axis=1)
    report = compare(ref, ours, args.details)
    if args.bundle:
        report["predictions"] = compare_predictions(args.bundle, ref, ours)
    report["capture"] = {"path": str(args.pcap), **stats}
    print_report(report, stats)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare src/flowmeter with the reference CICFlowMeter")
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="the Java tool's CSV for the same capture")
    parser.add_argument("--min-packets", type=int, default=1, help="compare only flows with this many packets")
    parser.add_argument("--bundle", type=Path, help="also compare predictions with this model bundle")
    parser.add_argument("--details", type=int, default=5, help="examples to show per mismatch (0: none)")
    parser.add_argument("--json", type=Path, help="write the full report here")
    sys.exit(main(parser.parse_args()))
