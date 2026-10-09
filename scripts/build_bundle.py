"""
Package a trained multiclass experiment as a model bundle for the IDS server.

    python scripts/build_bundle.py --exp EXP-59
    python scripts/build_bundle.py --exp 59 --out model_store

The bundle (see src/inference/bundle.py) holds the experiment's feature selector,
preprocessor and classifier, test metrics, a CPU latency benchmark and a self-test.
It is reloaded and verified from disk before the script finishes.
"""
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import load_split, model_artifact_path, TORCH_MODELS
from src.preprocessing.artifacts import get_fs_profile, preprocessing_artifact_paths
from src.evaluation.metrics import calculate_metrics
from src.inference.bundle import (
    Bundle, save_bundle, load_bundle, EXPECTED_CLASS_COL, EXPECTED_PROBA_PREFIX,
)


def resolve_experiment(config, exp):
    name = exp if exp.upper().startswith("EXP-") else f"EXP-{int(exp):02d}"
    for e in config["experiments"]:
        if e["name"] == name.upper():
            return e
    raise SystemExit(f"Experiment '{name}' not found in config.yaml")


def test_metrics(bundle, X_test, y_test, benign_class):
    proba = bundle.predict_proba(X_test)
    y_pred = bundle.classes[proba.argmax(axis=1)]
    multiclass = calculate_metrics(y_test, y_pred, proba, label_type="multiclass")

    # The server's first question is Attack vs Benign, so also score that view
    benign_col = list(bundle.classes).index(benign_class)
    binary = calculate_metrics(
        (y_test != benign_class).astype(int), (y_pred != benign_class).astype(int),
        1.0 - proba[:, benign_col], label_type="binary")
    return {"multiclass": multiclass, "attack_vs_benign": binary}


def selftest_rows(bundle, X_val, y_val, per_class):
    # A few validation rows per class, so the self-test exercises every class the model knows
    idx = y_val.groupby(y_val, group_keys=False).apply(
        lambda s: s.sample(min(per_class, len(s)), random_state=42)).index
    rows = X_val.loc[np.sort(idx)].reset_index(drop=True)

    proba = bundle.predict_proba(rows)
    out = rows.copy()
    out[EXPECTED_CLASS_COL] = bundle.classes[proba.argmax(axis=1)]
    for i, c in enumerate(bundle.classes):
        out[f"{EXPECTED_PROBA_PREFIX}{c}"] = proba[:, i]
    return out


def benchmark_cpu(bundle, X, n_single=200, batch_size=10000, repeats=3):
    """End-to-end (selection + preprocessing + classifier) latency, in-process."""
    bundle.predict_proba(X.iloc[:1])  # warm-up

    single = []
    for i in range(min(n_single, len(X))):
        row = X.iloc[[i]]
        start = time.perf_counter()
        bundle.predict_proba(row)
        single.append((time.perf_counter() - start) * 1000)

    batch = X.iloc[:batch_size]
    batch_ms = []
    for _ in range(repeats):
        start = time.perf_counter()
        bundle.predict_proba(batch)
        batch_ms.append((time.perf_counter() - start) * 1000)
    batch_median = float(np.median(batch_ms))

    return {
        "single_flow_ms_p50": round(float(np.percentile(single, 50)), 3),
        "single_flow_ms_p95": round(float(np.percentile(single, 95)), 3),
        "batch_size": len(batch),
        "batch_ms_median": round(batch_median, 1),
        "batch_flows_per_second": int(len(batch) / (batch_median / 1000)),
    }


