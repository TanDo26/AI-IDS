"""
Training utilities for the GeNIS IDS pipeline.
"""

import time
from pathlib import Path

import joblib

from tqdm import tqdm


def train_model(model, X_train, y_train, strategy, undersample_fn=None):

    start_time = time.perf_counter()

    with tqdm(total=3, desc="Training Pipeline", unit="stage") as progress:
        progress.set_description("Preparing training data")

        if strategy == "undersampling":

            if undersample_fn is None:
                raise ValueError("undersample_fn is required for undersampling.")

            X_train, y_train = undersample_fn(X_train, y_train)

        elif strategy == "class_weighting":

            pass

        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        progress.update(1)

        progress.set_description(f"Training {type(model).__name__}")

        model.fit(X_train, y_train)

        progress.update(1)

        progress.set_description("Training completed")

        progress.update(1)

    train_time = time.perf_counter() - start_time

    print(f"\nTraining completed in {train_time:.2f} seconds.")

    return model, train_time


def save_model(model, filepath):

    filepath = Path(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, filepath)

    print(f"Model saved to: {filepath}")