"""
Hyperparameter Optimization (HPO) using Optuna.
Supports every model in the registry. With --exp, tuning uses that experiment's split, label,
feature-selection profile and imbalance strategy; --auto-update writes the best params back
to configs/config.yaml.
"""

import re
import sys
import json
import time
import shutil
import argparse
from datetime import date
from pathlib import Path

import yaml
import optuna
import sklearn.metrics as metrics
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.training.train import prepare_data, SAMPLE_WEIGHT_MODELS
from src.preprocessing.artifacts import get_fs_profile
from src.imbalance.smote import apply_smote
from src.imbalance.undersampling import apply_undersampling
from src.models.registry import get_model

CONFIG_PATH = PROJECT_ROOT / "configs" / "config.yaml"

# ──────────────────────────────────────────────
# Search spaces per model (Optuna parameter names)
# ──────────────────────────────────────────────

def _rf_space(trial):
    return {
        "n_estimators": trial.suggest_int("n_estimators", 50, 500, step=50),
        "max_depth": trial.suggest_int("max_depth", 5, 60),
        "min_samples_split": trial.suggest_int("min_samples_split", 2, 20),
        "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 10),
        "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", None]),
    }


def _lr_space(trial):
    return {
        "C": trial.suggest_float("C", 1e-4, 100.0, log=True),
        "solver": trial.suggest_categorical("solver", ["lbfgs", "liblinear", "saga"]),
        "max_iter": trial.suggest_int("max_iter", 500, 5000, step=500),
    }


def _mlp_space(trial):
    n_layers = trial.suggest_int("n_layers", 2, 4)
    params = {"n_layers": n_layers}
    for i in range(n_layers):
        params[f"hidden_size_L{i}"] = trial.suggest_int(f"hidden_size_L{i}", 32, 512, step=32)
    params.update({
        "dropout": trial.suggest_float("dropout", 0.1, 0.5, step=0.05),
        "lr": trial.suggest_float("lr", 1e-4, 1e-2, log=True),
        "batch_size": trial.suggest_categorical("batch_size", [1024, 2048, 4096]),
        "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True),
    })
    return params


def _lstm_space(trial):
    return {
        "hidden_size": trial.suggest_int("hidden_size", 64, 256, step=32),
        "num_layers": trial.suggest_int("num_layers", 1, 3),
        "dropout": trial.suggest_float("dropout", 0.1, 0.5, step=0.05),
        "lr": trial.suggest_float("lr", 1e-4, 1e-2, log=True),
        "batch_size": trial.suggest_categorical("batch_size", [1024, 2048, 4096]),
        "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True),
        "bidirectional": trial.suggest_categorical("bidirectional", [True, False]),
    }


def _nb_space(trial):
    return {
        "var_smoothing": trial.suggest_float("var_smoothing", 1e-12, 1e-1, log=True),
    }


def _xgb_space(trial):
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
        "max_depth": trial.suggest_int("max_depth", 3, 12),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
    }


SEARCH_SPACES = {
    "random_forest": _rf_space,
    "random_forest_regularized": _rf_space,
    "logistic_regression": _lr_space,
    "mlp": _mlp_space,
    "lstm": _lstm_space,
    "naive_bayes": _nb_space,
    "xgboost": _xgb_space,
}

# Fixed during HPO only (shorter PyTorch training per trial); never written back to the config
HPO_FIXED = {
    "mlp": {"epochs": 20, "patience": 5},
    "lstm": {"epochs": 20, "patience": 5},
}


def to_config_params(model_name, params):
    """Translate Optuna parameter names to the config keys the model builders read."""
    params = dict(params)
    if model_name == "mlp":
        n_layers = params.pop("n_layers")
        hidden_sizes = [params.pop(f"hidden_size_L{i}") for i in range(n_layers)]
        params = {"hidden_sizes": hidden_sizes, **params}
    return params


# ──────────────────────────────────────────────
# Data + objective
# ──────────────────────────────────────────────

