import numpy as np
import pandas as pd


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

    duplicate_rows = int(df.duplicated().sum())

    df = df.drop_duplicates().copy()

    print(f"  Dropped {duplicate_rows:,} duplicate rows")


    df["OriginalLabel"] = df[target_column].copy()

    label_mapping = dataset_config["label_mapping"]

    benign_label = label_mapping["benign_label"]

    df["BinaryLabel"] = (df[target_column] != benign_label).astype(int)

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


    assert set(df["BinaryLabel"].unique()).issubset({0, 1}), "BinaryLabel must contain only 0 and 1."

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