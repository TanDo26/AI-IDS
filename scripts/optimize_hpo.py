"""
Hyperparameter Optimization (HPO) using Optuna.
Supports: random_forest, random_forest_regularized, logistic_regression, mlp, lstm.
"""

import sys
import json
import time
import argparse
from pathlib import Path
from functools import partial

import yaml
import numpy as np
import optuna
import sklearn.metrics as metrics
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import prepare_data
from src.preprocessing.artifacts import get_fs_profile

# ──────────────────────────────────────────────
# Search spaces per model
# ──────────────────────────────────────────────

def _rf_objective(trial, X_train, y_train, X_val, y_val):
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 50, 500, step=50),
        "max_depth": trial.suggest_int("max_depth", 5, 60),
        "min_samples_split": trial.suggest_int("min_samples_split", 2, 20),
        "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 10),
        "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", None]),
        "random_state": 42,
        "n_jobs": -1,
    }
    model = RandomForestClassifier(**params)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_val)
    return metrics.f1_score(y_val, y_pred, average="macro")


def _lr_objective(trial, X_train, y_train, X_val, y_val):
    params = {
        "C": trial.suggest_float("C", 1e-4, 100.0, log=True),
        "solver": trial.suggest_categorical("solver", ["lbfgs", "liblinear", "saga"]),
        "max_iter": trial.suggest_int("max_iter", 500, 5000, step=500),
        "random_state": 42,
    }
    model = LogisticRegression(**params)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_val)
    return metrics.f1_score(y_val, y_pred, average="macro")


def _mlp_objective(trial, X_train, y_train, X_val, y_val, config):
    from src.models.mlp import MLPNetwork
    from src.models.torch_wrapper import TorchClassifierWrapper

    n_layers = trial.suggest_int("n_layers", 2, 4)
    hidden_sizes = []
    for i in range(n_layers):
        h = trial.suggest_int(f"hidden_size_L{i}", 32, 512, step=32)
        hidden_sizes.append(h)

    dropout = trial.suggest_float("dropout", 0.1, 0.5, step=0.05)
    lr = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
    batch_size = trial.suggest_categorical("batch_size", [1024, 2048, 4096])
    weight_decay = trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True)

    factory = partial(MLPNetwork, hidden_sizes=hidden_sizes, dropout=dropout)
    wrapper = TorchClassifierWrapper(
        model_factory=factory,
        epochs=20,  # Giới hạn epoch cho HPO (nhanh hơn)
        batch_size=batch_size,
        lr=lr,
        weight_decay=weight_decay,
        patience=5,
    )
    wrapper.fit(X_train, y_train)
    y_pred = wrapper.predict(X_val)
    return metrics.f1_score(y_val, y_pred, average="macro")


def _lstm_objective(trial, X_train, y_train, X_val, y_val, config):
    from src.models.lstm import LSTMNetwork
    from src.models.torch_wrapper import TorchClassifierWrapper

    hidden_size = trial.suggest_int("hidden_size", 64, 256, step=32)
    num_layers = trial.suggest_int("num_layers", 1, 3)
    dropout = trial.suggest_float("dropout", 0.1, 0.5, step=0.05)
    lr = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
    batch_size = trial.suggest_categorical("batch_size", [1024, 2048, 4096])
    weight_decay = trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True)
    bidirectional = trial.suggest_categorical("bidirectional", [True, False])

    factory = partial(
        LSTMNetwork,
        hidden_size=hidden_size,
        num_layers=num_layers,
        dropout=dropout,
        bidirectional=bidirectional,
    )
    wrapper = TorchClassifierWrapper(
        model_factory=factory,
        epochs=20,
        batch_size=batch_size,
        lr=lr,
        weight_decay=weight_decay,
        patience=5,
    )
    wrapper.fit(X_train, y_train)
    y_pred = wrapper.predict(X_val)
    return metrics.f1_score(y_val, y_pred, average="macro")


# ──────────────────────────────────────────────
# Objective dispatcher
# ──────────────────────────────────────────────

OBJECTIVE_MAP = {
    "random_forest": _rf_objective,
    "random_forest_regularized": _rf_objective,
    "logistic_regression": _lr_objective,
    "mlp": _mlp_objective,
    "lstm": _lstm_objective,
}


def make_objective(model_name, X_train, y_train, X_val, y_val, config):
    base_fn = OBJECTIVE_MAP[model_name]
    # PyTorch models need the config argument
    if model_name in ("mlp", "lstm"):
        return lambda trial: base_fn(trial, X_train, y_train, X_val, y_val, config)
    return lambda trial: base_fn(trial, X_train, y_train, X_val, y_val)


# ──────────────────────────────────────────────
# Resolve experiment config
# ──────────────────────────────────────────────