def load_hpo_data(config, split_name, label_type, fs_profile, strategy, subsample):
    # Reuse the saved training preprocessing when it exists, so HPO sees exactly what training sees
    data = prepare_data(split_name, label_type, config, fs_profile,
                        save_artifacts=False, reuse_existing=True)
    X_train, y_train = data["X_train_t"], data["y_train"]

    # Same resampling as training, applied once before the study
    if strategy == "smote":
        X_train, y_train = apply_smote(X_train, y_train, config)
    elif strategy == "undersampling":
        X_train, y_train = apply_undersampling(X_train, y_train, config, label_type)

    if subsample:
        X_train, _, y_train, _ = train_test_split(
            X_train, y_train, train_size=subsample, stratify=y_train, random_state=42)
        print(f"  Subsampled training data to {len(y_train):,} rows ({subsample:.0%})")

    return X_train, y_train, data["X_val_t"], data["y_val"]


def make_objective(model_name, config, class_weight, X_train, y_train, X_val, y_val):
    # Models without a class_weight parameter get balanced sample weights, as in training
    fit_kwargs = {}
    if class_weight and model_name in SAMPLE_WEIGHT_MODELS:
        fit_kwargs["sample_weight"] = compute_sample_weight("balanced", y_train)

    def objective(trial):
        params = to_config_params(model_name, SEARCH_SPACES[model_name](trial))
        overrides = {**params, **HPO_FIXED.get(model_name, {})}
        model = get_model(model_name, config, class_weight=class_weight, overrides=overrides)
        model.fit(X_train, y_train, **fit_kwargs)
        return metrics.f1_score(y_val, model.predict(X_val), average="macro")

    return objective


# ──────────────────────────────────────────────
# Writing the best params back to config.yaml
# ──────────────────────────────────────────────
# Targeted text edits, not a YAML re-dump: re-dumping reformats unrelated lines of the
# hand-edited config (blank lines, trailing spaces). The result is re-parsed and checked.

def _tidy(value):
    return float(f"{value:.6g}") if isinstance(value, float) else value


def _yaml_value(value):
    # Dump inside a one-element flow list and strip the brackets: "[550]" -> "550", "[[448, 448]]" -> "[448, 448]"
    return yaml.safe_dump([_tidy(value)], default_flow_style=True, width=1000).strip()[1:-1]


def _block_end(lines, start, indent):
    """Index after the last line of the block starting at lines[start] whose body is indented > indent."""
    end = start + 1
    while end < len(lines) and lines[end].startswith(" " * (indent + 1)):
        end += 1
    return end


def _set_experiment_params(lines, exp_name, params, comment):
    start = next((i for i, l in enumerate(lines)
                  if re.fullmatch(rf"  - name: {re.escape(exp_name)}\s*", l)), None)
    if start is None:
        raise ValueError(f"Experiment '{exp_name}' not found in config.yaml")
    end = _block_end(lines, start, 3)

    # Drop an existing params block of this experiment
    entry = lines[start:end]
    p = next((i for i, l in enumerate(entry) if re.match(r"    params:", l)), None)
    if p is not None:
        entry = entry[:p] + entry[_block_end(entry, p, 5):]

    new_block = [f"    params:  # {comment}"] + [f"      {k}: {_yaml_value(v)}" for k, v in params.items()]
    lines[start:end] = entry + new_block


def _set_model_params(lines, model_name, params, comment):
    models_at = next(i for i, l in enumerate(lines) if re.match(r"models:", l))
    models_end = _block_end(lines, models_at, 0)
    start = next((i for i in range(models_at + 1, models_end)
                  if re.match(rf"  {re.escape(model_name)}:", lines[i])), None)
    if start is None:
        raise ValueError(f"models.{model_name} not found in config.yaml")
    lines[start] = f"  {model_name}:  # {comment}"

    end = _block_end(lines, start, 3)
    for key, value in params.items():
        new_line = f"    {key}: {_yaml_value(value)}"
        hit = next((i for i in range(start + 1, end) if re.match(rf"    {re.escape(key)}:", lines[i])), None)
        if hit is not None:
            lines[hit] = new_line
        else:
            lines.insert(end, new_line)
            end += 1