def main(exp, out_dir, per_class):
    with open(PROJECT_ROOT / "configs" / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    experiment = resolve_experiment(config, exp)
    name, model_name = experiment["name"], experiment["model"]
    split_name, label_type = experiment["split"], experiment.get("label", "binary")
    fs_profile = get_fs_profile(experiment)

    if label_type != "multiclass":
        raise SystemExit(f"{name} is {label_type}; a bundle needs a multiclass experiment "
                         f"(the server reports Benign / attack type / unknown)")
    if model_name in TORCH_MODELS:
        raise SystemExit(f"{name} uses {model_name}; PyTorch models are not served (plan §2)")

    ds_cfg = config["datasets"][config["active_dataset"]]
    with open(Path(ds_cfg["data_dir"]) / "label_mapping.json", "r", encoding="utf-8") as f:
        mapping = json.load(f)
    benign_class = mapping["label_to_int"][ds_cfg["label_mapping"]["benign_label"]]

    selector_path, preprocessor_path = preprocessing_artifact_paths(config, split_name, label_type, fs_profile)
    model_path = model_artifact_path(config, experiment)
    for p in (selector_path, preprocessor_path, model_path):
        if not p.exists():
            raise SystemExit(f"Missing {p}; train {name} first")

    print("=" * 70)
    print(f"  BUILD BUNDLE | {name} | {model_name} | {split_name} | fs={fs_profile}")
    print("=" * 70)

    bundle_id = f"{name}-{model_name}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    staged = Bundle(None, {"bundle_id": bundle_id},
                    joblib.load(selector_path), joblib.load(preprocessor_path), joblib.load(model_path))
    if benign_class not in staged.classes:
        raise SystemExit(f"{name}'s classifier has no Benign class ({benign_class})")

    _, X_val, X_test, _, y_val, y_test = load_split(split_name, label_type, config)

    print("  Scoring the test split...")
    metrics = test_metrics(staged, X_test, y_test, benign_class)
    print("  Benchmarking CPU latency...")
    latency = benchmark_cpu(staged, X_test)
    selftest_df = selftest_rows(staged, X_val, y_val, per_class)

    manifest = {
        "bundle_id": bundle_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "experiment": name, "model": model_name, "strategy": experiment.get("strategy"),
            "split": split_name, "label": label_type, "feature_selection": fs_profile,
            "params": experiment.get("params"),
        },
        "required_features": list(staged.selector.selected_columns_),
        "classes": [int(c) for c in staged.classes],
        "class_names": {str(int(c)): mapping["int_to_label"][str(int(c))] for c in staged.classes},
        "benign_class": int(benign_class),
        "metrics": {"test": metrics},
        "latency_cpu": latency,
        "selftest_rows": len(selftest_df),
    }

    path = Path(out_dir) / bundle_id
    save_bundle(path, manifest, staged.selector, staged.preprocessor, staged.classifier, selftest_df)

    # Prove the bundle works from disk alone: hashes, library versions, self-test
    bundle = load_bundle(path)

    mc, bv = metrics["multiclass"], metrics["attack_vs_benign"]
    print(f"\n  Bundle: {path}")
    print(f"  Features: {len(manifest['required_features'])} | Classes: {len(manifest['classes'])} "
          f"| Self-test: {len(selftest_df)} rows passed after reload")
    print(f"  Test  multiclass: macro-F1={mc['macro_f1']:.4f} macro-recall={mc['macro_recall']:.4f} "
          f"accuracy={mc['accuracy']:.4f}")
    print(f"  Test  attack vs benign: recall={bv['recall_attack']:.4f} FPR={bv['fpr']:.4f} "
          f"F1={bv['f1_attack']:.4f}")
    print(f"  CPU latency: 1 flow p50={latency['single_flow_ms_p50']} ms p95={latency['single_flow_ms_p95']} ms "
          f"| {latency['batch_size']} flows {latency['batch_ms_median']} ms "
          f"({latency['batch_flows_per_second']:,} flows/s)")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package a trained multiclass experiment as a model bundle")
    parser.add_argument("--exp", "-e", required=True, help="Experiment, e.g. EXP-59 or 59")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "model_store"),
                        help="Directory the bundle folder is created in (default: model_store/)")
    parser.add_argument("--selftest-per-class", type=int, default=2,
                        help="Validation rows per class stored for the self-test (default: 2)")
    args = parser.parse_args()
    main(args.exp, args.out, args.selftest_per_class)
