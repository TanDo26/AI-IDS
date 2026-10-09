"""
Open-set evaluation: how well does the bundle pipeline flag attack types it never saw?
Results: results/open_set/<protocol>_<tag>.csv and <protocol>_<tag>_by_label.csv
"""
import sys
import json
import time
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import load_split, fit_preprocessing, TORCH_MODELS, SAMPLE_WEIGHT_MODELS
from src.imbalance.smote import apply_smote
from src.imbalance.undersampling import apply_undersampling
from src.models.registry import get_model
from src.inference.open_set import anomaly_scores, decide, BENIGN, KNOWN_ATTACK, UNKNOWN
from scripts.build_bundle import fit_anomaly_detector, calibrate, resolve_experiment

RULES = ("argmax", "confidence", "anomaly", "combined")


def apply_rule(rule, proba, classes, anomaly, benign, thresholds):
    if rule == "anomaly":
        decision = np.where(anomaly > thresholds["anomaly"], UNKNOWN, BENIGN)
        return pd.DataFrame({"decision": decision,
                             "predicted_class": np.where(decision == BENIGN, benign, -1)})
    tau_known = 0.0 if rule == "argmax" else thresholds["known"]
    tau_anomaly = thresholds["anomaly"] if rule == "combined" else np.inf
    return decide(proba, classes, anomaly, benign, tau_known, tau_anomaly)


def score(rule, result, y, benign, known_classes):
    decision = result["decision"].to_numpy()
    predicted = result["predicted_class"].to_numpy()
    is_benign = y == benign
    unseen = ~np.isin(y, known_classes)
    known_attack = ~is_benign & ~unseen

    def share(mask, of):
        return round(float(mask[of].mean()), 6) if of.any() else None

    known_f1 = None
    if rule != "anomaly":
        # Known classes only; "unknown" counts as a wrong label for them
        # (averaged over known classes present in the test set: Thu-Fri contains only Benign of them)
        rows = ~unseen
        y_pred = np.where(decision == KNOWN_ATTACK, predicted, np.where(decision == BENIGN, benign, -1))
        present = np.intersect1d(known_classes, y[rows])
        known_f1 = round(float(f1_score(y[rows], y_pred[rows], labels=present,
                                        average="macro", zero_division=0)), 6)

    # Flow-weighted detection is dominated by big classes (DDoS); also average over unseen labels
    per_label = [float((decision[y == label] != BENIGN).mean()) for label in np.unique(y[unseen])]
    return {
        "unseen_flows": int(unseen.sum()),
        "unseen_detected": share(decision != BENIGN, unseen),
        "unseen_detected_label_avg": round(float(np.mean(per_label)), 6) if per_label else None,
        "unseen_as_unknown": share(decision == UNKNOWN, unseen),
        "unseen_as_known_type": share(decision == KNOWN_ATTACK, unseen),
        "unseen_missed": share(decision == BENIGN, unseen),
        "known_attack_flows": int(known_attack.sum()),
        "known_attack_detected": share(decision != BENIGN, known_attack),
        "known_attack_right_type": share((decision == KNOWN_ATTACK) & (predicted == y), known_attack),
        "benign_flows": int(is_benign.sum()),
        "benign_false_alarm": share(decision != BENIGN, is_benign),
        "known_macro_f1": known_f1,
    }


def by_label(rule, result, y, known_classes, names):
    decision = result["decision"].to_numpy()
    rows = []
    for label in sorted(set(y[~np.isin(y, known_classes)])):
        mask = y == label
        rows.append({"rule": rule, "label": names[str(int(label))], "flows": int(mask.sum()),
                     "as_unknown": round(float((decision[mask] == UNKNOWN).mean()), 6),
                     "as_known_type": round(float((decision[mask] == KNOWN_ATTACK).mean()), 6),
                     "missed": round(float((decision[mask] == BENIGN).mean()), 6)})
    return rows


