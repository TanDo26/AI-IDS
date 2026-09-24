from .logistic_regression import build_logistic_regression
from .random_forest import build_random_forest

MODEL_REGISTRY = {
    "logistic_regression": build_logistic_regression,
    "random_forest": build_random_forest,
    "random_forest_regularized": lambda cfg: build_random_forest(cfg, "random_forest_regularized"),
}


def get_model(model_name: str, config: dict):
    if model_name in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_name](config)

    if model_name.startswith("random_forest"):
        return build_random_forest(config, model_name)
    elif model_name.startswith("logistic_regression"):
        return build_logistic_regression(config, model_name)

    available = ", ".join(MODEL_REGISTRY.keys())
    raise ValueError(f"Unknown model '{model_name}'. Available: {available}")