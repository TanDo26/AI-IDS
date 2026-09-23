"""
Runs the full AI-IDS pipeline: prepare → train → evaluate.
"""
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_data import main as prepare
from scripts.train_all import main as train
from scripts.evaluate_all import main as evaluate


def main():
    start = time.perf_counter()

    print("=" * 70)
    print("  AI-IDS FULL PIPELINE".center(70))
    print("=" * 70)

    print("\n" + "=" * 70)
    print("  PHASE 1: DATA PREPARATION".center(70))
    print("=" * 70)
    prepare()

    print("\n" + "=" * 70)
    print("  PHASE 2: MODEL TRAINING".center(70))
    print("=" * 70)
    train()

    print("\n" + "=" * 70)
    print("  PHASE 3: EVALUATION".center(70))
    print("=" * 70)
    evaluate()

    elapsed = time.perf_counter() - start
    print("\n" + "=" * 70)
    print(f"  FULL PIPELINE COMPLETE in {elapsed:.1f}s".center(70))
    print("=" * 70)


if __name__ == "__main__":
    main()
