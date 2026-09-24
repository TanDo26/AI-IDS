"""
Trains all experiments as defined in config.yaml.
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

    print("=" * 70)
    print("  AI-IDS MODEL TRAINING".center(70))
    print("=" * 70)
    print(f"  Total experiments: {len(experiments)}")

    all_results = []
    start = time.perf_counter()

    for experiment in experiments:
        result = train_experiment(experiment, config)
        all_results.append({
            "experiment": experiment["name"],
            "split": experiment["split"],
            "label": experiment.get("label", "binary"),
            "train_time": result["train_time"],
        })

    elapsed = time.perf_counter() - start
    print(f"\n{'='*70}")
    print(f"  All training complete in {elapsed:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()