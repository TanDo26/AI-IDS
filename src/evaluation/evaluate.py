"""
Model evaluation utilities for the GeNIS IDS pipeline.
"""

import numpy as np
import pandas as pd

from .metrics import calculate_metrics, fpr_threshold
from src.preprocessing.artifacts import get_fs_profile

THRESHOLD_COLUMNS = ["recall_attack", "precision_attack", "f1_attack", "fpr", "tp", "fp", "tn", "fn"]
PER_CLASS_COLUMNS = ["experiment", "model", "strategy", "split", "label", "feature_selection", "rule",
                     "class_id", "class", "total", "detected", "correct", "recall"]


def evaluate_experiment(model, X_test, y_test, experiment: dict,
                        split_name: str):

    exp_name = experiment["name"]
    model_name = experiment["model"]
    strategy = experiment["strategy"]
    label_type = experiment.get("label", "binary")

    y_pred = model.predict(X_test)

    y_prob = None
    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X_test)
        if label_type == "binary":
            y_prob = y_prob[:, 1]
    elif hasattr(model, "decision_function"):
        y_prob = model.decision_function(X_test)

    metrics = calculate_metrics(y_test, y_pred, y_prob, label_type=label_type)

    metrics.update({
        "experiment": exp_name,
        "model": model_name,
        "strategy": strategy,
        "split": split_name,
        "label": label_type,
        "feature_selection": get_fs_profile(experiment),
        "training_time_s": round(getattr(model, "training_time_s", 0.0), 4),
    })

    return metrics, y_pred, y_prob


def evaluate_thresholds(model, X_val, y_val, y_test, y_prob, experiment: dict,
                        split_name: str, target_fprs):
    """
    A binary experiment's test results at the 0.5 threshold and at one threshold per target FPR,
    each picked on the validation split's Benign rows alone (no attack labels). A flow is an attack
    when P(attack) > the threshold. Returns one row per threshold, and each threshold's test
    predictions by rule.
    """
    val_benign = model.predict_proba(X_val)[:, 1][np.asarray(y_val) == 0]
    thresholds = [("0.5", None, 0.5)] + [
        (f"val FPR {target:.1%}".replace(".0%", "%"), target, fpr_threshold(val_benign, target))
        for target in target_fprs
    ]

    rows, predictions = [], {}
    for rule, target, threshold in thresholds:
        predictions[rule] = (y_prob > threshold).astype(int)
        test = calculate_metrics(y_test, predictions[rule], label_type="binary")
        rows.append({
            "experiment": experiment["name"],
            "model": experiment["model"],
            "strategy": experiment["strategy"],
            "split": split_name,
            "feature_selection": get_fs_profile(experiment),
            "rule": rule,
            "target_fpr": target,
            "threshold": threshold,
            "val_benign": len(val_benign),
            "val_fpr": round(float((val_benign > threshold).mean()), 6),
            **{c: test[c] for c in THRESHOLD_COLUMNS},
        })
    return rows, predictions


def per_class_counts(test_classes, y_pred, experiment: dict, split_name: str, rule: str,
                     class_names: dict, benign_class: int):
    """
    Test results per original class (MulticlassLabel), for binary experiments too: `total` rows,
    `detected` (predicted as any attack) and `correct` (binary: the right side, so a Benign row is
    correct when not flagged; multiclass: the exact class). recall = correct / total. The counts are
    kept so that a class of two rows can be reported as 1/2.
    """
    label_type = experiment.get("label", "binary")
    classes = np.asarray(test_classes)
    y_pred = np.asarray(y_pred).ravel()
    if label_type == "binary":
        detected = y_pred == 1
        correct = detected != (classes == benign_class)
    else:
        detected = y_pred != benign_class
        correct = y_pred == classes

    counts = (pd.DataFrame({"class_id": classes, "detected": detected, "correct": correct})
              .groupby("class_id")
              .agg(total=("detected", "size"), detected=("detected", "sum"), correct=("correct", "sum")))
    return [{
        "experiment": experiment["name"],
        "model": experiment["model"],
        "strategy": experiment["strategy"],
        "split": split_name,
        "label": label_type,
        "feature_selection": get_fs_profile(experiment),
        "rule": rule,
        "class_id": int(class_id),
        "class": class_names.get(str(class_id), str(class_id)),
        "total": int(c.total),
        "detected": int(c.detected),
        "correct": int(c.correct),
        "recall": round(c.correct / c.total, 4),
    } for class_id, c in counts.iterrows()]
