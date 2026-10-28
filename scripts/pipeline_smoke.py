"""
Pipeline smoke test (CI): the whole training path on a tiny synthetic dataset, on CPU.

    python scripts/pipeline_smoke.py                  # in a temporary directory, deleted afterwards
    python scripts/pipeline_smoke.py --keep DIR       # in DIR, kept for a look

Writes five day files shaped like CIC-IDS2017 (the 82 features + Label, with an "Attempted" row
that cleaning drops) and a config derived from configs/config.yaml with two small experiments
(RandomForest on the random split, XGBoost with Pearson selection on the temporal split). Then runs
prepare -> train -> evaluate, builds a bundle from the first experiment and loads it the way the
server does (hash and version checks, self-test), and predicts a few flows. Every path in the
config is relative, so all output stays in that directory; the project's data is never touched.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.flowmeter.schema import FEATURES
from src.pipeline_config import CONFIG_ENV

DATASET = "Smoke"
DAYS = {   # file -> (day, attack classes)
    "Benign-Monday.parquet": ("Monday", []),
    "Bruteforce-Tuesday.parquet": ("Tuesday", ["FTP-Patator", "SSH-Patator"]),
    "DoS-Wednesday.parquet": ("Wednesday", ["DoS Hulk"]),
    "Infiltration-Webattacks-Thursday.parquet": ("Thursday", ["Web Attack - Brute Force"]),
    "Portscan-DDos-Botnet-Friday.parquet": ("Friday", ["DDoS", "Portscan"]),
}
BENIGN_ROWS, ATTACK_ROWS = 1500, 300
EXPERIMENTS = [
    {"name": "EXP-01", "model": "random_forest", "strategy": "class_weight", "split": "random",
     "label": "multiclass", "params": {"n_estimators": 30, "n_jobs": 2}},
    {"name": "EXP-02", "model": "xgboost", "strategy": "undersampling", "split": "temporal",
     "label": "multiclass", "feature_selection": "pearson",
     "params": {"n_estimators": 30, "max_depth": 4, "n_jobs": 2, "device": "cpu"}},
]


def synthetic_days(out_dir: Path, seed: int = 0) -> None:
    """Each class is a cloud around its own centre, so the models have something to learn."""
    rng = np.random.default_rng(seed)
    classes = ["Benign"] + [c for _, attacks in DAYS.values() for c in attacks]
    centres = {c: rng.lognormal(3.0, 1.5, len(FEATURES)) for c in classes}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (_, attacks) in DAYS.items():
        frames = []
        for cls, n in [("Benign", BENIGN_ROWS)] + [(a, ATTACK_ROWS) for a in attacks]:
            df = pd.DataFrame(centres[cls] * rng.lognormal(0.0, 0.3, (n, len(FEATURES))), columns=FEATURES)
            df["Protocol"] = rng.choice([6.0, 17.0], n)
            df["Label"] = cls
            frames.append(df)
        day = pd.concat(frames, ignore_index=True)
        day.loc[0, "Label"] = "Attempted-relabel-as-Benign"      # dropped by drop_labels
        day.to_parquet(out_dir / name, index=False)


def smoke_config(work: Path) -> Path:
    with open(PROJECT_ROOT / "configs" / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    real = config["datasets"][config["active_dataset"]]
    config["active_dataset"] = DATASET
    config["datasets"] = {DATASET: {
        **real, "name": DATASET, "data_dir": f"dataset/{DATASET}",
        "day_mapping": {name: day for name, (day, _) in DAYS.items()},
        "files": list(DAYS),
    }}
    config["preprocessing"]["feature_selection_profiles"]["mi"]["sample_size"] = 2000
    config["open_set"]["anomaly_train_rows"] = 2000
    config["experiments"] = EXPERIMENTS
    path = work / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def run(work: Path) -> None:
    from scripts import build_bundle, evaluate_all, prepare_data, train_all
    from src.inference.bundle import load_bundle
    from src.inference.engine import InferenceEngine

    synthetic_days(work / "dataset" / DATASET)
    os.environ[CONFIG_ENV] = str(smoke_config(work))
    os.chdir(work)                                    # the config's output paths are relative

    prepare_data.main()
    train_all.main(exp_filter=None, force=True)
    evaluate_all.main(exp_filter=None)

    summary = pd.read_csv(work / "results" / "metrics" / "summary.csv")
    evaluated = set(summary["experiment"])
    missing = {e["name"] for e in EXPERIMENTS} - evaluated
    if missing:
        raise SystemExit(f"Not in results/metrics/summary.csv: {sorted(missing)}")

    built = build_bundle.main("EXP-01", str(work / "model_store"), 2)
    bundle = load_bundle(built.path)                  # as the server loads it: hashes, versions, self-test
    flows = pd.read_parquet(work / "dataset" / DATASET / "Portscan-DDos-Botnet-Friday.parquet").sample(
        200, random_state=0)
    result = InferenceEngine(bundle).predict(flows)
    agree = (result["class_name"].to_numpy() == flows["Label"].to_numpy()).mean()
    print(f"\nBundle {bundle.bundle_id}: {len(result)} flows predicted, class agreement {agree:.1%}")
    print(result["decision"].value_counts().to_string())
    if agree < 0.9:
        raise SystemExit(f"Predictions agree with the labels on only {agree:.1%} of easy synthetic flows")


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--keep", type=Path, help="Work in this directory and keep it")
    args = parser.parse_args()
    start = time.perf_counter()
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
        run(args.keep.resolve())
    else:
        work = Path(tempfile.mkdtemp(prefix="ids-smoke-"))
        try:
            run(work)
        finally:
            os.chdir(PROJECT_ROOT)
            shutil.rmtree(work, ignore_errors=True)
    print(f"\nPipeline smoke test passed in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
