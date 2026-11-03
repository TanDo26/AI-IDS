import json
import numpy as np
import pandas as pd
from pathlib import Path

CONFLICTING_LABELS = ("drop", "first")


def _drop_duplicates(df: pd.DataFrame, feature_columns: list, target_column: str,
                     conflicting_labels: str) -> pd.DataFrame:
    """
    A row is a duplicate when its features repeat an earlier row's, whatever day (file) either came
    from: rows are compared on the features alone, as the models see them. The first copy is kept,
    i.e. the one from the earliest file. A feature vector recorded under more than one label is
    dropped entirely ("drop"; one input can't be taught two answers) or kept with its first label ("first").
    """
    if conflicting_labels not in CONFLICTING_LABELS:
        raise ValueError(f"conflicting_labels must be one of {CONFLICTING_LABELS}, not {conflicting_labels!r}")

    copies = df.loc[df.duplicated(subset=feature_columns, keep=False)]
    conflicting = copies.groupby(feature_columns, sort=False)[target_column].transform("nunique") > 1

    if conflicting.any():
        label_sets = (copies.loc[conflicting]
                      .groupby(feature_columns, sort=False)[target_column]
                      .agg(lambda labels: " / ".join(sorted(set(labels)))))
        verb = "Dropped" if conflicting_labels == "drop" else "Kept the first label of"
        print(f"  {verb} {int(conflicting.sum()):,} rows of {len(label_sets):,} feature vectors "
              f"recorded under more than one label:")
        for labels, n in label_sets.value_counts().items():
            print(f"    {labels}: {n:,}")
        if conflicting_labels == "drop":
            df = df.drop(index=copies.index[conflicting])
            copies = copies.loc[~conflicting]

    duplicate = copies.duplicated(subset=feature_columns)
    other_day = ""
    if "_source_file" in copies.columns:
        first_file = copies.groupby(feature_columns, sort=False)["_source_file"].transform("first")
        n = int((first_file[duplicate] != copies.loc[duplicate, "_source_file"]).sum())
        other_day = f"; {n:,} repeat a row from another file"
    df = df.drop(index=copies.index[duplicate])
    print(f"  Dropped {int(duplicate.sum()):,} duplicate rows (same features as an earlier row{other_day})")

    return df.copy()


def clean_dataset(df: pd.DataFrame, config: dict) -> pd.DataFrame:

    dataset_name = config["active_dataset"]
    dataset_config = config["datasets"][dataset_name]

    target_column = dataset_config["target_column"]

    df = df.copy()

    initial_rows = len(df)

    print("=" * 70)
    print("Data Cleaning")
    print("=" * 70)

    drop_patterns = dataset_config.get("drop_labels", [])

    for pattern in drop_patterns:
        mask = (
            df[target_column]
            .astype(str)
            .str.contains(
                pattern,
                case=False,
                na=False
            )
        )

        dropped_rows = int(mask.sum())

        df = df.loc[~mask].copy()

        print(f"Dropped {dropped_rows:,} rows matching '{pattern}'")

    numeric_columns = df.select_dtypes(include="number").columns

    inf_count = int(np.isinf(df[numeric_columns]).sum().sum())

    if len(numeric_columns) > 0:
        df.loc[:, numeric_columns] = (df[numeric_columns].replace([np.inf, -np.inf], np.nan))

    print(f"  Replaced {inf_count:,} Inf values with NaN")


    nan_rows = int(df.isnull().any(axis=1).sum())

    df = df.dropna().copy()

    print(f"  Dropped {nan_rows:,} rows containing NaN")

    features = dataset_config["features"]
    feature_columns = features.get("numeric", []) + features.get("categorical", [])

    df = _drop_duplicates(df, feature_columns, target_column, dataset_config.get("conflicting_labels", "drop"))


    df["OriginalLabel"] = df[target_column].copy()

    label_mapping = dataset_config["label_mapping"]
    benign_label = label_mapping["benign_label"]

    df["BinaryLabel"] = (df[target_column] != benign_label).astype(int)

    unique_labels = sorted(df["OriginalLabel"].unique())
    label_to_int = {label: idx for idx, label in enumerate(unique_labels)}
    df["MulticlassLabel"] = df["OriginalLabel"].map(label_to_int)

    ds_name = config["active_dataset"]
    mapping_path = Path(config["datasets"][ds_name]["data_dir"]) / "label_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump({
            "label_to_int": label_to_int,
            "int_to_label": {str(v): k for k, v in label_to_int.items()},
            "num_classes": len(unique_labels),
        }, f, indent=2)

    final_rows = len(df)
    removed_rows = initial_rows - final_rows

    benign_count = int((df["BinaryLabel"] == 0).sum())

    attack_count = int((df["BinaryLabel"] == 1).sum())

    print("\n" + "=" * 70)
    print("Cleaning Summary")
    print("=" * 70)

    print(f"  Initial rows : {initial_rows:,}")

    print(f"  Final rows   : {final_rows:,}")

    print(f"  Removed      : {removed_rows:,}")

    print("\n  Binary class distribution:")

    print(f"    Benign (0): {benign_count:,}")

    print(f"    Attack (1): {attack_count:,}")

    print("\n  Original label distribution:")
    print(df["OriginalLabel"].value_counts().to_string())

    print(f"\n  Multiclass: {len(label_to_int)} classes")
    for label, idx in sorted(label_to_int.items(), key=lambda x: x[1]):
        count = int((df["MulticlassLabel"] == idx).sum())
        print(f"    {idx}: {label} ({count:,})")

    print(f"\n  Label mapping saved to {mapping_path}")


    assert set(df["BinaryLabel"].unique()).issubset({0, 1}), "BinaryLabel must contain only 0 and 1."

    assert not df["MulticlassLabel"].isnull().any(), "MulticlassLabel contains null values."

    assert not df["OriginalLabel"].astype(str).str.contains(
        "Attempted",
        case=False,
        na=False
    ).any(), "Excluded 'Attempted' labels remain."

    assert not df.isnull().any().any(), ("Cleaned dataset still contains NaN values.")

    numeric_columns = df.select_dtypes(include="number").columns

    assert not np.isinf(
        df[numeric_columns].to_numpy()
    ).any(), (
        "Cleaned dataset still contains Inf values."
    )

    return df.reset_index(drop=True)