def resolve_experiment(config, exp_name):
    """Look up an experiment by name in config.yaml and return (model, split, label, fs_profile)."""
    for exp in config.get("experiments", []):
        if exp["name"] == exp_name:
            return exp["model"], exp["split"], exp.get("label", "binary"), get_fs_profile(exp)
    available = [e["name"] for e in config.get("experiments", [])]
    raise ValueError(f"Experiment '{exp_name}' not found. Available: {available}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main(model_name, split_name, label_type, n_trials, fs_profile="none"):
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if model_name not in OBJECTIVE_MAP:
        available = ", ".join(OBJECTIVE_MAP.keys())
        print(f"Error: Unknown model '{model_name}'. Available: {available}")
        return

    print("=" * 60)
    print(f"  HPO | {model_name} | {split_name} | {label_type} | fs={fs_profile} | {n_trials} trials")
    print("=" * 60)

    # Keep pre-existing file names for the default profile
    run_tag = f"{model_name}_{split_name}_{label_type}"
    if fs_profile != "none":
        run_tag += f"_{fs_profile}"

    # 1. Load & preprocess data (reuses existing pipeline; never overwrites training artifacts)
    print("Loading and preprocessing data...")
    preprocessed_data = prepare_data(split_name, label_type, config, fs_profile,
                                     save_artifacts=False)
    X_train = preprocessed_data["X_train_t"]
    y_train = preprocessed_data["y_train"]
    X_val = preprocessed_data["X_val_t"]
    y_val = preprocessed_data["y_val"]

    # 2. Run Optuna study
    study = optuna.create_study(
        direction="maximize",
        study_name=f"hpo_{run_tag}",
    )

    objective_fn = make_objective(model_name, X_train, y_train, X_val, y_val, config)

    start = time.perf_counter()
    study.optimize(objective_fn, n_trials=n_trials, show_progress_bar=True)
    elapsed = time.perf_counter() - start

    # 3. Print results
    best = study.best_trial
    print(f"\n{'=' * 60}")
    print(f"  BEST TRIAL (#{best.number})")
    print(f"{'=' * 60}")
    print(f"  Macro F1-Score: {best.value:.6f}")
    print(f"  Total HPO time: {elapsed:.1f}s")
    print("  Best Hyperparameters:")
    for key, value in best.params.items():
        print(f"    {key}: {value}")

    # 4. Save results to JSON
    output_dir = PROJECT_ROOT / "results" / "hpo"
    output_dir.mkdir(parents=True, exist_ok=True)

    result_data = {
        "model": model_name,
        "split": split_name,
        "label": label_type,
        "feature_selection": fs_profile,
        "n_trials": n_trials,
        "best_trial_number": best.number,
        "best_macro_f1": best.value,
        "best_params": best.params,
        "elapsed_seconds": round(elapsed, 2),
        "all_trials": [
            {
                "number": t.number,
                "value": t.value,
                "params": t.params,
                "state": str(t.state),
            }
            for t in study.trials
        ],
    }

    result_path = output_dir / f"{run_tag}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {result_path}")

    # 5. Save Optuna visualization (if plotly is available)
    try:
        from optuna.visualization import (
            plot_optimization_history,
            plot_param_importances,
        )

        fig_hist = plot_optimization_history(study)
        fig_hist.write_image(str(output_dir / f"{run_tag}_history.png"))

        if n_trials >= 5:
            fig_imp = plot_param_importances(study)
            fig_imp.write_image(str(output_dir / f"{run_tag}_importances.png"))

        print("  Optuna plots saved.")
    except ImportError:
        print("  (Skipping Optuna plots — install plotly + kaleido for visualization)")

    # 6. Print suggestion for config.yaml update
    print(f"\n  To apply these params, update configs/config.yaml under models.{model_name}:")
    for key, value in best.params.items():
        print(f"    {key}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Hyperparameter Optimization with Optuna for AI-IDS"
    )
    parser.add_argument(
        "--exp", "-e", type=str, default=None,
        help="Experiment name (e.g. EXP-02). Auto-reads model/split/label from config.yaml"
    )
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Model to optimize (overrides --exp): random_forest, logistic_regression, mlp, lstm"
    )
    parser.add_argument("--split", type=str, default=None, help="Split type (random/temporal)")
    parser.add_argument("--label", type=str, default=None, help="Label type (binary/multiclass)")
    parser.add_argument("--fs", type=str, default=None,
                        help="Feature-selection profile from config.yaml (default: none)")
    parser.add_argument("--trials", "-n", type=int, default=20, help="Number of trials to run")
    args = parser.parse_args()

    # Resolve: --exp takes priority, individual flags override
    if args.exp:
        config_path = PROJECT_ROOT / "configs" / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        exp_model, exp_split, exp_label, exp_fs = resolve_experiment(config, args.exp)
        model_name = args.model or exp_model
        split_name = args.split or exp_split
        label_type = args.label or exp_label
        fs_profile = args.fs or exp_fs
    else:
        model_name = args.model or "random_forest"
        split_name = args.split or "random"
        label_type = args.label or "binary"
        fs_profile = args.fs or "none"

    main(
        model_name=model_name,
        split_name=split_name,
        label_type=label_type,
        n_trials=args.trials,
        fs_profile=fs_profile,
    )

