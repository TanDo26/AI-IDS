"""
Model evaluation utilities for the GeNIS IDS pipeline.
"""

import time
import pandas as pd
from .metrics import calculate_metrics


def evaluate_experiment(model, X_test, y_test, experiment: dict,
                        split_name: str):
    
    exp_name = experiment["name"]
    model_name = experiment["model"]
    strategy = experiment["strategy"]
    label_type = experiment.get("label", "binary")

    start = time.perf_counter()
    y_pred = model.predict(X_test)
    inference_time = time.perf_counter() - start

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
        "inference_time_s": round(inference_time, 4),
    })

    return metrics, y_pred, y_prob