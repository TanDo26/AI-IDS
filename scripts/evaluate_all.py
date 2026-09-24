"""
Evaluates all trained models and generates comparison report.
"""
import sys
import time
import json
from pathlib import Path

import joblib
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import load_split
from src.preprocessing.feature_selection import FeatureSelector
from src.evaluation.evaluate import evaluate_experiment
from src.evaluation.plots import plot_confusion_matrix, plot_pr_curve


def main():
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    experiments = config["experiments"]

    print("=" * 70)
    print("  AI-IDS MODEL EVALUATION".center(70))
    print("=" * 70)

    ds_name = config["active_dataset"]
    mapping_path = Path(config["datasets"][ds_name]["data_dir"]) / "label_mapping.json"
    class_names = None
    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping_data = json.load(f)
            class_names = mapping_data.get("int_to_label")

    all_metrics = []
    start = time.perf_counter()

    for experiment in experiments:
        exp_name = experiment["name"]
        model_name = experiment["model"]
        split_name = experiment["split"]
        label_type = experiment.get("label", "binary")

        preproc_dir = Path(config["output"]["preprocessors_dir"])
        selector = joblib.load(preproc_dir / f"{split_name}_feature_selector.pkl")
        preprocessor = joblib.load(preproc_dir / f"{split_name}_preprocessor.pkl")

        _, _, X_test, _, _, y_test = load_split(split_name, label_type, config)
        
        X_test = selector.transform(X_test)
        X_test_t = preprocessor.transform(X_test)

        model_path = (Path(config["output"]["models_dir"]) / split_name /
                      f"{exp_name}_{model_name}.pkl")
        model = joblib.load(model_path)

        metrics, y_pred, y_prob = evaluate_experiment(
            model, X_test_t, y_test, experiment, split_name
        )
        all_metrics.append(metrics)

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
        else:
            print(f"  {exp_name} ({split_name}|{label_type}) | "
                  f"Accuracy={metrics['accuracy']:.4f} | "
                  f"Macro-F1={metrics['macro_f1']:.4f} | "
                  f"Weighted-F1={metrics['weighted_f1']:.4f} | "
                  f"Macro-Recall={metrics['macro_recall']:.4f}")

    metrics_dir = Path(config["output"]["metrics_dir"])
    metrics_dir.mkdir(parents=True, exist_ok=True)
    df_metrics = pd.DataFrame(all_metrics)

    col_order = [
        "experiment", "model", "strategy", "split", "label",
        "f1_attack", "recall_attack", "fpr", "fnr", "macro_f1", "pr_auc",
        "accuracy", "precision_attack",
        "weighted_f1", "macro_recall", "weighted_recall", "macro_precision", "weighted_precision", "macro_pr_auc", "num_classes",
        "tp", "fp", "tn", "fn", "inference_time_s",
    ]
    col_order = [c for c in col_order if c in df_metrics.columns]
    df_metrics = df_metrics[col_order]
    df_metrics.to_csv(metrics_dir / "summary.csv", index=False)

    elapsed = time.perf_counter() - start
    print(f"\n{'='*70}")
    print(f"  Evaluation complete in {elapsed:.1f}s")
    print(f"  Results saved to {metrics_dir / 'summary.csv'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()