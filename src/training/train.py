"""
Training pipeline utilities for the IDS project.
"""

from sklearn.preprocessing import OneHotEncoder
import time
from pathlib import Path

import joblib

from tqdm import tqdm

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import (StandardScaler,OneHotEncoder)

def build_preprocessor(numerical_features, categorical_features):
    numerical_pipeline = Pipeline(
        steps = [
            ("imputer", SimpleImputer(strategy="median")),
            ("Scaler", StandardScaler)
        ]
    )

    categorical_pipeline = Pipeline(
        steps= [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore"))
        ]
    )

    preprocessor = ColumnTransformer(
        transformers= [
            ("numerical", numerical_pipeline, numerical_features),
            ("categorical", categorical_pipeline, categorical_features)
        ]
    )

    return preprocessor

def train_model(model, X_train, y_train, preprocessor, strategy, undersample_fn=None):
    start_time = time.perf_counter()

    stages = ["Preprocessing", "Undersampling", "Model Training"]

    progress = tqdm(total=len(stages), desc="Training Pipeline", unit="stage")

    preprocessor.fit(X_train)

    X_train_transformed = preprocessor.transform(X_train)

    progress.update(1)

    if strategy == "undersampling":
        if undersample_fn is None:
            raise ValueError("Undersampling function is required for this strategy")

        X_train_transformed, y_train = undersample_fn(X_train_transformed, y_train)

    elif strategy == "class_weighting":
        pass

    else: 
        raise ValueError("Unknown strategy: {strategy}")

    progress.update(1)

    model.fit(X_train_transformed, y_train)

    progress.update(1)

    progress.close()

    train_time = time.perf_counter() - start_time

    return model, preprocessor, train_time

def save_model(model, filepath):

    filepath = Path(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, filepath)

    print(f"Model saved to {filepath}")

def save_preprocessor(preprocessor, filepath):

    filepath = Path(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(preprocessor, filepath)

    print(f"Preprocessor saved to {filepath}")
