"""
Bundle benchmark (plan §F.6): CPU latency of one flow, a 10k-flow batch and one explanation, against
the targets. Runs on the host or inside the API image, which is where it matters:

    python scripts/benchmark_bundle.py --bundle model_store/EXP-59-xgboost-20261026T104156
    docker compose exec api python scripts/benchmark_bundle.py --bundle /app/model_store/<bundle_id>

Flows: the bundle's self-test rows (validation flows of every class and decision reason), repeated
to fill the batch; or --flows with a CSV of real flows (e.g. web/e2e/data/flows.csv).
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.inference.benchmark import benchmark_cpu
from src.inference.bundle import SELFTEST, load_bundle
from src.inference.engine import InferenceEngine
from src.inference.explain import FlowExplainer

# measure -> (target, unit); latency targets of plan §F.6 that the bundle alone decides
TARGETS = {"single_flow_ms_p95": 1.0, "batch_ms_median": 1000.0, "explain_ms_p95": 300.0}


def percentiles(samples) -> tuple[float, float]:
    return round(float(np.percentile(samples, 50)), 3), round(float(np.percentile(samples, 95)), 3)


def timed(fn, n) -> list[float]:
    fn(0)                                                    # warm-up
    out = []
    for i in range(n):
        start = time.perf_counter()
        fn(i)
        out.append((time.perf_counter() - start) * 1000)
    return out


def main(bundle_dir: Path, flows_csv: Path | None, n_single: int):
    bundle = load_bundle(bundle_dir)
    features = bundle.manifest["required_features"]
    if flows_csv is None:
        flows = pd.read_parquet(bundle_dir / SELFTEST)[features]
    else:
        engine = InferenceEngine(bundle)
        flows = engine.prepare(pd.read_csv(flows_csv, encoding="utf-8-sig")).features[features]
    X = pd.concat([flows] * (10_000 // len(flows) + 1), ignore_index=True)

    result = benchmark_cpu(bundle, X, n_single=n_single)
    engine = InferenceEngine(bundle)
    engine_ms = timed(lambda i: engine.predict(X.iloc[[i]]), n_single)
    explainer = FlowExplainer(bundle)
    predictions = bundle.predict(X.iloc[:n_single])
    explain_ms = timed(lambda i: explainer.explain(X.iloc[[i]], result=predictions.iloc[i]), min(n_single, 100))
    result["engine_single_ms_p50"], result["engine_single_ms_p95"] = percentiles(engine_ms)
    result["explain_ms_p50"], result["explain_ms_p95"] = percentiles(explain_ms)

    print(f"Bundle {bundle.bundle_id} ({len(flows)} distinct flows, {n_single} single-flow runs)\n")
    print(f"  {'measure':<26}{'value':>12}{'target':>12}")
    for key, value in result.items():
        target = TARGETS.get(key)
        verdict = "" if target is None else ("  ok" if value < target else "  MISSED")
        print(f"  {key:<26}{value:>12}{'' if target is None else f'< {target:g}':>12}{verdict}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CPU latency of a model bundle against the plan's targets")
    parser.add_argument("--bundle", type=Path, required=True, help="Bundle directory (model_store/<bundle_id>)")
    parser.add_argument("--flows", type=Path, help="CSV of flows to use instead of the self-test rows")
    parser.add_argument("--single", type=int, default=200, help="Single-flow runs (default: 200)")
    args = parser.parse_args()
    main(args.bundle, args.flows, args.single)
