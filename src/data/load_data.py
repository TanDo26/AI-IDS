from pathlib import Path

import pandas as pd

def load_dataset(config):
    dataset_name = config['active_dataset']
    dataset_config = config['datasets'][dataset_name]

    data_dir = Path(dataset_config["data_dir"])
    file_format = dataset_config["file_format"]
    filenames = dataset_config["files"]

    dataframes = []

    print("=" * 70)
    print(f"Loading dataset: {dataset_name}")
    print(f"Data directory: {data_dir}")
    print(f"File format: {file_format}")
    print("=" * 70)

    for filename in filenames:
        filepath = data_dir / filename

        if not filepath.exists():
            raise FileNotFoundError("Data file not found!")

        if file_format == "parquet":
            df = pd.read_parquet(filepath)

        elif file_format == "csv":
            df = pd.read_csv(filepath, low_memory=False)

        else:
            raise ValueError(f"Unsupported file format: {file_format}")

        df["_source_file"] = filename

        print(f"Loaded {filename}: {len(df):,} rows × {len(df.columns):,} columns")

        dataframes.append(df)

    if not dataframes:
        raise ValueError(f"No data files configured for dataset '{dataset_name}'.")

    combined = pd.concat(dataframes, ignore_index=True)

    print("\n" + "=" * 70)
    print("Combined dataset")
    print("=" * 70)

    print(
        f"Shape: "
        f"{combined.shape[0]:,} rows × "
        f"{combined.shape[1]:,} columns"
    )

    print("\nData types:")
    print(combined.dtypes)

    print("\nRows by source file:")
    print(
        combined["_source_file"]
        .value_counts()
        .sort_index()
    )

    return combined