def run_fold(config, spec, data, train_mask, benign, names, subsample):
    X_train, X_val, X_test, y_train, y_val, y_test = data
    X_tr, y_tr = X_train[train_mask], y_train[train_mask]
    if subsample:
        X_tr, _, y_tr, _ = train_test_split(X_tr, y_tr, train_size=subsample, stratify=y_tr, random_state=42)

    # Preprocessing is refit on the known classes only, so nothing about unseen attacks leaks in
    selector, preprocessor = fit_preprocessing(X_tr, y_tr, config, spec["fs"])
    X_tr_t = preprocessor.transform(selector.transform(X_tr))

    fit_kwargs, class_weight = {}, None
    if spec["strategy"] == "smote":
        X_tr_t, y_tr_fit = apply_smote(X_tr_t, y_tr, config)
    elif spec["strategy"] == "undersampling":
        X_tr_t, y_tr_fit = apply_undersampling(X_tr_t, y_tr, config, "multiclass")
    else:
        y_tr_fit = y_tr
        if spec["strategy"] == "class_weight":
            class_weight = "balanced"
            if spec["model"] in SAMPLE_WEIGHT_MODELS:
                fit_kwargs["sample_weight"] = compute_sample_weight("balanced", y_tr_fit)

    start = time.perf_counter()
    classifier = get_model(spec["model"], config, class_weight=class_weight, overrides=spec["params"])
    classifier.fit(X_tr_t, y_tr_fit, **fit_kwargs)
    train_s = time.perf_counter() - start
    known_classes = np.asarray(classifier.classes_)

    detector, _, _ = fit_anomaly_detector(config, selector, preprocessor, X_tr, y_tr, benign)
    val_known = np.isin(y_val.to_numpy(), known_classes)
    X_val_t = preprocessor.transform(selector.transform(X_val[val_known]))
    thresholds, _ = calibrate(config, classifier, detector, X_val_t, y_val[val_known], benign)

    X_test_t = preprocessor.transform(selector.transform(X_test))
    proba = classifier.predict_proba(X_test_t)
    anomaly = anomaly_scores(detector, X_test_t)
    y = y_test.to_numpy()

    rows, label_rows = [], []
    for rule in RULES:
        result = apply_rule(rule, proba, known_classes, anomaly, benign, thresholds)
        rows.append({"rule": rule, **score(rule, result, y, benign, known_classes)})
        label_rows += by_label(rule, result, y, known_classes, names)
    info = {"train_rows": len(y_tr), "known_classes": len(known_classes), "train_s": round(train_s, 1),
            "tau_known": thresholds["known"], "tau_anomaly": thresholds["anomaly"]}
    return rows, label_rows, info


