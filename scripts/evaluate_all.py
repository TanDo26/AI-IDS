"""
Evaluates all trained models and generates comparison report.
"""
import sys
import time
import json
import argparse
from pathlib import Path

import joblib
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline_config import config_path
from src.training.train import load_split
from src.preprocessing.artifacts import get_fs_profile, preprocessing_artifact_paths
from src.evaluation.evaluate import (PER_CLASS_COLUMNS, THRESHOLD_COLUMNS, evaluate_experiment,
                                     evaluate_thresholds, per_class_counts)
from src.evaluation.plots import plot_confusion_matrix, plot_pr_curve
from scripts.train_all import parse_exp_filter, filter_experiments

DEFAULT_THRESHOLD_FPRS = [0.001, 0.01]


def merge_existing(path: Path, df_new: pd.DataFrame, experiments, exp_filter) -> pd.DataFrame:
    """With a filter, keep the other experiments' rows of an existing file instead of overwriting it."""
    if exp_filter is None or not path.exists():
        return df_new
    df_existing = pd.read_csv(path)
    df_existing = df_existing[~df_existing["experiment"].isin({e["name"] for e in experiments})]
    return pd.concat([df_existing, df_new], ignore_index=True)


def test_classes(config: dict, split_name: str):
    """The test rows' original classes (MulticlassLabel), whatever label the experiment uses."""
    split_dir = Path(config["output"]["splits_dir"].format(dataset_name=config["active_dataset"])) / split_name
    return pd.read_parquet(split_dir / "y_test.parquet", columns=["MulticlassLabel"])["MulticlassLabel"].to_numpy()


