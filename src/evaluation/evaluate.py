"""
Model evaluation utilities for the GeNIS IDS pipeline.
"""

import time
from pathlib import Path

import pandas as pd

from .metrics import calculate_metrics

def evaluate_model(model, preprocessor, X_test, y_test, experiment_id, train_time=None, prediction_filepath=None):

    X_test_transformed = preprocessor.transform(X_test)

    start_time = time.perf_counter()

    y_pred = model.predict(X_test_transformed)

    inference_time = time.perf_counter() - start_time

    metrics = calculate_metrics(y_test, y_pred)
    metrics["experiment"] = experiment_id
    metrics["train_time"] = train_time
    metrics["inference_time"] = inference_time

    if prediction_filepath is not None:
        save_predictions(y_test, y_pred, prediction_filepath)

    return metrics

def save_predictions(y_test, y_pred, filepath):

    filepath = Path(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)

    predictions = pd.DataFrame({
        "y_true": y_test,
        "y_pred": y_pred
    })

    predictions.to_csv(filepath, index=False)

    print(f"Predictions saved to {filepath}")