def main(args):
    with open(PROJECT_ROOT / "configs" / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    ds_cfg = config["datasets"][config["active_dataset"]]
    with open(Path(ds_cfg["data_dir"]) / "label_mapping.json", "r", encoding="utf-8") as f:
        mapping = json.load(f)
    names, label_to_int = mapping["int_to_label"], mapping["label_to_int"]
    benign = label_to_int[ds_cfg["label_mapping"]["benign_label"]]

    if args.exp:
        exp = resolve_experiment(config, args.exp)
        spec = {"model": exp["model"], "strategy": exp.get("strategy"),
                "fs": exp.get("feature_selection") or "none", "params": exp.get("params")}
        tag = exp["name"]
    else:
        spec = {"model": args.model, "strategy": None if args.strategy == "none" else args.strategy,
                "fs": args.fs, "params": None}
        tag = f"{spec['model']}_{args.strategy}" + (f"_{args.fs}" if args.fs != "none" else "")
    if spec["model"] in TORCH_MODELS:
        raise SystemExit(f"{spec['model']} is not supported (bundles serve tree/linear models only)")
    if args.subsample:
        tag += f"_sub{args.subsample:g}"

    split = "temporal" if args.protocol == "temporal" else "random"
    data = load_split(split, "multiclass", config)
    y_train = data[3].to_numpy()

    if args.protocol == "temporal":
        folds = {"temporal": np.ones(len(y_train), dtype=bool)}
    else:
        families = ds_cfg["attack_families"]
        selected = args.families.split(",") if args.families else list(families)
        unknown = [f for f in selected if f not in families]
        if unknown:
            raise SystemExit(f"Unknown families {unknown}. Available: {', '.join(families)}")
        folds = {f: ~np.isin(y_train, [label_to_int[l] for l in families[f]]) for f in selected}

    print("=" * 78)
    print(f"  OPEN-SET EVALUATION | protocol={args.protocol} | {spec['model']} | strategy={spec['strategy']} "
          f"| fs={spec['fs']}" + (f" | subsample={args.subsample}" if args.subsample else ""))
    print("=" * 78)

    all_rows, all_label_rows = [], []
    for fold, train_mask in folds.items():
        print(f"\n  Fold '{fold}': training on {int(train_mask.sum()):,} rows...")
        rows, label_rows, info = run_fold(config, spec, data, train_mask, benign, names, args.subsample)
        print(f"    {info['known_classes']} known classes, {info['train_rows']:,} rows, trained in {info['train_s']}s "
              f"| tau_known={info['tau_known']:.6g} tau_anomaly={info['tau_anomaly']:.4f}")
        print(f"    {'rule':<11}{'unseen detected':>16}{'(label avg)':>12}{'-> unknown':>12}{'-> known type':>15}"
              f"{'missed':>9}{'known right type':>18}{'benign alarms':>15}{'known macro-F1':>16}")
        for r in rows:
            f1 = f"{r['known_macro_f1']:.4f}" if r["known_macro_f1"] is not None else "-"
            known = f"{r['known_attack_right_type']:.2%}" if r["known_attack_right_type"] is not None else "-"
            print(f"    {r['rule']:<11}{r['unseen_detected']:>16.2%}{r['unseen_detected_label_avg']:>12.2%}"
                  f"{r['unseen_as_unknown']:>12.2%}"
                  f"{r['unseen_as_known_type']:>15.2%}{r['unseen_missed']:>9.2%}{known:>18}"
                  f"{r['benign_false_alarm']:>15.2%}{f1:>16}")
        all_rows += [{"protocol": args.protocol, "fold": fold, **info, **r} for r in rows]
        all_label_rows += [{"protocol": args.protocol, "fold": fold, **r} for r in label_rows]

    out_dir = PROJECT_ROOT / "results" / "open_set"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / f"{args.protocol}_{tag}.csv"
    labels_path = out_dir / f"{args.protocol}_{tag}_by_label.csv"
    pd.DataFrame(all_rows).to_csv(summary_path, index=False)
    pd.DataFrame(all_label_rows).to_csv(labels_path, index=False)
    print(f"\n  Results: {summary_path}\n           {labels_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Open-set (unseen attack) evaluation")
    parser.add_argument("--protocol", required=True, choices=["temporal", "lofo"])
    parser.add_argument("--exp", "-e", default=None,
                        help="Take model/strategy/feature selection/params from an experiment, e.g. EXP-59")
    parser.add_argument("--model", default="xgboost", help="Model when --exp is not given (default: xgboost)")
    parser.add_argument("--strategy", default="class_weight",
                        choices=["none", "smote", "undersampling", "class_weight"],
                        help="Imbalance strategy when --exp is not given (default: class_weight)")
    parser.add_argument("--fs", default="none", help="Feature-selection profile when --exp is not given")
    parser.add_argument("--families", default=None, help="lofo only: comma-separated families (default: all)")
    parser.add_argument("--subsample", type=float, default=None,
                        help="Train on a stratified fraction of the training rows (quick runs)")
    main(parser.parse_args())