def main(exp_filter=None):
    with open(config_path(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    experiments = filter_experiments(config["experiments"], exp_filter)

    if not experiments:
        print("  No experiments matched the filter. Nothing to evaluate.")
        return

    print("=" * 70)
    print("  AI-IDS MODEL EVALUATION".center(70))
    print("=" * 70)
    exp_names = ", ".join(e["name"] for e in experiments)
    print(f"  Experiments ({len(experiments)}): {exp_names}")

    ds_name = config["active_dataset"]
    mapping_path = Path(config["datasets"][ds_name]["data_dir"]) / "label_mapping.json"
    if not mapping_path.exists():
        raise FileNotFoundError(f"{mapping_path} is missing: run scripts/prepare_data.py first.")
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping_data = json.load(f)
    class_names = mapping_data["int_to_label"]
    benign_class = mapping_data["label_to_int"][config["datasets"][ds_name]["label_mapping"]["benign_label"]]
    classes_by_split = {}

    target_fprs = config.get("evaluation", {}).get("threshold_fprs", DEFAULT_THRESHOLD_FPRS)

    all_metrics = []
    threshold_rows = []
    per_class_rows = []
    start = time.perf_counter()

    for experiment in experiments:
        exp_name = experiment["name"]
        model_name = experiment["model"]
        split_name = experiment["split"]
        label_type = experiment.get("label", "binary")
        fs_profile = get_fs_profile(experiment)

        selector_path, preprocessor_path = preprocessing_artifact_paths(
            config, split_name, label_type, fs_profile)
        if not selector_path.exists() or not preprocessor_path.exists():
            raise FileNotFoundError(
                f"{exp_name}: missing preprocessing artifacts {selector_path.name} / "
                f"{preprocessor_path.name}. Train the experiment first."
            )
        selector = joblib.load(selector_path)
        preprocessor = joblib.load(preprocessor_path)

        _, X_val, X_test, _, y_val, y_test = load_split(split_name, label_type, config)

        X_test = selector.transform(X_test)
        X_test_t = preprocessor.transform(X_test)

        if model_name in ("mlp", "lstm"):
            import torch
            model_path = (Path(config["output"]["models_dir"]) / split_name /
                          f"{exp_name}_{model_name}.pt")
            model = torch.load(model_path, weights_only=False)
        else:
            model_path = (Path(config["output"]["models_dir"]) / split_name /
                          f"{exp_name}_{model_name}.pkl")
            model = joblib.load(model_path)

        metrics, y_pred, y_prob = evaluate_experiment(
            model, X_test_t, y_test, experiment, split_name
        )
        all_metrics.append(metrics)
        if split_name not in classes_by_split:
            classes_by_split[split_name] = test_classes(config, split_name)
        classes = classes_by_split[split_name]

        plot_confusion_matrix(
            y_test, y_pred, exp_name, split_name,
            config["output"]["confusion_dir"],
            label_type=label_type, class_names=class_names
        )
        plot_pr_curve(
            y_test, y_prob, exp_name, split_name,
            config["output"]["pr_curves_dir"],
            label_type=label_type
        )

        if label_type == "binary":
            print(f"  {exp_name} ({split_name}|{label_type}) | "
                  f"F1={metrics['f1_attack']:.4f} | "
                  f"Recall={metrics['recall_attack']:.4f} | "
                  f"FPR={metrics['fpr']:.4f} | "
                  f"Macro-F1={metrics['macro_f1']:.4f} | "
                  f"PR-AUC={metrics.get('pr_auc', 'N/A')}")

            X_val_t = preprocessor.transform(selector.transform(X_val))
            rows, predictions = evaluate_thresholds(model, X_val_t, y_val, y_test, y_prob, experiment,
                                                    split_name, target_fprs)
            threshold_rows.extend(rows)
            for rule, predicted in predictions.items():
                per_class_rows.extend(per_class_counts(classes, predicted, experiment, split_name, rule,
                                                       class_names, benign_class))
            for row in rows[1:]:
                print(f"    {row['rule']:>12}: threshold={row['threshold']:.6g} | "
                      f"Recall={row['recall_attack']:.4f} | FPR={row['fpr']:.4f} | "
                      f"F1={row['f1_attack']:.4f}")
        else:
            print(f"  {exp_name} ({split_name}|{label_type}) | "
                  f"Accuracy={metrics['accuracy']:.4f} | "
                  f"Macro-F1={metrics['macro_f1']:.4f} | "
                  f"Weighted-F1={metrics['weighted_f1']:.4f} | "
                  f"Macro-Recall={metrics['macro_recall']:.4f}")
            per_class_rows.extend(per_class_counts(classes, y_pred, experiment, split_name, "argmax",
                                                   class_names, benign_class))

    metrics_dir = Path(config["output"]["metrics_dir"])
    metrics_dir.mkdir(parents=True, exist_ok=True)

    summary_path = metrics_dir / "summary.csv"
    df_metrics = merge_existing(summary_path, pd.DataFrame(all_metrics), experiments, exp_filter)

    # Rows written before feature-selection profiles existed used the base filters only
    df_metrics["feature_selection"] = df_metrics["feature_selection"].fillna("none")

    col_order = [
        "experiment", "model", "strategy", "split", "label", "feature_selection",
        "f1_attack", "recall_attack", "fpr", "fnr", "macro_f1", "pr_auc",
        "accuracy", "precision_attack",
        "weighted_f1", "macro_recall", "weighted_recall", "macro_precision", "weighted_precision", "macro_pr_auc", "num_classes",
        "tp", "fp", "tn", "fn", "training_time_s",
    ]
    col_order = [c for c in col_order if c in df_metrics.columns]
    df_metrics = df_metrics[col_order]
    df_metrics.to_csv(summary_path, index=False)

    # Binary experiments only: test results at 0.5 and at thresholds picked on validation Benign rows
    thresholds_path = metrics_dir / "thresholds.csv"
    df_thresholds = merge_existing(thresholds_path, pd.DataFrame(threshold_rows), experiments, exp_filter)
    if not df_thresholds.empty:
        df_thresholds = df_thresholds[
            ["experiment", "model", "strategy", "split", "feature_selection", "rule", "target_fpr",
             "threshold", "val_benign", "val_fpr", *THRESHOLD_COLUMNS]]
        df_thresholds.to_csv(thresholds_path, index=False)

    # Every experiment, per original class: binary at each threshold above, multiclass at argmax
    per_class_path = metrics_dir / "per_class.csv"
    df_per_class = merge_existing(per_class_path, pd.DataFrame(per_class_rows), experiments, exp_filter)
    df_per_class[PER_CLASS_COLUMNS].to_csv(per_class_path, index=False)

    elapsed = time.perf_counter() - start
    print(f"\n{'='*70}")
    print(f"  Evaluation complete in {elapsed:.1f}s")
    print(f"  Results saved to {summary_path}")
    if not df_thresholds.empty:
        print(f"  Thresholds saved to {thresholds_path}")
    print(f"  Per-class counts saved to {per_class_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate AI-IDS experiments")
    parser.add_argument(
        "--exp", "-e",
        type=str, default=".",
        help="Experiment filter: '.' for all, '15' for EXP-15, '10-13' for range, '5,8,12' for list"
    )
    args = parser.parse_args()
    exp_filter = parse_exp_filter(args.exp)
    main(exp_filter=exp_filter)