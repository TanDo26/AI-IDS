"""
Loads CIC-IDS2017, cleans data, performs both splits, saves to disk.
"""
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.load_data import load_dataset
from src.data.clean_data import clean_dataset
from src.data.split_data import random_split, temporal_split, save_split


def main():
    start = time.perf_counter()

    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print("=" * 70)
    print("  AI-IDS DATA PREPARATION".center(70))
    print("=" * 70)

    print("\n[Step 1/4] Loading dataset...")
    df = load_dataset(config)

    print("\n[Step 2/4] Cleaning dataset...")
    df = clean_dataset(df, config)

    print("\n[Step 3/4] Random stratified split (70/15/15)...")
    X_tr, X_v, X_te, y_tr, y_v, y_te = random_split(df, config)
    save_split(X_tr, X_v, X_te, y_tr, y_v, y_te, "random", config)
    print(f"  Train: {len(X_tr):,} | Val: {len(X_v):,} | Test: {len(X_te):,}")

    print("\n[Step 4/4] Temporal split (Mon-Wed / Thu-Fri)...")
    X_tr, X_v, X_te, y_tr, y_v, y_te = temporal_split(df, config)
    save_split(X_tr, X_v, X_te, y_tr, y_v, y_te, "temporal", config)
    print(f"  Train: {len(X_tr):,} | Val: {len(X_v):,} | Test: {len(X_te):,}")

    elapsed = time.perf_counter() - start
    print(f"\n{'='*70}")
    print(f"  Data preparation complete in {elapsed:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()