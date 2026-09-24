from .logistic_regression import build_logistic_regression
from .random_forest import build_random_forest

MODEL_REGISTRY = {
    "logistic_regression": build_logistic_regression,
    "random_forest": build_random_forest,
    "random_forest_regularized": build_random_forest,
}


def get_model(model_name: str, config: dict, class_weight=None):
    if model_name.startswith("random_forest"):
        return build_random_forest(config, model_name, class_weight=class_weight)
    elif model_name.startswith("logistic_regression"):
        return build_logistic_regression(config, model_name, class_weight=class_weight)

    available = ", ".join(MODEL_REGISTRY.keys())
    raise ValueError(f"Unknown model '{model_name}'. Available: {available}")