"""
Runs the full AI-IDS pipeline: prepare → train → evaluate.
"""
import sys
import time
import argparse
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_data import main as prepare
from scripts.train_all import main as train, parse_exp_filter
from scripts.evaluate_all import main as evaluate


def main():
    parser = argparse.ArgumentParser(description="Run the full AI-IDS pipeline")
    parser.add_argument(
        "--exp", "-e",
        type=str, default=".",
        help="Experiment filter: '.' for all, '15' for EXP-15, '10-13' for range, '5,8,12' for list"
    )
    parser.add_argument(
        "--skip-prepare", action="store_true",
        help="Skip data preparation phase (useful when data is already prepared)"
    )
    args = parser.parse_args()
    exp_filter = parse_exp_filter(args.exp)

    start = time.perf_counter()

    print("=" * 70)
    print("  AI-IDS FULL PIPELINE".center(70))
    print("=" * 70)
    if exp_filter:
        print(f"  Filter: {', '.join(sorted(exp_filter))}")

    if not args.skip_prepare:
        print("\n" + "=" * 70)
        print("  PHASE 1: DATA PREPARATION".center(70))
        print("=" * 70)
        prepare()
    else:
        print("\n  [Skipping data preparation]")

    print("\n" + "=" * 70)
    print("  PHASE 2: MODEL TRAINING".center(70))
    print("=" * 70)
    train(exp_filter=exp_filter)

    print("\n" + "=" * 70)
    print("  PHASE 3: EVALUATION".center(70))
    print("=" * 70)
    evaluate(exp_filter=exp_filter)

    elapsed = time.perf_counter() - start
    print("\n" + "=" * 70)
    print(f"  FULL PIPELINE COMPLETE in {elapsed:.1f}s".center(70))
    print("=" * 70)


if __name__ == "__main__":
    main()
