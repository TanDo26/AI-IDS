"""
Write a sample upload: real flows from a split's test set, as a CSV the web app accepts.

The rows keep the training feature names and add made-up endpoints (Src/Dst IP and port,
Timestamp), so the results page has metadata to show. Like real traffic, the file has no Label
column; the classes it holds are printed. Used by the browser smoke test (web/e2e/) and for demos.

    python scripts/make_sample_upload.py                          # -> web/e2e/data/flows.csv
    python scripts/make_sample_upload.py --benign 5000 --per-attack 300 --out sample.csv
"""
import sys
import json
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline_config import config_path
from src.training.train import load_split


def main(split, n_benign, per_attack, seed, out):
    with open(config_path(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    ds_cfg = config["datasets"][config["active_dataset"]]
    with open(Path(ds_cfg["data_dir"]) / "label_mapping.json", "r", encoding="utf-8") as f:
        mapping = json.load(f)
    benign = mapping["label_to_int"][ds_cfg["label_mapping"]["benign_label"]]

    *_, X_test, _, _, y_test = load_split(split, "multiclass", config)
    rng = np.random.default_rng(seed)
    picked = []
    for cls, idx in y_test.groupby(y_test).groups.items():
        n = n_benign if cls == benign else per_attack
        picked.extend(rng.choice(np.asarray(idx), size=min(n, len(idx)), replace=False))
    picked = rng.permutation(picked)

    df = X_test.loc[picked].reset_index(drop=True)
    n = len(df)
    seconds = rng.integers(0, 8 * 3600, n)
    df.insert(0, "Src IP", [f"192.168.10.{i}" for i in rng.integers(2, 250, n)])
    df.insert(1, "Src Port", rng.integers(1024, 65535, n))
    df.insert(2, "Dst IP", [f"205.174.165.{i}" for i in rng.integers(2, 250, n)])
    df.insert(3, "Dst Port", rng.choice([21, 22, 80, 443, 8080], n))
    df.insert(4, "Timestamp", [f"05/07/2017 {9 + s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}" for s in seconds])

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"  {n:,} flows -> {out}")
    for label, count in Counter(mapping["int_to_label"][str(int(c))] for c in y_test.loc[picked]).most_common():
        print(f"    {count:>6,}  {label}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write real test-split flows as an upload CSV")
    parser.add_argument("--split", default="random", choices=["random", "temporal"])
    parser.add_argument("--benign", type=int, default=1500, help="Benign flows (default 1500)")
    parser.add_argument("--per-attack", type=int, default=100,
                        help="Flows per attack type, fewer when the test set has fewer (default 100)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "web" / "e2e" / "data" / "flows.csv")
    args = parser.parse_args()
    main(args.split, args.benign, args.per_attack, args.seed, args.out)
