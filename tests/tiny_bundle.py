"""
A tiny but real model bundle for tests: same classes and file layout as scripts/build_bundle.py,
trained in about a second on synthetic flows, so every decision it makes is fixed.

PortScan's confidence threshold is above 1, so every PortScan prediction is "low_confidence";
together with CANONICAL_FLOWS this exercises all four decision reasons.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier

from src.inference.bundle import (
    Bundle, save_bundle,
    EXPECTED_CLASS_COL, EXPECTED_PROBA_PREFIX, EXPECTED_ANOMALY_COL, EXPECTED_DECISION_COL,
)
from src.preprocessing import FeatureSelector, build_preprocessor

BENIGN, DDOS, PORTSCAN = 0, 2, 5        # gaps on purpose, like the real label mapping
CLASS_NAMES = {str(BENIGN): "Benign", str(DDOS): "DDoS", str(PORTSCAN): "PortScan"}

# Training names; the zero-variance column is dropped by the selector, so it is not required
FEATURES = ["Flow Duration", "Total Fwd Packets", "Total Backward Packets", "Fwd Packets Length Total",
            "Flow Bytes/s", "Init Fwd Win Bytes", "Bwd PSH Flags"]
NOISE_FEATURE = "Init Fwd Win Bytes"    # same distribution in every class
CONSTANT_FEATURE = "Bwd PSH Flags"

CENTERS = {
    BENIGN:   {"Flow Duration": 50_000, "Total Fwd Packets": 10, "Total Backward Packets": 8,
               "Fwd Packets Length Total": 1_200, "Flow Bytes/s": 20_000},
    DDOS:     {"Flow Duration": 2_000, "Total Fwd Packets": 3, "Total Backward Packets": 40,
               "Fwd Packets Length Total": 20, "Flow Bytes/s": 5_000_000},
    PORTSCAN: {"Flow Duration": 50, "Total Fwd Packets": 1, "Total Backward Packets": 1,
               "Fwd Packets Length Total": 2, "Flow Bytes/s": 1_000},
}
NOISE_MEAN = 8_192.0

THRESHOLDS = {"known": 0.9, "known_per_class": {str(DDOS): 0.9, str(PORTSCAN): 1.01}}


def flow(center: int, **changes) -> dict:
    """One raw flow (training column names) at a class center."""
    row = {**CENTERS[center], NOISE_FEATURE: NOISE_MEAN, CONSTANT_FEATURE: 0}
    row.update(changes)
    return {k: float(v) for k, v in row.items()}


# name -> (raw flow, expected decision, reason, predicted class)
CANONICAL_FLOWS = {
    "benign":      (flow(BENIGN), "benign", "benign", BENIGN),
    "ddos":        (flow(DDOS), "known_attack", "known", DDOS),
    "portscan":    (flow(PORTSCAN), "unknown", "low_confidence", PORTSCAN),
    # Further onto the benign side than any benign flow (benign has the longest flows and the most
    # forward traffic), so the classifier says Benign while the anomaly detector flags it
    "odd_benign":  (flow(BENIGN, **{"Flow Duration": 5e7, "Total Fwd Packets": 1e3,
                                    "Fwd Packets Length Total": 1.2e5, NOISE_FEATURE: 1e9}),
                    "unknown", "anomalous", BENIGN),
}


def synthetic_flows(seed: int, per_class: int = 300) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    frames, labels = [], []
    for cls, center in CENTERS.items():
        df = pd.DataFrame({k: v * rng.lognormal(0.0, 0.15, per_class) for k, v in center.items()})
        df[NOISE_FEATURE] = rng.normal(NOISE_MEAN, 100.0, per_class)
        df[CONSTANT_FEATURE] = 0.0
        frames.append(df[FEATURES])
        labels.append(np.full(per_class, cls))
    return pd.concat(frames, ignore_index=True), pd.Series(np.concatenate(labels), name="MulticlassLabel")


def build_tiny_bundle(out_dir, bundle_id: str, seed: int = 0) -> Path:
    """Train, calibrate the anomaly threshold, write and return the bundle directory."""
    X, y = synthetic_flows(seed)

    selector = FeatureSelector(drop_high_correlation=False).fit(X, y)
    X_sel = selector.transform(X)
    preprocessor = build_preprocessor(list(X_sel.columns), [], None).fit(X_sel)
    X_t = preprocessor.transform(X_sel)

    # n_jobs=1: RandomForest probabilities are only bit-reproducible single-threaded
    classifier = RandomForestClassifier(n_estimators=20, max_depth=4, random_state=seed, n_jobs=1).fit(X_t, y)
    benign = (y == BENIGN).to_numpy()
    detector = IsolationForest(n_estimators=50, max_samples=128, random_state=seed, n_jobs=1).fit(X_t[benign])

    benign_scores = -detector.score_samples(X_t[benign])
    thresholds = {**THRESHOLDS, "anomaly": float(np.quantile(benign_scores, 0.99)) + 1e-9}
    manifest = {
        "bundle_id": bundle_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": {"experiment": "TINY", "model": "random_forest", "strategy": "none",
                   "split": "synthetic", "label": "multiclass", "feature_selection": "none", "params": None},
        "required_features": list(selector.selected_columns_),
        "classes": [int(c) for c in classifier.classes_],
        "class_names": CLASS_NAMES,
        "benign_class": BENIGN,
        "open_set": {"thresholds": thresholds, "calibration": {}, "anomaly_detector": {"type": "isolation_forest"}},
        "benign_profile": {c: {"median": float(X_sel.loc[benign, c].median()), "std": float(X_sel.loc[benign, c].std())}
                           for c in X_sel.columns},
        # Fixed placeholder values (not measured), in build_bundle.py's layout, for the admin page
        "metrics": {"test": {"multiclass": {"macro_f1": 0.99},
                             "attack_vs_benign": {"recall_attack": 0.98, "fpr": 0.01},
                             "open_set": {"benign_as_unknown": 0.01, "attack_as_unknown": 0.3, "attack_missed": 0.02}}},
        "latency_cpu": {"single_flow_ms_p50": 1.5, "single_flow_ms_p95": 3.0, "batch_flows_per_second": 100000},
    }

    staged = Bundle(None, manifest, selector, preprocessor, classifier, detector)
    rows = pd.concat([pd.DataFrame([f for f, *_ in CANONICAL_FLOWS.values()])[FEATURES],
                      X.groupby(y).head(3)], ignore_index=True)
    result = staged.predict(rows)
    selftest = rows.copy()
    selftest[EXPECTED_CLASS_COL] = result["predicted_class"].to_numpy()
    for i, c in enumerate(staged.classes):
        selftest[f"{EXPECTED_PROBA_PREFIX}{c}"] = staged.predict_proba(rows)[:, i]
    selftest[EXPECTED_ANOMALY_COL] = result["anomaly_score"].to_numpy()
    selftest[EXPECTED_DECISION_COL] = result["decision"].to_numpy()
    manifest["selftest_rows"] = len(selftest)

    path = Path(out_dir) / bundle_id
    save_bundle(path, manifest, selector, preprocessor, classifier, detector, selftest)
    return path
