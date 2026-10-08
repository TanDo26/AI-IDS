from .logistic_regression import build_logistic_regression
from .random_forest import build_random_forest
from .mlp import build_mlp
from .lstm import build_lstm
from .naive_bayes import build_naive_bayes
from .xgboost_model import build_xgboost

MODEL_REGISTRY = {
    "logistic_regression": build_logistic_regression,
    "random_forest": build_random_forest,
    "random_forest_regularized": build_random_forest,
    "mlp": build_mlp,
    "lstm": build_lstm,
    "naive_bayes": build_naive_bayes,
    "xgboost": build_xgboost,
}


def get_model(model_name: str, config: dict, class_weight=None, overrides=None):
    if overrides:
        # Per-experiment tuned params (experiments[].params) win over models.<name>
        base = config["models"].get(model_name, {})
        config = {**config, "models": {**config["models"], model_name: {**base, **overrides}}}

    if model_name.startswith("random_forest"):
        return build_random_forest(config, model_name, class_weight=class_weight)
    elif model_name.startswith("logistic_regression"):
        return build_logistic_regression(config, model_name, class_weight=class_weight)
    elif model_name == "mlp":
        return build_mlp(config, model_name, class_weight=class_weight)
    elif model_name == "lstm":
        return build_lstm(config, model_name, class_weight=class_weight)
    elif model_name == "naive_bayes":
        return build_naive_bayes(config, model_name, class_weight=class_weight)
    elif model_name == "xgboost":
        return build_xgboost(config, model_name, class_weight=class_weight)

    available = ", ".join(MODEL_REGISTRY.keys())
    raise ValueError(f"Unknown model '{model_name}'. Available: {available}")
