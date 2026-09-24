from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split


def _get_feature_columns(config):
    ds_cfg = config["datasets"][config["active_dataset"]]
    features = ds_cfg["features"]

    return (features.get("numeric", []) + features.get("categorical", []))


def _get_meta_columns(config):
    ds_cfg = config["datasets"][config["active_dataset"]]

    return [ds_cfg["target_column"], "BinaryLabel", "MulticlassLabel", "OriginalLabel", "_source_file"]


LABEL_COLUMNS = ["BinaryLabel", "MulticlassLabel"]


def random_split(df, config):
    split_cfg = config["splitting"]["random"]
    seed = config["splitting"]["random_state"]

    feature_cols = _get_feature_columns(config)

    X = df[feature_cols].copy()
    y = df[LABEL_COLUMNS].copy()

    stratify_col = df["OriginalLabel"]

    X_train, X_temp, y_train, y_temp, s_train, s_temp = (
        train_test_split(
            X,
            y,
            stratify_col,
            train_size=split_cfg["train_size"],
            stratify=stratify_col,
            random_state=seed,
        )
    )

    val_size = split_cfg["validation_size"]
    test_size = split_cfg["test_size"]

    test_ratio = test_size / (val_size + test_size)

    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=test_ratio,
        stratify=s_temp,
        random_state=seed,
    )

    return (
        X_train.reset_index(drop=True),
        X_val.reset_index(drop=True),
        X_test.reset_index(drop=True),
        y_train.reset_index(drop=True),
        y_val.reset_index(drop=True),
        y_test.reset_index(drop=True),
    )


def temporal_split(df, config):

    ds_cfg = config["datasets"][config["active_dataset"]]

    day_map = ds_cfg["day_mapping"]
    temp_cfg = ds_cfg["temporal_split"]

    seed = config["splitting"]["random_state"]

    feature_cols = _get_feature_columns(config)

    df = df.copy()
    df["_day"] = df["_source_file"].map(day_map)

    train_days = temp_cfg["train_days"]
    test_days = temp_cfg["test_days"]

    df_train_full = df[df["_day"].isin(train_days)]
    df_test = df[df["_day"].isin(test_days)]

    X_test = df_test[feature_cols].reset_index(drop=True)
    y_test = df_test[LABEL_COLUMNS].reset_index(drop=True)

    val_frac = temp_cfg["val_fraction_from_train"]

    X_train_full = df_train_full[feature_cols]
    y_train_full = df_train_full[LABEL_COLUMNS]

    stratify_col = df_train_full["BinaryLabel"]

    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full,
        y_train_full,
        test_size=val_frac,
        stratify=stratify_col,
        random_state=seed,
    )

    return (
        X_train.reset_index(drop=True),
        X_val.reset_index(drop=True),
        X_test.reset_index(drop=True),
        y_train.reset_index(drop=True),
        y_val.reset_index(drop=True),
        y_test.reset_index(drop=True),
    )


def save_split(X_train, X_val, X_test, y_train, y_val, y_test, split_name, config):

    ds_name = config["active_dataset"]

    out_dir = Path(config["output"]["splits_dir"].format(dataset_name=ds_name))

    split_dir = out_dir / split_name
    split_dir.mkdir(parents=True, exist_ok=True)

    X_train.to_parquet(split_dir / "X_train.parquet", index=False)

    X_val.to_parquet(split_dir / "X_val.parquet", index=False)

    X_test.to_parquet(split_dir / "X_test.parquet", index=False)

    y_train.to_parquet(split_dir / "y_train.parquet", index=False)

    y_val.to_parquet(split_dir / "y_val.parquet", index=False)

    y_test.to_parquet(split_dir / "y_test.parquet", index=False)