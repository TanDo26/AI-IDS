"""
Package a trained multiclass experiment as a model bundle for the IDS server.

    python scripts/build_bundle.py --exp EXP-59
    python scripts/build_bundle.py --exp 59 --out model_store

The bundle (see src/inference/bundle.py) holds the experiment's feature selector,
preprocessor and classifier, plus an anomaly detector fitted on benign training flows
and the two open-set thresholds calibrated on the validation split
(src/inference/open_set.py). The manifest records test metrics, a CPU latency
benchmark and file hashes; the bundle is reloaded and verified before the script ends.
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
from src.models.anomaly import build_anomaly_detector
from src.inference.open_set import anomaly_scores, decide, BENIGN, KNOWN_ATTACK, UNKNOWN
from src.inference.bundle import (
    Bundle, save_bundle, load_bundle,
    EXPECTED_CLASS_COL, EXPECTED_PROBA_PREFIX, EXPECTED_ANOMALY_COL, EXPECTED_DECISION_COL,
)


def resolve_experiment(config, exp):
    name = exp if exp.upper().startswith("EXP-") else f"EXP-{int(exp):02d}"
    for e in config["experiments"]:
        if e["name"] == name.upper():
            return e
    raise SystemExit(f"Experiment '{name}' not found in config.yaml")


def fit_anomaly_detector(config, selector, preprocessor, X_train, y_train, benign_class):
    os_cfg = config["open_set"]
    benign = X_train[(y_train == benign_class).to_numpy()]
    n = min(os_cfg["anomaly_train_rows"], len(benign))
    sample = benign.sample(n, random_state=os_cfg.get("random_state", 42))
    detector = build_anomaly_detector(config).fit(preprocessor.transform(selector.transform(sample)))
    # Fit in parallel, score single-threaded: faster for both 1 flow and 10k-flow batches
    detector.set_params(n_jobs=1)
    info = {"type": os_cfg.get("anomaly_detector", "isolation_forest"), "train_rows": n,
            "n_estimators": detector.n_estimators, "max_samples": detector.max_samples}
    return detector, info


def calibrate(config, classifier, detector, X_val_t, y_val, benign_class):
    """Open-set thresholds from the validation split."""
    os_cfg = config["open_set"]
    y = y_val.to_numpy()
    proba = classifier.predict_proba(X_val_t)
    predicted = np.asarray(classifier.classes_)[proba.argmax(axis=1)]
    confidence = proba.max(axis=1)
    anomaly = anomaly_scores(detector, X_val_t)

    correct_attack = (y != benign_class) & (predicted == y)
    benign_ok = (y == benign_class) & (predicted == benign_class)
    if not correct_attack.any() or not benign_ok.any():
        raise SystemExit("Validation split has no correctly classified attacks or benign flows to calibrate on")

    return {
        # Correct known attacks below this confidence become "unknown" (known_quantile of them)
        "known": float(np.quantile(confidence[correct_attack], os_cfg["known_quantile"])),
        # Classifier-benign flows above this anomaly score become "unknown" (target_benign_fpr of them)
        "anomaly": float(np.quantile(anomaly[benign_ok], 1 - os_cfg["target_benign_fpr"])),
    }, {
        "known_quantile": os_cfg["known_quantile"],
        "target_benign_fpr": os_cfg["target_benign_fpr"],
        "val_correct_attack_rows": int(correct_attack.sum()),
        "val_benign_rows": int(benign_ok.sum()),
    }


def open_set_breakdown(result, y_true, benign_class):
    """Share of benign / attack flows per decision (attacks also split by correct vs wrong type)."""
    y = y_true.to_numpy()
    decision = result["decision"].to_numpy()
    predicted = result["predicted_class"].to_numpy()
    benign, attack = y == benign_class, y != benign_class

    def share(mask, of):
        return round(float(mask[of].mean()), 6) if of.any() else None

    return {
        "benign_flows": int(benign.sum()),
        "benign_as_benign": share(decision == BENIGN, benign),
        "benign_as_unknown": share(decision == UNKNOWN, benign),
        "benign_as_known_attack": share(decision == KNOWN_ATTACK, benign),
        "attack_flows": int(attack.sum()),
        "attack_known_correct_type": share((decision == KNOWN_ATTACK) & (predicted == y), attack),
        "attack_known_wrong_type": share((decision == KNOWN_ATTACK) & (predicted != y), attack),
        "attack_as_unknown": share(decision == UNKNOWN, attack),
        "attack_missed": share(decision == BENIGN, attack),
    }


def test_metrics(bundle, X_test, y_test, benign_class):
    X = bundle.transform(X_test)
    proba = bundle.classifier.predict_proba(X)
    y_pred = bundle.classes[proba.argmax(axis=1)]
    multiclass = calculate_metrics(y_test, y_pred, proba, label_type="multiclass")

    # The server's first question is Attack vs Benign, so also score that view
    benign_col = list(bundle.classes).index(benign_class)
    binary = calculate_metrics(
        (y_test != benign_class).astype(int), (y_pred != benign_class).astype(int),
        1.0 - proba[:, benign_col], label_type="binary")

    thresholds = bundle.manifest["open_set"]["thresholds"]
    result = decide(proba, bundle.classes, anomaly_scores(bundle.anomaly_detector, X), benign_class,
                    thresholds["known"], thresholds["anomaly"])
    return {"multiclass": multiclass, "attack_vs_benign": binary,
            "open_set": open_set_breakdown(result, y_test, benign_class)}


def selftest_rows(bundle, X_val, y_val, val_result, per_class):
    # A few validation rows per class and per decision reason, so the self-test
    # exercises every class and every branch of the open-set decision
    by_class = y_val.groupby(y_val, group_keys=False).apply(
        lambda s: s.sample(min(per_class, len(s)), random_state=42)).index
    reasons = pd.Series(val_result["reason"].to_numpy(), index=y_val.index)
    by_reason = reasons.groupby(reasons, group_keys=False).apply(
        lambda s: s.sample(min(per_class, len(s)), random_state=42)).index
    rows = X_val.loc[np.sort(by_class.union(by_reason))].reset_index(drop=True)

    proba = bundle.predict_proba(rows)
    result = bundle.predict(rows)
    out = rows.copy()
    out[EXPECTED_CLASS_COL] = result["predicted_class"].to_numpy()
    for i, c in enumerate(bundle.classes):
        out[f"{EXPECTED_PROBA_PREFIX}{c}"] = proba[:, i]
    out[EXPECTED_ANOMALY_COL] = result["anomaly_score"].to_numpy()
    out[EXPECTED_DECISION_COL] = result["decision"].to_numpy()
    return out


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

    selector, preprocessor = joblib.load(selector_path), joblib.load(preprocessor_path)
    classifier = joblib.load(model_path)
    if benign_class not in np.asarray(classifier.classes_):
        raise SystemExit(f"{name}'s classifier has no Benign class ({benign_class})")

    X_train, X_val, X_test, y_train, y_val, y_test = load_split(split_name, label_type, config)

    print("  Fitting the anomaly detector on benign training flows...")
    detector, detector_info = fit_anomaly_detector(config, selector, preprocessor, X_train, y_train, benign_class)
    print("  Calibrating open-set thresholds on the validation split...")
    X_val_t = preprocessor.transform(selector.transform(X_val))
    thresholds, calibration = calibrate(config, classifier, detector, X_val_t, y_val, benign_class)

    bundle_id = f"{name}-{model_name}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    open_set = {"thresholds": thresholds, "calibration": calibration, "anomaly_detector": detector_info}
    staged = Bundle(None, {"bundle_id": bundle_id, "benign_class": int(benign_class), "open_set": open_set},
                    selector, preprocessor, classifier, detector)

    val_result = staged.predict(X_val)
    calibration["val"] = open_set_breakdown(val_result, y_val, benign_class)

    print("  Scoring the test split...")
    metrics = test_metrics(staged, X_test, y_test, benign_class)
    print("  Benchmarking CPU latency...")
    latency = benchmark_cpu(staged, X_test)
    selftest_df = selftest_rows(staged, X_val, y_val, val_result, per_class)

    manifest = {
        "bundle_id": bundle_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "experiment": name, "model": model_name, "strategy": experiment.get("strategy"),
            "split": split_name, "label": label_type, "feature_selection": fs_profile,
            "params": experiment.get("params"),
        },
        "required_features": list(selector.selected_columns_),
        "classes": [int(c) for c in staged.classes],
        "class_names": {str(int(c)): mapping["int_to_label"][str(int(c))] for c in staged.classes},
        "benign_class": int(benign_class),
        "open_set": open_set,
        "metrics": {"test": metrics},
        "latency_cpu": latency,
        "selftest_rows": len(selftest_df),
    }

    path = Path(out_dir) / bundle_id
    save_bundle(path, manifest, selector, preprocessor, classifier, detector, selftest_df)

    # Prove the bundle works from disk alone: format, hashes, library versions, self-test
    bundle = load_bundle(path)

    mc, bv, os_test = metrics["multiclass"], metrics["attack_vs_benign"], metrics["open_set"]
    val = calibration["val"]
    print(f"\n  Bundle: {path}")
    print(f"  Features: {len(manifest['required_features'])} | Classes: {len(manifest['classes'])} "
          f"| Self-test: {len(selftest_df)} rows passed after reload")
    print(f"  Thresholds: known >= {thresholds['known']:.6g} confidence | "
          f"anomaly > {thresholds['anomaly']:.6g}")
    print(f"  Validation: benign -> unknown {val['benign_as_unknown']:.2%} "
          f"(target {calibration['target_benign_fpr']:.2%}) | attacks -> unknown {val['attack_as_unknown']:.2%}")
    print(f"  Test  multiclass: macro-F1={mc['macro_f1']:.4f} macro-recall={mc['macro_recall']:.4f} "
          f"accuracy={mc['accuracy']:.4f}")
    print(f"  Test  attack vs benign (classifier only): recall={bv['recall_attack']:.4f} FPR={bv['fpr']:.4f}")
    print(f"  Test  open-set: benign -> benign {os_test['benign_as_benign']:.2%}, unknown "
          f"{os_test['benign_as_unknown']:.2%}, known attack {os_test['benign_as_known_attack']:.2%}")
    print(f"                  attacks -> known (right type) {os_test['attack_known_correct_type']:.2%}, "
          f"known (wrong type) {os_test['attack_known_wrong_type']:.2%}, unknown "
          f"{os_test['attack_as_unknown']:.2%}, missed {os_test['attack_missed']:.2%}")
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
                        help="Validation rows per class and per decision reason in the self-test (default: 2)")
    args = parser.parse_args()
    main(args.exp, args.out, args.selftest_per_class)
