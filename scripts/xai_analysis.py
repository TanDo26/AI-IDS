"""
Explainable AI (XAI) analysis using SHAP.
Supports: random_forest, random_forest_regularized, logistic_regression.
Generates: summary plot, bar plot, top-N feature table (CSV + console).
"""

import sys
import argparse
from pathlib import Path

import yaml
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import prepare_data
from src.preprocessing.artifacts import get_fs_profile
from src.models.label_encoded import LabelEncodedClassifier

try:
    import shap
except ImportError:
    print("Vui lòng cài đặt thư viện 'shap': pip install shap")
    sys.exit(1)


def load_model(exp_name, model_type, split_name, config):
    """Load a trained sklearn model (.pkl) from the models directory."""
    if model_type in ("mlp", "lstm"):
        print(f"⚠ PyTorch models ({model_type}) hiện dùng KernelExplainer (chậm hơn).")
        import torch
        model_path = (
            PROJECT_ROOT / config["output"]["models_dir"] / split_name
            / f"{exp_name}_{model_type}.pt"
        )
        if not model_path.exists():
            raise FileNotFoundError(f"Không tìm thấy model: {model_path}")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.load(model_path, map_location=device, weights_only=False)
    else:
        model_path = (
            PROJECT_ROOT / config["output"]["models_dir"] / split_name
            / f"{exp_name}_{model_type}.pkl"
        )
        if not model_path.exists():
            raise FileNotFoundError(f"Không tìm thấy model: {model_path}")
        return joblib.load(model_path)


def _per_class_outputs(shap_values, label_type):
    """Binary -> SHAP values of the Attack class; multiclass -> list of (n_samples, n_features), one per class."""
    if label_type == "binary":
        if isinstance(shap_values, list):
            return shap_values[1]  # Attack class
        elif hasattr(shap_values, "shape") and len(shap_values.shape) == 3:
            return shap_values[:, :, 1]
        return shap_values
    if hasattr(shap_values, "shape") and len(shap_values.shape) == 3:
        # Convert (n_samples, n_features, n_classes) to list of (n_samples, n_features)
        return [shap_values[:, :, i] for i in range(shap_values.shape[2])]
    return shap_values


def compute_shap_values(model, model_type, X_sample, label_type):
    """Compute SHAP values using the appropriate explainer for the model type."""
    if model_type in ("random_forest", "random_forest_regularized", "xgboost"):
        # XGBoost is wrapped in LabelEncodedClassifier; explain the fitted booster inside.
        # (Not getattr(model, "estimator_"): RandomForest's estimator_ is its unfitted template tree.)
        if isinstance(model, LabelEncodedClassifier):
            model = model.estimator_
        explainer = shap.TreeExplainer(model)
        return _per_class_outputs(explainer.shap_values(X_sample), label_type)

    elif model_type == "logistic_regression":
        explainer = shap.LinearExplainer(model, X_sample)
        return explainer.shap_values(X_sample)

    else:
        # Model-agnostic (Naive Bayes, MLP, LSTM): KernelExplainer is slow, so only the first 200 rows
        background = shap.kmeans(X_sample, 50)
        explainer = shap.KernelExplainer(model.predict_proba, background)
        shap_values = explainer.shap_values(X_sample[:200])
        return _per_class_outputs(shap_values, label_type)


def plot_summary(shap_values, X_sample, feature_names, output_path, label_type):
    """SHAP beeswarm summary plot."""
    plt.figure(figsize=(12, 8))
    if label_type == "multiclass" and isinstance(shap_values, list):
        mean_abs_shap = np.mean([np.abs(sv) for sv in shap_values], axis=0)
        shap.summary_plot(mean_abs_shap, X_sample, feature_names=feature_names, show=False)
    else:
        shap.summary_plot(shap_values, X_sample, feature_names=feature_names, show=False)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Summary plot → {output_path}")


def plot_bar(shap_values, X_sample, feature_names, output_path, label_type):
    """SHAP bar plot (mean |SHAP|)."""
    plt.figure(figsize=(12, 8))
    if label_type == "multiclass" and isinstance(shap_values, list):
        mean_abs_shap = np.mean([np.abs(sv) for sv in shap_values], axis=0)
        shap.summary_plot(mean_abs_shap, X_sample, feature_names=feature_names,
                          plot_type="bar", show=False)
    else:
        shap.summary_plot(shap_values, X_sample, feature_names=feature_names,
                          plot_type="bar", show=False)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Bar plot    → {output_path}")


def plot_waterfall(shap_values, X_sample, feature_names, output_path, sample_idx=0):
    """SHAP waterfall plot for a single sample."""
    try:
        explanation = shap.Explanation(
            values=shap_values[sample_idx],
            base_values=0,
            data=X_sample[sample_idx] if hasattr(X_sample, "__getitem__") else None,
            feature_names=feature_names,
        )
        plt.figure(figsize=(12, 8))
        shap.waterfall_plot(explanation, show=False)
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"Waterfall   → {output_path}")
    except Exception as e:
        print(f"Waterfall plot skipped: {e}")


