"""
Training utilities for the GeNIS IDS pipeline.
"""

import time
import joblib
from pathlib import Path
import pandas as pd
from tqdm import tqdm


from src.data.split_data import _get_feature_columns
from src.preprocessing.feature_selection import build_feature_selector
from src.preprocessing.build_preprocessor import build_preprocessor
from src.preprocessing.artifacts import get_fs_profile, preprocessing_artifact_paths
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


TORCH_MODELS = ("mlp", "lstm")


def model_artifact_path(config: dict, experiment: dict) -> Path:
    model_name = experiment["model"]
    ext = ".pt" if model_name in TORCH_MODELS else ".pkl"
    return (Path(config["output"]["models_dir"]) / experiment["split"]
            / f"{experiment['name']}_{model_name}{ext}")


def _fit_preprocessing(X_train, y_train, config: dict, fs_profile: str):
    selector = build_feature_selector(config, fs_profile)
    X_train = selector.fit_transform(X_train, y_train)
    print(f"  Feature selection: {selector.summary()}")

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
    preprocessor.fit(X_train)
    return selector, preprocessor


def prepare_data(split_name: str, label_type: str, config: dict,
                 fs_profile: str = "none", save_artifacts: bool = True,
                 reuse_existing: bool = False):
    print(f"\n{'='*60}")
    print(f"  PREPARING DATA | {split_name} | {label_type} | fs={fs_profile}")
    print(f"{'='*60}")

    X_train, X_val, X_test, y_train, y_val, y_test = load_split(split_name, label_type, config)

    selector_path, preprocessor_path = preprocessing_artifact_paths(
        config, split_name, label_type, fs_profile)

    if reuse_existing and selector_path.exists() and preprocessor_path.exists():
        selector = joblib.load(selector_path)
        preprocessor = joblib.load(preprocessor_path)
        print(f"  Reusing saved preprocessing: {selector_path.name}, {preprocessor_path.name}")
    else:
        selector, preprocessor = _fit_preprocessing(X_train, y_train, config, fs_profile)
        # Analysis runs (HPO, XAI)
        if save_artifacts:
            selector_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(selector, selector_path)
            joblib.dump(preprocessor, preprocessor_path)

    X_train_t = preprocessor.transform(selector.transform(X_train))
    X_val_t = preprocessor.transform(selector.transform(X_val))
    X_test_t = preprocessor.transform(selector.transform(X_test))
    print(f"  Preprocessing ready. Output shape: {X_train_t.shape}")

    return {
        "X_train_t": X_train_t, "X_val_t": X_val_t, "X_test_t": X_test_t,
        "y_train": y_train, "y_val": y_val, "y_test": y_test,
        "selector": selector, "preprocessor": preprocessor,
        "fs_profile": fs_profile,
    }


def train_experiment(experiment: dict, config: dict, preprocessed_data: dict = None):

    exp_name = experiment["name"]
    model_name = experiment["model"]
    strategy = experiment.get("strategy")
    split_name = experiment["split"]
    label_type = experiment.get("label", "binary")
    fs_profile = get_fs_profile(experiment)

    print(f"\n{'='*60}")
    print(f"  {exp_name} | {model_name} | {strategy} | {split_name} | {label_type} | fs={fs_profile}")
    print(f"{'='*60}")

    if preprocessed_data is None:
        preprocessed_data = prepare_data(split_name, label_type, config, fs_profile)
        
    X_train_t = preprocessed_data["X_train_t"]
    X_val_t = preprocessed_data["X_val_t"]
    X_test_t = preprocessed_data["X_test_t"]
    y_train = preprocessed_data["y_train"]
    y_val = preprocessed_data["y_val"]
    y_test = preprocessed_data["y_test"]
    selector = preprocessed_data["selector"]
    preprocessor = preprocessed_data["preprocessor"]

    steps = [
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
    if strategy == "smote":
        X_train_t, y_train = apply_smote(X_train_t, y_train, config)
    elif strategy == "undersampling":
        X_train_t, y_train = apply_undersampling(X_train_t, y_train, config)
    elif strategy == "class_weight":
        print("  Using class_weight='balanced' (no resampling)")
    pbar.update(1)

    pbar.set_postfix_str(steps[1])
    class_weight = "balanced" if strategy == "class_weight" else None
    model = get_model(model_name, config, class_weight=class_weight)
    print(f"  Training {model_name}...")
    start = time.perf_counter()
    model.fit(X_train_t, y_train)
    train_time = time.perf_counter() - start
    model.training_time_s = train_time
    print(f"  Training complete in {train_time:.2f}s")
    pbar.update(1)

    pbar.set_postfix_str(steps[2])
    model_path = model_artifact_path(config, experiment)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    if model_name in TORCH_MODELS:
        import torch
        torch.save(model, model_path)
    else:
        joblib.dump(model, model_path)

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
