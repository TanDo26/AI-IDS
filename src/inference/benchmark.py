"""
CPU latency of a bundle: one flow at a time, and a 10k-flow batch (plan §F.6 targets).

Used by scripts/build_bundle.py (recorded in the manifest) and scripts/benchmark_bundle.py
(any bundle, e.g. inside the API container).
"""

import time

import numpy as np


def benchmark_cpu(bundle, X, n_single=200, batch_size=10000, repeats=3):
    """End-to-end (selection + preprocessing + classifier + anomaly detector + decision) latency."""
    bundle.predict(X.iloc[:1])  # warm-up

    single = []
    for i in range(min(n_single, len(X))):
        row = X.iloc[[i]]
        start = time.perf_counter()
        bundle.predict(row)
        single.append((time.perf_counter() - start) * 1000)

    batch = X.iloc[:batch_size]
    batch_ms = []
    for _ in range(repeats):
        start = time.perf_counter()
        bundle.predict(batch)
        batch_ms.append((time.perf_counter() - start) * 1000)
    batch_median = float(np.median(batch_ms))

    return {
        "single_flow_ms_p50": round(float(np.percentile(single, 50)), 3),
        "single_flow_ms_p95": round(float(np.percentile(single, 95)), 3),
        "batch_size": len(batch),
        "batch_ms_median": round(batch_median, 1),
        "batch_flows_per_second": int(len(batch) / (batch_median / 1000)),
    }