def export_top_features(shap_values, feature_names, output_path, top_n=20):
    """Export top-N important features by mean |SHAP| to CSV and print to console."""
    if isinstance(shap_values, list):
        # Multiclass: average across all classes
        abs_shap = np.mean([np.abs(sv) for sv in shap_values], axis=0)
    else:
        abs_shap = np.abs(shap_values)

    mean_importance = abs_shap.mean(axis=0)

    df = pd.DataFrame({
        "Feature": feature_names,
        "Mean_Abs_SHAP": mean_importance,
    }).sort_values("Mean_Abs_SHAP", ascending=False).reset_index(drop=True)

    df.index += 1  # 1-indexed ranking
    df.index.name = "Rank"

    df.to_csv(output_path)
    print(f"Top features → {output_path}")

    # Print top N to console
    print(f"\n  Top-{top_n} Most Important Features:")
    print(f"  {'Rank':<6} {'Feature':<30} {'Mean |SHAP|':<15}")
    print(f"  {'-'*6} {'-'*30} {'-'*15}")
    for rank, row in df.head(top_n).iterrows():
        print(f"  {rank:<6} {row['Feature']:<30} {row['Mean_Abs_SHAP']:<15.6f}")


def main(exp_name, model_type, split_name, label_type, n_samples, fs_profile="none"):
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print("=" * 60)
    print(f"  XAI | {exp_name} | {model_type} | {split_name} | {label_type} | fs={fs_profile}")
    print("=" * 60)

    # 1. Load model
    model = load_model(exp_name, model_type, split_name, config)
    print(f"  Model loaded: {exp_name}_{model_type}")

    # 2. Load & preprocess data
    print("  Preparing data...")
    preprocessed_data = prepare_data(split_name, label_type, config, fs_profile,
                                     save_artifacts=False)
    X_test = preprocessed_data["X_test_t"]
    selector = preprocessed_data["selector"]
    feature_names = selector.selected_columns_

    # Limit samples for SHAP computation
    X_sample = X_test[:n_samples]
    print(f"  Using {X_sample.shape[0]} test samples for SHAP analysis")

    # 3. Compute SHAP values
    print("  Computing SHAP values (this may take a few minutes)...")
    shap_values = compute_shap_values(model, model_type, X_sample, label_type)

    # KernelExplainer explains only the first rows; plot against the same rows
    n_explained = len(shap_values[0] if isinstance(shap_values, list) else shap_values)
    X_sample = X_sample[:n_explained]

    # 4. Generate outputs
    output_dir = PROJECT_ROOT / "results" / "xai"
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"{exp_name}_{model_type}"

    plot_summary(shap_values, X_sample, feature_names,
                 output_dir / f"{prefix}_shap_summary.png", label_type)

    plot_bar(shap_values, X_sample, feature_names,
             output_dir / f"{prefix}_shap_bar.png", label_type)

    # Waterfall only for binary (single SHAP array)
    sv_for_waterfall = shap_values
    if label_type == "binary":
        plot_waterfall(sv_for_waterfall, X_sample, feature_names,
                       output_dir / f"{prefix}_shap_waterfall.png", sample_idx=0)

    export_top_features(shap_values, feature_names,
                        output_dir / f"{prefix}_feature_importance.csv")

    print(f"\n{'=' * 60}")
    print(f"  XAI analysis complete. Results in: {output_dir}")
    print(f"{'=' * 60}")


def parse_exp_filter(exp_str):
    if exp_str is None or exp_str.strip() == ".":
        return None

    names = set()
    for part in exp_str.split(","):
        part = part.strip()
        if "-" in part and not part.startswith("-"):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explainable AI analysis for AI-IDS")
    parser.add_argument("--exp", "-e", type=str, default="EXP-02",
                        help="Experiment filter: '.' for all, '02' for EXP-02, '1-8' for range, '2,5,8' for list")
    parser.add_argument("--samples", type=int, default=1000,
                        help="Number of test samples for SHAP (default: 1000)")
    args = parser.parse_args()

    # Auto-resolve from experiment config
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Parse filter and handle single exp format like "EXP-02" or just "2"
    exp_str = args.exp
    if exp_str.startswith("EXP-"):
        exp_str = exp_str.replace("EXP-", "")
    
    exp_filter = parse_exp_filter(exp_str)
    experiments_to_run = filter_experiments(cfg.get("experiments", []), exp_filter)

    if not experiments_to_run:
        print("No experiments matched the filter.")
        sys.exit(0)

    for exp_cfg in experiments_to_run:
        exp_name = exp_cfg["name"]
        model_type = exp_cfg["model"]
        split_name = exp_cfg["split"]
        label_type = exp_cfg.get("label", "binary")

        try:
            main(exp_name, model_type, split_name, label_type, args.samples,
                 get_fs_profile(exp_cfg))
        except Exception as e:
            print(f"Error running XAI for {exp_name}: {e}")
