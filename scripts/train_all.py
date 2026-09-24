"""
Trains all experiments as defined in config.yaml.
"""
import sys
import time
import argparse
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import train_experiment


def parse_exp_filter(exp_str):
    if exp_str is None or exp_str.strip() == ".":
        return None

    names = set()
    for part in exp_str.split(","):
        part = part.strip()
        if "-" in part and not part.startswith("-"):
            # Range: e.g. "10-13"
            start_s, end_s = part.split("-", 1)
            for i in range(int(start_s), int(end_s) + 1):
                names.add(f"EXP-{i:02d}")
        else:
            names.add(f"EXP-{int(part):02d}")
    return names


def filter_experiments(experiments, exp_filter):
    if exp_filter is None:
        return experiments
    return [e for e in experiments if e["name"] in exp_filter]


def main(exp_filter=None):
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    experiments = filter_experiments(config["experiments"], exp_filter)

    if not experiments:
        print("  No experiments matched the filter. Nothing to train.")
        return

    print("=" * 70)
    print("  AI-IDS MODEL TRAINING".center(70))
    print("=" * 70)
    exp_names = ", ".join(e["name"] for e in experiments)
    print(f"  Experiments ({len(experiments)}): {exp_names}")

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
    parser = argparse.ArgumentParser(description="Train AI-IDS experiments")
    parser.add_argument(
        "--exp", "-e",
        type=str, default=".",
        help="Experiment filter: '.' for all, '15' for EXP-15, '10-13' for range, '5,8,12' for list"
    )
    args = parser.parse_args()
    exp_filter = parse_exp_filter(args.exp)
    main(exp_filter=exp_filter)