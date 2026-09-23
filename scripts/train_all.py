"""
Trains all experiments across all split strategies.
"""
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import train_experiment


def main():
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    experiments = config["experiments"]
    split_strategies = config["splitting"]["strategies"]

    print("=" * 70)
    print("  AI-IDS MODEL TRAINING".center(70))
    print("=" * 70)
    print(f"  Experiments: {len(experiments)}")
    print(f"  Splits: {split_strategies}")
    print(f"  Total runs: {len(experiments) * len(split_strategies)}")

    all_results = []
    start = time.perf_counter()

    for split_name in split_strategies:
        for experiment in experiments:
            result = train_experiment(experiment, split_name, config)
            all_results.append({
                "experiment": experiment["name"],
                "split": split_name,
                "train_time": result["train_time"],
            })

    elapsed = time.perf_counter() - start
    print(f"\n{'='*70}")
    print(f"  All training complete in {elapsed:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()