def update_config(config_path, model_name, params, comment, exp_name=None):
    raw = config_path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(newline)

    if exp_name:
        _set_experiment_params(lines, exp_name, params, comment)
        location = f"experiments[{exp_name}].params"
    else:
        _set_model_params(lines, model_name, params, comment)
        location = f"models.{model_name}"

    new_raw = newline.join(lines)
    check = yaml.safe_load(new_raw)
    written = (next(e for e in check["experiments"] if e["name"] == exp_name)["params"]
               if exp_name else check["models"][model_name])
    if any(written.get(k) != _tidy(v) for k, v in params.items()):
        raise RuntimeError(f"Config update check failed for {location}; config.yaml left unchanged")

    shutil.copy2(config_path, config_path.with_name(config_path.name + ".bak"))
    config_path.write_bytes(new_raw.encode("utf-8"))
    return location


# ──────────────────────────────────────────────
# Resolve experiment config
# ──────────────────────────────────────────────

def resolve_experiment(config, exp_name):
    """Look up an experiment by name in config.yaml."""
    for exp in config.get("experiments", []):
        if exp["name"] == exp_name:
            return exp
    available = [e["name"] for e in config.get("experiments", [])]
    raise ValueError(f"Experiment '{exp_name}' not found. Available: {available}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main(model_name, split_name, label_type, n_trials, fs_profile="none", strategy=None,
         exp_name=None, subsample=None, auto_update=False):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if model_name not in SEARCH_SPACES:
        available = ", ".join(SEARCH_SPACES.keys())
        print(f"Error: Unknown model '{model_name}'. Available: {available}")
        return

    print("=" * 60)
    print(f"  HPO | {exp_name or '-'} | {model_name} | {split_name} | {label_type} | "
          f"fs={fs_profile} | strategy={strategy} | {n_trials} trials")
    print("=" * 60)

    if exp_name:
        run_tag = f"{exp_name}_{model_name}"
    else:
        # Keep pre-existing file names for the default profile / no strategy
        run_tag = f"{model_name}_{split_name}_{label_type}"
        if fs_profile != "none":
            run_tag += f"_{fs_profile}"
        if strategy:
            run_tag += f"_{strategy}"

    # 1. Load & preprocess data (never overwrites training artifacts)
    print("Loading and preprocessing data...")
    X_train, y_train, X_val, y_val = load_hpo_data(
        config, split_name, label_type, fs_profile, strategy, subsample)

    # 2. Run Optuna study
    study = optuna.create_study(direction="maximize", study_name=f"hpo_{run_tag}")
    class_weight = "balanced" if strategy == "class_weight" else None
    objective_fn = make_objective(model_name, config, class_weight, X_train, y_train, X_val, y_val)

    start = time.perf_counter()
    study.optimize(objective_fn, n_trials=n_trials, show_progress_bar=True)
    elapsed = time.perf_counter() - start

    # 3. Print results
    best = study.best_trial
    config_params = to_config_params(model_name, best.params)
    print(f"\n{'=' * 60}")
    print(f"  BEST TRIAL (#{best.number})")
    print(f"{'=' * 60}")
    print(f"  Macro F1-Score: {best.value:.6f}")
    print(f"  Total HPO time: {elapsed:.1f}s")
    print("  Best Hyperparameters (config keys):")
    for key, value in config_params.items():
        print(f"    {key}: {value}")

    # 4. Save results to JSON
    output_dir = PROJECT_ROOT / "results" / "hpo"
    output_dir.mkdir(parents=True, exist_ok=True)

    result_data = {
        "experiment": exp_name,
        "model": model_name,
        "split": split_name,
        "label": label_type,
        "feature_selection": fs_profile,
        "strategy": strategy,
        "subsample": subsample,
        "n_trials": n_trials,
        "best_trial_number": best.number,
        "best_macro_f1": best.value,
        "best_params": best.params,
        "best_config_params": config_params,
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

    # 5. Write the best params back to config.yaml
    if auto_update:
        comment = f"HPO {date.today()}: val macro-F1 {best.value:.4f}, {n_trials} trials"
        if subsample:
            comment += f", {subsample:.0%} of train"
        location = update_config(CONFIG_PATH, model_name, config_params, comment, exp_name)
        print(f"  config.yaml updated: {location} (backup: config.yaml.bak)")

        if exp_name:
            affected = [exp_name]
        else:
            affected = [e["name"] for e in config["experiments"] if e["model"] == model_name]
            print(f"  Note: models.{model_name} is shared by {len(affected)} experiments "
                  f"(those with their own params block keep them)")
        nums = ",".join(n.split("-")[1] for n in affected)
        print("  Retrain with the new params (existing models are skipped without --force):")
        print(f"    python scripts/train_all.py -e {nums} --force")
        print(f"    python scripts/evaluate_all.py -e {nums}")
    else:
        print("\n  To write these params to configs/config.yaml, rerun with --auto-update.")

    # 6. Save Optuna visualization (optional; needs plotly + kaleido)
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
    except Exception as e:
        print(f"  (Skipping Optuna plots: {type(e).__name__}. Install plotly + kaleido for visualization)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Hyperparameter Optimization with Optuna for AI-IDS"
    )
    parser.add_argument(
        "--exp", "-e", type=str, default=None,
        help="Experiment name (e.g. EXP-53). Reads model/split/label/fs/strategy from config.yaml"
    )
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help=f"Model to optimize (overrides --exp): {', '.join(SEARCH_SPACES)}"
    )
    parser.add_argument("--split", type=str, default=None, help="Split type (random/temporal)")
    parser.add_argument("--label", type=str, default=None, help="Label type (binary/multiclass)")
    parser.add_argument("--fs", type=str, default=None,
                        help="Feature-selection profile from config.yaml (default: none)")
    parser.add_argument("--strategy", type=str, default=None,
                        choices=["none", "smote", "undersampling", "class_weight"],
                        help="Imbalance strategy (default: the experiment's, or none)")
    parser.add_argument("--trials", "-n", type=int, default=20, help="Number of trials to run")
    parser.add_argument("--subsample", type=float, default=None,
                        help="Tune on a stratified fraction of the training rows, e.g. 0.2")
    parser.add_argument("--auto-update", action="store_true",
                        help="Write the best params to config.yaml: experiments[EXP].params with "
                             "--exp, otherwise models.<model>")
    args = parser.parse_args()

    strategy_arg = None if args.strategy == "none" else args.strategy

    # Resolve: --exp takes priority, individual flags override
    if args.exp:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            exp = resolve_experiment(yaml.safe_load(f), args.exp)
        resolved = {
            "model": args.model or exp["model"],
            "split": args.split or exp["split"],
            "label": args.label or exp.get("label", "binary"),
            "fs": args.fs or get_fs_profile(exp),
            "strategy": strategy_arg if args.strategy else exp.get("strategy"),
        }
        if args.auto_update:
            # Params written to an experiment must be tuned under that experiment's own setup
            actual = {"model": exp["model"], "split": exp["split"], "label": exp.get("label", "binary"),
                      "fs": get_fs_profile(exp), "strategy": exp.get("strategy")}
            diff = [k for k in actual if resolved[k] != actual[k]]
            if diff:
                parser.error(f"--auto-update with --exp cannot override {', '.join(diff)} "
                             f"of {args.exp}; drop those flags or omit --exp")
    else:
        resolved = {
            "model": args.model or "random_forest",
            "split": args.split or "random",
            "label": args.label or "binary",
            "fs": args.fs or "none",
            "strategy": strategy_arg,
        }

    main(
        model_name=resolved["model"],
        split_name=resolved["split"],
        label_type=resolved["label"],
        n_trials=args.trials,
        fs_profile=resolved["fs"],
        strategy=resolved["strategy"],
        exp_name=args.exp,
        subsample=args.subsample,
        auto_update=args.auto_update,
    )
