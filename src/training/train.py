"""
Training utilities for the GeNIS IDS pipeline.
"""

import time
import joblib
from pathlib import Path
import pandas as pd
from tqdm import tqdm


from src.data.split_data import _get_feature_columns
from src.preprocessing.feature_selection import FeatureSelector
from src.preprocessing.build_preprocessor import build_preprocessor
from src.imbalance.smote import apply_smote
from src.imbalance.undersampling import apply_undersampling
from src.models.registry import get_model


def load_split(split_name: str, label_type: str, config: dict):
    ds_name = config["active_dataset"]
    split_dir = Path(config["output"]["splits_dir"].format(
        dataset_name=ds_name)) / split_name

    label_col = "BinaryLabel" if label_type == "binary" else "MulticlassLabel"

    X_train = pd.read_parquet(split_dir / "X_train.parquet")
    X_val = pd.read_parquet(split_dir / "X_val.parquet")
    X_test = pd.read_parquet(split_dir / "X_test.parquet")
    y_train = pd.read_parquet(split_dir / "y_train.parquet")[label_col]
    y_val = pd.read_parquet(split_dir / "y_val.parquet")[label_col]
    y_test = pd.read_parquet(split_dir / "y_test.parquet")[label_col]

    return X_train, X_val, X_test, y_train, y_val, y_test


def train_experiment(experiment: dict, config: dict):

    exp_name = experiment["name"]
    model_name = experiment["model"]
    strategy = experiment["strategy"]
    split_name = experiment["split"]
    label_type = experiment.get("label", "binary")

    print(f"\n{'='*60}")
    print(f"  {exp_name} | {model_name} | {strategy} | {split_name} | {label_type}")
    print(f"{'='*60}")

    steps = [
        "Loading data",
        "Feature selection",
        "Preprocessing",
        "Imbalance handling",
        "Model training",
        "Saving artifacts",
    ]
    pbar = tqdm(
        total=len(steps),
        desc=f"[{exp_name}]",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ncols=80,
        leave=True,
    )

    pbar.set_postfix_str(steps[0])
    X_train, X_val, X_test, y_train, y_val, y_test = load_split(split_name, label_type, config)
    pbar.update(1)

    pbar.set_postfix_str(steps[1])
    fs_cfg = config["preprocessing"]["feature_selection"]
    selector = FeatureSelector(
        drop_zero_variance=fs_cfg["drop_zero_variance"],
        drop_high_correlation=fs_cfg["drop_high_correlation"],
        correlation_threshold=fs_cfg["correlation_threshold"],
    )
    X_train = selector.fit_transform(X_train)
    X_val = selector.transform(X_val)
    X_test = selector.transform(X_test)
    print(f"  Feature selection: {selector.summary()}")
    pbar.update(1)

    pbar.set_postfix_str(steps[2])
    ds_cfg = config["datasets"][config["active_dataset"]]
    numeric_feats = [c for c in selector.selected_columns_
                     if c in ds_cfg["features"].get("numeric", [])]
    categorical_feats = [c for c in selector.selected_columns_
                         if c in ds_cfg["features"].get("categorical", [])]

    preprocessor = build_preprocessor(
        numeric_feats,
        categorical_feats if categorical_feats else None,
        config,
    )
    X_train_t = preprocessor.fit_transform(X_train)
    X_val_t = preprocessor.transform(X_val)
    X_test_t = preprocessor.transform(X_test)
    print(f"  Preprocessor fitted. Output shape: {X_train_t.shape}")
    pbar.update(1)

    pbar.set_postfix_str(steps[3])
    if strategy == "smote":
        X_train_t, y_train = apply_smote(X_train_t, y_train, config)
    elif strategy == "undersampling":
        X_train_t, y_train = apply_undersampling(X_train_t, y_train, config)
    elif strategy == "class_weight":
        print("  Using class_weight='balanced' (no resampling)")
    pbar.update(1)

    pbar.set_postfix_str(steps[4])
    class_weight = "balanced" if strategy == "class_weight" else None
    model = get_model(model_name, config, class_weight=class_weight)
    print(f"  Training {model_name}...")
    start = time.perf_counter()
    model.fit(X_train_t, y_train)
    train_time = time.perf_counter() - start
    print(f"  Training complete in {train_time:.2f}s")
    pbar.update(1)

    pbar.set_postfix_str(steps[5])
    models_dir = Path(config["output"]["models_dir"]) / split_name
    models_dir.mkdir(parents=True, exist_ok=True)
    model_path = models_dir / f"{exp_name}_{model_name}.pkl"
    joblib.dump(model, model_path)

    preproc_dir = Path(config["output"]["preprocessors_dir"])
    preproc_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(selector, preproc_dir / f"{split_name}_feature_selector.pkl")
    joblib.dump(preprocessor, preproc_dir / f"{split_name}_preprocessor.pkl")

    print(f"  Saved model to {model_path}")
    pbar.set_postfix_str("Done ")
    pbar.update(1)
    pbar.close()

    return {
        "model": model,
        "preprocessor": preprocessor,
        "selector": selector,
        "X_val": X_val_t,
        "y_val": y_val,
        "X_test": X_test_t,
        "y_test": y_test,
        "train_time": train_time,
    }
